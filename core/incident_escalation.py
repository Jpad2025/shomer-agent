"""
Escalamiento de incidentes recurrentes — evita mandar un mensaje Telegram por
cada caída de un equipo que ya está flapping (ej. AP HAB 104: 81 mensajes en
un día, mismo problema físico sin resolver).

Este módulo es el paso 5 (y `is_flapping` el paso 6) del Mapa de decisión de
alertas (CLAUDE.md, Sesión 72) -- pasos 1-4 (ping, blip gateway, blip masivo,
umbral por nodo) ya corrieron antes, en el poller de network_monitor, y ya
decidieron que esto SÍ es un evento real que vale la pena avisar.
Usado por watch_guardian_nodes (wifi) y watch_infra (switches/impresoras/
cámaras/datáfonos, desde v1.1.3) -- mismo entity_key "guardian:{ip}" para
ambos, sin colisión posible porque son conjuntos de IPs distintos.

Ciclo de vida por entidad (ip):
  1. Primera falla -> se manda el aviso normal (sin cambios de formato).
  2. Fallas siguientes dentro de la ventana de agregación (ESCALATION_AGG_WINDOW_SEC)
     -> se cuentan, no se reenvían.
  3. Al cerrar la ventana, si hubo fallas extra -> 1 mensaje resumen con botón
     "Ya lo estoy resolviendo".
  4. Si el técnico confirma -> silencio por ESCALATION_GRACE_HOURS.
  5. Si no confirma en ESCALATION_ACK_TIMEOUT_SEC -> recordatorio.
  6. Si tampoco responde el recordatorio en ESCALATION_REMINDER_TIMEOUT_SEC ->
     escalamiento: aviso al técnico + Telegram al coordinador + correo si hay SMTP.
  7. Si sigue fallando tras la gracia -> se reabre avisando "ya te había avisado".
  8. Sin fallas nuevas por ESCALATION_CLOSE_AFTER_HOURS -> se cierra en silencio
     (o con un aviso de estabilidad, si hubo escalamiento de por medio).

Estado persistido en knowledge.db para sobrevivir reinicios del contenedor
(ver PENDIENTES_LAB.md — 42 reinicios en 40 días).
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import sqlite3 as _sq
import time
from datetime import datetime
from email.message import EmailMessage
from typing import Awaitable, Callable, Dict, Optional

from telegram import Bot

from core import fmt as msgfmt

log = logging.getLogger("shomer-escalation")

_KNOWLEDGE_DB = "/app/data/knowledge.db"


def is_enabled() -> bool:
    return os.environ.get("ESCALATION_ENABLED", "1").strip().lower() in ("1", "true", "yes")


def _agg_window_sec() -> float:
    return max(60.0, float(os.environ.get("ESCALATION_AGG_WINDOW_SEC", "3600")))


def _ack_timeout_sec() -> float:
    return max(60.0, float(os.environ.get("ESCALATION_ACK_TIMEOUT_SEC", "43200")))


def _reminder_timeout_sec() -> float:
    return max(60.0, float(os.environ.get("ESCALATION_REMINDER_TIMEOUT_SEC", "43200")))


def _grace_hours() -> float:
    return max(0.5, float(os.environ.get("ESCALATION_GRACE_HOURS", "4")))


def _grace_visit_hours() -> float:
    """Gracia larga para 'lo reviso en la próxima visita' — problema físico,
    el técnico no está en sitio y solo pasa periódicamente."""
    return max(1.0, float(os.environ.get("ESCALATION_GRACE_VISIT_HOURS", "168")))


def _close_after_hours() -> float:
    return max(1.0, float(os.environ.get("ESCALATION_CLOSE_AFTER_HOURS", "6")))


def _coordinator_chat_id() -> str:
    return (
        os.environ.get("SUPPORT_COORDINATOR_CHAT_ID", "").strip()
        or os.environ.get("AGENT_DEVELOPER_CHAT_ID", "").strip()
    )


# ── Estado en memoria (bot y send_fn inyectados en init, como triage.py) ─────

_bot: Optional[Bot] = None
_send_fn: Optional[Callable] = None
_timers: Dict[str, asyncio.Task] = {}


def init(bot: Bot, send_fn: Callable) -> None:
    global _bot, _send_fn
    _bot = bot
    _send_fn = send_fn
    _init_db()
    _reload_pending_timers()
    if is_enabled():
        log.info(
            "Escalamiento de incidentes activo — ventana %.0fs, ack %.0fs, "
            "recordatorio %.0fs, gracia %.1fh, cierre %.1fh, coordinador=%s",
            _agg_window_sec(), _ack_timeout_sec(), _reminder_timeout_sec(),
            _grace_hours(), _close_after_hours(), _coordinator_chat_id() or "(sin configurar)",
        )


# ── Persistencia (knowledge.db) ──────────────────────────────────────────────

def _init_db() -> None:
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS escalation_incidents (
            entity_key           TEXT PRIMARY KEY,
            entity_name          TEXT,
            ip                   TEXT,
            state                TEXT NOT NULL DEFAULT 'open',
            severity             TEXT DEFAULT 'critical',
            opened_at            REAL,
            last_event_at        REAL,
            window_end_at        REAL,
            digest_sent_at       REAL,
            ack_deadline_at      REAL,
            reminder_deadline_at REAL,
            reminder_sent        INTEGER DEFAULT 0,
            grace_until_at       REAL,
            ack_by               TEXT,
            ack_at               REAL,
            event_count          INTEGER DEFAULT 1,
            reopened_count       INTEGER DEFAULT 0,
            escalated_count      INTEGER DEFAULT 0,
            updated_at           TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS eventos_filtrados (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ts           TEXT NOT NULL DEFAULT (datetime('now')),
            ip           TEXT NOT NULL,
            entity_name  TEXT,
            fuente       TEXT NOT NULL,
            motivo       TEXT NOT NULL,
            event_count  INTEGER
        )""")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_eventos_filtrados_ts ON eventos_filtrados (ts)"
        )


def _get_row(entity_key: str) -> Optional[dict]:
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.row_factory = _sq.Row
        row = conn.execute(
            "SELECT * FROM escalation_incidents WHERE entity_key=?", (entity_key,)
        ).fetchone()
    return dict(row) if row else None


def _create_row(entity_key: str, ip: str, name: str, now: float, severity: str) -> None:
    window_end = now + _agg_window_sec()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute(
            "INSERT INTO escalation_incidents "
            "(entity_key, entity_name, ip, state, severity, opened_at, last_event_at, window_end_at, event_count) "
            "VALUES (?,?,?,'open',?,?,?,?,1) "
            "ON CONFLICT(entity_key) DO UPDATE SET "
            "entity_name=excluded.entity_name, state='open', severity=excluded.severity, "
            "opened_at=excluded.opened_at, last_event_at=excluded.last_event_at, "
            "window_end_at=excluded.window_end_at, event_count=1, "
            "reminder_sent=0, ack_by=NULL, ack_at=NULL, grace_until_at=NULL",
            (entity_key, name, ip, severity, now, now, window_end),
        )


def _bump_event(entity_key: str, now: float) -> None:
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute(
            "UPDATE escalation_incidents SET event_count = event_count + 1, last_event_at=? WHERE entity_key=?",
            (now, entity_key),
        )


def _set_state(entity_key: str, state: str) -> None:
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute("UPDATE escalation_incidents SET state=? WHERE entity_key=?", (state, entity_key))


def _reopen_row(entity_key: str, now: float, severity: str) -> None:
    window_end = now + _agg_window_sec()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute(
            "UPDATE escalation_incidents SET state='open', severity=?, last_event_at=?, window_end_at=?, "
            "event_count=1, reminder_sent=0, ack_by=NULL, ack_at=NULL, grace_until_at=NULL, "
            "reopened_count=reopened_count+1 WHERE entity_key=?",
            (severity, now, window_end, entity_key),
        )


def _mark_digest_sent(entity_key: str, now: float) -> None:
    deadline = now + _ack_timeout_sec()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute(
            "UPDATE escalation_incidents SET state='awaiting_ack', digest_sent_at=?, ack_deadline_at=? "
            "WHERE entity_key=?",
            (now, deadline, entity_key),
        )


def _mark_reminder_sent(entity_key: str, now: float) -> None:
    deadline = now + _reminder_timeout_sec()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute(
            "UPDATE escalation_incidents SET reminder_sent=1, reminder_deadline_at=? WHERE entity_key=?",
            (deadline, entity_key),
        )


def _bump_escalated(entity_key: str) -> None:
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute(
            "UPDATE escalation_incidents SET escalated_count=escalated_count+1 WHERE entity_key=?",
            (entity_key,),
        )


def _fmt_hora(ts) -> str:
    if not ts:
        return "?"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M")
    except Exception:
        return "?"


# ── Temporizadores (patrón igual a triage.py) ────────────────────────────────

def _schedule(entity_key: str, kind: str, delay: float) -> None:
    old = _timers.get(entity_key)
    if old:
        old.cancel()
    _timers[entity_key] = asyncio.create_task(_delayed_fire(entity_key, kind, delay))


async def _delayed_fire(entity_key: str, kind: str, delay: float) -> None:
    try:
        await asyncio.sleep(max(0.0, delay))
        await _fire(entity_key, kind)
    except asyncio.CancelledError:
        pass


async def _fire(entity_key: str, kind: str) -> None:
    row = _get_row(entity_key)
    if not row:
        return
    try:
        if kind == "window" and row["state"] == "open":
            await _flush_digest(entity_key, row)
        elif kind == "ack_timeout" and row["state"] == "awaiting_ack" and not row["reminder_sent"]:
            await _send_reminder(entity_key, row)
        elif kind == "reminder_timeout" and row["state"] == "awaiting_ack" and row["reminder_sent"]:
            await _escalate(entity_key, row)
    except Exception as e:
        log.warning("incident_escalation _fire(%s,%s) error: %s", entity_key, kind, e)


def _reload_pending_timers() -> None:
    now = time.time()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.row_factory = _sq.Row
        rows = conn.execute("SELECT * FROM escalation_incidents WHERE state != 'closed'").fetchall()
    for r in rows:
        key = r["entity_key"]
        if r["state"] == "open" and r["window_end_at"]:
            _schedule(key, "window", max(1.0, r["window_end_at"] - now))
        elif r["state"] == "awaiting_ack" and not r["reminder_sent"] and r["ack_deadline_at"]:
            _schedule(key, "ack_timeout", max(1.0, r["ack_deadline_at"] - now))
        elif r["state"] == "awaiting_ack" and r["reminder_sent"] and r["reminder_deadline_at"]:
            _schedule(key, "reminder_timeout", max(1.0, r["reminder_deadline_at"] - now))
        # 'acknowledged' no necesita temporizador propio — se evalúa en el próximo evento


# ── Mensajes generados por el módulo ─────────────────────────────────────────

def _ack_buttons(ip: str):
    return msgfmt.kb(
        [msgfmt.btn("🔧 Lo resuelvo ahora (remoto)", f"ack_incident:remote:{ip}")],
        [msgfmt.btn("📅 Lo reviso en la próxima visita", f"ack_incident:visit:{ip}")],
    )


_ACK_HINT = "\n<i>O /silenciar {ip} &lt;duración&gt; para otro tiempo (ej. /silenciar {ip} 2d)</i>"


async def _flush_digest(entity_key: str, row: dict) -> None:
    if row["event_count"] <= 1:
        # No volvió a fallar durante la ventana -> se cierra en silencio.
        _set_state(entity_key, "closed")
        return
    ip, name = row["ip"], row["entity_name"]
    now = time.time()
    mins = max(1, int(_agg_window_sec() // 60))
    lines = [
        msgfmt.alert_line(
            "📋", f"{name} sigue fallando",
            f"{row['event_count']} eventos en los últimos {mins} min — mismo problema, "
            "sin novedad adicional. ¿Lo estás resolviendo?",
            raw=True,
        ) + _ACK_HINT.format(ip=ip),
    ]
    await _send_fn(
        _bot, "\n".join(lines), reply_markup=_ack_buttons(ip),
        monitor="equipos_red", severity=row.get("severity") or "warn",
    )
    _mark_digest_sent(entity_key, now)
    _schedule(entity_key, "ack_timeout", _ack_timeout_sec())


async def _send_reminder(entity_key: str, row: dict) -> None:
    ip, name = row["ip"], row["entity_name"]
    hora = _fmt_hora(row["digest_sent_at"])
    lines = [
        msgfmt.alert_line(
            "⚠️", f"Recordatorio — {name} sigue fallando",
            f"te avisé a las {hora} y no respondiste — sigue con el mismo problema",
            raw=True,
        ) + _ACK_HINT.format(ip=ip),
    ]
    await _send_fn(
        _bot, "\n".join(lines), reply_markup=_ack_buttons(ip),
        monitor="equipos_red", severity=row.get("severity") or "warn",
    )
    _mark_reminder_sent(entity_key, time.time())
    _schedule(entity_key, "reminder_timeout", _reminder_timeout_sec())


async def _escalate(entity_key: str, row: dict) -> None:
    ip, name = row["ip"], row["entity_name"]
    hora = _fmt_hora(row["digest_sent_at"])
    lines = [
        msgfmt.alert_line(
            "🚨", f"Escalado — {name}",
            f"sin respuesta desde las {hora} — se avisó al coordinador de soporte",
            raw=True,
        ),
    ]
    await _send_fn(_bot, "\n".join(lines), monitor="equipos_red", severity="critical")
    await _notify_coordinator(ip, name, row)
    _set_state(entity_key, "escalated")
    _bump_escalated(entity_key)


async def _notify_coordinator(ip: str, name: str, row: dict) -> None:
    chat_id = _coordinator_chat_id()
    if chat_id and _bot is not None:
        try:
            texto = (
                "🚨 <b>Escalamiento — sin atender</b>\n"
                f"Equipo: {msgfmt.host(name, ip)}\n"
                f"Eventos acumulados: {row['event_count']}\n"
                f"Primer aviso: {_fmt_hora(row['opened_at'])}\n"
                "Sin respuesta del técnico tras dos avisos."
            )
            await _bot.send_message(chat_id=chat_id, text=texto, parse_mode="HTML")
            try:
                from core.monitor import _registrar_envio_real
                _registrar_envio_real("coordinador", texto)
            except Exception:
                pass
        except Exception as e:
            log.warning("escalation: no se pudo notificar al coordinador por Telegram: %s", e)
    else:
        log.info("escalation: sin SUPPORT_COORDINATOR_CHAT_ID/AGENT_DEVELOPER_CHAT_ID configurado")
    await _send_email(ip, name, row)


def _send_email_sync(subject: str, body: str) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    to_addr = os.environ.get("SUPPORT_EMAIL_TO", "").strip()
    if not host or not to_addr:
        log.info("escalation: SMTP no configurado — omito correo (%s)", subject)
        return
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    pwd = os.environ.get("SMTP_PASS", "").strip()
    from_addr = os.environ.get("SUPPORT_EMAIL_FROM", "").strip() or user or "shomer@localhost"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            if user:
                s.login(user, pwd)
            s.send_message(msg)
    except Exception as e:
        log.warning("escalation: error enviando correo: %s", e)


async def _send_email(ip: str, name: str, row: dict) -> None:
    subject = f"[Shomer] Sin atender — {name} ({ip})"
    body = (
        f"El equipo {name} ({ip}) sigue fallando y no fue atendido por el técnico "
        "tras dos avisos por Telegram.\n\n"
        f"Eventos acumulados: {row['event_count']}\n"
        f"Primer aviso: {_fmt_hora(row['opened_at'])}\n\n"
        "Revisar en el panel Shomer o contactar al técnico del sitio."
    )
    await asyncio.to_thread(_send_email_sync, subject, body)


# ── API pública usada por watch_guardian_nodes ───────────────────────────────

async def handle_event(
    bot: Bot,
    ip: str,
    name: str,
    kind: str,
    *,
    send_first_fn: Callable[[], Awaitable[None]],
    severity: str = "critical",
) -> bool:
    """
    Punto de entrada por cada evento offline/no-internet/degraded de Guardian.
    `send_first_fn` es el envío "rico" original (con pattern_analysis, botón
    reboot, diagnóstico IA, etc.) — solo se llama cuando de verdad hay que
    avisar (incidente nuevo o reapertura tras vencer la gracia).
    Retorna True si se mandó algo al técnico, False si solo se contó en silencio.
    """
    if not is_enabled():
        await send_first_fn()
        return True

    entity_key = f"guardian:{ip}"
    now = time.time()
    row = _get_row(entity_key)

    if row is None or row["state"] == "closed":
        _create_row(entity_key, ip, name, now, severity)
        await send_first_fn()
        _schedule(entity_key, "window", _agg_window_sec())
        return True

    state = row["state"]

    if state == "acknowledged" and now >= (row["grace_until_at"] or 0):
        _reopen_row(entity_key, now, severity)
        ack_hora = _fmt_hora(row["ack_at"])
        lines = [
            msgfmt.alert_line(
                "🔁", f"{name} sigue fallando",
                f"se había marcado en resolución a las {ack_hora} — sigue con el mismo problema",
                raw=True,
            ),
        ]
        await _send_fn(bot, "\n".join(lines), monitor="equipos_red", severity=severity)
        _schedule(entity_key, "window", _agg_window_sec())
        return True

    # open / awaiting_ack / acknowledged-en-gracia / escalated -> silencio, solo contar
    _bump_event(entity_key, now)
    return False


def is_flapping(ip: str) -> bool:
    """True si el incidente Guardian de esta IP ya acumuló más de una falla
    dentro de la ventana de agregación actual (evento 2+, contado en silencio
    por `handle_event`). watch_guardian_nodes lo usa para no repetir 'Nodo
    recuperado' en cada blip de un equipo que está flapeando — la primera
    recuperación de un incidente sí se avisa normal, igual que la primera
    falla (ver docstring del módulo)."""
    row = _get_row(f"guardian:{ip}")
    return bool(row and row["state"] != "closed" and (row["event_count"] or 0) > 1)


def record_filtered_event(ip: str, name: str, fuente: str, motivo: str = "recuperacion_repetida") -> None:
    """Tarea pendiente 2 (14 ago): registra un 'recuperado' suprimido por
    is_flapping -- separa "qué pasó" de "si se avisó" sin tocar esa decisión
    (llamar justo donde ya se decidió no mandar el mensaje)."""
    try:
        row = _get_row(f"guardian:{ip}")
        event_count = (row or {}).get("event_count")
        with _sq.connect(_KNOWLEDGE_DB) as conn:
            conn.execute(
                "INSERT INTO eventos_filtrados (ip, entity_name, fuente, motivo, event_count) "
                "VALUES (?, ?, ?, ?, ?)",
                (ip, name, fuente, motivo, event_count),
            )
    except Exception as e:
        log.debug("record_filtered_event: %s", e)


def acknowledge(
    ip: str, technician: str = "", *, kind: str = "remote", custom_hours: Optional[float] = None,
) -> Optional[dict]:
    """Llamado desde los botones de ack o desde /silenciar <ip> <duración>.
    kind: 'remote' (gracia corta, se puede atender ahora) | 'visit' (gracia
    larga, problema físico que espera a la próxima visita) — ignorado si se
    da custom_hours."""
    entity_key = f"guardian:{ip}"
    row = _get_row(entity_key)
    if not row or row["state"] not in ("awaiting_ack", "open"):
        return None
    now = time.time()
    if custom_hours is not None:
        horas = max(0.1, float(custom_hours))
    elif kind == "visit":
        horas = _grace_visit_hours()
    else:
        horas = _grace_hours()
    grace_until = now + horas * 3600
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute(
            "UPDATE escalation_incidents SET state='acknowledged', ack_by=?, ack_at=?, grace_until_at=? "
            "WHERE entity_key=?",
            (technician, now, grace_until, entity_key),
        )
    old = _timers.pop(entity_key, None)
    if old:
        old.cancel()
    return {"ip": ip, "name": row["entity_name"], "grace_until_at": grace_until}


def close_stale_incidents() -> list[tuple[str, str, bool]]:
    """Cierra incidentes sin fallas nuevas hace ESCALATION_CLOSE_AFTER_HOURS.
    Un incidente 'acknowledged' (ej. gracia de 7 días por 'próxima visita') NO
    se cierra hasta que venza SU gracia, aunque sea más larga que
    ESCALATION_CLOSE_AFTER_HOURS — si no, el próximo evento llegaría como
    incidente "nuevo" y rompería el silencio prometido.
    Retorna (ip, nombre, fue_escalado) por cada uno cerrado."""
    now = time.time()
    threshold = now - _close_after_hours() * 3600
    closed: list[tuple[str, str, bool]] = []
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.row_factory = _sq.Row
        rows = conn.execute(
            "SELECT * FROM escalation_incidents WHERE state != 'closed' AND ("
            "  (state = 'acknowledged' AND grace_until_at < ?)"
            "  OR (state != 'acknowledged' AND last_event_at < ?)"
            ")",
            (now, threshold),
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE escalation_incidents SET state='closed' WHERE entity_key=?", (r["entity_key"],))
            closed.append((r["ip"], r["entity_name"], r["state"] == "escalated"))
            old = _timers.pop(r["entity_key"], None)
            if old:
                old.cancel()
    return closed


async def watch_cleanup(bot: Bot) -> None:
    """Cierra incidentes fríos y avisa estabilidad si hubo escalamiento previo."""
    await asyncio.sleep(150)
    while True:
        try:
            if is_enabled():
                for ip, name, was_escalated in close_stale_incidents():
                    if was_escalated:
                        horas = int(_close_after_hours())
                        lines = [
                            msgfmt.alert_line(
                                "✅", f"{name} estable",
                                f"sin nuevas fallas hace {horas}h — incidente cerrado",
                                raw=True,
                            ),
                        ]
                        await _send_fn(bot, "\n".join(lines), monitor="equipos_red", severity="info")
        except Exception as e:
            log.debug("incident_escalation watch_cleanup error: %s", e)
        await asyncio.sleep(600)
