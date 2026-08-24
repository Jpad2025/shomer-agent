"""
Monitor automático — corre en background dentro del bot.
Detecta cambios y notifica al técnico sin que tenga que preguntar.
"""
import asyncio
import html as _html
import logging
import os
import re
import time
from contextvars import ContextVar
from datetime import datetime, time as dtime, timedelta
from typing import Any, Dict, Optional, Set

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from core import device_manager as dm
from core import shomer_api
from core.groq_helper import explain
from core import access as acc
from core.identity import alert_prefix
from core.events import ShomerEvent
from core import triage
from core import auto_tasks
from core import fmt as msgfmt

log = logging.getLogger("shomer-monitor")

_TELEGRAM_ENVIADOS_DB = "/app/data/telegram_enviados.db"


def _registrar_envio_real(origen: str, resumen: str) -> None:
    """Contador de verdad -- registra CADA mensaje que de verdad salió a
    Telegram desde este proceso. Mismo archivo que usa Guardian (canal
    directo, network_monitor) para el mismo fin -- /app/data acá adentro es
    /storage/shomer-agent/data afuera, compartido y escribible por los dos
    lados (a diferencia de /storage/db, solo-lectura para el bot). Ver
    Sesión 23 ago: reconstruir el conteo solo desde memoria_alertas tenía
    un hueco real (el canal directo de Guardian nunca quedaba ahí)."""
    try:
        import sqlite3
        conn = sqlite3.connect(_TELEGRAM_ENVIADOS_DB, timeout=5)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS enviados ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "ts TEXT DEFAULT (datetime('now')), "
            "origen TEXT, resumen TEXT)"
        )
        conn.execute(
            "INSERT INTO enviados (origen, resumen) VALUES (?, ?)",
            (origen, (resumen or "")[:80]),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


_NOTAS_REPORTE_DB = "/app/data/knowledge.db"


def _agregar_nota_reporte(fuente: str, texto: str) -> None:
    """Libreta compartida para el grupo 'salud del propio Shomer' (24 ago):
    en vez de que watch_docker / watch_network_audit / watch_port_errors
    manden su propio mensaje suelto, anotan acá -- los dos reportes
    programados (07:00 y 22:00) la leen y la vacían. Persistida (no en
    memoria) para no perder una nota si el bot se reinicia entre reportes."""
    try:
        import sqlite3
        conn = sqlite3.connect(_NOTAS_REPORTE_DB, timeout=5)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notas_reporte ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "ts TEXT DEFAULT (datetime('now')), "
            "fuente TEXT, texto TEXT)"
        )
        conn.execute(
            "INSERT INTO notas_reporte (fuente, texto) VALUES (?, ?)", (fuente, texto),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.debug("_agregar_nota_reporte: %s", e)


def _leer_y_vaciar_notas_reporte() -> list[str]:
    """Lee todas las notas acumuladas desde el último reporte y las borra."""
    try:
        import sqlite3
        conn = sqlite3.connect(_NOTAS_REPORTE_DB, timeout=5)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notas_reporte ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "ts TEXT DEFAULT (datetime('now')), "
            "fuente TEXT, texto TEXT)"
        )
        rows = conn.execute("SELECT texto FROM notas_reporte ORDER BY id").fetchall()
        conn.execute("DELETE FROM notas_reporte")
        conn.commit()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        log.debug("_leer_y_vaciar_notas_reporte: %s", e)
        return []


_monitor_ctx: ContextVar[Optional[str]] = ContextVar("shomer_monitor", default=None)


def _resolve_monitor(monitor: Optional[str]) -> str:
    if monitor is not None:
        return monitor
    return _monitor_ctx.get() or "bot"


def _a(icon: str, event: str, detail: str = "", *, raw: bool = False) -> str:
    """Atajo local — formato unificado de alerta."""
    return msgfmt.alert_line(icon, event, detail, raw=raw)


def _kn(ip: str) -> str:
    """Sufijo HTML — antecedente + consejo de memoria (knowledge.db)."""
    try:
        dec = shomer_api.knowledge_decision(ip)
    except Exception:
        return ""
    parts: list[str] = []
    hint = (dec.get("hint") or "").strip()
    if hint:
        if len(hint) > 55:
            hint = hint[:54] + "…"
        parts.append(f"📋 {_html.escape(hint)}")
    advice = (dec.get("advice") or "").strip()
    if advice:
        if len(advice) > 120:
            advice = advice[:119] + "…"
        parts.append(f"💡 {_html.escape(advice)}")
    if not parts:
        return ""
    return " · " + " · ".join(parts)


def _save_kb_after_reboot(ip: str) -> InlineKeyboardMarkup:
    """Post-reboot — tags limpios para memoria / IA."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💾 Reinicio resolvió", callback_data=f"save_know:r:{ip}"),
            InlineKeyboardButton("🔌 Cable/PoE", callback_data=f"save_know:p:{ip}"),
        ],
        [
            InlineKeyboardButton("📝 Otra causa", callback_data=f"save_know:o:{ip}"),
            InlineKeyboardButton("No guardar", callback_data="save_know:x:0"),
        ],
    ])


def _save_kb_recovery(ip: str) -> InlineKeyboardMarkup:
    """Recuperación espontánea — invita a documentar con tag."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💾 Reinicio / volvió solo", callback_data=f"save_know:r:{ip}"),
            InlineKeyboardButton("🔌 Cable/PoE", callback_data=f"save_know:p:{ip}"),
        ],
        [
            InlineKeyboardButton("📝 Describir", callback_data=f"save_know:o:{ip}"),
            InlineKeyboardButton("No guardar", callback_data="save_know:x:0"),
        ],
    ])

CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
_DEV_CHAT_ID = os.environ.get("AGENT_DEVELOPER_CHAT_ID", "").strip()

# Estado interno — detectar cambios
_blocked_ips: Set[str] = set()
_device_status: Dict[str, str] = {}   # ip -> "online"|"offline"
_last_summary_day: Optional[int] = None
_offline_counts: Dict[str, int] = {}  # ip -> ticks consecutivos offline

# Ventana para considerar un bloqueo "reciente" (evento nuevo vs pre-existente al arrancar)
HUNTER_NEW_BLOCK_WINDOW_SECS = 600  # 10 minutos

# ── Tracking de monitores ─────────────────────────────────────────────────────
import time as _time_module

_monitor_status: Dict[str, Dict] = {}  # name -> {last_ok, last_alert, error}

def _tick(name: str, alerted: bool = False, error: str = "") -> None:
    entry = _monitor_status.setdefault(name, {"last_ok": None, "last_alert": None, "error": ""})
    now = _time_module.time()
    if error:
        entry["error"] = error
    else:
        entry["last_ok"] = now
        entry["error"] = ""
    if alerted:
        entry["last_alert"] = now

def get_monitor_status() -> Dict[str, Dict]:
    return dict(_monitor_status)

# ── Modo en sitio — supresiones por equipo ────────────────────────────────────

_suppressions: Dict[str, Dict] = {}  # ip -> {name, until, mins_left}


def set_suppression(ip: str, name: str, minutes: int) -> None:
    _suppressions[ip] = {
        "name": name,
        "until": _time_module.time() + minutes * 60,
        "mins_left": minutes,
    }
    log.info("Supresión activada: %s (%s) por %d min", ip, name, minutes)


def cancel_suppression(ip: str) -> None:
    _suppressions.pop(ip, None)


def get_site_suppressions() -> Dict[str, Dict]:
    now = _time_module.time()
    expired = [ip for ip, s in _suppressions.items() if s["until"] <= now]
    for ip in expired:
        _suppressions.pop(ip)
    for ip, s in _suppressions.items():
        s["mins_left"] = max(0, int((s["until"] - now) / 60))
    return dict(_suppressions)


def _is_suppressed(ip: str) -> bool:
    s = _suppressions.get(ip)
    if not s:
        return False
    if _time_module.time() > s["until"]:
        _suppressions.pop(ip)
        return False
    return True


def _get_top_processes(n: int = 5) -> list[dict]:
    """Top N procesos por CPU usando psutil."""
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
            try:
                procs.append({
                    "name": p.info["name"] or "?",
                    "cpu":  p.info["cpu_percent"] or 0.0,
                    "mem":  p.info["memory_percent"] or 0.0,
                })
            except Exception:
                pass
        return sorted(procs, key=lambda x: x["cpu"], reverse=True)[:n]
    except Exception:
        return []


async def _send(
    bot: Bot, text: str, reply_markup=None, *, monitor: Optional[str] = None, severity: str = "info",
) -> None:
    if not CHAT_ID:
        return
    mon = _resolve_monitor(monitor)
    prefix = alert_prefix()
    msg = f"<b>{_html.escape(prefix)}</b>\n{text}" if prefix else text

    def _memoria_log(ok: bool) -> None:
        try:
            from core import memoria_central
            memoria_central.log_telegram_alert(mon, msg, sent_ok=ok, severity=severity)
        except Exception:
            pass

    def _noc_mirror() -> None:
        """Mismos avisos que Telegram → ticker NOC (sin mensaje extra)."""
        try:
            import re as _re
            from core.shomer_api import log_ia_action
            plain = _re.sub(r"<[^>]+>", " ", msg or "")
            plain = _re.sub(r"\s+", " ", plain).strip()
            eng = "Groq" if (mon or "").startswith("watch_") else (mon or "Agente")
            # etiquetas cortas legibles en TV
            if "hunter" in (mon or "").lower() or "bloque" in plain.lower():
                eng = "Hunter"
            elif "infra" in (mon or "").lower() or "watch_infra" in (mon or ""):
                eng = "Infra"
            elif "guardian" in (mon or "").lower() or "watch_node" in (mon or ""):
                eng = "Guardian"
            log_ia_action(eng, plain[:140], "telegram")
        except Exception:
            pass

    try:
        await bot.send_message(
            chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_markup=reply_markup,
        )
        _memoria_log(True)
        _registrar_envio_real("bot", msg)
        _noc_mirror()
    except TelegramError as e:
        log.warning("Telegram send error: %s", e)
        if _DEV_CHAT_ID and _DEV_CHAT_ID != CHAT_ID:
            try:
                await bot.send_message(
                    chat_id=_DEV_CHAT_ID, text=msg, parse_mode="HTML", reply_markup=reply_markup,
                )
                _memoria_log(True)
                _registrar_envio_real("bot_dev_fallback", msg)
                _noc_mirror()
            except TelegramError as e2:
                log.warning("Telegram send error (fallback developer): %s", e2)
                _memoria_log(False)
        else:
            _memoria_log(False)


async def _send_critical(
    bot: Bot, text: str, reply_markup=None, *, monitor: Optional[str] = None, severity: str = "critical",
) -> None:
    await _send(bot, text, reply_markup=reply_markup, monitor=monitor, severity=severity)


async def _emit(
    bot: Bot,
    *,
    origen: str,
    entidad: str,
    metrica: str,
    lines: list[str],
    severity: str = "info",
    valor: str = "",
    reply_markup=None,
    bypass_buffer: bool = False,
    critical: bool = False,
) -> None:
    """Emite evento → triage (Capa C) o Telegram directo."""
    event = ShomerEvent(
        origen=origen,
        entidad=entidad,
        metrica=metrica,
        valor=valor or severity,
        severity=severity,
        lines=lines,
        reply_markup=reply_markup,
        bypass_buffer=bypass_buffer,
    )

    async def _dispatch(b: Bot, text: str, reply_markup=None) -> None:
        if critical:
            await _send_critical(
                b, text, reply_markup=reply_markup, monitor=origen, severity=severity,
            )
        else:
            await _send(
                b, text, reply_markup=reply_markup, monitor=origen, severity=severity,
            )

    await triage.notify(bot, event, _dispatch)


async def _diagnostico_degradando(bot: Bot, ip: str) -> None:
    try:
        from core import pattern_analysis as _pa
        p = _pa.get_pattern_for_entity(entity_ip=ip)
        if not p or p.get("tendencia") != "degradando":
            return
        nl = chr(10)
        ctx = (
            f"Equipo: {p['entidad']}{nl}"
            f"Caídas última semana: {p['ocurrencias']}{nl}"
            f"Tendencia: degradando{nl}"
            f"Sugerencia: {p.get('sugerencia', '')}"
        )
        prompt = (
            f"El AP {p['entidad']} acaba de caerse otra vez y viene degradándose. "
            "Formato DIAGNÓSTICO / CAUSA PROBABLE / ACCIÓN, máximo 4 líneas."
        )
        loop = asyncio.get_event_loop()

        def _ask_openai():
            try:
                from core import openai_helper as _oai
                client = _oai._get_client()
                if client is None:
                    from core import groq_helper as _gh2
                    return _gh2.explain(prompt, context=ctx, level="tecnico")
                model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Técnico de redes de hotel. Breve."},
                        {"role": "user", "content": f"{ctx}{nl}{prompt}"},
                    ],
                    max_tokens=250,
                    temperature=0.3,
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as e:
                from core import groq_helper as _gh2
                log.warning("diagnostico OpenAI falló: %s", e)
                return _gh2.explain(prompt, context=ctx, level="tecnico")

        texto = await loop.run_in_executor(None, _ask_openai)
        if texto:
            await _send(
                bot, f"🔬 Diagnóstico IA — {p['entidad']}{nl}{nl}{texto}",
                monitor="ia_diagnostico", severity="info",
            )
    except Exception as e:
        log.debug("diagnostico_degradando: %s", e)


async def _emit_guardian(
    bot: Bot,
    ip: str,
    lines: list[str],
    *,
    severity: str = "info",
    reply_markup=None,
    bypass_buffer: bool = False,
    critical: bool = False,
    allow_ia: bool = False,
) -> None:
    try:
        from core import pattern_analysis as _pa
        _sfx = _pa.alert_suffix(entity_ip=ip)
        if _sfx:
            lines = list(lines) + [_sfx]
        if allow_ia:
            from core import pulse_correlate as _pc
            p = _pa.get_pattern_for_entity(entity_ip=ip)
            if p and p.get("tendencia") == "degradando" and _pc.ia_diagnostico_allowed(ip):
                asyncio.create_task(_diagnostico_degradando(bot, ip))
    except Exception:
        pass
    await _emit(
        bot,
        origen="equipos_red",
        entidad=f"guardian:{ip}",
        metrica="node_status",
        lines=lines,
        severity=severity,
        reply_markup=reply_markup,
        bypass_buffer=bypass_buffer,
        critical=critical,
    )




# ── 1. Hunter: explicar nuevos bloqueos ──────────────────────────────────────

_HUNTER_RIESGOS_TIPOS = (
    "Revisar: puertos abiertos, actualizaciones y parches pendientes."
)
_HUNTER_RIESGOS_PANEL = (
    "Entrá al panel → Hunter → Riesgos de Red para ver detalle y cómo remediar."
)

async def watch_hunter(bot: Bot) -> None:
    """Cada 60s detecta nuevas IPs bloqueadas y las explica."""
    global _blocked_ips
    await asyncio.sleep(15)  # esperar que el bot esté listo

    # Primera lectura: cargar el estado actual sin alertar.
    # Evita spam al reiniciar el container cuando ya hay IPs bloqueadas.
    try:
        seed = shomer_api.get_blocked_ips()
        if seed:
            _blocked_ips = {item["ip"] for item in seed}
            log.info("watch_hunter: %d IPs pre-existentes cargadas (sin alerta)", len(_blocked_ips))
    except Exception:
        pass

    while True:
        try:
            data = shomer_api.get_blocked_ips()
            if data:
                current = {item["ip"] for item in data}
                nuevas  = current - _blocked_ips
                now     = time.time()
                for ip in nuevas:
                    item = next((x for x in data if x["ip"] == ip), {})

                    # Verificar si el bloqueo es reciente (evento real) o pre-existente.
                    # "blocked_at" es ISO8601 UTC. Si es antiguo (>10 min), fue
                    # bloqueado antes de que este ciclo lo detectara — no es un evento nuevo.
                    blocked_at_str = item.get("blocked_at", "")
                    is_new_event = True
                    if blocked_at_str:
                        try:
                            from datetime import datetime, timezone
                            blocked_ts = datetime.fromisoformat(
                                blocked_at_str.replace("Z", "+00:00")
                            ).timestamp()
                            age_secs   = now - blocked_ts
                            if age_secs > HUNTER_NEW_BLOCK_WINDOW_SECS:
                                log.debug(
                                    "watch_hunter: IP %s pre-existente (bloqueada hace %.0f min) — omitida",
                                    ip, age_secs / 60
                                )
                                is_new_event = False
                        except Exception:
                            pass  # sin timestamp fiable → asumir nuevo

                    if not is_new_event:
                        continue

                    sig         = item.get("alert_signature", "sin firma")
                    fw_blocked  = item.get("firewall_blocked", False)
                    block_count = item.get("block_count", 1)
                    recurrencia = f" (vez #{block_count})" if block_count and block_count > 1 else ""

                    _tick("watch_hunter", alerted=True)

                    keyboard = InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔓 Desbloquear", callback_data=f"block_unblock_{ip}"),
                    ]])
                    from core.hunter_labels import humanize_hunter_signature
                    h = humanize_hunter_signature(sig)
                    criticidad = {"critico": "crítico", "alto": "alto", "medio": "medio"}.get(
                        h.get("risk", "alto"), "alto"
                    )
                    accion = (
                        f"Hunter bloqueó {ip} en el firewall"
                        if fw_blocked
                        else f"Hunter registró {ip} en el panel — firewall sin confirmar, revisar Hunter"
                    )
                    msg_text = msgfmt.executive_alert(
                        criticidad, "Hunter",
                        impacto=f"{h['title']} — IP {ip}{recurrencia}. {h['detail']}",
                        accion_automatica=accion,
                        sugerencia=h.get("action", "") + _kn(ip),
                    )
                    # Contexto IA / fijo: ruido vs amenaza + qué hacer en el hotel
                    try:
                        from core import hunter_context as _hctx
                        hint = _hctx.diagnose_hunter_block(
                            ip, sig,
                            severity=int(item.get("severity") or 3),
                            firewall_blocked=bool(fw_blocked),
                            block_count=int(block_count or 1),
                            blocked_by=str(item.get("blocked_by") or "auto"),
                        )
                        if hint:
                            msg_text += f"\n💡 <i>{_html.escape(hint[:320])}</i>"
                    except Exception as _he:
                        log.debug("hunter ctx: %s", _he)
                    await _emit(
                        bot,
                        origen="watch_hunter",
                        entidad="hunter:blocks",
                        metrica="new_block",
                        lines=[msg_text],
                        severity="warn",
                        reply_markup=keyboard,
                    )
                _blocked_ips = current
            _tick("watch_hunter")
        except Exception as e:
            _tick("watch_hunter", error=str(e)); log.debug("watch_hunter error: %s", e)
        await asyncio.sleep(60)


# ── 2 & 3. Equipos del agente: caída y recuperación ─────────────────────────

async def watch_devices(bot: Bot) -> None:
    """Cada 2 min hace ping a todos los equipos del agente y notifica cambios."""
    global _device_status, _offline_counts
    await asyncio.sleep(30)

    while True:
        try:
            devices = dm.list_devices()
            for dev in devices:
                ip = dev["ip"]
                nombre = dev.get("name", ip)
                result = dm.ping_device(ip)
                nuevo = "online" if result["ok"] else "offline"
                anterior = _device_status.get(ip)

                if nuevo == "offline":
                    _offline_counts[ip] = _offline_counts.get(ip, 0) + 1
                else:
                    _offline_counts[ip] = 0

                # Alerta caída — solo tras 3 ticks consecutivos (6 min)
                if nuevo == "offline" and _offline_counts.get(ip, 0) == 3:
                    await _send_critical(
                        bot,
                        _a(
                            "🔴", "Equipo sin respuesta",
                            f"{msgfmt.host(nombre, ip)} — ~6 min",
                            raw=True,
                        ),
                    monitor="watch_devices",
                    )

                # Confirmación recuperación
                if nuevo == "online" and anterior == "offline":
                    await _send(
                        bot,
                        _a("✅", "Equipo recuperado", msgfmt.host(nombre, ip), raw=True),
                    monitor="watch_devices",
                    )

                _device_status[ip] = nuevo
                dm.update_status(ip, nuevo)
            _tick("watch_devices")
        except Exception as e:
            _tick("watch_devices", error=str(e)); log.debug("watch_devices error: %s", e)
        await asyncio.sleep(120)


# ── 4. Resumen diario 07:00 ──────────────────────────────────────────────────

def _build_server_line() -> str:
    """CPU/RAM/disco/servicios -- compartido entre el reporte de la mañana
    y el de la noche (24 ago), para no repetir la misma lógica dos veces."""
    try:
        from core import repair as _repair
        metrics = shomer_api.get_server_metrics()
        disk = shomer_api.get_disk_usage()
        svc = _repair.check_services()
        parts = []
        if metrics and metrics.get("success"):
            m = metrics.get("now", {})
            parts.append(f"CPU {m.get('cpu', 0):.0f}% · RAM {m.get('ram', 0):.0f}%")
        if disk.get("ok") and disk.get("partitions"):
            peor = max(disk["partitions"], key=lambda p: p.get("pct", 0))
            parts.append(f"Disco {peor.get('mount', '?')} {peor.get('pct', 0):.0f}%")
        if svc:
            caidos = [_repair.SERVICES[k]["label"] for k, s in svc.items() if s != "active"]
            parts.append("Servicios ✅" if not caidos else f"⚠️ caídos: {', '.join(caidos)}")
        return "\n🖥️ " + " · ".join(parts) if parts else ""
    except Exception as e:
        log.debug("_build_server_line error: %s", e)
        return ""


async def daily_summary(bot: Bot) -> None:
    """Envía resumen cada mañana a las 07:00 (America/Bogota — ver TZ del
    contenedor). 24 ago: incluye también las notas acumuladas de
    watch_docker/watch_network_audit/watch_port_errors -- un solo mensaje
    de la mañana en vez de varios sueltos (ver Sesión 74, grupo "salud del
    propio Shomer")."""
    global _last_summary_day
    await asyncio.sleep(20)

    while True:
        try:
            now = datetime.now()
            if now.hour == 7 and now.minute < 2 and _last_summary_day != now.day:
                _last_summary_day = now.day
                shomer_ctx = shomer_api.summary_text()
                daily_health = shomer_api.get_daily_health()
                visibility_block = ""
                if daily_health.get("success") and daily_health.get("text_combined"):
                    visibility_block = f"\n\n{daily_health['text_combined']}"
                devices = dm.list_devices()
                dev_ctx = ""
                if devices:
                    online = sum(1 for d in devices if d.get("status") == "online")
                    dev_ctx = f"\nEquipos agente: {online}/{len(devices)} online"

                import functools
                from core import llm_router as _llm
                loop = asyncio.get_event_loop()
                resumen = await loop.run_in_executor(
                    None,
                    functools.partial(
                        explain,
                        "Genera un resumen matutino del estado de la red. "
                        "Incluye Infra (equipos caídos), protección Hunter (IPs contenidas, "
                        "riesgos de red pendientes) y si hay algo urgente. "
                        "Tono tranquilizador: Hunter protege, no alarmista. Máximo 6 líneas.",
                        shomer_ctx + dev_ctx,
                    ),
                )
                ia_lines = _llm.status_lines()
                server_line = _build_server_line()

                # 24 ago: notas acumuladas de watch_docker/watch_network_audit/
                # watch_port_errors desde el reporte anterior -- un solo mensaje.
                notas = _leer_y_vaciar_notas_reporte()
                notas_block = "\n\n" + "\n\n".join(notas) if notas else ""

                _tick("daily_summary", alerted=True)
                await _send(
                    bot,
                    f"☀️ <b>Resumen de la mañana</b>\n\n{resumen}{visibility_block}{server_line}"
                    f"{notas_block}\n\n" + "\n".join(ia_lines),
                monitor="daily_summary",
                )
        except Exception as e:
            _tick("daily_summary", error=str(e)); log.debug("daily_summary error: %s", e)
        await asyncio.sleep(60)


_last_evening_day: Optional[int] = None


async def evening_summary(bot: Bot) -> None:
    """Reporte de cierre a las 22:00 (24 ago, Sesión 74) -- más liviano que
    el de la mañana: salud del servidor + lo que se acumuló en la libreta
    desde el reporte de las 07:00 (watch_docker/watch_network_audit/
    watch_port_errors). Si no hay nada nuevo, avisa "sin novedades" en vez
    de quedarse callado -- así el técnico sabe que el sistema sigue vivo y
    de verdad no pasó nada, no que se le olvidó revisar."""
    global _last_evening_day
    await asyncio.sleep(30)

    while True:
        try:
            now = datetime.now()
            if now.hour == 22 and now.minute < 2 and _last_evening_day != now.day:
                _last_evening_day = now.day
                server_line = _build_server_line()
                notas = _leer_y_vaciar_notas_reporte()
                notas_block = "\n\n" + "\n\n".join(notas) if notas else "\n\nSin novedades desde la mañana."

                _tick("evening_summary", alerted=True)
                await _send(
                    bot,
                    f"🌙 <b>Cierre del día</b>{server_line}{notas_block}",
                    monitor="evening_summary",
                )
        except Exception as e:
            _tick("evening_summary", error=str(e)); log.debug("evening_summary error: %s", e)
        await asyncio.sleep(60)


# ── 5. Recursos del servidor ─────────────────────────────────────────────────

_CPU_THRESHOLD  = int(os.environ.get("ALERT_CPU_THRESHOLD", "88"))
_CPU_TICKS      = int(os.environ.get("ALERT_CPU_TICKS", "2"))
_RAM_THRESHOLD  = int(os.environ.get("ALERT_RAM_THRESHOLD", "90"))

_resource_alerted = False
_cpu_high_ticks = 0   # contador de mediciones consecutivas con CPU alto

async def watch_resources(bot: Bot) -> None:
    """
    Alerta si CPU o RAM supera el umbral de forma SOSTENIDA.
    CPU requiere N ticks consecutivos (configurable) para evitar falsos positivos
    de Suricata durante ráfagas normales de tráfico espejo.
    """
    global _resource_alerted, _cpu_high_ticks
    await asyncio.sleep(45)

    while True:
        try:
            metrics = shomer_api.get_server_metrics()
            if metrics and metrics.get("success"):
                now_m = metrics.get("now", {})
                cpu  = now_m.get("cpu", 0)
                ram  = now_m.get("ram", 0)
                temp = now_m.get("temp", 0)

                # CPU: contar ticks consecutivos altos
                if cpu > _CPU_THRESHOLD:
                    _cpu_high_ticks += 1
                else:
                    _cpu_high_ticks = 0

                cpu_sostenido = _cpu_high_ticks >= _CPU_TICKS
                ram_alta      = ram > _RAM_THRESHOLD

                if (cpu_sostenido or ram_alta) and not _resource_alerted:
                    _resource_alerted = True
                    motivo = []
                    if cpu_sostenido:
                        motivo.append(
                            f"CPU al {cpu:.0f}% sostenido "
                            f"({_cpu_high_ticks} mediciones × 3 min)"
                        )
                    if ram_alta:
                        motivo.append(f"RAM al {ram:.0f}%")

                    _tick("watch_resources", alerted=True)
                    detalle = " · ".join(motivo)
                    if temp:
                        detalle += f" · {temp:.0f}°C"
                    jhint = ""
                    try:
                        from core import journal_context as _jctx
                        jhint = _jctx.diagnose_with_journal(
                            f"Servidor Shomer bajo alta carga: {detalle}",
                            host_signals=True,
                        )
                    except Exception as _je:
                        log.debug("journal ctx resources: %s", _je)
                    msg = _a("⚠️", "Servidor bajo alta carga", detalle, raw=True)
                    if jhint:
                        msg += f"\n💡 <i>{_html.escape(jhint[:280])}</i>"
                    await _send_critical(
                        bot,
                        msg,
                    monitor="watch_resources",
                    )

                elif cpu < (_CPU_THRESHOLD - 10) and ram < (_RAM_THRESHOLD - 10):
                    if _resource_alerted:
                        _resource_alerted = False
                        await _send_critical(
                            bot,
                            _a(
                                "✅", "Carga del servidor normalizada",
                                f"CPU {cpu:.0f}% · RAM {ram:.0f}%",
                                raw=True,
                            ),
                        monitor="watch_resources",
                        )
                    _cpu_high_ticks = 0
                _tick("watch_resources")
        except Exception as e:
            _tick("watch_resources", error=str(e)); log.debug("watch_resources error: %s", e)
        await asyncio.sleep(180)


# ── 6. Backup por equipo — horario configurable ──────────────────────────────

_backup_alerted: Dict[str, int] = {}   # device_name -> último día alertado

async def watch_backups(bot: Bot) -> None:
    """
    Lee backup_devices de la BD de Shomer cada hora.
    Alerta si last_backup_at tiene más de MAX_HOURS_WITHOUT_BACKUP horas.
    Horario de chequeo configurable por equipo en devices.json del agente
    (campo 'backup_check_hour'); default: 08:00.
    """
    MAX_HOURS = int(os.environ.get("BACKUP_MAX_HOURS", "26"))
    await asyncio.sleep(70)

    while True:
        try:
            now = datetime.now()
            devices_cfg = {d["ip"]: d for d in dm.list_devices()}
            backup_devs = shomer_api.get_backup_devices()

            for dev in backup_devs:
                if not dev.get("schedule_enabled", True):
                    continue
                nombre = dev["name"]
                ip     = dev["ip"]
                dtype  = dev.get("device_type", "?")
                ultimo = dev.get("last_backup_at")
                status = dev.get("last_status", "")

                # Hora de chequeo: tomar del devices.json del agente si existe
                cfg = devices_cfg.get(ip, {})
                check_hour = int(cfg.get("backup_check_hour", 8))

                if now.hour != check_hour or now.minute >= 5:
                    continue
                if _backup_alerted.get(nombre) == now.day:
                    continue

                _backup_alerted[nombre] = now.day
                problema = None

                if not ultimo:
                    problema = "nunca ha tenido backup registrado"
                else:
                    from datetime import timezone
                    try:
                        ts = datetime.fromisoformat(ultimo.replace("Z",""))
                        horas = (datetime.now() - ts).total_seconds() / 3600
                        if horas > MAX_HOURS:
                            problema = f"último backup hace {horas:.0f}h (límite {MAX_HOURS}h)"
                    except Exception:
                        problema = "fecha de último backup inválida"

                if "error" in (status or "").lower():
                    problema = (problema or "") + f" | error: {status[:60]}"

                if problema:
                    _tick("watch_backups", alerted=True)
                    await _emit(
                        bot,
                        origen="watch_backups",
                        entidad=f"protector:{nombre}",
                        metrica="backup_stale",
                        lines=[
                            _a(
                                "⚠️",
                                "Backup falló" if "error" in (status or "").lower()
                                else "Backup no corrido",
                                f"{_html.escape(str(nombre))} — {_html.escape(str(problema))}",
                                raw=True,
                            ),
                        ],
                        severity="warn",
                    )
                else:
                    log.debug("Backup OK: %s (%s)", nombre, ultimo)

            _tick("watch_backups")
        except Exception as e:
            _tick("watch_backups", error=str(e)); log.debug("watch_backups error: %s", e)
        await asyncio.sleep(55)


# ── 8. WAN coordinada con topología de grupos ────────────────────────────────

_wan_alert_active = False
_wan_outage_start: Optional[float] = None   # timestamp inicio caída
_wan_last_repeat: Optional[float] = None    # timestamp último recordatorio
_group_alerts: Dict[str, bool] = {}

WAN_REPEAT_INTERVAL = 600  # recordatorio cada 10 min mientras dure la caída

async def watch_wan_outage(bot: Bot) -> None:
    """
    Lógica de tres niveles:
    1. Grupo offline (ej. todos los APs del piso 2) → switch del piso
    2. Multi-grupo offline → verificar WAN desde el firewall
    3. WAN confirmada caída → alerta ISP
    """
    global _wan_alert_active, _group_alerts, _wan_outage_start, _wan_last_repeat
    await asyncio.sleep(40)

    # Leer firewall desde devices.json (el que tenga is_wan_probe=true)
    def _get_wan_probe():
        for d in dm.list_devices():
            if d.get("is_wan_probe"):
                return d
        return None

    while True:
        try:
            # --- recopilar estado actual ---
            agent_devices = dm.list_devices()
            nodes_data    = shomer_api.get_guardian_nodes()
            guardian_nodes = nodes_data if isinstance(nodes_data, list) else []

            # Agrupar agente por campo 'group'
            groups: Dict[str, list] = {}
            for d in agent_devices:
                g = d.get("group", "sin_grupo")
                groups.setdefault(g, []).append(d)

            # --- nivel 1: grupos con todos sus equipos offline ---
            for grupo, devs in groups.items():
                if grupo == "sin_grupo" or len(devs) < 2:
                    continue
                todos_offline = all(d.get("status") == "offline" for d in devs)
                nombres = [d.get("name", d.get("ip")) for d in devs]
                if todos_offline and not _group_alerts.get(grupo):
                    _group_alerts[grupo] = True
                    lista = ", ".join(_html.escape(str(n)) for n in nombres[:4])
                    extra = f" (+{len(nombres) - 4})" if len(nombres) > 4 else ""
                    await _send(
                        bot,
                        _a(
                            "🟠", "Posible switch caído",
                            f"{_html.escape(str(grupo))}: {lista}{extra}",
                            raw=True,
                        ),
                    monitor="watch_wan_outage",
                    )
                elif not todos_offline and _group_alerts.get(grupo):
                    _group_alerts[grupo] = False
                    await _send(
                        bot,
                        _a(
                            "✅", "Grupo recuperado",
                            f"{_html.escape(str(grupo))} en línea",
                            raw=True,
                        ),
                    monitor="watch_wan_outage",
                    )

            # --- nivel 2: múltiples grupos o Guardian offline → verificar WAN ---
            grupos_offline = [g for g, d in _group_alerts.items() if d]
            guardian_offline = [n for n in guardian_nodes
                                 if n.get("status") in ("offline", "no-internet")]
            total_offline = len(guardian_offline) + sum(
                1 for d in agent_devices if d.get("status") == "offline"
            )
            total_equipos = len(guardian_nodes) + len(agent_devices)

            import time as _time
            now_ts = _time.time()

            if (len(grupos_offline) >= 2 or len(guardian_offline) >= 2):
                probe = _get_wan_probe()
                wan_ok = True
                if probe:
                    wan_ok = shomer_api.ping_from_firewall(
                        probe["ip"], probe["user"], probe["password"]
                    )

                es_nueva = not _wan_alert_active
                repeat_due = (
                    _wan_last_repeat is not None and
                    (now_ts - _wan_last_repeat) >= WAN_REPEAT_INTERVAL
                )

                if es_nueva or repeat_due:
                    _wan_alert_active = True
                    _wan_last_repeat = now_ts
                    if _wan_outage_start is None:
                        _wan_outage_start = now_ts
                    duracion = int((now_ts - _wan_outage_start) / 60)
                    sufijo = f" (lleva {duracion} min)" if duracion > 0 else ""

                    if not wan_ok:
                        await _send_critical(
                            bot,
                            msgfmt.executive_alert(
                                "crítico", "Conectividad WAN",
                                impacto=f"{total_offline}/{total_equipos} equipos sin servicio{sufijo}",
                                accion_automatica="Ninguna — la caída es del proveedor de internet, no de Shomer",
                                sugerencia="Contactar al ISP del hotel",
                            ),
                        monitor="watch_wan_outage",
                        )
                    else:
                        await _send_critical(
                            bot,
                            msgfmt.executive_alert(
                                "alto", "Red interna",
                                impacto=f"{total_offline}/{total_equipos} equipos sin respuesta{sufijo} (WAN del servidor OK)",
                                accion_automatica="Ninguna automática — Guardian seguirá reintentando por equipo",
                                sugerencia="Revisar switch/cableado del sector afectado",
                            ),
                        monitor="watch_wan_outage",
                        )

            elif total_offline == 0 and _wan_alert_active:
                _wan_alert_active = False
                _wan_outage_start = None
                _wan_last_repeat = None
                await _send_critical(
                    bot, _a("✅", "Red recuperada", "todos los equipos en línea"),
                monitor="watch_wan_outage",
                )

            _tick("watch_wan_outage")
        except Exception as e:
            _tick("watch_wan_outage", error=str(e)); log.debug("watch_wan_outage error: %s", e)
        await asyncio.sleep(90)


# ── 7. Disco — limpieza automática por niveles (todas las particiones) ────────

# mount -> "alert"|"warn"|"critical"|None — estado por partición, no global.
# Antes esto era un único Optional[str] y el código leía disk["pct"] / disk["free_gb"]
# directo sobre la respuesta de la API — pero /api/disk-partitions devuelve una LISTA
# de particiones (/, /var, /opt, /home, /storage, /srv), no un dict plano con esas claves.
# Resultado: KeyError('pct') en cada ciclo, atrapado por el except → este monitor llevaba
# tiempo "corriendo" sin chequear nada en realidad. Por eso nadie avisó cuando /var se
# llenó al 100% el 7 jun 2026 y tumbó shomer-guardian. Corregido 8 jun 2026 — ver CLAUDE.md §AJ.
_disk_alerted_level: Dict[str, Optional[str]] = {}

def _free_gb_for(mount: str, fallback: float) -> float:
    disk2 = shomer_api.get_disk_usage()
    if disk2 and disk2.get("ok"):
        for p in disk2.get("partitions", []):
            if p["mount"] == mount:
                return p["free_gb"]
    return fallback

async def watch_disk(bot: Bot) -> None:
    """
    Por cada partición relevante del host (/, /var, /opt, /home, /storage, /srv):
    80% → alerta informativa
    85% → alerta + limpieza automática segura (logs, journal, tmp, apt)
    92% → alerta crítica + limpieza segura + aviso developer sobre reglas pendientes
    """
    from core import repair
    await asyncio.sleep(50)

    while True:
        try:
            disk = shomer_api.get_disk_usage()
            if not disk.get("ok"):
                await asyncio.sleep(300)
                continue

            for part in disk.get("partitions", []):
                mount = part["mount"]
                label = part.get("label", mount)
                pct   = part["pct"]
                free  = part["free_gb"]
                level = _disk_alerted_level.get(mount)
                tag   = f"{mount} ({label})" if label != mount else mount

                if pct >= 92 and level != "critical":
                    _disk_alerted_level[mount] = "critical"
                    ran = await auto_tasks.maybe_run(
                        "TASK-001", bot,
                        {"mount": mount, "label": label, "pct": pct, "free": free},
                        _send, _send_critical,
                    )
                    if not ran:
                        repair.run_safe_cleanup()
                        free2 = _free_gb_for(mount, free)
                        warn_rules = [r for r in repair.DISK_CLEANUP_RULES if r["level"] == "warn"]
                        jhint = ""
                        try:
                            from core import journal_context as _jctx
                            jhint = _jctx.diagnose_with_journal(
                                f"Disco {tag} al {pct}% (crítico)",
                                host_signals=True,
                            )
                        except Exception as _je:
                            log.debug("journal ctx disk: %s", _je)
                        sug = "Si vuelve a subir pronto, revisar journal/logs grandes manualmente"
                        if jhint:
                            sug = jhint[:200]
                        await _send_critical(
                            bot,
                            msgfmt.executive_alert(
                                "crítico", "Servidor Shomer",
                                impacto=f"Disco {tag} al {pct}% — riesgo de fallas en BD/logs si se llena",
                                accion_automatica=f"Limpieza automática ejecutada — quedan {free2}GB libres",
                                sugerencia=sug,
                            ),
                        monitor="watch_disk",
                        )

                elif pct >= 85 and level not in ("warn", "critical"):
                    _disk_alerted_level[mount] = "warn"
                    ran = await auto_tasks.maybe_run(
                        "TASK-001", bot,
                        {"mount": mount, "label": label, "pct": pct, "free": free},
                        _send, _send_critical,
                    )
                    if not ran:
                        repair.run_safe_cleanup()
                        free2 = _free_gb_for(mount, free)
                        jhint = ""
                        try:
                            from core import journal_context as _jctx
                            jhint = _jctx.diagnose_with_journal(
                                f"Disco {tag} al {pct}%",
                                host_signals=True,
                            )
                        except Exception as _je:
                            log.debug("journal ctx disk85: %s", _je)
                        extra = f"\n💡 <i>{_html.escape(jhint[:280])}</i>" if jhint else ""
                        await _send_critical(
                            bot,
                            _a(
                                "⚠️", "Disco alto",
                                f"{tag} {pct}% — limpieza automática, quedan {free2}GB",
                                raw=True,
                            ) + extra,
                        monitor="watch_disk",
                        )

                elif pct >= 80 and level is None:
                    _disk_alerted_level[mount] = "alert"
                    await _emit(
                        bot,
                        origen="watch_disk",
                        entidad=f"disk:{mount}",
                        metrica="usage_warn",
                        lines=[
                            _a(
                                "⚠️", "Disco elevado",
                                f"{tag} {pct}% — quedan {free}GB libres",
                                raw=True,
                            ),
                        ],
                        severity="warn",
                        critical=True,
                    )

                elif pct < 78 and level:
                    _disk_alerted_level[mount] = None

            _tick("watch_disk")
        except Exception as e:
            _tick("watch_disk", error=str(e)); log.debug("watch_disk error: %s", e)
        await asyncio.sleep(300)


# ── TASK-005: truncar logs Shomer grandes (03:00 diario) ─────────────────────

_last_log_truncate_day: Optional[int] = None


async def watch_log_truncate(bot: Bot) -> None:
    """Diario 03:00 Bogotá — trunca logs >50 MB. Sin Telegram si OK (ver ui_notify TASK-005)."""
    global _last_log_truncate_day
    await asyncio.sleep(110)

    while True:
        try:
            now = datetime.now()
            if (
                now.hour == 3
                and now.minute < 5
                and _last_log_truncate_day != now.day
                and auto_tasks.get_task_mode("TASK-005") != "off"
            ):
                _last_log_truncate_day = now.day
                await auto_tasks.maybe_run("TASK-005", bot, {}, _send, _send_critical)
            _tick("watch_log_truncate")
        except Exception as e:
            _tick("watch_log_truncate", error=str(e))
            log.debug("watch_log_truncate error: %s", e)
        await asyncio.sleep(60)


# ── Protector: auditoría muestral semanal (TASK-006) ─────────────────────────

_last_protector_sample_week: Optional[int] = None


async def watch_protector_sample(bot: Bot) -> None:
    """Domingo ~08:00 Bogotá — audita 3 equipos Protector al azar (solo lectura)."""
    global _last_protector_sample_week
    await asyncio.sleep(100)

    while True:
        try:
            now = datetime.now()
            if (
                now.weekday() == 6
                and now.hour == 8
                and now.minute < 5
                and _last_protector_sample_week != now.isocalendar()[1]
                and auto_tasks.get_task_mode("TASK-006") != "off"
            ):
                _last_protector_sample_week = now.isocalendar()[1]
                await auto_tasks.maybe_run("TASK-006", bot, {}, _send, _send_critical)
            _tick("watch_protector_sample")
        except Exception as e:
            _tick("watch_protector_sample", error=str(e))
            log.debug("watch_protector_sample error: %s", e)
        await asyncio.sleep(60)


# ── 8. Pipeline Hunter ────────────────────────────────────────────────────────

_pipeline_alerted = False

async def watch_pipeline(bot: Bot) -> None:
    global _pipeline_alerted
    from core import repair
    await asyncio.sleep(90)

    # Primera lectura: si el pipeline ya está degradado al arrancar,
    # marcar como notificado para no re-alertar en cada reinicio del container.
    try:
        seed = shomer_api.get_pipeline_health()
        if seed and not seed.get("overall_ok", True):
            _pipeline_alerted = True
            last_age = seed.get("checks", {}).get("last_event_age_sec")
            age_str = f" (último evento hace {int(last_age // 60)} min)" if last_age else ""
            log.info("watch_pipeline: pipeline ya degradado al arrancar%s — suprimiendo alerta inicial", age_str)
    except Exception:
        pass

    while True:
        try:
            data = shomer_api.get_pipeline_health()
            if data:
                ok = data.get("overall_ok", True)
                # Alertar en cada transición OK→degradado.
                # La semilla al arrancar ya evita el falso positivo de restart.
                if not ok and not _pipeline_alerted:
                    _pipeline_alerted = True
                    issues = data.get("issues") or []
                    warnings = data.get("warnings") or []
                    checks = data.get("checks") or {}
                    stale_min = int((checks.get("stale_threshold_sec") or 900) // 60)
                    last_age = checks.get("last_event_age_sec")
                    age_str = f" (último evento hace {int(last_age // 60)} min)" if last_age else ""
                    if (
                        auto_tasks.get_task_mode("TASK-009") != "off"
                        and not repair.is_suricata_active()
                    ):
                        await auto_tasks.maybe_run("TASK-009", bot, {}, _send, _send_critical)
                    await _emit(
                        bot,
                        origen="watch_pipeline",
                        entidad="pipeline:hunter",
                        metrica="degraded",
                        lines=[
                            _a(
                                "🟠", "Hunter sin datos recientes",
                                f"Suricata sin tráfico en espejo{age_str}. "
                                f"➡️ Revisar cable espejo — panel Hunter → Pipeline",
                                raw=True,
                            ),
                        ],
                        severity="warn",
                    )
                elif ok and _pipeline_alerted:
                    _pipeline_alerted = False
                    await _emit(
                        bot,
                        origen="watch_pipeline",
                        entidad="pipeline:hunter",
                        metrica="recovered",
                        lines=[_a("✅", "Hunter operativo", "Detección recibiendo tráfico con normalidad")],
                    )
                _tick("watch_pipeline")
        except Exception as e:
            _tick("watch_pipeline", error=str(e)); log.debug("watch_pipeline error: %s", e)
        await asyncio.sleep(180)


# ── 9. Monitor de servicios Shomer ───────────────────────────────────────────

_service_alerted: Dict[str, bool] = {}

async def watch_services(bot: Bot) -> None:
    """Cada 2 min verifica que guardian/tools/nginx estén activos."""
    from core import repair
    await asyncio.sleep(60)

    while True:
        try:
            status = repair.check_services()
            for key, state in status.items():
                label = repair.SERVICES[key]["label"]
                task_id = auto_tasks.SERVICE_TASK_MAP.get(key)

                if state != "active" and not _service_alerted.get(key):
                    _service_alerted[key] = True
                    # Journal filtrado → causa probable (no inventario del hotel)
                    jhint = ""
                    try:
                        from core import journal_context as _jctx
                        jhint = _jctx.diagnose_with_journal(
                            f"El servicio {label} está caído o no responde",
                            unit_key=key,
                        )
                    except Exception as _je:
                        log.debug("journal ctx services: %s", _je)
                    ran = False
                    if task_id:
                        ran = await auto_tasks.maybe_run(
                            task_id, bot, {"service_key": key},
                            _send, _send_critical,
                        )
                        if ran and repair.check_services().get(key) == "active":
                            _service_alerted[key] = False
                    if not ran:
                        ok, detail = repair.restart_service(key)
                        if ok:
                            lines_down = [
                                _a(
                                    "⚠️", f"{label} se detuvo",
                                    "reinicio automático en curso",
                                    raw=True,
                                ),
                            ]
                            if jhint:
                                lines_down.append(f"💡 <i>{_html.escape(jhint[:280])}</i>")
                            await _emit(
                                bot,
                                origen="watch_services",
                                entidad=f"services:{key}",
                                metrica="restart",
                                lines=lines_down,
                                severity="warn",
                                bypass_buffer=True,
                                critical=True,
                            )
                            await asyncio.sleep(30)
                            status2 = repair.check_services()
                            if status2.get(key) == "active":
                                await _emit(
                                    bot,
                                    origen="watch_services",
                                    entidad=f"services:{key}",
                                    metrica="recovered",
                                    lines=[
                                        _a(
                                            "✅", f"{label} recuperado",
                                            "activo tras reinicio automático",
                                            raw=True,
                                        ),
                                    ],
                                    severity="info",
                                )
                                _service_alerted[key] = False
                            else:
                                lines_fail = [
                                    _a(
                                        "🔴", f"{label} no respondió",
                                        "reinicio automático falló — usar /salud",
                                        raw=True,
                                    ),
                                ]
                                if jhint:
                                    lines_fail.append(f"💡 <i>{_html.escape(jhint[:280])}</i>")
                                await _emit(
                                    bot,
                                    origen="watch_services",
                                    entidad=f"services:{key}",
                                    metrica="restart_failed",
                                    lines=lines_fail,
                                    severity="critical",
                                    bypass_buffer=True,
                                    critical=True,
                                )
                        else:
                            port = repair.SERVICES[key]["port"]
                            if auto_tasks.get_task_mode("TASK-008") != "off":
                                await auto_tasks.maybe_run(
                                    "TASK-008", bot,
                                    {"port": port, "service_key": key},
                                    _send, _send_critical,
                                )
                            lines_down2 = [
                                _a(
                                    "🔴", f"{label} caído",
                                    _html.escape(str(detail[:120])),
                                    raw=True,
                                ),
                            ]
                            if jhint:
                                lines_down2.append(f"💡 <i>{_html.escape(jhint[:280])}</i>")
                            await _emit(
                                bot,
                                origen="watch_services",
                                entidad=f"services:{key}",
                                metrica="down",
                                lines=lines_down2,
                                severity="critical",
                                bypass_buffer=True,
                                critical=True,
                            )
                    else:
                        if repair.check_services().get(key) == "active":
                            _service_alerted[key] = False

                elif state == "active" and _service_alerted.get(key):
                    _service_alerted[key] = False
                    await _emit(
                        bot,
                        origen="watch_services",
                        entidad=f"services:{key}",
                        metrica="online",
                        lines=[
                            _a("✅", f"{label} recuperado", "servicio activo", raw=True),
                        ],
                    )
            _tick("watch_services")
        except Exception as e:
            _tick("watch_services", error=str(e)); log.debug("watch_services error: %s", e)
        await asyncio.sleep(120)


# ── 12. Nodos Guardian: caída, recuperación, patrón y verificación post-reboot ─

_guardian_status: Dict[str, str] = {}       # ip -> último status conocido
_guardian_last_reboot: Dict[str, int] = {}  # ip -> epoch del último reboot conocido
_guardian_reboot_count: Dict[str, list] = {} # ip -> lista de epoch de reboots hoy
_guardian_verify_pending: Dict[str, float] = {} # ip -> when to verify (epoch)
_guardian_down_streak: Dict[str, int] = {}  # ip -> polls consecutivos offline/no-internet (bot)
_guardian_down_alerted: Set[str] = set()    # IPs con alerta caída ya enviada (incidente actual)
_GUARDIAN_ALERT_CYCLES = max(1, int(os.environ.get("BOT_GUARDIAN_ALERT_CYCLES", "2")))
_GUARDIAN_REBOOT_VERIFY_MAX_AGE = max(60, int(os.environ.get("BOT_GUARDIAN_REBOOT_VERIFY_MAX_AGE", "600")))
# Sesión 69 — a partir de N caídas activas en patrones_detectados, la alerta de caída
# pasa a formato compacto (ver watch_guardian_nodes). No suprime avisos, solo acorta
# el texto para equipos ya identificados como flapping crónico.
_CHRONIC_ALERT_MIN_OCURRENCIAS = max(2, int(os.environ.get("BOT_CHRONIC_ALERT_MIN_OCURRENCIAS", "5")))
_AUTO_UNBLOCK_HOURS = int(os.environ.get("BOT_AUTO_UNBLOCK_HOURS", "0"))


async def watch_guardian_nodes(bot: Bot) -> None:
    """
    Cada 30s detecta cambios de estado en nodos Guardian.
    - Caída (offline/no-internet): alerta Telegram solo tras BOT_GUARDIAN_ALERT_CYCLES
      polls consecutivos malos (default 2 ≈ 60 s) — evita falso positivo en microcortes.
      Guardian no se modifica.
    - Degradado: orienta con causa probable, sin botón de reboot
    - Recuperación: avisa al volver online solo si hubo alerta de caída previa
    - Reboot detectado (Guardian automático): agenda verificación 3 min después (solo reboot reciente)
    - Post-reboot: confirma que AP está online o escala si sigue caído
    - Patrón recurrente: alerta si AP se reinicia 3+ veces en el día
    """
    global _guardian_status, _guardian_last_reboot, _guardian_reboot_count
    global _guardian_verify_pending, _guardian_down_streak, _guardian_down_alerted
    await asyncio.sleep(35)

    while True:
        try:
            nodes = shomer_api.get_guardian_nodes()
            if not nodes or not isinstance(nodes, list):
                await asyncio.sleep(30)
                continue

            now_ts = _time_module.time()
            recoveries: list[tuple[str, str]] = []

            # Procesar verificaciones post-reboot pendientes
            verify_ok: list[str] = []
            for ip, verify_at in list(_guardian_verify_pending.items()):
                if now_ts < verify_at:
                    continue
                del _guardian_verify_pending[ip]
                node = next((n for n in nodes
                             if n.get("ip") == ip or n.get("ip_address") == ip), None)
                if not node:
                    continue
                nombre = node.get("name", ip)
                status = node.get("status", "unknown")
                if status == "online":
                    verify_ok.append(nombre)
                    _guardian_status[ip] = "online"
                else:
                    icon = "🔴" if status == "offline" else "🟠"
                    await _emit_guardian(
                        bot, ip,
                        [
                            _a(
                                icon, f"{nombre} sigue caído",
                                "revisar alimentación, cable o switch del sector",
                                raw=True,
                            ),
                        ],
                        severity="critical",
                        bypass_buffer=True,
                        critical=True,
                    )
            if len(verify_ok) == 1:
                await _emit_guardian(
                    bot, "batch",
                    [_a("✅", "Nodo recuperado", f"{_html.escape(verify_ok[0])} tras reinicio", raw=True)],
                )
            elif len(verify_ok) > 1:
                txt = ", ".join(_html.escape(n) for n in verify_ok[:6])
                if len(verify_ok) > 6:
                    txt += f" (+{len(verify_ok) - 6})"
                await _send(
                    bot,
                    _a("✅", f"{len(verify_ok)} nodos recuperados tras reinicio", txt, raw=True),
                monitor="equipos_red",
                )

            for n in nodes:
                ip     = n.get("ip") or n.get("ip_address", "?")
                nombre = n.get("name", ip)
                status = n.get("status", "unknown")
                prev   = _guardian_status.get(ip)

                if prev is None:
                    _guardian_status[ip] = status
                    _guardian_down_streak[ip] = 1 if status in ("offline", "no-internet") else 0
                    data = shomer_api.get_node_failures(ip)
                    if data.get("last_reboot"):
                        _guardian_last_reboot[ip] = data["last_reboot"]
                    continue

                data = shomer_api.get_node_failures(ip)
                last_reboot_now = data.get("last_reboot") or 0
                last_reboot_prev = _guardian_last_reboot.get(ip, 0)

                if last_reboot_now and last_reboot_now != last_reboot_prev:
                    _guardian_last_reboot[ip] = last_reboot_now
                    reboot_age = now_ts - last_reboot_now
                    hoy_reboots = [t for t in _guardian_reboot_count.get(ip, [])
                                   if (now_ts - t) < 86400]
                    hoy_reboots.append(now_ts)
                    _guardian_reboot_count[ip] = hoy_reboots

                    if reboot_age <= _GUARDIAN_REBOOT_VERIFY_MAX_AGE:
                        _guardian_verify_pending[ip] = now_ts + 180
                        fails = data.get("failures", 0)
                        await _emit_guardian(
                            bot, ip,
                            [
                                _a(
                                    "⚡", "Reinicio automático Guardian",
                                    f"{_html.escape(str(nombre))} — {fails} alertas",
                                    raw=True,
                                ),
                            ],
                            severity="warn",
                        )

                    # Patrón recurrente: 3+ reboots en 24h
                    if len(hoy_reboots) >= 3:
                        dec = shomer_api.knowledge_decision(ip)
                        extra = ""
                        if dec.get("prefer_physical") or dec.get("reboot_resolved_count", 0) >= 2:
                            extra = " — historial sugiere revisión física, no otro reboot"
                        elif dec.get("advice"):
                            extra = f" — {_html.escape(dec['advice'][:90])}"
                        await _emit_guardian(
                            bot, ip,
                            [
                                _a(
                                    "🔁", "Reinicios repetidos",
                                    f"{_html.escape(str(nombre))} — {len(hoy_reboots)} veces en 24 h{extra}",
                                    raw=True,
                                ),
                            ],
                            severity="critical",
                            bypass_buffer=True,
                            critical=True,
                        )

                if status in ("offline", "no-internet"):
                    streak = _guardian_down_streak.get(ip, 0) + 1
                    _guardian_down_streak[ip] = streak
                    if (
                        streak >= _GUARDIAN_ALERT_CYCLES
                        and ip not in _guardian_down_alerted
                        and not _is_suppressed(ip)
                    ):
                        icon = "🔴" if status == "offline" else "🟠"
                        motivo = "sin LAN" if status == "offline" else "sin internet"
                        fails = data.get("failures", 0)
                        boton_label = f"⚡ Reiniciar {nombre}"
                        try:
                            hist = shomer_api.get_knowledge(ip=ip, limit=1)
                            if hist and "reinici" in (hist[0].get("action") or "").lower():
                                boton_label = f"⚡ Reiniciar {nombre} (resolvió antes)"
                        except Exception as e:
                            log.debug("get_knowledge lookup failed for %s: %s", ip, e)

                        markup = InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                boton_label,
                                callback_data=f"reboot_confirm:{ip}",
                            )
                        ]])
                        accion_g = (
                            f"Guardian reintentó {fails} veces; reiniciará automáticamente si cumple el umbral"
                            if status == "offline"
                            else "Guardian seguirá monitoreando — sin reboot (solo degrada WAN, no LAN)"
                        )

                        # Mapa de decisión de alertas (CLAUDE.md), paso 7 — patrón
                        # crónico. Sesión 69 — equipo "flapper" crónico ya identificado
                        # por pattern_analysis (patrones_detectados): en vez de repetir
                        # el bloque completo (impacto/acción/sugerencia) en cada caída
                        # nueva -- ej. AP REST SCALA tuvo 29 alertas críticas completas
                        # en 40 días -- se manda un aviso corto que sigue notificando
                        # cada caída (no se suprime nada) pero sin inflar el chat con
                        # texto repetido de un problema físico ya conocido/reportado.
                        _pat = {}
                        try:
                            from core import pattern_analysis as _pa
                            _pat = _pa.get_pattern_for_entity(entity_ip=ip, entity_name=nombre) or {}
                        except Exception:
                            pass
                        _chronic = _pat.get("ocurrencias", 0) >= _CHRONIC_ALERT_MIN_OCURRENCIAS

                        if _chronic:
                            lines = [
                                _a(
                                    icon, f"{nombre} {motivo}",
                                    f"caída #{_pat['ocurrencias']} de un patrón ya conocido "
                                    f"({_pat.get('tendencia', 'estable')}) — sin novedad, "
                                    "ver /consultar_memoria para histórico",
                                    raw=True,
                                ),
                            ]
                        else:
                            lines = [
                                msgfmt.executive_alert(
                                    "crítico" if status == "offline" else "alto", "Guardian",
                                    impacto=f"{nombre} {motivo} — usuarios sin servicio en ese equipo",
                                    accion_automatica=accion_g,
                                    sugerencia="Revisar cableado/alimentación física",
                                ) + _kn(ip),
                            ]

                        _sev = "critical" if status == "offline" else "warn"

                        async def _send_first(
                            _bot=bot, _ip=ip, _lines=lines, _sev=_sev,
                            _markup=markup, _allow_ia=(status == "offline"),
                        ):
                            await _emit_guardian(
                                _bot, _ip, _lines,
                                severity=_sev, reply_markup=_markup, allow_ia=_allow_ia,
                            )

                        # Mapa de decisión de alertas (CLAUDE.md), paso 5 —
                        # escalamiento crónico: agrupa repetidas del MISMO
                        # equipo en la ventana de agregación, no avisa una x una.
                        from core import incident_escalation as _esc
                        await _esc.handle_event(
                            bot, ip, nombre, "offline",
                            send_first_fn=_send_first, severity=_sev,
                        )
                        _guardian_down_alerted.add(ip)

                elif status == "degraded" and prev not in ("degraded",) and not _is_suppressed(ip):
                    _guardian_down_streak[ip] = 0

                    async def _send_first_degraded(_bot=bot, _ip=ip, _nombre=nombre):
                        await _emit_guardian(
                            _bot, _ip,
                            [
                                _a(
                                    "🟡", f"{_nombre} con señal débil",
                                    "interferencia, cable o muchos clientes",
                                    raw=True,
                                ),
                            ],
                            severity="warn",
                        )

                    # Mapa de decisión de alertas (CLAUDE.md), paso 5 (igual que arriba).
                    from core import incident_escalation as _esc
                    await _esc.handle_event(
                        bot, ip, nombre, "degraded",
                        send_first_fn=_send_first_degraded, severity="warn",
                    )

                elif status == "online":
                    if (
                        prev in ("offline", "no-internet")
                        and ip in _guardian_down_alerted
                        and not _is_suppressed(ip)
                    ):
                        # Mapa de decisión de alertas (CLAUDE.md), paso 6 —
                        # recuperación repetida (Sesión 71): si el equipo ya
                        # está flapeando, no repetir "recuperado" en cada blip.
                        from core import incident_escalation as _esc
                        if not _esc.is_flapping(ip):
                            recoveries.append((ip, nombre))
                        else:
                            _esc.record_filtered_event(ip, nombre, "watch_guardian_nodes")
                    _guardian_down_streak[ip] = 0
                    _guardian_down_alerted.discard(ip)

                else:
                    _guardian_down_streak[ip] = 0

                _guardian_status[ip] = status

            for ip, nombre in recoveries:
                await _emit_guardian(
                    bot, ip,
                    [_a("✅", "Nodo recuperado", msgfmt.host(nombre, ip), raw=True)],
                    reply_markup=_save_kb_recovery(ip),
                )

            _tick("watch_guardian_nodes")
        except Exception as e:
            _tick("watch_guardian_nodes", error=str(e)); log.debug("watch_guardian_nodes error: %s", e)
        await asyncio.sleep(30)


# ── Arrancar todos los monitores ─────────────────────────────────────────────

async def preventive_reboot(bot: Bot) -> None:
    """
    Cada día a las 03:00 (Bogotá) revisa APs con uptime > 30 días.
    Reinicia en silencio si OK; solo Telegram si el reinicio falla.
    Aplica solo a equipos sin 'no_reboot: true'.
    """
    await asyncio.sleep(60)
    _last_day: Optional[int] = None

    while True:
        try:
            now = datetime.now()
            if now.hour == 3 and now.minute < 2 and _last_day != now.day:
                _last_day = now.day
                devices = dm.list_devices()
                for dev in devices:
                    if dev.get("no_reboot"):
                        continue
                    info = dm.get_info(dev["ip"])
                    if not info.get("ok"):
                        continue
                    uptime_str = info.get("data", {}).get("uptime", "")
                    # Detectar uptime > 30 días en texto (ej. "45d 3h 20m")
                    dias = 0
                    if "d" in uptime_str:
                        try:
                            dias = int(uptime_str.split("d")[0].strip().split()[-1])
                        except Exception:
                            pass
                    if dias >= 30:
                        result = dm.reboot_device(dev["ip"])
                        ok_r = result.get("ok")
                        if ok_r:
                            log.info(
                                "Reinicio preventivo OK: %s (%s d) — sin Telegram",
                                dev.get("name"), dias,
                            )
                            continue
                        estado = f"falló: {result.get('message', '')}"
                        await _send_critical(
                            bot,
                            _a(
                                "🔄", "Reinicio preventivo falló",
                                f"{_html.escape(str(dev['name']))} — {dias} días · {estado}",
                                raw=True,
                            ),
                        monitor="preventive_reboot",
                        )
            _tick("preventive_reboot")
        except Exception as e:
            _tick("preventive_reboot", error=str(e)); log.debug("preventive_reboot error: %s", e)
        await asyncio.sleep(60)


# ── 11. Backup semanal automático ─────────────────────────────────────────────

_last_weekly_backup_week: Optional[int] = None


async def weekly_backup(bot: Bot) -> None:
    """
    Cada domingo a las 02:00 Bogotá crea backup del sistema.
    Silencio si OK; Telegram solo si falla.
    """
    global _last_weekly_backup_week
    from core import backup_manager
    await asyncio.sleep(80)  # esperar que el bot esté listo

    while True:
        try:
            now = datetime.now()
            # Domingo = 6, entre 02:00 y 02:05
            if (now.weekday() == 6 and now.hour == 2 and now.minute < 5
                    and _last_weekly_backup_week != now.isocalendar()[1]):
                _last_weekly_backup_week = now.isocalendar()[1]
                ok, msg, size_mb = backup_manager.create_backup()
                if ok:
                    log.info("Backup semanal OK: %s — sin Telegram", msg)
                else:
                    await _send_critical(
                        bot,
                        _a(
                            "⚠️", "Backup semanal falló",
                            _html.escape(str(msg) or "revisar configuración o espacio"),
                            raw=True,
                        ),
                    monitor="weekly_backup",
                    )
            _tick("weekly_backup")
        except Exception as e:
            _tick("weekly_backup", error=str(e)); log.debug("weekly_backup error: %s", e)
        await asyncio.sleep(60)


# ── Protector: retry y patrón de fallos ──────────────────────────────────────

_backup_consecutive_fails: Dict[str, int] = {}  # nombre -> fallos consecutivos

async def watch_protector_retry(bot: Bot) -> None:
    """
    Detecta backups fallidos y ofrece retry / escala si falla 3 noches seguidas.
    Corre cada hora, pero solo actúa cuando hay cambio de estado.
    """
    _backup_status_prev: Dict[str, str] = {}
    await asyncio.sleep(90)

    while True:
        try:
            backup_devs = shomer_api.get_backup_devices()
            for dev in backup_devs:
                nombre = dev["name"]
                ip     = dev.get("ip", "?")
                status = dev.get("last_status", "") or ""
                ultimo = dev.get("last_backup_at")

                prev_status = _backup_status_prev.get(nombre)
                _backup_status_prev[nombre] = status

                es_fallo = "error" in status.lower() or "fail" in status.lower()
                es_ok    = "ok" in status.lower() or "success" in status.lower()

                if es_fallo and prev_status != status:
                    # Incrementar contador de fallos consecutivos
                    _backup_consecutive_fails[nombre] = _backup_consecutive_fails.get(nombre, 0) + 1
                    fallos = _backup_consecutive_fails[nombre]

                    st_l = status.lower()
                    b2_fallo = "b2" in st_l or "cloud" in st_l
                    equipo_apagado = (
                        "connect" in st_l or "timeout" in st_l
                        or "unreachable" in st_l or "no route" in st_l
                    )
                    permiso_repo = (
                        "permission" in st_l or "permiso" in st_l
                        or "open /srv" in st_l or "load(<index" in st_l
                        or "restic" in st_l and "index" in st_l
                    )
                    credencial = (
                        "logon" in st_l or "access denied" in st_l
                        or "nt_status" in st_l or "auth" in st_l
                        or "mount.cifs" in st_l or "permission denied" in st_l
                    )

                    if b2_fallo:
                        detalle = f"{_html.escape(str(nombre))} — local OK, B2 falló"
                        titulo = "Backup sin subir a nube"
                        icono = "☁️"
                    elif equipo_apagado:
                        detalle = f"{_html.escape(str(nombre))} — equipo apagado o sin red"
                        titulo = "Backup falló"
                        icono = "⚠️"
                    elif permiso_repo:
                        detalle = (
                            f"{_html.escape(str(nombre))} — repo local /srv "
                            "(permisos o índice Restic); no es credencial Windows"
                        )
                        titulo = "Backup falló"
                        icono = "⚠️"
                    elif credencial:
                        detalle = f"{_html.escape(str(nombre))} — revisar credenciales"
                        titulo = "Backup falló"
                        icono = "⚠️"
                    else:
                        detalle = (
                            f"{_html.escape(str(nombre))} — revisar Protector "
                            f"({_html.escape(status[:120])})"
                        )
                        titulo = "Backup falló"
                        icono = "⚠️"

                    await _send(
                        bot,
                        _a(icono, titulo, detalle, raw=True),
                        monitor="watch_protector_retry",
                    )

                    if fallos >= 3:
                        await _send_critical(
                            bot,
                            _a(
                                "🔴", "Backups fallidos repetidos",
                                f"{_html.escape(str(nombre))} — {fallos} noches seguidas",
                                raw=True,
                            ),
                        monitor="watch_protector_retry",
                        )

                elif es_ok and _backup_consecutive_fails.get(nombre, 0) > 0:
                    _backup_consecutive_fails[nombre] = 0

            _tick("watch_protector_retry")
        except Exception as e:
            _tick("watch_protector_retry", error=str(e)); log.debug("watch_protector_retry error: %s", e)
        await asyncio.sleep(3600)


# ── Hunter: verificar bloqueo efectivo ───────────────────────────────────────

_hunter_blocked_verify: Dict[str, float] = {}  # ip -> epoch cuando se bloqueó
_hunter_internal_warned: Set[str] = set()

async def watch_hunter_verify(bot: Bot) -> None:
    """
    - Detecta IPs recién bloqueadas y verifica 30s después que siguen en la lista
    - Alerta si una IP interna (privada) fue bloqueada — puede ser error
    - Detecta IPs que se bloquean y desbloquean de forma recurrente
    """
    import ipaddress
    _block_count: Dict[str, int] = {}  # ip -> veces bloqueada/desbloqueada

    await asyncio.sleep(100)

    _known_blocked: Set[str] = set()
    try:
        seed = shomer_api.get_blocked_ips() or []
        _known_blocked = {item["ip"] for item in seed if item.get("ip")}
        if _known_blocked:
            log.info(
                "watch_hunter_verify: %d IP(s) pre-existentes (sin re-verificación)",
                len(_known_blocked),
            )
    except Exception:
        pass

    while True:
        try:
            blocked_data = shomer_api.get_blocked_ips() or []
            current_blocked = {item["ip"] for item in blocked_data}

            # Nuevas IPs bloqueadas desde el último tick
            nuevas = current_blocked - _known_blocked
            for ip in nuevas:
                _hunter_blocked_verify[ip] = _time_module.time() + 30
                _block_count[ip] = _block_count.get(ip, 0) + 1

                # Alerta si es IP interna (privada)
                try:
                    addr = ipaddress.ip_address(ip)
                    if addr.is_private and ip not in _hunter_internal_warned:
                        _hunter_internal_warned.add(ip)
                        await _send_critical(
                            bot,
                            _a(
                                "⚠️", "IP interna bloqueada — revisar",
                                f"<code>{_html.escape(str(ip))}</code> puede ser equipo del hotel. "
                                f"➡️ Panel Hunter o /desbloquear si es legítimo",
                                raw=True,
                            ),
                        monitor="watch_hunter_verify",
                        )
                except ValueError:
                    pass

                # Memoria: si el técnico guardó "falso positivo", orientar decisión
                dec = shomer_api.knowledge_decision(ip)
                if dec.get("likely_false_positive"):
                    await _send_critical(
                        bot,
                        _a(
                            "⚠️", "Bloqueo con antecedente de falso positivo",
                            f"<code>{_html.escape(str(ip))}</code> — en memoria figura como falso positivo. "
                            f"➡️ Revisar /desbloquear si aplica · {_html.escape((dec.get('hint') or '')[:80])}",
                            raw=True,
                        ),
                    monitor="watch_hunter_verify",
                    )

                # Patrón recurrente: misma IP bloqueada 3+ veces
                if _block_count.get(ip, 0) >= 3:
                    await _send_critical(
                        bot,
                        _a(
                            "🔁", "Misma IP bloqueada varias veces",
                            f"<code>{_html.escape(str(ip))}</code> — {_block_count[ip]} veces. "
                            f"➡️ Revisar /alertas; ataque persistente o falso positivo",
                            raw=True,
                        ),
                    monitor="watch_hunter_verify",
                    )

            _known_blocked = current_blocked

            # Verificar que el bloqueo se aplicó realmente (30s después)
            now_ts = _time_module.time()
            for ip, verify_at in list(_hunter_blocked_verify.items()):
                if now_ts < verify_at:
                    continue
                del _hunter_blocked_verify[ip]
                current = shomer_api.get_blocked_ips() or []
                still_blocked = any(x["ip"] == ip for x in current)
                if not still_blocked:
                    await _send_critical(
                        bot,
                        _a(
                            "⚠️", "Bloqueo pendiente en firewall",
                            f"<code>{_html.escape(str(ip))}</code> registrada pero no aplicada. "
                            f"➡️ Verificar credenciales en panel Hunter → Firewall",
                            raw=True,
                        ),
                    monitor="watch_hunter_verify",
                    )
            _tick("watch_hunter_verify")
        except Exception as e:
            _tick("watch_hunter_verify", error=str(e)); log.debug("watch_hunter_verify error: %s", e)
        await asyncio.sleep(60)


# ── Docker: salud del container ───────────────────────────────────────────────

_docker_restart_count_prev: Optional[int] = None
_docker_alerted = False
_AGENT_RESTART_MARKER = os.environ.get("AGENT_RESTART_MARKER", "/app/data/.agent_last_start")

async def watch_docker(bot: Bot) -> None:
    """
    Detecta reinicios del propio agente comparando un marcador de arranque
    persistido en /app/data (volumen Docker, sobrevive reinicios). No usa
    `docker inspect`/docker.sock -- el agente no tiene el socket de Docker
    montado por seguridad (un bot con acceso a docker.sock podría controlar
    cualquier container del host) y el binario `docker` ni siquiera existe
    dentro de la imagen, así que ese chequeo nunca pudo funcionar (fallaba
    siempre con "[Errno 2] No such file or directory: 'docker'").
    """
    await asyncio.sleep(5)
    try:
        now_ts = _time_module.time()
        prev_ts = None
        if os.path.exists(_AGENT_RESTART_MARKER):
            try:
                with open(_AGENT_RESTART_MARKER) as f:
                    prev_ts = float(f.read().strip())
            except Exception:
                prev_ts = None
        with open(_AGENT_RESTART_MARKER, "w") as f:
            f.write(str(now_ts))
        if prev_ts:
            mins = int((now_ts - prev_ts) / 60)
            ago = f"{mins} min" if mins < 60 else f"{mins // 60} h"
            # 24 ago: ya no manda mensaje suelto -- queda anotado para el
            # próximo reporte (07:00 o 22:00, el que venga primero).
            _agregar_nota_reporte("watch_docker", f"⚠️ Agente reiniciado — último arranque hace {ago}")
        _tick("watch_docker")
    except Exception as e:
        _tick("watch_docker", error=str(e)); log.debug("watch_docker error: %s", e)

    # Vivo = sigue corriendo. No hay más que chequear sin docker.sock --
    # este tick periódico solo confirma que el loop del agente no se colgó.
    while True:
        await asyncio.sleep(300)
        _tick("watch_docker")


# ── Conectividad: interfaces y WAN del servidor ───────────────────────────────

_iface_state_prev: Dict[str, str] = {}
_server_wan_alert = False

async def watch_connectivity(bot: Bot) -> None:
    """
    Cada 3 min verifica:
    - Cambios UP/DOWN en interfaces del servidor
    - NIC de gestión sin IP (crítico)
    - NIC espejo caída (Hunter queda ciego)
    - WAN propia del servidor
    """
    await asyncio.sleep(110)

    while True:
        try:
            import subprocess
            ifaces = shomer_api.get_interfaces()

            for iface in ifaces:
                name  = iface["name"]
                state = iface["state"]
                prev  = _iface_state_prev.get(name)

                if prev is not None and state != prev:
                    if state == "DOWN":
                        if "enp4" in name or "eth1" in name or "ens4" in name:
                            msg = _a(
                                "🟠", "Cable espejo desconectado",
                                f"{name} — Hunter no ve tráfico. "
                                f"➡️ Revisar cable SPAN; panel Hunter → Pipeline",
                                raw=True,
                            )
                        elif "enp2" in name or "eth0" in name or "ens3" in name:
                            msg = _a(
                                "🔴", "Cable gestión desconectado",
                                f"{name} — panel puede quedar inaccesible",
                                raw=True,
                            )
                        else:
                            msg = _a(
                                "🔴", "Interfaz de red caída",
                                f"{name} DOWN",
                                raw=True,
                            )
                        await _send_critical(bot, msg, monitor="watch_connectivity")
                    elif state == "UP" and prev == "DOWN":
                        await _send(
                            bot,
                            _a("✅", "Interfaz recuperada", f"{name} UP", raw=True),
                        monitor="watch_connectivity",
                        )

                _iface_state_prev[name] = state

            # Verificar WAN del servidor mismo (ping 8.8.8.8)
            wan = shomer_api.get_wan_status()
            global _server_wan_alert
            wan_ok = (wan or {}).get("internet", True)
            if not wan_ok and not _server_wan_alert:
                _server_wan_alert = True
                await _send_critical(
                    bot,
                    _a("🔴", "Servidor sin internet", "alertas e IA pueden fallar"),
                monitor="watch_connectivity",
                )
            elif wan_ok and _server_wan_alert:
                _server_wan_alert = False
                await _send(bot, _a("✅", "Internet recuperada", "servidor Shomer online"), monitor="watch_connectivity")
            _tick("watch_connectivity")
        except Exception as e:
            _tick("watch_connectivity", error=str(e)); log.debug("watch_connectivity error: %s", e)
        await asyncio.sleep(180)


# ── Groq: conectividad y modo degradado ──────────────────────────────────────

_groq_ok = True
_groq_fail_since: Optional[float] = None
_groq_alerted = False
_groq_alert_day = ""   # YYYY-MM-DD del último aviso — tope 1 alerta/día (plan free)

async def watch_groq(bot: Bot) -> None:
    """
    Cada 5 min verifica conectividad con Groq.
    Si falla >10 min: alerta developer (el bot responderá sin IA).
    """
    global _groq_ok, _groq_fail_since, _groq_alerted, _groq_alert_day
    import socket
    await asyncio.sleep(150)

    while True:
        try:
            # Prueba TCP básica
            sock = socket.create_connection(("api.groq.com", 443), timeout=8)
            sock.close()
            tcp_ok = True
        except Exception:
            tcp_ok = False

        ok = False
        # Motivo del fallo para redactar la alerta con la causa REAL:
        #   - sin_conexion : ni siquiera abre el socket TCP (internet/DNS del server)
        #   - limite       : Groq responde pero rechaza por cuota / rate-limit (429) — lo más común en el plan free
        #   - sobrecargado : Groq 503/529 (saturado del lado de ellos)
        #   - error        : otro error de la API
        fail_reason = "sin_conexion"
        if tcp_ok:
            try:
                from groq import Groq as _Groq
                import os as _os
                _test_client = _Groq(api_key=_os.environ["GROQ_API_KEY"], timeout=10.0)
                # Antes esto mandaba un chat real cada 5 min (288 llamadas/día) que
                # GASTABAN cuota del plan free y competían con los monitores. models.list()
                # verifica API + credencial SIN consumir tokens (no toca el límite TPM).
                _test_client.models.list()
                ok = True
            except Exception as _ge:
                # Hay conexión (TCP abrió); el fallo es de la API, casi siempre cuota/límite.
                _emsg = f"{type(_ge).__name__} {_ge}".lower()
                if "429" in _emsg or "rate" in _emsg or "quota" in _emsg or "limit" in _emsg:
                    fail_reason = "limite"
                elif "503" in _emsg or "529" in _emsg or "overload" in _emsg:
                    fail_reason = "sobrecargado"
                else:
                    fail_reason = "error"
                ok = False


        try:
            now_ts = _time_module.time()
            if not ok:
                if _groq_ok:
                    _groq_fail_since = now_ts
                _groq_ok = False
                fail_min = int((now_ts - (_groq_fail_since or now_ts)) / 60)
                _today_str = _time_module.strftime("%Y-%m-%d")
                # Tope 1 alerta/día: en plan free Groq toca su límite varias veces al
                # día; sin este tope llegaban "Groq caído" repetidos. Es informativo.
                if fail_min >= 10 and not _groq_alerted and _groq_alert_day != _today_str:
                    _groq_alerted = True
                    _groq_alert_day = _today_str
                    # Título y detalle según la causa real (no siempre es "sin conexión").
                    _titulo, _detalle = {
                        "limite":       ("Groq — límite de uso (plan free)",
                                         f"{fail_min} min sin responder por cuota/rate-limit — el chat IA usa respaldo. No es caída del hotel."),
                        "sobrecargado": ("Groq — servicio saturado",
                                         f"{fail_min} min con Groq sobrecargado (503/529) — reintenta solo. No es caída del hotel."),
                        "sin_conexion": ("Groq sin conexión",
                                         f"{fail_min} min sin salida a api.groq.com — revisar internet/DNS del servidor."),
                    }.get(fail_reason,
                          ("Groq no responde",
                           f"{fail_min} min con error de la API de Groq — el chat IA usa respaldo."))
                    await _send(
                        bot,
                        _a("⚠️", _titulo, _detalle, raw=True),
                    monitor="watch_groq",
                    )
            else:
                # Solo avisar recuperación si la caída fue lo bastante larga como para
                # haberse anunciado (_groq_alerted). Antes esto avisaba "recuperado" hasta
                # por blips de un solo ciclo (5 min) que nunca llegaron a anunciarse como
                # caídos — generando mensajes huérfanos sin valor real. Corregido 8 jun 2026.
                if not _groq_ok and _groq_alerted:
                    fail_min = int((now_ts - (_groq_fail_since or now_ts)) / 60)
                    await _send(
                        bot,
                        _a("✅", "Groq restablecido", f"IA sin servicio {fail_min} min — ya responde", raw=True),
                    monitor="watch_groq",
                    )
                _groq_ok = True
                _groq_alerted = False
                _groq_fail_since = None
            _tick("watch_groq")
        except Exception as e:
            _tick("watch_groq", error=str(e)); log.debug("watch_groq error: %s", e)
        await asyncio.sleep(300)


# ── OpenAI: conectividad chat interactivo ─────────────────────────────────────

_openai_ok = True
_openai_fail_since: Optional[float] = None
_openai_alerted = False


async def watch_openai(bot: Bot) -> None:
    """Verifica OpenAI cuando LLM_PROVIDER_INTERACTIVE=openai."""
    global _openai_ok, _openai_fail_since, _openai_alerted
    import socket
    await asyncio.sleep(165)

    while True:
        try:
            if os.environ.get("LLM_PROVIDER_INTERACTIVE", "groq").strip().lower() != "openai":
                _tick("watch_openai")
                await asyncio.sleep(600)
                continue

            ok = False
            try:
                sock = socket.create_connection(("api.openai.com", 443), timeout=8)
                sock.close()
                from core import openai_helper as _oai
                ok = _oai.is_available()
            except Exception:
                ok = False

            now_ts = _time_module.time()
            if not ok:
                if _openai_ok:
                    _openai_fail_since = now_ts
                _openai_ok = False
                fail_min = int((now_ts - (_openai_fail_since or now_ts)) / 60)
                if fail_min >= 10 and not _openai_alerted:
                    _openai_alerted = True
                    await _send(
                        bot,
                        _a(
                            "⚠️", "OpenAI sin conexión",
                            f"{fail_min} min — chat usa Groq",
                            raw=True,
                        ),
                    monitor="watch_openai",
                    )
                    _tick("watch_openai", alerted=True)
            else:
                if not _openai_ok and _openai_alerted:
                    fail_min = int((now_ts - (_openai_fail_since or now_ts)) / 60)
                    await _send(
                        bot,
                        _a("✅", "OpenAI recuperado", f"estuvo caído {fail_min} min", raw=True),
                    monitor="watch_openai",
                    )
                    _tick("watch_openai", alerted=True)
                else:
                    _tick("watch_openai")
                _openai_ok = True
                _openai_alerted = False
                _openai_fail_since = None
        except Exception as e:
            _tick("watch_openai", error=str(e))
            log.debug("watch_openai error: %s", e)
        await asyncio.sleep(300)


async def watch_mikrotik_security(bot: Bot) -> None:
    """
    Monitor de seguridad perimetral — lee logs del firewall Hunter (OpenWrt/Linux) vía SSH.

    Detecta cada 5 min:
    - Pico de drops: delta > DROP_THRESHOLD en el período
    - Atacante individual: >IP_THRESHOLD drops de una misma IP externa
    - Connection flood: >CONN_THRESHOLD conexiones simultáneas activas

    Complementa a Suricata: ve tráfico bloqueado ANTES de entrar al espejo.
    """
    await asyncio.sleep(120)  # warm-up

    POLL   = 300          # 5 minutos
    DROP_T = 80           # drops totales en período para alertar
    IP_T   = 25           # drops de una sola IP para alertar
    CONN_T = 3000         # conexiones simultáneas para alertar

    _last_drops: int = 0
    _alerted_ips: Set[str] = set()
    _conn_alerted: bool = False

    while True:
        try:
            data = shomer_api.get_firewall_security_log()
            if not data.get("ok"):
                _tick("watch_mikrotik_security", error=data.get("error", "firewall no configurado o sin credenciales"))
                await asyncio.sleep(POLL)
                continue

            fw_ip   = data["fw_ip"]
            drops   = data["drop_count"]
            conns   = data["conn_count"]
            top_atk = data["top_attackers"]

            msgs = []

            # 1. Pico de drops en el período
            delta = drops - _last_drops
            if delta >= DROP_T:
                msgs.append(
                    _a(
                        "🛡️", "Firewall bloqueando tráfico sospechoso",
                        f"{delta} intentos rechazados en 5 min — la red está protegida",
                        raw=True,
                    )
                )
            _last_drops = drops

            # 2. IP individual agresiva (nueva)
            for atk in top_atk:
                ip, n = atk["ip"], atk["drops"]
                if n >= IP_T and ip not in _alerted_ips:
                    msgs.append(
                        _a(
                            "🛡️", "IP externa contenida",
                            f"<code>{_html.escape(str(ip))}</code> — {n} intentos bloqueados",
                            raw=True,
                        )
                    )
                    _alerted_ips.add(ip)

            # 3. Connection flood (reset cuando baja)
            if conns >= CONN_T and not _conn_alerted:
                msgs.append(
                    _a(
                        "🟠", "Muchas conexiones en firewall",
                        f"{conns} conexiones — monitorear; panel Hunter si persiste",
                        raw=True,
                    )
                )
                _conn_alerted = True
            elif conns < int(CONN_T * 0.6):
                _conn_alerted = False

            for msg in msgs:
                await _send_critical(bot, msg, monitor="watch_mikrotik_security")
            _tick("watch_mikrotik_security")
        except Exception as e:
            _tick("watch_mikrotik_security", error=str(e)); log.debug("watch_mikrotik_security error: %s", e)
        await asyncio.sleep(POLL)


async def auto_unblock(bot: Bot) -> None:
    """Si BOT_AUTO_UNBLOCK_HOURS > 0, desbloquea IPs que llevan más de X horas sin reincidencia."""
    if _AUTO_UNBLOCK_HOURS <= 0:
        return
    await asyncio.sleep(120)
    from datetime import timezone

    while True:
        try:
            blocked = shomer_api.get_blocked_ips() or []
            now = datetime.now(timezone.utc)
            for item in blocked:
                ip = item.get("ip")
                blocked_at_str = item.get("blocked_at")
                if not ip or not blocked_at_str:
                    continue
                try:
                    blocked_at = datetime.fromisoformat(blocked_at_str.replace("Z", "+00:00"))
                    horas = (now - blocked_at).total_seconds() / 3600
                    if horas >= _AUTO_UNBLOCK_HOURS:
                        ok, msg = shomer_api.unblock_ip(ip)
                        if ok:
                            await _send(
                                bot,
                                _a(
                                    "🔓", "IP liberada automáticamente",
                                    f"<code>{_html.escape(str(ip))}</code> — {horas:.0f} h",
                                    raw=True,
                                ),
                            monitor="auto_unblock",
                            )
                            log.info("Auto-unblock: %s (bloqueada hace %.0fh)", ip, horas)
                except Exception as e:
                    log.debug("auto_unblock parse error %s: %s", ip, e)
            _tick("auto_unblock")
        except Exception as e:
            _tick("auto_unblock", error=str(e)); log.debug("auto_unblock error: %s", e)
        await asyncio.sleep(1800)  # revisar cada 30 min


# ── Inframonitor: caídas, tóner, desconexión de servicio ─────────────────────

_infra_prev_status: Dict[str, str] = {}
_infra_stale_reminded: Set[str] = set()
_infra_toner_level: Dict[str, int] = {}
_infra_paper_alerted: Set[str] = set()
_infra_tcp_down: Set[str] = set()
_infra_loc_alert_ts: Dict[str, float] = {}
_infra_flap_times: Dict[str, list] = {}
_infra_flap_alerted: Set[str] = set()
_infra_offline_streak: Dict[str, int] = {}
_infra_last_checked_at: Dict[str, str] = {}
_infra_snmp_ports_alerted: Dict[str, Set[str]] = {}
_infra_snmp_ports_up: Dict[str, Set[str]] = {}
_infra_vpn_ports_up: Dict[str, Set[str]] = {}
_infra_wave_active_ips: Dict[str, float] = {}
_infra_snmp_port_down_streak: Dict[tuple, int] = {}
_infra_pulse_batches_seen: Dict[str, set] = {}

# VPN — digest agrupado en vez de un mensaje por conexión/desconexión (Sesión 69).
# Antes: 267 mensajes en 40 días (17% del total de alertas), uno por evento individual.
# Ahora: se acumulan y se envían agrupados cada _VPN_DIGEST_INTERVAL_SEC.
_vpn_digest_events: list = []  # [(nombre, usuario, "conectado"|"desconectado")]
_vpn_digest_last_flush: float = 0.0
_infra_seed_done = False

_INFRA_TONER_WARN = int(os.environ.get("INFRA_TONER_WARN_PCT", "15"))
_INFRA_TONER_CRIT = int(os.environ.get("INFRA_TONER_CRIT_PCT", "5"))
_INFRA_STALE_MINS = int(os.environ.get("INFRA_STALE_REMINDER_MINS", "120"))
_INFRA_GROUP_COOLDOWN = int(os.environ.get("INFRA_GROUP_COOLDOWN_SEC", "1800"))
_INFRA_FLAP_WINDOW = int(os.environ.get("INFRA_FLAP_WINDOW_SEC", "21600"))  # 6 h

# Ubicaciones placeholder del inventario — NO son un sitio físico real.
# Agrupar por ellas genera spam falso ("2 equipos sin respuesta — Por confirmar…").
_INFRA_LOC_PLACEHOLDERS = {
    "",
    "por confirmar",
    "por confirmar ubicacion",
    "por confirmar ubicación",
    "sin ubicacion",
    "sin ubicación",
    "n/a",
    "na",
    "unknown",
    "desconocida",
}


def _infra_location_key(raw: Optional[str]) -> str:
    """Normaliza ubicación; placeholders → '' (no agrupar como sitio común)."""
    loc = (raw or "").strip()
    if not loc:
        return ""
    norm = (
        loc.lower()
        .replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u")
    )
    if norm in _INFRA_LOC_PLACEHOLDERS or norm.startswith("por confirmar"):
        return ""
    return loc

_INFRA_FLAP_MIN = int(os.environ.get("INFRA_FLAP_MIN_CHANGES", "4"))
# Chequeos consecutivos "offline" (~120s c/u, ciclo de este watcher) antes de avisar
# caída real -- evita que un blip de unos segundos (cola de hilos, ping perdido)
# dispare "Equipo Infra caído" + "recuperado" sin que haya pasado nada real.
_INFRA_OFFLINE_CONFIRM = int(os.environ.get("INFRA_OFFLINE_CONFIRM_CHECKS", "2"))
_INFRA_OFFLINE_CONFIRM_PRINTER = int(os.environ.get("INFRA_OFFLINE_CONFIRM_PRINTER", "3"))


def _infra_offline_confirm_needed(device_type: str, monitor_profile: Optional[str] = None) -> int:
    mp = (monitor_profile or "").strip()
    if device_type in ("printer", "pos") or mp == "printer":
        return _INFRA_OFFLINE_CONFIRM_PRINTER
    return _INFRA_OFFLINE_CONFIRM


_INFRA_SNMP_TYPES = {"switch", "router", "server", "nas", "controller"}
_INFRA_SNMP_PORT_ALERTS = os.environ.get("INFRA_SNMP_PORT_ALERTS", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
_INFRA_SNMP_PORT_DEBOUNCE = int(os.environ.get("INFRA_SNMP_PORT_DEBOUNCE_POLLS", "2"))
_INFRA_VPN_ALERT_DISCONNECT = os.environ.get("INFRA_VPN_ALERT_DISCONNECT", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
# Ventana de agrupación del digest VPN (Sesión 69) — default 30 min.
_VPN_DIGEST_INTERVAL_SEC = max(60, int(os.environ.get("VPN_DIGEST_INTERVAL_SEC", "1800")))


def _is_vpn_iface(port: str) -> bool:
    """OpenVPN/PPP dinámicos en MikroTik (USB Ingeniería — acceso remoto)."""
    n = (port or "").lower()
    return "<ovpn-" in n or "<ppp" in n or "<l2tp-" in n or "<pptp-" in n


def _snmp_physical_ports(ports) -> set:
    return {p for p in (ports or []) if p and not _is_vpn_iface(p)}


def _snmp_vpn_ports(ports) -> set:
    return {p for p in (ports or []) if p and _is_vpn_iface(p)}


def _vpn_user_from_iface(port: str) -> str:
    """<ovpn-sistemas> → sistemas | <ovpn-angy.monroy> → angy.monroy"""
    n = (port or "").strip().strip("<>").lower()
    for prefix in ("ovpn-", "ppp-", "l2tp-", "pptp-"):
        if n.startswith(prefix):
            return n[len(prefix):] or n
    return n or "desconocido"


async def _flush_vpn_digest(bot: Bot) -> bool:
    """Envía un único mensaje agrupando las conexiones/desconexiones VPN
    acumuladas desde el último flush (ventana _VPN_DIGEST_INTERVAL_SEC).

    Sesión 69 — antes cada conexión VPN generaba un mensaje Telegram individual
    (267 mensajes en 40 días, 17% del total de alertas del sitio, para un evento
    puramente informativo). Ahora se agrupa: no se pierde información (todo queda
    igual en memoria_alertas vía el mensaje agrupado), solo baja la frecuencia de
    interrupciones en Telegram.
    """
    global _vpn_digest_last_flush
    now = _time_module.time()
    if not _vpn_digest_events:
        if _vpn_digest_last_flush == 0.0:
            _vpn_digest_last_flush = now
        return False
    if now - _vpn_digest_last_flush < _VPN_DIGEST_INTERVAL_SEC:
        return False

    events = list(_vpn_digest_events)
    _vpn_digest_events.clear()
    _vpn_digest_last_flush = now

    counts: Dict[tuple, int] = {}
    for _name, user, accion in events:
        counts[(user, accion)] = counts.get((user, accion), 0) + 1

    partes = []
    for (user, accion), n in sorted(counts.items(), key=lambda kv: -kv[1]):
        icon = "🔐" if accion == "conectado" else "🔓"
        suf = f" x{n}" if n > 1 else ""
        partes.append(f"{icon} <b>{_html.escape(user)}</b> {accion}{suf}")

    mins = _VPN_DIGEST_INTERVAL_SEC // 60
    await _send(
        bot,
        _a("🔐", f"VPN — últimos {mins} min", " · ".join(partes), raw=True),
        monitor="watch_infra_vpn",
    )
    return True


_WATCH_INFRA_INTERVAL_SEC = max(30, int(os.environ.get("WATCH_INFRA_INTERVAL_SEC", "60")))


async def _process_pulse_ewma_events(bot: Bot, poll_ctx: dict) -> bool:
    """Telegram Pulse EWMA — degradando/recuperado desde poll_context.pulse_events."""
    if not poll_ctx.get("pulse_events") and not poll_ctx:
        return False
    if not poll_ctx.get("pulse_events"):
        return False
    from core import pulse_correlate as _pulse
    batch_id = str(poll_ctx.get("batch_id") or "")
    if not batch_id:
        return False
    seen = _infra_pulse_batches_seen.setdefault(batch_id, set())
    alerted = False
    for ev in poll_ctx.get("pulse_events") or []:
        ip = ev.get("ip") or ""
        trans = ev.get("transition") or ""
        if not ip or not trans:
            continue
        eid = f"{ip}:{trans}"
        if eid in seen:
            continue
        seen.add(eid)
        if trans == "enter_degrading":
            if not _pulse.ewma_alert_allowed(ip):
                continue
            await _send(
                bot,
                _pulse.format_ewma_degrading(ev),
                monitor="equipos_red",
            )
            try:
                shomer_api.pulse_alert_ack(ip)
            except Exception as e:
                log.debug("pulse_alert_ack %s: %s", ip, e)
            alerted = True
        elif trans == "exit_degrading":
            await _send(
                bot,
                _pulse.format_ewma_recovered(ev),
                monitor="equipos_red",
            )
            alerted = True
    if len(_infra_pulse_batches_seen) > 30:
        oldest = next(iter(_infra_pulse_batches_seen))
        _infra_pulse_batches_seen.pop(oldest, None)
    return alerted


def _infra_duration_mins(label: Optional[str]) -> int:
    """Convierte state_duration del panel ('2h 15m', '45m') a minutos."""
    if not label:
        return 0
    total = 0
    hm = re.search(r"(\d+)h", label)
    mm = re.search(r"(\d+)m", label)
    if hm:
        total += int(hm.group(1)) * 60
    if mm:
        total += int(mm.group(1))
    if not hm and not mm:
        sm = re.search(r"(\d+)s", label)
        if sm:
            total += int(sm.group(1)) // 60
    return total


async def watch_infra(bot: Bot) -> None:
    """
    Lee /infra/devices cada WATCH_INFRA_INTERVAL_SEC (default 60s):
    - Caída / recuperación de equipos (Telegram unificado desde el agente)
    - Varios equipos caídos en la misma ubicación (switch/energía)
    - Flapping (muchos cambios de estado en pocas horas)
    - Puertos SNMP: solo alerta UP→DOWN (no puertos vacíos eternamente apagados)
    - Recordatorio si lleva >2 h caído
    - Tóner y papel bajo en impresoras/POS
    - Ping OK pero puerto TCP caído (servicio desconectado)
    """
    global _infra_seed_done
    await asyncio.sleep(100)

    while True:
        eq_alert = pr_alert = svc_alert = snmp_alert = flap_alert = pulse_alert = False
        try:
            snap = shomer_api.get_infra_snapshot()
            devices = snap.get("devices") or []
            from core import pulse_correlate as _pulse
            poll_ctx = snap.get("poll_context") or {}
            last_blip = snap.get("last_blip") or {}
            _cycle_new_offline: List[dict] = []
            _cycle_recoveries: List[dict] = []
            _wave_sent_this_cycle = False

            if await _process_pulse_ewma_events(bot, poll_ctx):
                pulse_alert = True

            if not _infra_seed_done:
                for d in devices:
                    _infra_prev_status[d["ip"]] = d.get("status", "unknown")
                    ip = d["ip"]
                    all_snmp = set(d.get("snmp_up_ports") or [])
                    _infra_snmp_ports_up[ip] = _snmp_physical_ports(all_snmp)
                    _infra_vpn_ports_up[ip] = _snmp_vpn_ports(all_snmp)
                    if d.get("checked_at"):
                        _infra_last_checked_at[ip] = d["checked_at"]
                _infra_seed_done = True
                log.info("watch_infra: %d equipos cargados (sin alerta inicial)", len(devices))
                _tick("watch_infra_equipment")
                _tick("watch_infra_printer")
                _tick("watch_infra_service")
                _tick("watch_infra_snmp")
                _tick("watch_infra_vpn")
                _tick("watch_infra_flap")
                await asyncio.sleep(_WATCH_INFRA_INTERVAL_SEC)
                continue

            offline = [d for d in devices if d.get("status") == "offline" and d.get("device_type") != "ap"]
            now_ts = time.time()

            for d in devices:
                ip = d["ip"]
                name = d.get("name", ip)
                status = d.get("status", "unknown")
                dtype = d.get("device_type", "generic")
                mprofile = d.get("monitor_profile") or ""
                icon = d.get("icon", "📡")
                loc = (d.get("location") or "").strip()
                checked_at = d.get("checked_at")

                if dtype == "ap":
                    continue

                poll_fresh = bool(checked_at) and checked_at != _infra_last_checked_at.get(ip)
                if poll_fresh:
                    _infra_last_checked_at[ip] = checked_at

                confirmed_prev = _infra_prev_status.get(ip)

                if status == "offline":
                    if not poll_fresh:
                        continue
                    streak = _infra_offline_streak.get(ip, 0) + 1
                    _infra_offline_streak[ip] = streak

                    if confirmed_prev != "offline" and streak >= _infra_offline_confirm_needed(dtype, mprofile):
                        # Confirmado tras N chequeos seguidos -- recién aquí es "caída real"
                        flaps = _infra_flap_times.setdefault(ip, [])
                        flaps.append(now_ts)
                        _infra_flap_times[ip] = [
                            t for t in flaps if now_ts - t <= _INFRA_FLAP_WINDOW
                        ]
                        if (
                            len(_infra_flap_times[ip]) >= _INFRA_FLAP_MIN
                            and ip not in _infra_flap_alerted
                        ):
                            window_h = max(1, _INFRA_FLAP_WINDOW // 3600)
                            await _send(
                                bot,
                                _a(
                                    "⚠️", "Flapping detectado",
                                    f"{msgfmt.host(name, ip)} — "
                                    f"{len(_infra_flap_times[ip])} cambios en {window_h} h",
                                    raw=True,
                                ),
                            monitor="equipos_red",
                            )
                            _infra_flap_alerted.add(ip)
                            flap_alert = True

                        # Mapa de decisión de alertas (CLAUDE.md), paso 7 — patrón
                        # crónico. Sesión 69 — mismo criterio que Guardian: equipo ya
                        # identificado como flapper crónico en patrones_detectados
                        # (ej. Bixolon .60 y .243, 94 alertas completas c/u en 40 días)
                        # -> aviso compacto, sin repetir el bloque completo cada caída.
                        _pat = {}
                        try:
                            from core import pattern_analysis as _pa
                            _pat = _pa.get_pattern_for_entity(entity_ip=ip, entity_name=name) or {}
                        except Exception:
                            pass
                        _chronic = _pat.get("ocurrencias", 0) >= _CHRONIC_ALERT_MIN_OCURRENCIAS

                        if _chronic:
                            etiqueta = "Impresora" if dtype in ("printer", "pos") else "Equipo"
                            msg = _a(
                                "🔴", f"{etiqueta} {name} no responde",
                                f"caída #{_pat['ocurrencias']} de un patrón ya conocido "
                                f"({_pat.get('tendencia', 'estable')}) — sin novedad, "
                                "ver /consultar_memoria para histórico",
                                raw=True,
                            )
                        elif dtype in ("printer", "pos"):
                            msg = msgfmt.executive_alert(
                                "alto", "Inframonitor",
                                impacto=f"Impresora {name} no responde — sin imprimir",
                                accion_automatica="Ninguna — Inframonitor solo monitorea, no reinicia equipos de terceros",
                                sugerencia="Verificar alimentación/cable físicamente",
                            ) + _kn(ip)
                        else:
                            ubic = f" — {loc}" if loc else ""
                            msg = msgfmt.executive_alert(
                                "alto", "Inframonitor",
                                impacto=f"Equipo {name}{ubic} no responde",
                                accion_automatica="Ninguna — Inframonitor solo monitorea, no reinicia equipos de terceros",
                                sugerencia="Verificar alimentación/cable físicamente",
                            ) + _kn(ip)

                        if _pulse.blip_recent(poll_ctx, last_blip):
                            if _pulse.should_inform_blip(now_ts):
                                await _send(
                                    bot,
                                    _pulse.format_blip_message(poll_ctx, last_blip),
                                    monitor="equipos_red",
                                )
                                eq_alert = True
                                pulse_alert = True
                            _infra_prev_status[ip] = "offline"
                            continue

                        _cycle_new_offline.append({
                            "ip": ip,
                            "name": name,
                            "location": loc,
                            "device_type": dtype,
                            "monitor_profile": mprofile,
                            "msg": msg,
                        })
                        continue
                    # streak < umbral y aún no confirmado offline → blip silencioso, no se avisa

                else:
                    if poll_fresh:
                        _infra_offline_streak[ip] = 0
                    if confirmed_prev == "offline" and poll_fresh and status in ("online", "degraded"):
                        dur = d.get("state_duration") or ""
                        detail = msgfmt.host(name, ip)
                        if dur:
                            detail += f" · estuvo caído {_html.escape(dur)}"
                        evt = "Impresora recuperada" if dtype in ("printer", "pos") else "Equipo Infra recuperado"
                        rec = {
                            "ip": ip,
                            "name": name,
                            "detail": detail,
                            "evt": evt,
                        }
                        if ip in _infra_wave_active_ips:
                            _cycle_recoveries.append(rec)
                        else:
                            # Mapa de decisión de alertas (CLAUDE.md), paso 6 —
                            # recuperación repetida (mismo criterio que Sesión 71
                            # en Guardian): si el equipo ya está flapeando, no
                            # repetir "recuperado" en cada blip.
                            from core import incident_escalation as _esc
                            if not _esc.is_flapping(ip):
                                await _send(
                                    bot, _a("🟢", evt, detail, raw=True),
                                    reply_markup=_save_kb_recovery(ip),
                                    monitor="equipos_red",
                                )
                                eq_alert = True
                            else:
                                _esc.record_filtered_event(ip, name, "watch_infra")
                    if poll_fresh and status in ("online", "degraded"):
                        _infra_prev_status[ip] = status
                        _infra_wave_active_ips.pop(ip, None)
                    if poll_fresh:
                        _infra_stale_reminded.discard(ip)
                    last_flap = max(_infra_flap_times.get(ip) or [0])
                    if ip in _infra_flap_alerted and now_ts - last_flap > _INFRA_FLAP_WINDOW:
                        _infra_flap_alerted.discard(ip)
                        _infra_flap_times.pop(ip, None)

            # ── Pulse Correlate: oleada o caídas individuales ───────────────
            _wave_thr = _pulse.wave_threshold(poll_ctx)
            if _cycle_new_offline:
                if len(_cycle_new_offline) >= _wave_thr:
                    await _send(
                        bot,
                        _pulse.format_wave_message(_cycle_new_offline, poll_ctx),
                        monitor="equipos_red",
                    )
                    for item in _cycle_new_offline:
                        _infra_prev_status[item["ip"]] = "offline"
                        _infra_stale_reminded.discard(item["ip"])
                        _infra_wave_active_ips[item["ip"]] = now_ts
                    _wave_sent_this_cycle = True
                    eq_alert = True
                    pulse_alert = True
                else:
                    # Mapa de decisión de alertas (CLAUDE.md), paso 5 —
                    # escalamiento crónico. Antes watch_infra no pasaba por
                    # acá (a diferencia de Guardian) -- un switch/impresora
                    # flapeando mandaba un mensaje completo por cada caída,
                    # igual que le pasaba a OFC-COCINA en Guardian (Sesión 71).
                    for item in _cycle_new_offline:
                        async def _send_first(_bot=bot, _item=item):
                            await _send(_bot, _item["msg"], monitor="equipos_red")

                        from core import incident_escalation as _esc
                        await _esc.handle_event(
                            bot, item["ip"], item["name"], "offline",
                            send_first_fn=_send_first, severity="warn",
                        )
                        _infra_prev_status[item["ip"]] = "offline"
                        _infra_stale_reminded.discard(item["ip"])
                        eq_alert = True

            if len(_cycle_recoveries) >= _wave_thr:
                await _send(
                    bot,
                    _pulse.format_wave_recovery(_cycle_recoveries),
                    monitor="equipos_red",
                )
                for item in _cycle_recoveries:
                    _infra_wave_active_ips.pop(item["ip"], None)
                eq_alert = True
                pulse_alert = True
            else:
                from core import incident_escalation as _esc
                for item in _cycle_recoveries:
                    # Mapa de decisión de alertas (CLAUDE.md), paso 6 (igual que arriba).
                    if not _esc.is_flapping(item["ip"]):
                        await _send(
                            bot,
                            _a("🟢", item["evt"], item["detail"], raw=True),
                            reply_markup=_save_kb_recovery(item["ip"]),
                            monitor="equipos_red",
                        )
                        eq_alert = True
                    else:
                        _esc.record_filtered_event(item["ip"], item["name"], "watch_infra")
                    _infra_wave_active_ips.pop(item["ip"], None)

            # ── Varios caídos en la misma ubicación ─────────────────────────
            # Solo ubicaciones reales (switch/piso). Placeholders tipo
            # "Por confirmar ubicación" no agrupan: no implica mismo rack.
            if len(offline) >= 2 and not _wave_sent_this_cycle:
                by_loc: Dict[str, list] = {}
                for d in offline:
                    loc = _infra_location_key(d.get("location"))
                    if not loc:
                        continue
                    by_loc.setdefault(loc, []).append(d)
                for loc_key, devs in by_loc.items():
                    if len(devs) < 2:
                        continue
                    if (now_ts - _infra_loc_alert_ts.get(loc_key, 0)) < _INFRA_GROUP_COOLDOWN:
                        continue
                    names = ", ".join(
                        _html.escape(str(x.get("name", x["ip"]))) for x in devs[:5]
                    )
                    extra = f" (+{len(devs) - 5})" if len(devs) > 5 else ""
                    subtitulo = f"{_html.escape(loc_key)}: {names}{extra}"
                    await _send(
                        bot,
                        _a(
                            "🔴", f"{len(devs)} equipos Infra sin respuesta",
                            subtitulo,
                            raw=True,
                        ),
                    monitor="equipos_red",
                    )
                    _infra_loc_alert_ts[loc_key] = now_ts
                    eq_alert = True

            # ── Sigue caído > N minutos (un aviso por caída) ─────────────────
            for d in offline:
                ip = d["ip"]
                if ip in _infra_stale_reminded:
                    continue
                mins = _infra_duration_mins(d.get("state_duration"))
                if mins >= _INFRA_STALE_MINS:
                    icon = d.get("icon", "📡")
                    await _send(
                        bot,
                        _a(
                            "🔴", "Equipo sigue caído",
                            f"{msgfmt.host(d.get('name', ip), ip)} — "
                            f"~{mins // 60}h {mins % 60}m sin respuesta",
                            raw=True,
                        ),
                    monitor="equipos_red",
                    )
                    _infra_stale_reminded.add(ip)
                    eq_alert = True

            # ── Impresoras: tóner y papel ────────────────────────────────────
            for d in devices:
                if d.get("device_type") not in ("printer", "pos"):
                    continue
                if d.get("status") != "online":
                    continue
                ip = d["ip"]
                name = d.get("name", ip)
                pr = d.get("printer") or {}
                toner = pr.get("toner_pct")
                if toner is not None:
                    last = _infra_toner_level.get(ip)
                    notify = (
                        (last is None and toner <= _INFRA_TONER_WARN)
                        or (last is not None and last > _INFRA_TONER_WARN and toner <= _INFRA_TONER_WARN)
                        or (toner <= _INFRA_TONER_CRIT and (last is None or last > _INFRA_TONER_CRIT))
                    )
                    if notify:
                        icon = "🔴" if toner <= _INFRA_TONER_CRIT else "🟡"
                        await _send(
                            bot,
                            _a(
                                icon, "Tóner bajo",
                                f"{_html.escape(str(name))} — queda ~{toner}%",
                                raw=True,
                            ),
                        monitor="equipos_red",
                        )
                        _infra_toner_level[ip] = toner
                        pr_alert = True
                    elif toner > _INFRA_TONER_WARN:
                        _infra_toner_level.pop(ip, None)

                paper_c = pr.get("paper_current")
                paper_m = pr.get("paper_max")
                paper_low = pr.get("paper_low")
                if paper_low is None and paper_c is not None and paper_m and paper_m > 0:
                    paper_low = paper_c <= max(10, int(paper_m * 0.08))
                if paper_low and ip not in _infra_paper_alerted:
                    trays = pr.get("paper_trays") or []
                    tray_hint = ""
                    if len(trays) > 1:
                        empty_n = sum(1 for t in trays if t.get("state") == "empty")
                        tray_hint = f" ({empty_n}/{len(trays)} bandejas vacías)"
                    await _send(
                        bot,
                        _a(
                            "📄", "Papel bajo",
                            f"{_html.escape(str(name))} — sin papel en bandejas activas{tray_hint}",
                            raw=True,
                        ),
                        monitor="equipos_red",
                    )
                    _infra_paper_alerted.add(ip)
                    pr_alert = True
                if ip in _infra_paper_alerted and pr.get("paper_ok"):
                    _infra_paper_alerted.discard(ip)

            # ── Servicio TCP caído (host responde ping) ───────────────────────
            # Switches L2 suelen no tener HTTPS en :443 — ping basta; evita falsos positivos.
            for d in devices:
                if d.get("status") != "online" or d.get("tcp_ok") != 0:
                    continue
                if d.get("device_type") == "switch":
                    continue
                ip = d["ip"]
                if ip in _infra_tcp_down:
                    continue
                port = d.get("tcp_port", "?")
                await _send(
                    bot,
                    _a(
                        "⚠️", "Servicio desconectado",
                        f"{_html.escape(str(d.get('name', ip)))} — "
                        f"responde ping pero puerto {msgfmt.port_label(port)} no",
                        raw=True,
                    ),
                monitor="equipos_red",
                )
                _infra_tcp_down.add(ip)
                svc_alert = True

            for d in devices:
                ip = d["ip"]
                if d.get("tcp_ok") != 0 and ip in _infra_tcp_down:
                    _infra_tcp_down.discard(ip)
                    await _send(
                        bot,
                        _a(
                            "✅", "Servicio recuperado",
                            f"{_html.escape(str(d.get('name', ip)))} "
                            f"puerto {msgfmt.port_label(d.get('tcp_port', '?'))}",
                            raw=True,
                        ),
                    monitor="equipos_red",
                    )
                    svc_alert = True

            # ── Puertos SNMP: solo transición UP → DOWN (ignora vacíos siempre apagados)
            if _INFRA_SNMP_PORT_ALERTS:
                for d in devices:
                    ip = d["ip"]
                    name = d.get("name", ip)
                    if d.get("status") != "online" or d.get("snmp_ok") != 1:
                        _infra_snmp_ports_up.pop(ip, None)
                        _infra_snmp_ports_alerted.pop(ip, None)
                        _infra_vpn_ports_up.pop(ip, None)
                        continue
                    if d.get("device_type") not in _INFRA_SNMP_TYPES:
                        continue
                    all_up = set(d.get("snmp_up_ports") or [])
                    current_up = _snmp_physical_ports(all_up)
                    prev_up = _snmp_physical_ports(_infra_snmp_ports_up.get(ip, set()))
                    # Poll SNMP incompleto: muchos puertos UP desaparecen de golpe → no alertar
                    if prev_up and len(current_up) < max(1, len(prev_up) // 2):
                        log.debug(
                            "watch_infra: snmp ports %s omitido (poll incompleto %d→%d up)",
                            ip, len(prev_up), len(current_up),
                        )
                        continue
                    for port in prev_up - current_up:
                        key = (ip, port)
                        streak = _infra_snmp_port_down_streak.get(key, 0) + 1
                        _infra_snmp_port_down_streak[key] = streak
                        if streak < _INFRA_SNMP_PORT_DEBOUNCE:
                            continue
                        await _send(
                            bot,
                            _a(
                                "⚠️", f"{_html.escape(str(name))} — puerto sin enlace",
                                _html.escape(port),
                                raw=True,
                            ),
                            monitor="equipos_red",
                        )
                        snmp_alert = True
                        _infra_snmp_ports_alerted.setdefault(ip, set()).add(port)
                    for port in current_up - prev_up:
                        _infra_snmp_port_down_streak.pop((ip, port), None)
                        if port in _infra_snmp_ports_alerted.get(ip, set()):
                            await _send(
                                bot,
                                _a(
                                    "✅", "Puerto recuperado",
                                    f"{_html.escape(str(name))} — {_html.escape(port)} UP",
                                    raw=True,
                                ),
                            monitor="equipos_red",
                            )
                            snmp_alert = True
                            _infra_snmp_ports_alerted[ip].discard(port)
                    _infra_snmp_ports_up[ip] = current_up
                    if not _infra_snmp_ports_alerted.get(ip):
                        _infra_snmp_ports_alerted.pop(ip, None)

                    # VPN OpenVPN/PPP — informativo (USB Ingeniería entra/sale del hotel).
                    # Sesión 69: se agrupa en digest (_vpn_digest_events) en vez de un
                    # mensaje Telegram por conexión — ver flush más abajo.
                    current_vpn = _snmp_vpn_ports(all_up)
                    prev_vpn = _snmp_vpn_ports(_infra_vpn_ports_up.get(ip, set()))
                    for port in current_vpn - prev_vpn:
                        user = _vpn_user_from_iface(port)
                        _vpn_digest_events.append((str(name), user, "conectado"))
                    for port in prev_vpn - current_vpn:
                        if not _INFRA_VPN_ALERT_DISCONNECT:
                            continue
                        user = _vpn_user_from_iface(port)
                        _vpn_digest_events.append((str(name), user, "desconectado"))
                    _infra_vpn_ports_up[ip] = current_vpn

            if await _flush_vpn_digest(bot):
                snmp_alert = True

            _tick("watch_infra_equipment", alerted=eq_alert)
            _tick("watch_infra_printer", alerted=pr_alert)
            _tick("watch_infra_service", alerted=svc_alert)
            _tick("watch_infra_snmp", alerted=snmp_alert)
            _tick("watch_infra_vpn", alerted=snmp_alert)
            _tick("watch_infra_flap", alerted=flap_alert)
            _tick("watch_infra_pulse", alerted=pulse_alert)

        except Exception as e:
            err = str(e)
            _tick("watch_infra_equipment", error=err)
            _tick("watch_infra_printer", error=err)
            _tick("watch_infra_service", error=err)
            _tick("watch_infra_snmp", error=err)
            _tick("watch_infra_vpn", error=err)
            _tick("watch_infra_flap", error=err)
            _tick("watch_infra_pulse", error=err)
            log.debug("watch_infra error: %s", e)
        await asyncio.sleep(_WATCH_INFRA_INTERVAL_SEC)


# ── Amenazas activas: sin repetir bloqueos ya conocidos ───────────────────────
# watch_hunter avisa bloqueos nuevos. Este monitor solo evita re-alertar al reiniciar.

_active_threats_known_ips: Set[str] = set()


async def watch_active_threats(bot: Bot) -> None:
    """Mantiene estado de IPs bloqueadas sin mensajes periódicos (evita spam)."""
    global _active_threats_known_ips
    await asyncio.sleep(260)
    try:
        seed = shomer_api.get_blocked_ips() or []
        _active_threats_known_ips = {item["ip"] for item in seed if item.get("ip")}
        if _active_threats_known_ips:
            log.info(
                "watch_active_threats: %d IP(s) bloqueada(s) conocidas (sin resumen repetido)",
                len(_active_threats_known_ips),
            )
    except Exception:
        pass
    while True:
        try:
            blocked = shomer_api.get_blocked_ips() or []
            _active_threats_known_ips = {item["ip"] for item in blocked if item.get("ip")}
            _tick("watch_active_threats")
        except Exception as e:
            _tick("watch_active_threats", error=str(e))
            log.debug("watch_active_threats error: %s", e)
        await asyncio.sleep(600)


_audit_last_risk_counts: Optional[tuple] = None  # (criticos, altos) ya avisados
_audit_stale_scan_alerted: bool = False


async def watch_network_audit(bot: Bot) -> None:
    """
    Recordatorio al técnico si:
    1. No se ha hecho auditoría en más de 30 días.
    2. Hay hallazgos críticos/altos pendientes (solo si el conteo sube — no repetir cada 6 h).
    Revisar cada 6 horas. Solo alerta al técnico (no al developer).
    """
    global _audit_last_risk_counts, _audit_stale_scan_alerted
    _NO_AUDIT_DAYS = 30
    _CHECK_INTERVAL = 21600  # 6 horas
    await asyncio.sleep(300)  # espera 5 min al arrancar
    while True:
        try:
            from core import shomer_api
            summary = shomer_api.get_network_audit_summary()
            if not isinstance(summary, dict):
                _tick("watch_network_audit")
                await asyncio.sleep(_CHECK_INTERVAL)
                continue

            last_scan = summary.get("last_scan")
            alerted = False

            # 1. Sin escaneo en 30 días -- 24 ago: anotado, no mensaje suelto
            if not last_scan:
                _agregar_nota_reporte(
                    "watch_network_audit",
                    f"🔍 Auditoría de red pendiente — no hay escaneo registrado. "
                    f"{_HUNTER_RIESGOS_TIPOS}",
                )
                _tick("watch_network_audit", alerted=True)
                await asyncio.sleep(_CHECK_INTERVAL * 4)  # no repetir por 24h
                continue

            scan_ts = last_scan.get("started_at") or ""
            if scan_ts:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(scan_ts.replace("Z","") + "+00:00")
                    days_ago = (datetime.now(timezone.utc) - dt).days
                    if days_ago >= _NO_AUDIT_DAYS and not _audit_stale_scan_alerted:
                        _agregar_nota_reporte(
                            "watch_network_audit",
                            f"🔍 Auditoría de red atrasada — hace {days_ago} días sin escanear. "
                            f"{_HUNTER_RIESGOS_TIPOS}",
                        )
                        _audit_stale_scan_alerted = True
                        alerted = True
                except Exception:
                    pass

            # 2. Hallazgos críticos/altos pendientes — solo si sube el conteo
            by_sev = summary.get("by_severity", {})
            criticos = int(by_sev.get("critico", 0) or 0)
            altos    = int(by_sev.get("alto", 0) or 0)
            risk_key = (criticos, altos)
            if criticos == 0 and altos == 0:
                _audit_last_risk_counts = (0, 0)
            elif (criticos > 0 or altos > 0) and not alerted:
                prev = _audit_last_risk_counts or (0, 0)
                if risk_key > prev:
                    partes = []
                    if criticos > 0:
                        partes.append(f"{criticos} crítico{'s' if criticos > 1 else ''}")
                    if altos > 0:
                        partes.append(f"{altos} alto{'s' if altos > 1 else ''}")
                    counts = ", ".join(partes)
                    _agregar_nota_reporte(
                        "watch_network_audit",
                        f"⚠️ Riesgos de red pendientes — {counts}. {_HUNTER_RIESGOS_TIPOS}",
                    )
                    _audit_last_risk_counts = risk_key
                    alerted = True

            _tick("watch_network_audit", alerted=alerted)
        except Exception as e:
            _tick("watch_network_audit", error=str(e))
            log.debug("watch_network_audit error: %s", e)
        await asyncio.sleep(_CHECK_INTERVAL)


_PORT_ERRORS_BASELINE: Dict[str, Dict[str, int]] = {}  # {ip -> {port_name -> in_errors+out_errors}}
_PORT_ERRORS_BASELINE_FILE = "/app/data/port_errors_baseline.json"

_PORT_CAUSES = [
    "Cable dañado o conector RJ45 mal crimpado",
    "Duplex mismatch (un lado forzado, el otro en auto)",
    "Tarjeta de red defectuosa en el equipo conectado",
    "Interferencia eléctrica (cable cerca de alimentación eléctrica o A/C)",
    "Puerto del switch degradado",
]


def _load_port_baseline() -> None:
    import json as _json
    global _PORT_ERRORS_BASELINE
    try:
        with open(_PORT_ERRORS_BASELINE_FILE) as f:
            _PORT_ERRORS_BASELINE = _json.load(f)
    except Exception:
        _PORT_ERRORS_BASELINE = {}


def _save_port_baseline(data: Dict[str, Dict[str, int]]) -> None:
    import json as _json
    global _PORT_ERRORS_BASELINE
    _PORT_ERRORS_BASELINE = data
    try:
        with open(_PORT_ERRORS_BASELINE_FILE, "w") as f:
            _json.dump(data, f)
    except Exception:
        pass


async def watch_port_errors(bot: Bot) -> None:
    """
    Informe diario de errores de puerto en switches/routers con SNMP.
    24 ago: ya no manda su propio mensaje -- calcula a las 06:58 (2 min
    antes del reporte de la mañana) y anota, para que daily_summary (07:00)
    lo encuentre listo. Compara contadores actuales contra el baseline del
    día anterior — reporta solo los incrementos nuevos. Causas y
    recomendación generadas por IA (Groq).
    """
    _load_port_baseline()
    await asyncio.sleep(120)
    while True:
        try:
            now = datetime.now()
            # Calcular segundos hasta las 06:58 (2 min antes del reporte 07:00)
            target = now.replace(hour=6, minute=58, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_sec = (target - now).total_seconds()
            await asyncio.sleep(wait_sec)
        except Exception:
            await asyncio.sleep(3600)
            continue

        try:
            switches = shomer_api.get_switch_port_errors()
            if not switches:
                _tick("watch_port_errors")
                continue

            # Construir snapshot actual {ip -> {port -> total_errors}}
            current: Dict[str, Dict[str, int]] = {}
            for sw in switches:
                current[sw["ip"]] = {
                    p["name"]: p["in_errors"] + p["out_errors"]
                    for p in sw["ports"]
                }

            # Calcular deltas respecto al baseline
            _ERROR_THRESHOLD = 10  # errores nuevos en 24h para reportar
            report_lines = []
            for sw in switches:
                ip = sw["ip"]
                prev = _PORT_ERRORS_BASELINE.get(ip, {})
                deltas = []
                for p in sw["ports"]:
                    total = p["in_errors"] + p["out_errors"]
                    prev_total = prev.get(p["name"], total)  # si no hay baseline, asumir igual (no alarmar)
                    delta = total - prev_total
                    if delta >= _ERROR_THRESHOLD:
                        speed = f" ({p['speed_mbps']}M)" if p.get("speed_mbps") else ""
                        deltas.append(f"  {p['name']}{speed} → +{delta:,} errores")
                if deltas:
                    report_lines.append(f"<b>{sw['name']}</b>")
                    report_lines.extend(deltas)

            # Actualizar baseline siempre (para el día siguiente)
            _save_port_baseline(current)

            if not report_lines:
                _tick("watch_port_errors")
                continue

            # Generar diagnóstico con IA
            causes_txt = "\n".join(f"• {c}" for c in _PORT_CAUSES)
            diag_prompt = (
                f"Un switch de red tiene errores nuevos en puertos de red hoy:\n"
                f"{chr(10).join(report_lines)}\n\n"
                f"Las causas más comunes son:\n{causes_txt}\n\n"
                f"En una sola oración corta: ¿cuál es la causa más probable y qué debe revisar primero el técnico? "
                f"Responde solo en español, sin listas, máximo 25 palabras."
            )
            try:
                diagnosis = explain(diag_prompt, level="tecnico")
            except Exception:
                diagnosis = "Revisar cables físicos en los puertos con errores, comenzando por el de mayor incremento."

            # Armar nota para el reporte de la mañana (24 ago: ya no manda solo)
            body = "\n".join(report_lines)
            nota = (
                f"📊 <b>Errores de puerto</b>\n"
                f"{body}\n"
                f"💡 <i>{diagnosis}</i> "
                f"Empezar por el puerto con más errores nuevos, cable físico primero."
            )
            _agregar_nota_reporte("watch_port_errors", nota)
            _tick("watch_port_errors", alerted=True)

        except Exception as e:
            _tick("watch_port_errors", error=str(e))
            log.debug("watch_port_errors error: %s", e)


# ── Análisis de patrones — Groq correlaciona eventos reales del sitio ───────

PATTERN_ANALYSIS_INTERVAL = int(os.environ.get("PATTERN_ANALYSIS_INTERVAL_SEC", str(6 * 3600)))


async def watch_pattern_analysis(bot: Bot) -> None:
    """Cada N horas (default 6h): busca correlaciones reales en auto_task_runs +
    status_events (Guardian) + infra_events (Inframonitor). Sin Telegram propio
    a propósito — solo guarda en BD; se consulta vía chat (L5) o /salud futuro."""
    from core import pattern_analysis

    await asyncio.sleep(300)
    while True:
        try:
            nuevos = await asyncio.to_thread(pattern_analysis.run_pattern_detection_sync)
            if nuevos:
                log.info("pattern_analysis: %d patrón(es) nuevo(s)", len(nuevos))
            _tick("watch_pattern_analysis")
        except Exception as e:
            _tick("watch_pattern_analysis", error=str(e))
            log.debug("watch_pattern_analysis error: %s", e)
        await asyncio.sleep(PATTERN_ANALYSIS_INTERVAL)


# ── Memoria unificada — sync incremental de solo lectura (réplica local) ────

MEMORIA_SYNC_INTERVAL = int(os.environ.get("MEMORIA_SYNC_INTERVAL_SEC", "180"))


async def watch_memoria_sync(bot: Bot) -> None:
    """Cada 3 min (default): copia incidentes nuevos de Guardian/Infra/auto_task
    a la memoria propia del bot. Solo lectura sobre las fuentes — nunca escribe
    ahí. Todo el razonamiento futuro (vigilante, investigación, chat) debe leer
    de memoria_central, no de las fuentes en vivo."""
    from core import memoria_central

    await asyncio.sleep(90)
    while True:
        try:
            counts = await asyncio.to_thread(memoria_central.run_sync_once)
            total = sum(counts.values())
            if total:
                log.info("memoria_sync: %d eventos nuevos %s", total, counts)
            _tick("watch_memoria_sync")
        except Exception as e:
            _tick("watch_memoria_sync", error=str(e))
            log.debug("watch_memoria_sync error: %s", e)
        await asyncio.sleep(MEMORIA_SYNC_INTERVAL)


# ── Opción 2 (24 ago) — releva lo que Guardian encola en vez de mandar
# directo. Formato consistente (mismo _send que todo lo demás, mismo
# prefijo de sitio, misma auditoría en memoria_alertas + telegram_enviados).
# Si esto no releva en 60s, shomer_telegram_relay.py (lado network_monitor)
# lo manda directo como respaldo -- ver ese módulo para el porqué.
PENDING_GUARDIAN_POLL_SEC = int(os.environ.get("PENDING_GUARDIAN_POLL_SEC", "10"))


async def watch_pending_guardian(bot: Bot) -> None:
    await asyncio.sleep(20)
    while True:
        try:
            import sqlite3
            conn = sqlite3.connect(_TELEGRAM_ENVIADOS_DB, timeout=5)
            try:
                conn.row_factory = sqlite3.Row
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS notificaciones_pendientes ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "ts TEXT DEFAULT (datetime('now')), "
                    "mensaje TEXT NOT NULL, "
                    "estado TEXT DEFAULT 'pendiente', "
                    "procesado_at TEXT)"
                )
                rows = conn.execute(
                    "SELECT id, mensaje FROM notificaciones_pendientes WHERE estado='pendiente'"
                ).fetchall()
                for row in rows:
                    # Marcar DESPUÉS de enviar -- si el envío se cae a mitad de
                    # camino, la fila se queda "pendiente" y el respaldo de
                    # Guardian (60s) la agarra igual. Marcar antes arriesgaría
                    # perderla en silencio si _send() falla puertas adentro.
                    await _send(bot, row["mensaje"], monitor="equipos_red", severity="warn")
                    conn.execute(
                        "UPDATE notificaciones_pendientes SET estado='relevado_bot', "
                        "procesado_at=datetime('now') WHERE id=?",
                        (row["id"],),
                    )
                    conn.commit()
            finally:
                conn.close()
            _tick("watch_pending_guardian")
        except Exception as e:
            _tick("watch_pending_guardian", error=str(e))
            log.debug("watch_pending_guardian error: %s", e)
        await asyncio.sleep(PENDING_GUARDIAN_POLL_SEC)


def start_all(bot: Bot) -> None:
    triage.init(bot, _send)
    from core import incident_escalation
    incident_escalation.init(bot, _send)
    loop = asyncio.get_event_loop()
    loop.create_task(incident_escalation.watch_cleanup(bot))
    loop.create_task(watch_hunter(bot))
    loop.create_task(watch_devices(bot))
    loop.create_task(daily_summary(bot))
    loop.create_task(evening_summary(bot))
    loop.create_task(watch_resources(bot))
    loop.create_task(watch_backups(bot))
    loop.create_task(watch_wan_outage(bot))
    loop.create_task(watch_services(bot))
    loop.create_task(watch_disk(bot))
    loop.create_task(watch_pipeline(bot))
    loop.create_task(preventive_reboot(bot))
    loop.create_task(weekly_backup(bot))
    loop.create_task(watch_guardian_nodes(bot))
    loop.create_task(auto_unblock(bot))
    loop.create_task(watch_protector_retry(bot))
    loop.create_task(watch_hunter_verify(bot))
    loop.create_task(watch_docker(bot))
    loop.create_task(watch_connectivity(bot))
    loop.create_task(watch_groq(bot))
    loop.create_task(watch_openai(bot))
    loop.create_task(watch_mikrotik_security(bot))
    loop.create_task(watch_network_audit(bot))
    loop.create_task(watch_protector_sample(bot))
    loop.create_task(watch_log_truncate(bot))
    loop.create_task(watch_pattern_analysis(bot))
    loop.create_task(watch_memoria_sync(bot))
    loop.create_task(watch_infra(bot))
    loop.create_task(watch_active_threats(bot))
    loop.create_task(watch_port_errors(bot))
    loop.create_task(watch_pending_guardian(bot))
    tasks_cfg = auto_tasks.get_tasks_config()
    log.info(
        "Monitores iniciados (28 tasks) — triage=%s auto_tasks=%s escalation=%s",
        triage.is_enabled(),
        tasks_cfg or "{}",
        incident_escalation.is_enabled(),
    )
