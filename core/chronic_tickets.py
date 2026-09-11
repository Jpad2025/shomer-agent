"""chronic_tickets — pendientes de largo plazo para patrones ya crónicos.

Pedido Juan Pablo (3 sep 2026): cuando pattern_analysis ya reconoce un
equipo como crónico (5+ ocurrencias), en vez de solo silenciarlo para
siempre (Tarea pendiente 2, opción 3), abrir un "pendiente" que:
  - avisa una sola vez al abrirse
  - se recuerda unas pocas veces al día (no cada vez que vuelve a fallar)
  - el técnico lo cierra (se arregló de verdad) o lo pausa (ej. esperando
    un repuesto -- reusa el mismo mecanismo de silencio que ya existe,
    `monitor.set_suppression`, no uno nuevo)

Distinto de incident_escalation.py: ese vive por episodio (ventana de 1h,
se cierra solo si no vuelve a fallar). Esto vive mientras el problema de
fondo siga sin resolverse -- días o semanas, hasta que alguien lo cierre.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any, Optional

log = logging.getLogger("shomer-chronic-tickets")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")


def _init_db() -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS chronic_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                entity_name TEXT NOT NULL,
                fuente TEXT NOT NULL,
                opened_at TEXT DEFAULT (datetime('now')),
                status TEXT NOT NULL DEFAULT 'open',
                closed_at TEXT,
                last_reminder_at TEXT
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_chronic_tickets_open "
            "ON chronic_tickets(status, ip, fuente)"
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("chronic_tickets init: %s", e)


_init_db()


def get_or_create(ip: str, entity_name: str, fuente: str) -> tuple[int, bool]:
    """Devuelve (ticket_id, es_nuevo). Si ya hay uno abierto para esta
    IP+fuente, lo reutiliza en vez de duplicar."""
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT id FROM chronic_tickets WHERE ip=? AND fuente=? AND status='open'",
            (ip, fuente),
        ).fetchone()
        if row:
            return row["id"], False
        cur = con.execute(
            "INSERT INTO chronic_tickets (ip, entity_name, fuente) VALUES (?, ?, ?)",
            (ip, entity_name, fuente),
        )
        con.commit()
        return cur.lastrowid, True
    finally:
        con.close()


def close_ticket(ticket_id: int) -> bool:
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        cur = con.execute(
            "UPDATE chronic_tickets SET status='closed', closed_at=datetime('now') "
            "WHERE id=? AND status='open'",
            (ticket_id,),
        )
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def list_open() -> list[dict[str, Any]]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT * FROM chronic_tickets WHERE status='open' ORDER BY opened_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def mark_reminded(ticket_id: int) -> None:
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        con.execute(
            "UPDATE chronic_tickets SET last_reminder_at=datetime('now') WHERE id=?",
            (ticket_id,),
        )
        con.commit()
    finally:
        con.close()


NETWORK_MONITOR_DB = "/storage/db/network_monitor.db"


def _ips_del_ticket(t: dict[str, Any]) -> list[str]:
    """IPs involucradas: la del ticket más las que el cerebro puso en el nombre.

    Los tickets que abre el cerebro llevan en entity_name la lista de equipos
    del cluster (ej. "🧠 23.218.213.23, 192.73.243.141"), así que el problema
    sigue vivo solo si ALGUNA de ellas sigue bloqueada.
    """
    ips = {(t.get("ip") or "").strip()}
    ips |= set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", t.get("entity_name") or ""))
    return [ip for ip in ips if ip]


def _sigue_bloqueada(ips: list[str]) -> Optional[bool]:
    """True si alguna sigue bloqueada, False si todas fueron liberadas.

    None = no aplica (ninguna de esas IPs pasó nunca por Hunter). En ese caso no
    se toca el ticket: la ausencia de registro no es evidencia de que se resolvió.
    """
    if not ips:
        return None
    try:
        con = sqlite3.connect(f"file:{NETWORK_MONITOR_DB}?mode=ro", uri=True, timeout=3)
    except Exception:
        return None
    try:
        marcas = ",".join("?" * len(ips))
        filas = con.execute(
            f"SELECT ip, unblocked_at FROM blocked_ips WHERE ip IN ({marcas})", ips
        ).fetchall()
    except Exception:
        return None
    finally:
        con.close()
    if not filas:
        return None
    return any(f[1] is None for f in filas)


def cerrar_resueltos_por_evidencia() -> list[dict[str, Any]]:
    """Cierra los pendientes cuyo motivo ya no existe. Devuelve los cerrados.

    Un pendiente que nadie cierra se recuerda para siempre, y si nació de un
    falso positivo el sistema se auto-contamina: el 8 sep 2026 el cerebro abrió
    tickets por IPs que Hunter había bloqueado mal (Akamai, tráfico de
    videollamadas). Esas IPs se liberaron el mismo día, pero los tickets
    siguieron recordándose 3 veces al día durante 3 días por algo que ya no
    existía. Depender de que el técnico los cierre no alcanza: de 9 tickets, 7
    seguían abiertos.
    """
    cerrados: list[dict[str, Any]] = []
    for t in list_open():
        if _sigue_bloqueada(_ips_del_ticket(t)) is False:
            if close_ticket(int(t["id"])):
                t["motivo_cierre"] = (
                    "las IPs que lo originaron fueron liberadas: el bloqueo era "
                    "un falso positivo ya corregido"
                )
                cerrados.append(t)
                log.info("chronic_tickets: #%s cerrado solo — %s",
                         t["id"], t["motivo_cierre"])
    return cerrados


def get_ticket(ticket_id: int) -> Optional[dict[str, Any]]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM chronic_tickets WHERE id=?", (ticket_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()
