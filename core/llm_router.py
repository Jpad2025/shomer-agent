"""Router de proveedores LLM.

- Chat interactivo (msg_natural): OpenAI si LLM_PROVIDER_INTERACTIVE=openai, sino Groq
- Monitores, /doc, explain(): siempre Groq (gratis)
- Si OpenAI falla o supera caps → fallback automático a Groq
- Si ambos fallan (sin internet) → degraded_response() con datos locales

Flag: LLM_PROVIDER_INTERACTIVE=openai|groq (default: groq)
"""
from __future__ import annotations

import logging
import os

from core import memory as _memory
from core import groq_helper as _groq

log = logging.getLogger("llm-router")

PROVIDER_INTERACTIVE = os.environ.get("LLM_PROVIDER_INTERACTIVE", "groq").strip().lower()

_CLOUD_ERRORS = (
    "sin conexión", "connection", "timeout", "timed out",
    "no pude contactar", "no pude procesar", "error del asistente",
    "cuota groq agotada", "❌", "⏱", "⏳",
)


def _is_cloud_error(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _CLOUD_ERRORS)


def _local_context_struct() -> dict:
    """Estado local sin depender de ninguna API cloud. Devuelve dict estructurado."""
    d: dict = {
        "online": [], "offline": [], "wan": None, "maintenance": False,
        "cpu": None, "ram": None, "disk": None,
        "blocked_ips": 0, "failed_backups": [],
    }
    try:
        import redis as _redis
        r = _redis.Redis(host="127.0.0.1", port=6379, decode_responses=True, socket_timeout=1)
        keys = r.keys("node_status:*")
        d["online"]  = [k.split(":")[-1] for k in keys if r.get(k) == "online"]
        d["offline"] = [k.split(":")[-1] for k in keys if r.get(k) in ("offline", "no-internet")]
        d["wan"] = r.get("wan_status")
        d["maintenance"] = r.get("shomer_maintenance") == "1"
    except Exception:
        pass
    try:
        import psutil
        d["cpu"]  = psutil.cpu_percent(interval=0.2)
        d["ram"]  = psutil.virtual_memory().percent
        d["disk"] = psutil.disk_usage("/").percent
    except Exception:
        pass
    try:
        import sqlite3, os as _os
        db = "/storage/db/network_monitor.db"
        if _os.path.exists(db):
            con = sqlite3.connect(db, timeout=2)
            row = con.execute("SELECT COUNT(*) FROM blocked_ips WHERE unblocked_at IS NULL").fetchone()
            failed = con.execute(
                "SELECT name FROM backup_devices WHERE last_status='failed' LIMIT 3"
            ).fetchall()
            con.close()
            d["blocked_ips"] = row[0] if row else 0
            d["failed_backups"] = [r[0] for r in failed]
    except Exception:
        pass
    return d


def _local_context() -> str:
    """Versión string del snapshot local — para inyectar en LLM."""
    d = _local_context_struct()
    lines: list[str] = []
    if d["online"]:
        lines.append(f"Nodos Guardian online ({len(d['online'])}): {', '.join(d['online'])}")
    if d["offline"]:
        lines.append(f"⚠️ Nodos CAÍDOS ({len(d['offline'])}): {', '.join(d['offline'])}")
    if d["wan"]:
        lines.append(f"WAN servidor: {d['wan']}")
    if d["maintenance"]:
        lines.append("Modo mantenimiento: ACTIVO")
    if d["cpu"] is not None:
        lines.append(f"Recursos: CPU {d['cpu']:.0f}% · RAM {d['ram']:.0f}% · Disco {d['disk']:.0f}%")
    if d["blocked_ips"]:
        lines.append(f"IPs bloqueadas activas: {d['blocked_ips']}")
    if d["failed_backups"]:
        lines.append(f"⚠️ Backups fallidos: {', '.join(d['failed_backups'])}")
    return "\n".join(lines) if lines else "Sin datos locales disponibles."


def _live_snapshot() -> str:
    """Estado vivo inyectado en cada chat — el modelo responde sin tools para lo común."""
    return _local_context()


def _degraded_response(history: list[dict]) -> str:
    """Delega a local_fallback.build_local_digest con el snapshot vivo."""
    from core.local_fallback import build_local_digest
    log.warning("DEGRADED MODE — sin acceso a LLM cloud. Respondiendo con snapshot local.")
    snapshot = _local_context_struct()
    question = ""
    for m in reversed(history):
        if m.get("role") == "user":
            question = str(m.get("content", "")).strip()
            break
    return build_local_digest(snapshot, question)


def _inject_snapshot(history: list[dict]) -> list[dict]:
    """Estado vivo + L5 (skills + SITE + knowledge) como system message."""
    parts: list[str] = []
    snapshot = _live_snapshot()
    if snapshot:
        parts.append(f"Estado actual del sistema:\n{snapshot}")
    try:
        from core import agente_skills

        learn = agente_skills.get_learning_context()
        if learn:
            parts.append(learn)
    except Exception as e:
        log.debug("learning context: %s", e)
    if not parts:
        return history
    injected = {"role": "system", "content": "\n\n".join(parts)}
    return [injected] + list(history)


def _groq_chat_safe(enriched: list[dict], level: str, history: list[dict]) -> str:
    """Llama a Groq con red; si falla por excepción o error cloud → _degraded_response."""
    try:
        out = _groq.chat(enriched, level=level)
    except Exception as e:
        log.warning("Groq excepción en chat(): %s — activando modo local", e)
        return _degraded_response(history)
    if _is_cloud_error(out):
        return _degraded_response(history)
    return out


def _chat_inner(enriched: list[dict], level: str, user_id, history: list[dict]) -> tuple:
    """Resuelve la llamada LLM y devuelve (out, engine_used)."""
    if not _openai_enabled():
        return _groq_chat_safe(enriched, level, history), "Groq"

    try:
        from core import openai_helper as _oai
    except Exception as e:
        log.warning("openai_helper import error: %s — usando Groq", e)
        return _groq_chat_safe(enriched, level, history), "Groq"

    if not _oai.is_available():
        log.warning("OpenAI no disponible (%s) — fallback a Groq", _oai.availability_error())
        return _groq_chat_safe(enriched, level, history), "Groq"

    allowed, reason = _memory.check_openai_caps(user_id)
    if not allowed:
        log.warning("Cap OpenAI alcanzado (%s) — fallback a Groq", reason)
        return _groq_chat_safe(enriched, level, history), "Groq"

    out = _oai.chat(enriched, level=level, user_id=user_id)
    if out is None:
        log.info("OpenAI devolvió None — fallback a Groq")
        return _groq_chat_safe(enriched, level, history), "Groq"

    return out, "OpenAI"


def chat(history: list[dict], level: str = "tecnico", user_id: int | str = "") -> str:
    enriched = _inject_snapshot(history)
    out, engine_used = _chat_inner(enriched, level, user_id, history)
    # NO se loguea al NOC -- el NOC es una pantalla pública sin login (TV del hotel)
    # y esto exponía el texto literal de las preguntas privadas del técnico
    # (ej. detalles de backups, nombres de servidores) a cualquiera que la viera.
    # El feed del NOC queda solo con explicaciones de monitores via explain().
    return out


def _openai_enabled() -> bool:
    return PROVIDER_INTERACTIVE == "openai"


def explain(prompt: str, context: str = "", include_doc: bool = False,
            level: str = "tecnico") -> str:
    out = _groq.explain(prompt, context=context, include_doc=include_doc, level=level)
    # Log para display NOC (solo si generó contenido real)
    try:
        first = (out or "").split('\n')[0].strip()
        if len(first) > 20 and "No pude" not in first and not first.startswith("⚠️"):
            from core.shomer_api import log_ia_action
            log_ia_action("Groq", first, "monitor")
    except Exception:
        pass
    return out


def active_provider() -> str:
    if _openai_enabled():
        try:
            from core import openai_helper as _oai
            if _oai.is_available():
                return f"openai ({_oai.OPENAI_MODEL}) + groq (monitores)"
            return f"groq (openai no disponible: {_oai.availability_error()})"
        except Exception:
            return "groq (openai no importable)"
    return "groq (llama-3.3-70b)"


def status_lines(*, html: bool = True) -> list[str]:
    """Estado de OpenAI + Groq para /salud, resúmenes y contexto LLM."""
    from core import maintenance as _mnt

    bold = (lambda t: f"<b>{t}</b>") if html else (lambda t: t)
    stats = _memory.get_provider_stats_today()
    groq_t = stats.get("groq", 0)
    openai_t = stats.get("openai", 0)
    budget = _memory.check_token_budget()
    budget_icon = {"ok": "✅", "warn": "⚠️", "exceeded": "🔴"}.get(budget, "❓")

    lines = [
        f"  🤖 Chat: {bold(active_provider())}",
        f"  {'⏸' if _mnt.is_paused() else '✅'} Asistente: "
        f"{_mnt.paused_until_str() if _mnt.is_paused() else 'activo'}",
        f"  📊 Tokens hoy — Groq: {groq_t:,} · OpenAI: {openai_t:,}",
        f"  {budget_icon} Presupuesto global tokens: {budget}",
        f"  ℹ️ Resúmenes automáticos: Groq (Llama 3.3 70B)",
    ]

    if _openai_enabled():
        try:
            from core import openai_helper as _oai
            if _oai.is_available():
                lines.insert(
                    2,
                    f"  ✅ OpenAI {bold(_oai.OPENAI_MODEL)} — chat interactivo",
                )
            else:
                err = _oai.availability_error() or "no disponible"
                lines.insert(2, f"  ❌ OpenAI: {err} — chat usa Groq")
        except Exception as ex:
            lines.insert(2, f"  ❌ OpenAI: {ex}")
    else:
        lines.insert(2, "  ℹ️ OpenAI desactivado (LLM_PROVIDER_INTERACTIVE=groq)")

    return lines
