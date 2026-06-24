"""Capa D — Catálogo de tareas autónomas (TASK-001…010) con modos off/learning/approved."""
from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import os
import random
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from telegram import Bot

from core import health
from core import repair
from core import shomer_api
from core import access as acc

log = logging.getLogger("shomer-auto-tasks")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")

VERIFY_SEC = float(os.environ.get("AUTO_TASK_VERIFY_SEC", "30"))
COOLDOWN_SEC = float(os.environ.get("AUTO_TASK_COOLDOWN_SEC", "900"))
PROMOTE_AFTER = int(os.environ.get("AUTO_TASK_SUGGEST_PROMOTE_AFTER", "5"))

_MODES = ("off", "learning", "approved")
_last_run: Dict[str, float] = {}

# service_key → task_id
SERVICE_TASK_MAP = {
    "guardian": "TASK-002",
    "tools": "TASK-003",
    "nginx": "TASK-004",
}
TASK_SERVICE_MAP = {v: k for k, v in SERVICE_TASK_MAP.items()}

TASK_CATALOG: Dict[str, str] = {
    "TASK-001": "Limpieza disco safe (≥85 %)",
    "TASK-002": "Restart shomer-guardian (:8000)",
    "TASK-003": "Restart shomer-tools (:8001)",
    "TASK-004": "Restart nginx (:80)",
    "TASK-005": "Truncar logs Shomer >50 MB",
    "TASK-006": "Auditoría muestral Protector (solo lectura)",
    "TASK-007": "Alerta backup >26 h (solo informar)",
    "TASK-008": "Kill zombie puerto 8000/8001",
    "TASK-009": "Restart Suricata (pipeline degradado)",
    "TASK-010": "Reboot AP — prohibido (Guardian Capa A)",
}


@dataclass
class TaskRunResult:
    task_id: str
    ok: bool
    action: str
    green_ok: bool
    green_detail: str
    context: Dict[str, Any] = field(default_factory=dict)
    error: str = ""


def _init_db() -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS auto_task_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                ok INTEGER NOT NULL,
                green_ok INTEGER,
                action TEXT,
                detail TEXT,
                context_json TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS auto_task_stats (
                task_id TEXT PRIMARY KEY,
                runs_total INTEGER DEFAULT 0,
                runs_ok INTEGER DEFAULT 0,
                green_ok_total INTEGER DEFAULT 0,
                human_confirmations INTEGER DEFAULT 0,
                suggested_promote_at TEXT,
                last_run_at TEXT,
                last_mode TEXT
            );
            CREATE TABLE IF NOT EXISTS auto_task_modes (
                task_id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                updated_by TEXT DEFAULT ''
            );
            """
        )
        # Migración columnas nuevas en tablas existentes
        cols = {r[1] for r in con.execute("PRAGMA table_info(auto_task_stats)").fetchall()}
        if "human_confirmations" not in cols:
            con.execute("ALTER TABLE auto_task_stats ADD COLUMN human_confirmations INTEGER DEFAULT 0")
        if "suggested_promote_at" not in cols:
            con.execute("ALTER TABLE auto_task_stats ADD COLUMN suggested_promote_at TEXT")
        con.commit()
        con.close()
    except Exception as e:
        log.warning("auto_task db init: %s", e)


_init_db()


def get_tasks_config() -> Dict[str, str]:
    raw = os.environ.get("BOT_AUTO_TASKS_CONFIG", "{}").strip()
    env_cfg: Dict[str, str] = {}
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for k, v in data.items():
                    mode = str(v).lower()
                    if mode in _MODES:
                        env_cfg[str(k).upper()] = mode
        except json.JSONDecodeError:
            log.warning("BOT_AUTO_TASKS_CONFIG JSON inválido")
    # Overrides en BD (post /aprobar_task)
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        rows = con.execute("SELECT task_id, mode FROM auto_task_modes").fetchall()
        con.close()
        for tid, mode in rows:
            if mode in _MODES:
                env_cfg[str(tid).upper()] = mode
    except Exception:
        pass
    return env_cfg


def get_task_mode(task_id: str) -> str:
    return get_tasks_config().get(task_id.upper(), "off")


def set_task_mode(task_id: str, mode: str, updated_by: str = "") -> bool:
    tid = task_id.upper()
    if mode not in _MODES:
        return False
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            INSERT INTO auto_task_modes (task_id, mode, updated_by, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(task_id) DO UPDATE SET
                mode=excluded.mode, updated_by=excluded.updated_by, updated_at=datetime('now')
            """,
            (tid, mode, updated_by),
        )
        con.commit()
        con.close()
        log.info("auto_task %s → modo %s (by %s)", tid, mode, updated_by)
        return True
    except Exception as e:
        log.warning("set_task_mode: %s", e)
        return False


def get_task_stats(task_id: str) -> Dict[str, Any]:
    tid = task_id.upper()
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        row = con.execute(
            "SELECT runs_total, runs_ok, green_ok_total, human_confirmations, "
            "suggested_promote_at, last_run_at, last_mode FROM auto_task_stats WHERE task_id=?",
            (tid,),
        ).fetchone()
        con.close()
        if not row:
            return {
                "task_id": tid,
                "runs_total": 0,
                "runs_ok": 0,
                "green_ok_total": 0,
                "human_confirmations": 0,
                "mode": get_task_mode(tid),
            }
        return {
            "task_id": tid,
            "runs_total": row[0],
            "runs_ok": row[1],
            "green_ok_total": row[2],
            "human_confirmations": row[3] or 0,
            "suggested_promote_at": row[4],
            "last_run_at": row[5],
            "last_mode": row[6],
            "mode": get_task_mode(tid),
        }
    except Exception:
        return {"task_id": tid, "mode": get_task_mode(tid)}


def list_all_status() -> List[Dict[str, Any]]:
    out = []
    for tid in TASK_CATALOG:
        st = get_task_stats(tid)
        st["label"] = TASK_CATALOG[tid]
        out.append(st)
    return out


def _log_run(result: TaskRunResult, mode: str) -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            INSERT INTO auto_task_runs
            (task_id, mode, ok, green_ok, action, detail, context_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.task_id,
                mode,
                1 if result.ok else 0,
                1 if result.green_ok else 0,
                result.action,
                result.green_detail or result.error,
                json.dumps(result.context, ensure_ascii=False)[:4000],
            ),
        )
        con.execute(
            """
            INSERT INTO auto_task_stats (task_id, runs_total, runs_ok, green_ok_total, last_run_at, last_mode)
            VALUES (?, 1, ?, ?, datetime('now'), ?)
            ON CONFLICT(task_id) DO UPDATE SET
                runs_total = runs_total + 1,
                runs_ok = runs_ok + excluded.runs_ok,
                green_ok_total = green_ok_total + excluded.green_ok_total,
                last_run_at = datetime('now'),
                last_mode = excluded.last_mode
            """,
            (
                result.task_id,
                1 if result.ok else 0,
                1 if result.green_ok else 0,
                mode,
            ),
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("auto_task log_run FALLÓ (task=%s, mode=%s): %s", result.task_id, mode, e)


def _mark_suggested_promote(task_id: str) -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            "UPDATE auto_task_stats SET suggested_promote_at=datetime('now') WHERE task_id=?",
            (task_id.upper(),),
        )
        con.commit()
        con.close()
    except Exception:
        pass


async def _maybe_suggest_promote(bot: Bot, task_id: str, mode: str) -> None:
    if mode != "learning":
        return
    st = get_task_stats(task_id)
    if st.get("suggested_promote_at"):
        return
    runs_ok = st.get("runs_ok", 0)
    if runs_ok < PROMOTE_AFTER:
        return
    _mark_suggested_promote(task_id)
    label = TASK_CATALOG.get(task_id, task_id)
    log.info(
        "TASK %s (%s) — %d/%d OK en learning; promoción vía /aprobar_task",
        task_id, label, runs_ok, PROMOTE_AFTER,
    )
    try:
        from core import learning

        await learning.notify_promote_suggestion(bot, task_id, runs_ok, PROMOTE_AFTER)
    except Exception as e:
        log.debug("suggest_promote notify: %s", e)


def _cooldown_active(task_id: str) -> bool:
    last = _last_run.get(task_id)
    if last is None:
        return False
    import time

    return (time.time() - last) < COOLDOWN_SEC


async def _task_001_disk_cleanup(ctx: Dict[str, Any]) -> TaskRunResult:
    mount = ctx.get("mount", "/")
    pct_before = float(ctx.get("pct", 0))
    label = ctx.get("label", mount)

    results = repair.run_safe_cleanup()
    await asyncio.sleep(VERIFY_SEC)

    if mount == "/":
        green = health.check_disk_improved(pct_before)
    else:
        disk = shomer_api.get_disk_usage()
        part = next(
            (p for p in disk.get("partitions", []) if p.get("mount") == mount),
            None,
        )
        pct_after = float(part.get("pct", pct_before)) if part else pct_before
        green = {
            "ok": pct_after < 80 or pct_after <= pct_before - 2,
            "detail": f"{pct_before}%→{pct_after}%",
            "pct_after": pct_after,
        }

    ok = any(r.get("ok") for r in results) or green.get("ok", False)
    return TaskRunResult(
        task_id="TASK-001",
        ok=ok,
        action=f"Limpieza disco segura en {label}",
        green_ok=bool(green.get("ok")),
        green_detail=str(green.get("detail", "")),
        context={
            "mount": mount,
            "pct_before": pct_before,
            "cleanup_steps": len(results),
            "pct_after": green.get("pct_after"),
        },
    )


async def _task_restart_service(ctx: Dict[str, Any], task_id: str) -> TaskRunResult:
    service_key = ctx.get("service_key") or TASK_SERVICE_MAP.get(task_id, "")
    svc = repair.SERVICES.get(service_key)
    if not svc:
        return TaskRunResult(
            task_id=task_id,
            ok=False,
            action="Restart servicio",
            green_ok=False,
            green_detail="servicio desconocido",
            error=f"key={service_key}",
        )

    label = svc["label"]
    port = svc["port"]
    ok, detail = repair.restart_service(service_key)

    if not ok and get_task_mode("TASK-008") != "off":
        zk_ok, _ = repair.kill_zombie(port)
        if zk_ok:
            ok, detail = repair.restart_service(service_key)
            ctx["zombie_killed"] = True

    await asyncio.sleep(VERIFY_SEC)
    green = health.check_service(service_key)

    return TaskRunResult(
        task_id=task_id,
        ok=ok,
        action=f"Restart {label}",
        green_ok=bool(green.get("ok")),
        green_detail=str(green.get("detail", detail[:120])),
        context={
            "service_key": service_key,
            "label": label,
            "restart_ok": ok,
            "zombie_killed": ctx.get("zombie_killed", False),
        },
        error="" if ok else detail[:200],
    )


async def _task_005_truncate_logs(ctx: Dict[str, Any]) -> TaskRunResult:
    files = repair.truncate_large_shomer_logs()
    truncated = [f["file"] for f in files if f.get("file") != "(ninguno)"]
    had_work = bool(truncated and truncated[0] != "(ninguno)")
    return TaskRunResult(
        task_id="TASK-005",
        ok=True,
        action="Truncar logs Shomer grandes",
        green_ok=True,
        green_detail=f"{len(truncated)} archivo(s)" if had_work else "sin archivos >50MB",
        context={"files": truncated[:10]},
    )


async def _task_006_protector_sample(ctx: Dict[str, Any]) -> TaskRunResult:
    devices = shomer_api.get_backup_devices()
    active = [d for d in devices if d.get("is_active")]
    sample_size = min(3, len(active))
    if sample_size == 0:
        return TaskRunResult(
            task_id="TASK-006",
            ok=True,
            action="Auditoría muestral Protector",
            green_ok=True,
            green_detail="sin equipos activos",
            context={"sample": []},
        )

    picked = random.sample(active, sample_size)
    lines = []
    issues = 0
    max_hours = int(os.environ.get("BACKUP_MAX_HOURS", "26"))
    for d in picked:
        name = d.get("name") or d.get("ip") or "?"
        status = (d.get("last_status") or "desconocido").lower()
        last_at = d.get("last_backup_at") or "nunca"
        ok_dev = status in ("ok", "success", "completed")
        if last_at and last_at != "nunca":
            try:
                from datetime import datetime

                ts = datetime.fromisoformat(last_at.replace("Z", ""))
                horas = (datetime.now() - ts).total_seconds() / 3600
                if horas > max_hours:
                    ok_dev = False
            except Exception:
                pass
        if not ok_dev:
            issues += 1
        icon = "✅" if ok_dev else "⚠️"
        lines.append(f"{icon} {_html.escape(str(name))}: {status} ({last_at})")

    health_api = shomer_api.get_backup_health()
    api_ok = bool(health_api and health_api.get("ok", health_api.get("success")))

    return TaskRunResult(
        task_id="TASK-006",
        ok=True,
        action="Auditoría muestral Protector (solo lectura)",
        green_ok=issues == 0 and api_ok,
        green_detail=f"{issues} problema(s) en {sample_size} equipos",
        context={
            "sample": [d.get("name") for d in picked],
            "issues": issues,
            "api_ok": api_ok,
            "lines": lines,
        },
    )


async def _task_008_kill_zombie(ctx: Dict[str, Any]) -> TaskRunResult:
    port = int(ctx.get("port", 8000))
    service_key = ctx.get("service_key", "guardian" if port == 8000 else "tools")
    ok, detail = repair.kill_zombie(port)
    await asyncio.sleep(5)
    port_green = health.check_port_free(port)
    if ok:
        repair.restart_service(service_key)
        await asyncio.sleep(VERIFY_SEC)
    svc_green = health.check_service(service_key)
    green_ok = bool(port_green.get("ok")) and bool(svc_green.get("ok"))
    return TaskRunResult(
        task_id="TASK-008",
        ok=ok,
        action=f"Kill zombie puerto {port}",
        green_ok=green_ok,
        green_detail=f"{port_green.get('detail')} · {svc_green.get('detail')}",
        context={"port": port, "detail": detail[:120]},
    )


async def _task_009_suricata(ctx: Dict[str, Any]) -> TaskRunResult:
    ok, detail = repair.restart_suricata()
    await asyncio.sleep(VERIFY_SEC)
    green = health.check_suricata_active()
    return TaskRunResult(
        task_id="TASK-009",
        ok=ok,
        action="Restart Suricata",
        green_ok=bool(green.get("ok")),
        green_detail=str(green.get("detail", detail[:80])),
        context={"restart_ok": ok},
    )


async def _task_007_info_only(ctx: Dict[str, Any]) -> TaskRunResult:
    """Solo registro — la alerta la envía el monitor vía triage."""
    return TaskRunResult(
        task_id="TASK-007",
        ok=True,
        action="Alerta backup sin remediación",
        green_ok=True,
        green_detail=ctx.get("problema", "informado"),
        context=ctx,
    )


async def _task_010_blocked(ctx: Dict[str, Any]) -> TaskRunResult:
    return TaskRunResult(
        task_id="TASK-010",
        ok=False,
        action="Reboot AP — prohibido en catálogo",
        green_ok=False,
        green_detail="usar Guardian Capa A",
        error="TASK-010 siempre off",
    )


_HANDLERS = {
    "TASK-001": _task_001_disk_cleanup,
    "TASK-002": lambda ctx: _task_restart_service(ctx, "TASK-002"),
    "TASK-003": lambda ctx: _task_restart_service(ctx, "TASK-003"),
    "TASK-004": lambda ctx: _task_restart_service(ctx, "TASK-004"),
    "TASK-005": _task_005_truncate_logs,
    "TASK-006": _task_006_protector_sample,
    "TASK-007": _task_007_info_only,
    "TASK-008": _task_008_kill_zombie,
    "TASK-009": _task_009_suricata,
    "TASK-010": _task_010_blocked,
}


async def run_task(task_id: str, ctx: Optional[Dict[str, Any]] = None) -> Optional[TaskRunResult]:
    tid = task_id.upper()
    handler = _HANDLERS.get(tid)
    if not handler:
        log.debug("auto_task sin handler: %s", tid)
        return None
    return await handler(ctx or {})


async def maybe_run(
    task_id: str,
    bot: Bot,
    ctx: Dict[str, Any],
    send_fn: Callable,
    send_critical_fn: Optional[Callable] = None,
) -> bool:
    tid = task_id.upper()
    mode = get_task_mode(tid)
    if mode == "off":
        return False
    if tid == "TASK-010":
        return False
    if _cooldown_active(tid):
        log.debug("auto_task %s en cooldown", tid)
        return False

    import time

    _last_run[tid] = time.time()
    result = await run_task(tid, ctx)
    if result is None:
        return False

    _log_run(result, mode)

    try:
        from core import learning

        learning.on_task_completed(result, mode)
    except Exception:
        pass

    if mode in ("learning", "approved"):
        await _notify_result(bot, result, mode, send_fn, send_critical_fn)
        if result.green_ok:
            await _maybe_suggest_promote(bot, tid, mode)
    return True


async def _notify_result(
    bot: Bot,
    result: TaskRunResult,
    mode: str,
    send_fn: Callable,
    send_critical_fn: Optional[Callable],
) -> None:
    from core import ui_notify
    from core import learning

    msg = ui_notify.task_result_message(result.task_id, result, mode)
    fn = send_critical_fn if not result.green_ok else send_fn
    markup = learning.task_feedback_markup(result.task_id) if learning.supervised_enabled() else None
    await fn(bot, msg, markup)
