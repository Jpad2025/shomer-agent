"""Memoria unificada del bot — réplica local de solo lectura.

No es la BD de Shomer ni la comparte. Sincroniza cada N segundos (incremental,
por checkpoint) desde las fuentes reales (Guardian, Inframonitor, tareas del
bot) hacia una tabla propia. Todo el razonamiento posterior (vigilante,
investigación, chat) lee de ESTA tabla, nunca de las fuentes en vivo —
así Shomer se toca poco y de forma controlada, y el bot puede consultar su
propia copia tantas veces como quiera sin volver a tocar Shomer.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Dict

log = logging.getLogger("shomer-memoria")

MEMORIA_DB = os.environ.get("MEMORIA_DB_PATH", "/app/data/memoria.db")
NETWORK_MONITOR_DB = os.environ.get("NETWORK_MONITOR_DB_PATH", "/storage/db/network_monitor.db")
KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")
RETENTION_DAYS = int(os.environ.get("MEMORIA_RETENTION_DAYS", "180"))


def init_db() -> None:
    try:
        con = sqlite3.connect(MEMORIA_DB)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS memoria_incidentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                source TEXT NOT NULL,
                entity_ip TEXT DEFAULT '',
                entity_name TEXT DEFAULT '',
                device_type TEXT DEFAULT '',
                event TEXT NOT NULL,
                detail TEXT DEFAULT '',
                UNIQUE(source, ts, entity_ip, event)
            );
            CREATE INDEX IF NOT EXISTS idx_memoria_entity ON memoria_incidentes(entity_ip, ts);
            CREATE INDEX IF NOT EXISTS idx_memoria_ts ON memoria_incidentes(ts);
            CREATE TABLE IF NOT EXISTS memoria_checkpoints (
                source TEXT PRIMARY KEY,
                last_id INTEGER DEFAULT 0
            );
            """
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("memoria_central init: %s", e)


init_db()


def _get_checkpoint(con: sqlite3.Connection, source: str) -> int:
    row = con.execute("SELECT last_id FROM memoria_checkpoints WHERE source=?", (source,)).fetchone()
    return row[0] if row else 0


def _set_checkpoint(con: sqlite3.Connection, source: str, last_id: int) -> None:
    con.execute(
        "INSERT INTO memoria_checkpoints (source, last_id) VALUES (?, ?) "
        "ON CONFLICT(source) DO UPDATE SET last_id=excluded.last_id",
        (source, last_id),
    )


def _open_source_ro(path: str) -> sqlite3.Connection:
    # mode=ro: nunca puede escribir por accidente. timeout corto: nunca puede colgar nada.
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)


def _sync_status_events(mem_con: sqlite3.Connection) -> int:
    """Guardian — status_events (APs/routers)."""
    try:
        src = _open_source_ro(NETWORK_MONITOR_DB)
    except Exception as e:
        log.debug("memoria sync: status_events no disponible: %s", e)
        return 0
    try:
        last_id = _get_checkpoint(mem_con, "guardian")
        rows = src.execute(
            "SELECT id, ts, name, ip, device_type, prev_status, status, reason "
            "FROM status_events WHERE id > ? ORDER BY id ASC LIMIT 500",
            (last_id,),
        ).fetchall()
    finally:
        src.close()
    for r in rows:
        mem_con.execute(
            "INSERT OR IGNORE INTO memoria_incidentes "
            "(ts, source, entity_ip, entity_name, device_type, event, detail) "
            "VALUES (?, 'guardian', ?, ?, ?, ?, ?)",
            (r[1], r[3], r[2] or r[3], r[4] or "", f"{r[5]}→{r[6]}", r[7] or ""),
        )
    if rows:
        _set_checkpoint(mem_con, "guardian", rows[-1][0])
    return len(rows)


def _sync_infra_events(mem_con: sqlite3.Connection) -> int:
    """Inframonitor — infra_events (switches, cámaras, impresoras)."""
    try:
        src = _open_source_ro(NETWORK_MONITOR_DB)
    except Exception as e:
        log.debug("memoria sync: infra_events no disponible: %s", e)
        return 0
    try:
        last_id = _get_checkpoint(mem_con, "infra")
        rows = src.execute(
            "SELECT e.id, e.ts, e.ip, e.event, d.name, d.device_type "
            "FROM infra_events e LEFT JOIN infra_devices d ON d.ip = e.ip "
            "WHERE e.id > ? ORDER BY e.id ASC LIMIT 500",
            (last_id,),
        ).fetchall()
    finally:
        src.close()
    for r in rows:
        mem_con.execute(
            "INSERT OR IGNORE INTO memoria_incidentes "
            "(ts, source, entity_ip, entity_name, device_type, event, detail) "
            "VALUES (?, 'infra', ?, ?, ?, ?, '')",
            (r[1], r[2], r[4] or r[2], r[5] or "", r[3]),
        )
    if rows:
        _set_checkpoint(mem_con, "infra", rows[-1][0])
    return len(rows)


def _sync_auto_task_runs(mem_con: sqlite3.Connection) -> int:
    """Bot — auto_task_runs (TASK-001..009: limpiezas, restarts, backups muestrales)."""
    try:
        src = _open_source_ro(KNOWLEDGE_DB)
    except Exception as e:
        log.debug("memoria sync: auto_task_runs no disponible: %s", e)
        return 0
    try:
        last_id = _get_checkpoint(mem_con, "auto_task")
        rows = src.execute(
            "SELECT id, created_at, task_id, action, detail FROM auto_task_runs "
            "WHERE id > ? ORDER BY id ASC LIMIT 500",
            (last_id,),
        ).fetchall()
    finally:
        src.close()
    for r in rows:
        mem_con.execute(
            "INSERT OR IGNORE INTO memoria_incidentes (ts, source, entity_name, event, detail) "
            "VALUES (?, 'auto_task', ?, ?, ?)",
            (r[1], r[2], r[3], (r[4] or "")[:200]),
        )
    if rows:
        _set_checkpoint(mem_con, "auto_task", rows[-1][0])
    return len(rows)


def _prune(mem_con: sqlite3.Connection) -> None:
    mem_con.execute(
        "DELETE FROM memoria_incidentes WHERE ts < datetime('now', ?)",
        (f"-{RETENTION_DAYS} days",),
    )


def run_sync_once() -> Dict[str, int]:
    """Síncrono a propósito — se llama desde asyncio.to_thread() en el watcher."""
    mem_con = sqlite3.connect(MEMORIA_DB, timeout=3)
    counts: Dict[str, int] = {}
    try:
        counts["guardian"] = _sync_status_events(mem_con)
        counts["infra"] = _sync_infra_events(mem_con)
        counts["auto_task"] = _sync_auto_task_runs(mem_con)
        _prune(mem_con)
        mem_con.commit()
    finally:
        mem_con.close()
    return counts
