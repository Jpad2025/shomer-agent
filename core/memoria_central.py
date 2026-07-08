"""Memoria unificada del bot — bitácora en BD aparte (memoria.db).

No escribe en network_monitor.db. Sincroniza incrementalmente (solo lectura)
desde Shomer + registra copia local de alertas Telegram del bot.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

log = logging.getLogger("shomer-memoria")

MEMORIA_DB = os.environ.get("MEMORIA_DB_PATH", "/app/data/memoria.db")
NETWORK_MONITOR_DB = os.environ.get(
    "NETWORK_MONITOR_DB_PATH", "/storage/db/network_monitor.db"
)
KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")
RETENTION_DAYS = int(os.environ.get("MEMORIA_RETENTION_DAYS", "180"))
# status_events es canónico desde jun 2026; infra_events legacy duplica filas en bitácora
SYNC_INFRA_LEGACY = os.environ.get("MEMORIA_SYNC_INFRA_LEGACY", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)


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
                batch_id TEXT DEFAULT '',
                severity TEXT DEFAULT 'info',
                UNIQUE(source, ts, entity_ip, event, batch_id)
            );
            CREATE INDEX IF NOT EXISTS idx_memoria_entity ON memoria_incidentes(entity_ip, ts);
            CREATE INDEX IF NOT EXISTS idx_memoria_ts ON memoria_incidentes(ts);
            CREATE INDEX IF NOT EXISTS idx_memoria_source ON memoria_incidentes(source, ts);

            CREATE TABLE IF NOT EXISTS memoria_alertas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT (datetime('now')),
                monitor TEXT DEFAULT '',
                severity TEXT DEFAULT 'info',
                summary TEXT NOT NULL,
                body TEXT DEFAULT '',
                sent_ok INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_memoria_alertas_ts ON memoria_alertas(ts);

            CREATE TABLE IF NOT EXISTS memoria_checkpoints (
                source TEXT PRIMARY KEY,
                last_id INTEGER DEFAULT 0
            );
            """
        )
        _migrate_incidentes_columns(con)
        con.commit()
        con.close()
    except Exception as e:
        log.warning("memoria_central init: %s", e)


def _migrate_incidentes_columns(con: sqlite3.Connection) -> None:
    """Añade columnas nuevas sin romper BD existente."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(memoria_incidentes)")}
    if "batch_id" not in cols:
        con.execute("ALTER TABLE memoria_incidentes ADD COLUMN batch_id TEXT DEFAULT ''")
    if "severity" not in cols:
        con.execute("ALTER TABLE memoria_incidentes ADD COLUMN severity TEXT DEFAULT 'info'")


init_db()


def _get_checkpoint(con: sqlite3.Connection, source: str) -> int:
    row = con.execute(
        "SELECT last_id FROM memoria_checkpoints WHERE source=?", (source,)
    ).fetchone()
    return row[0] if row else 0


def _set_checkpoint(con: sqlite3.Connection, source: str, last_id: int) -> None:
    con.execute(
        "INSERT INTO memoria_checkpoints (source, last_id) VALUES (?, ?) "
        "ON CONFLICT(source) DO UPDATE SET last_id=excluded.last_id",
        (source, last_id),
    )


def _open_source_ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)


def _severity_for_status(prev: str, status: str) -> str:
    if status == "offline":
        return "warn"
    if prev == "offline" and status in ("online", "degraded"):
        return "info"
    if status == "degraded":
        return "info"
    return "info"


def _sync_status_events(mem_con: sqlite3.Connection) -> int:
    """status_events (Guardian + Inframonitor) — fuente canónica post-deploy."""
    try:
        src = _open_source_ro(NETWORK_MONITOR_DB)
    except Exception as e:
        log.debug("memoria sync: status_events no disponible: %s", e)
        return 0
    try:
        last_id = _get_checkpoint(mem_con, "status_events")
        rows = src.execute(
            "SELECT id, ts, source, name, ip, device_type, prev_status, status, "
            "reason, batch_id, loss_pct "
            "FROM status_events WHERE id > ? ORDER BY id ASC LIMIT 500",
            (last_id,),
        ).fetchall()
    except Exception as e:
        log.debug("memoria sync: status_events query: %s", e)
        src.close()
        return 0
    finally:
        try:
            src.close()
        except Exception:
            pass
    for r in rows:
        _id, ts, src_name, name, ip, dtype, prev, status, reason, batch_id, loss = r
        src_key = (src_name or "unknown").lower()
        if src_key not in ("guardian", "infra"):
            src_key = src_key or "unknown"
        detail_parts = [reason or ""]
        if loss is not None:
            detail_parts.append(f"loss={loss}%")
        detail = " | ".join(p for p in detail_parts if p)
        mem_con.execute(
            "INSERT OR IGNORE INTO memoria_incidentes "
            "(ts, source, entity_ip, entity_name, device_type, event, detail, "
            "batch_id, severity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ts,
                src_key,
                ip or "",
                name or ip or "",
                dtype or "",
                f"{prev}→{status}",
                detail[:500],
                batch_id or "",
                _severity_for_status(prev or "", status or ""),
            ),
        )
    if rows:
        _set_checkpoint(mem_con, "status_events", rows[-1][0])
    return len(rows)


def _sync_infra_events(mem_con: sqlite3.Connection) -> int:
    """infra_events legacy (pre status_events) — solo si la tabla existe."""
    try:
        src = _open_source_ro(NETWORK_MONITOR_DB)
    except Exception as e:
        log.debug("memoria sync: infra_events no disponible: %s", e)
        return 0
    try:
        has = src.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='infra_events'"
        ).fetchone()
        if not has:
            return 0
        last_id = _get_checkpoint(mem_con, "infra_legacy")
        rows = src.execute(
            "SELECT e.id, e.ts, e.ip, e.event, d.name, d.device_type "
            "FROM infra_events e LEFT JOIN infra_devices d ON d.ip = e.ip "
            "WHERE e.id > ? ORDER BY e.id ASC LIMIT 500",
            (last_id,),
        ).fetchall()
    except Exception as e:
        log.debug("memoria sync: infra_events query: %s", e)
        return 0
    finally:
        src.close()
    for r in rows:
        mem_con.execute(
            "INSERT OR IGNORE INTO memoria_incidentes "
            "(ts, source, entity_ip, entity_name, device_type, event, detail, batch_id) "
            "VALUES (?, 'infra_legacy', ?, ?, ?, ?, '', '')",
            (r[1], r[2], r[4] or r[2], r[5] or "", r[3]),
        )
    if rows:
        _set_checkpoint(mem_con, "infra_legacy", rows[-1][0])
    return len(rows)


def _sync_auto_task_runs(mem_con: sqlite3.Connection) -> int:
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
    except Exception as e:
        log.debug("memoria sync: auto_task_runs query: %s", e)
        return 0
    finally:
        src.close()
    for r in rows:
        mem_con.execute(
            "INSERT OR IGNORE INTO memoria_incidentes "
            "(ts, source, entity_name, event, detail, batch_id) "
            "VALUES (?, 'auto_task', ?, ?, ?, '')",
            (r[1], r[2], r[3], (r[4] or "")[:200]),
        )
    if rows:
        _set_checkpoint(mem_con, "auto_task", rows[-1][0])
    return len(rows)


def _prune(mem_con: sqlite3.Connection) -> None:
    cutoff = f"-{RETENTION_DAYS} days"
    mem_con.execute(
        "DELETE FROM memoria_incidentes WHERE ts < datetime('now', ?)", (cutoff,)
    )
    mem_con.execute(
        "DELETE FROM memoria_alertas WHERE ts < datetime('now', ?)", (cutoff,)
    )


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def log_telegram_alert(
    monitor: str,
    text: str,
    *,
    sent_ok: bool = True,
    severity: str = "info",
) -> None:
    """Copia local de cada alerta Telegram del bot (no toca network_monitor.db)."""
    plain = _strip_html(text)
    if not plain:
        return
    lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
    summary = (lines[0] if lines else plain)[:240]
    body = plain[:4000]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        con = sqlite3.connect(MEMORIA_DB, timeout=3)
        con.execute(
            "INSERT INTO memoria_alertas (ts, monitor, severity, summary, body, sent_ok) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, (monitor or "bot")[:80], severity[:16], summary, body, 1 if sent_ok else 0),
        )
        con.commit()
        con.close()
    except Exception as e:
        log.debug("log_telegram_alert: %s", e)


def _ensure_checkpoints(mem_con: sqlite3.Connection) -> None:
    """Migración suave: no re-importar todo al renombrar checkpoint guardian → status_events."""
    if _get_checkpoint(mem_con, "status_events") == 0:
        old = _get_checkpoint(mem_con, "guardian")
        if old:
            _set_checkpoint(mem_con, "status_events", old)


def backfill_status_events(since_ts: str = "2026-06-22") -> Dict[str, int]:
    """Reimporta status_events desde una fecha (corrige source/batch_id). Solo memoria.db."""
    mem_con = sqlite3.connect(MEMORIA_DB, timeout=15)
    result = {"deleted": 0, "from_source": 0, "inserted_attempts": 0}
    try:
        deleted = mem_con.execute(
            "DELETE FROM memoria_incidentes WHERE source IN ('guardian', 'infra') AND ts >= ?",
            (since_ts,),
        ).rowcount
        result["deleted"] = deleted

        src = _open_source_ro(NETWORK_MONITOR_DB)
        try:
            rows = src.execute(
                "SELECT id, ts, source, name, ip, device_type, prev_status, status, "
                "reason, batch_id, loss_pct FROM status_events WHERE ts >= ? ORDER BY id ASC",
                (since_ts,),
            ).fetchall()
            max_id_row = src.execute("SELECT MAX(id) FROM status_events").fetchone()
        finally:
            src.close()

        result["from_source"] = len(rows)
        for r in rows:
            _id, ts, src_name, name, ip, dtype, prev, status, reason, batch_id, loss = r
            src_key = (src_name or "unknown").lower()
            if src_key not in ("guardian", "infra"):
                src_key = src_key or "unknown"
            detail_parts = [reason or ""]
            if loss is not None:
                detail_parts.append(f"loss={loss}%")
            detail = " | ".join(p for p in detail_parts if p)
            mem_con.execute(
                "INSERT OR IGNORE INTO memoria_incidentes "
                "(ts, source, entity_ip, entity_name, device_type, event, detail, "
                "batch_id, severity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts,
                    src_key,
                    ip or "",
                    name or ip or "",
                    dtype or "",
                    f"{prev}→{status}",
                    detail[:500],
                    batch_id or "",
                    _severity_for_status(prev or "", status or ""),
                ),
            )
            result["inserted_attempts"] += 1

        if max_id_row and max_id_row[0]:
            _set_checkpoint(mem_con, "status_events", int(max_id_row[0]))

        _prune(mem_con)
        mem_con.commit()

        row = mem_con.execute(
            "SELECT source, COUNT(*) FROM memoria_incidentes WHERE ts >= ? GROUP BY source",
            (since_ts,),
        ).fetchall()
        result["by_source_since"] = {r[0]: r[1] for r in row}
    finally:
        mem_con.close()
    return result


def run_sync_once() -> Dict[str, int]:
    """Síncrono — invocar vía asyncio.to_thread() desde el watcher."""
    mem_con = sqlite3.connect(MEMORIA_DB, timeout=3)
    counts: Dict[str, int] = {}
    try:
        _ensure_checkpoints(mem_con)
        counts["status_events"] = _sync_status_events(mem_con)
        if SYNC_INFRA_LEGACY:
            counts["infra_legacy"] = _sync_infra_events(mem_con)
        else:
            counts["infra_legacy"] = 0
        counts["auto_task"] = _sync_auto_task_runs(mem_con)
        _prune(mem_con)
        mem_con.commit()
    finally:
        mem_con.close()
    return counts


def list_incidents(
    hours: int = 48,
    source: Optional[str] = None,
    limit: int = 40,
) -> List[dict]:
    """Incidentes recientes para /bitacora."""
    q = (
        "SELECT ts, source, entity_ip, entity_name, event, detail, batch_id, severity "
        "FROM memoria_incidentes WHERE ts >= datetime('now', ?) "
    )
    params: list = [f"-{max(1, hours)} hours"]
    if source:
        q += "AND source = ? "
        params.append(source.lower())
    q += "ORDER BY ts DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    try:
        con = sqlite3.connect(MEMORIA_DB, timeout=3)
        con.row_factory = sqlite3.Row
        rows = con.execute(q, params).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug("list_incidents: %s", e)
        return []


def list_alerts(hours: int = 48, limit: int = 20) -> List[dict]:
    try:
        con = sqlite3.connect(MEMORIA_DB, timeout=3)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT ts, monitor, severity, summary, sent_ok FROM memoria_alertas "
            "WHERE ts >= datetime('now', ?) ORDER BY ts DESC LIMIT ?",
            (f"-{max(1, hours)} hours", max(1, min(limit, 100))),
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug("list_alerts: %s", e)
        return []


def stats(hours: int = 48) -> dict:
    try:
        con = sqlite3.connect(MEMORIA_DB, timeout=3)
        inc = con.execute(
            "SELECT source, COUNT(*) FROM memoria_incidentes "
            "WHERE ts >= datetime('now', ?) GROUP BY source",
            (f"-{max(1, hours)} hours",),
        ).fetchall()
        alerts = con.execute(
            "SELECT COUNT(*) FROM memoria_alertas WHERE ts >= datetime('now', ?)",
            (f"-{max(1, hours)} hours",),
        ).fetchone()[0]
        batches = con.execute(
            "SELECT COUNT(DISTINCT batch_id) FROM memoria_incidentes "
            "WHERE batch_id != '' AND ts >= datetime('now', ?)",
            (f"-{max(1, hours)} hours",),
        ).fetchone()[0]
        con.close()
        return {
            "by_source": {r[0]: r[1] for r in inc},
            "telegram_alerts": alerts,
            "distinct_batches": batches,
        }
    except Exception as e:
        log.debug("stats: %s", e)
        return {"by_source": {}, "telegram_alerts": 0, "distinct_batches": 0}


def export_incidents_csv(hours: int = 168) -> str:
    """CSV en memoria para descarga o Copilot."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["ts", "source", "entity_ip", "entity_name", "event", "detail", "batch_id", "severity"]
    )
    try:
        con = sqlite3.connect(MEMORIA_DB, timeout=5)
        rows = con.execute(
            "SELECT ts, source, entity_ip, entity_name, event, detail, batch_id, severity "
            "FROM memoria_incidentes WHERE ts >= datetime('now', ?) ORDER BY ts ASC",
            (f"-{max(1, hours)} hours",),
        ).fetchall()
        con.close()
        w.writerows(rows)
    except Exception as e:
        log.warning("export_incidents_csv: %s", e)
    return buf.getvalue()
