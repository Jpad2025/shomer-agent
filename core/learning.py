"""Correlación aprendizaje L3–L5 — incident_knowledge ↔ TASK-* ↔ agente_skills."""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Dict, Optional

log = logging.getLogger("shomer-learning")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")

_TASK_KEYWORDS: dict[str, list[str]] = {
    "TASK-001": ["disco", "lleno", "journal", "espacio", "gb libres", "limpieza"],
    "TASK-002": ["guardian", "8000", "panel"],
    "TASK-003": ["tools", "8001", "tracker", "protector"],
    "TASK-004": ["nginx", "https", "8443", "proxy"],
    "TASK-005": ["log", "api.log", "truncar"],
    "TASK-006": ["backup", "protector", "restic", "b2"],
    "TASK-008": ["zombie", "puerto", "8000", "8001"],
    "TASK-009": ["suricata", "pipeline", "amenazas", "espejo"],
}

# TASK T1 — L4 solo si BOT_AUTO_SAFE_ONLY=1
_T1_TASKS = frozenset(
    {"TASK-001", "TASK-002", "TASK-003", "TASK-004", "TASK-005", "TASK-006", "TASK-008", "TASK-009"}
)


def supervised_enabled() -> bool:
    return os.environ.get("BOT_LEARN_SUPERVISED", "0").strip().lower() in ("1", "true", "yes")


def autonomous_enabled() -> bool:
    return os.environ.get("BOT_LEARN_AUTONOMOUS", "0").strip().lower() in ("1", "true", "yes")


def auto_safe_only() -> bool:
    return os.environ.get("BOT_AUTO_SAFE_ONLY", "1").strip().lower() in ("1", "true", "yes")


def infer_task_from_text(problem: str, action: str) -> str | None:
    blob = f"{problem} {action}".lower()
    best_id = None
    best_score = 0
    for task_id, words in _TASK_KEYWORDS.items():
        score = sum(1 for w in words if w in blob)
        if score > best_score:
            best_score = score
            best_id = task_id
    return best_id if best_score >= 2 else None


def record_human_confirmation(task_id: str, source: str = "knowledge") -> None:
    if not supervised_enabled() or not task_id:
        return
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            INSERT INTO auto_task_stats (task_id, human_confirmations, runs_total, runs_ok, green_ok_total)
            VALUES (?, 1, 0, 0, 0)
            ON CONFLICT(task_id) DO UPDATE SET
                human_confirmations = human_confirmations + 1
            """,
            (task_id.upper(),),
        )
        con.commit()
        con.close()
        log.info("learning: +1 confirmación humana %s (%s)", task_id, source)
    except Exception as e:
        log.debug("record_human_confirmation: %s", e)


def on_knowledge_saved(
    problem: str,
    action: str,
    *,
    device_ip: str = "",
    device_name: str = "",
    saved_by: str = "",
) -> Dict[str, Any]:
    """L3 — tras guardar incident_knowledge."""
    task_id = infer_task_from_text(problem, action)
    skill_id = None
    if supervised_enabled():
        try:
            from core import agente_skills

            skill_id = agente_skills.record_from_human(
                problem,
                action,
                device_ip=device_ip,
                device_name=device_name,
                task_id=task_id or "",
                saved_by=saved_by,
            )
        except Exception as e:
            log.debug("on_knowledge_saved skills: %s", e)
    if task_id:
        record_human_confirmation(task_id, "incident_knowledge")
    return {"task_id": task_id, "skill_id": skill_id}


def on_task_completed(result, mode: str) -> None:
    """L4 — tras ejecutar TASK con Green State."""
    if not autonomous_enabled():
        return
    tid = (getattr(result, "task_id", None) or "").upper()
    if not tid or tid == "TASK-010":
        return
    if auto_safe_only() and tid not in _T1_TASKS:
        return
    try:
        from core import agente_skills
        from core import fmt

        title = fmt.TASK_TITLES.get(tid, tid)
        trigger = f"{title} — {result.action}"
        detail = getattr(result, "green_detail", "") or ""
        agente_skills.record_from_task(
            tid,
            trigger_label=trigger,
            action_label=result.action,
            green_ok=bool(getattr(result, "green_ok", False)),
            detail=detail,
        )
        if getattr(result, "green_ok", False):
            log.info("L4 skill auto OK %s (%s)", tid, mode)
    except Exception as e:
        log.debug("on_task_completed: %s", e)


def feedback_suffix(meta: Optional[Dict[str, Any]]) -> str:
    """HTML extra para Telegram tras guardar."""
    if not meta:
        return ""
    tid = meta.get("task_id")
    sid = meta.get("skill_id")
    parts = []
    if tid:
        from core import fmt

        title = fmt.TASK_TITLES.get(tid, tid)
        parts.append(f"📊 Correlacionado con <b>{fmt.e(tid)}</b> ({fmt.e(title)}).")
    if sid and supervised_enabled():
        parts.append(f"🧠 Skill #{sid} actualizada.")
    return "\n" + "\n".join(parts) if parts else ""


def task_feedback_markup(task_id: str):
    """Teclado inline post-TASK — import lazy telegram."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    tid = task_id.upper()
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Funcionó", callback_data=f"save_task:y:{tid}"),
            InlineKeyboardButton("❌ No ayudó", callback_data=f"save_task:n:{tid}"),
        ],
        [
            InlineKeyboardButton("📝 Describir", callback_data=f"save_task:o:{tid}"),
            InlineKeyboardButton("Omitir", callback_data="save_task:x:0"),
        ],
    ])


async def notify_promote_suggestion(bot, task_id: str, runs_ok: int, threshold: int) -> None:
    """Aviso developer — sugerencia promover learning → approved."""
    import os
    from core import fmt

    dev_chat = os.environ.get("AGENT_DEVELOPER_CHAT_ID", "").strip()
    if not dev_chat:
        return
    tid = task_id.upper()
    title = fmt.TASK_TITLES.get(tid, tid)
    text = (
        f"📈 <b>Promoción sugerida</b>\n"
        f"{fmt.e(tid)} — {fmt.e(title)}\n"
        f"Green OK: {runs_ok}/{threshold}\n"
        f"➡️ <code>/aprobar_task {tid}</code> para pasar a approved en este sitio."
    )
    try:
        await bot.send_message(chat_id=int(dev_chat), text=text, parse_mode="HTML")
    except Exception as e:
        log.debug("notify_promote: %s", e)
