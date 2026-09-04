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
