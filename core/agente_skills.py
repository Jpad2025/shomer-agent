"""agente_skills — memoria operativa L3 (humano) + L4 (auto Green State)."""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

log = logging.getLogger("shomer-agente-skills")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")
SITE_MD_PATHS = (
    "/opt/network_monitor/SITE.md",
    "/app/docs/SITE.md",
)
SITE_EXCERPT_MAX = int(os.environ.get("AGENT_SITE_MD_MAX", "3500"))
SKILLS_CONTEXT_MAX = int(os.environ.get("AGENT_SKILLS_CONTEXT_MAX", "4000"))


def _site_name() -> str:
    return (os.environ.get("SITE_NAME") or "").strip()


def init_db() -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS agente_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site TEXT DEFAULT '',
                trigger_key TEXT NOT NULL,
                trigger_label TEXT NOT NULL,
                action_key TEXT NOT NULL,
                action_label TEXT NOT NULL,
                device_ip TEXT DEFAULT '',
                device_name TEXT DEFAULT '',
                task_id TEXT DEFAULT '',
                source TEXT NOT NULL DEFAULT 'human',
                success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                last_ok_at TEXT,
                last_fail_at TEXT,
                notes TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(site, trigger_key, action_key)
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_agente_skills_ip ON agente_skills(device_ip)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_agente_skills_task ON agente_skills(task_id)"
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("agente_skills init: %s", e)


init_db()


def _upsert(
    *,
    trigger_key: str,
    trigger_label: str,
    action_key: str,
    action_label: str,
    source: str,
    device_ip: str = "",
    device_name: str = "",
    task_id: str = "",
    notes: str = "",
    ok: bool = True,
) -> Optional[int]:
    init_db()
    site = _site_name()
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        row = con.execute(
            "SELECT id, success_count, fail_count FROM agente_skills "
            "WHERE site=? AND trigger_key=? AND action_key=?",
            (site, trigger_key, action_key),
        ).fetchone()
        if row:
            sid, succ, fail = row
            if ok:
                con.execute(
                    """
                    UPDATE agente_skills SET
                        success_count=success_count+1,
                        last_ok_at=datetime('now'),
                        updated_at=datetime('now'),
                        trigger_label=?, action_label=?,
                        device_ip=COALESCE(NULLIF(?,''), device_ip),
                        device_name=COALESCE(NULLIF(?,''), device_name),
                        task_id=COALESCE(NULLIF(?,''), task_id),
                        notes=CASE WHEN ? != '' THEN ? ELSE notes END,
                        source=CASE WHEN source='human' THEN source ELSE ? END
                    WHERE id=?
                    """,
                    (
                        trigger_label,
                        action_label,
                        device_ip,
                        device_name,
                        task_id,
                        notes,
                        notes,
                        source,
                        sid,
                    ),
                )
            else:
                con.execute(
                    """
                    UPDATE agente_skills SET
                        fail_count=fail_count+1,
                        last_fail_at=datetime('now'),
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (sid,),
                )
            con.commit()
            con.close()
            return int(sid)
        cur = con.execute(
            """
            INSERT INTO agente_skills (
                site, trigger_key, trigger_label, action_key, action_label,
                device_ip, device_name, task_id, source,
                success_count, fail_count, notes,
                last_ok_at, last_fail_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                CASE WHEN ? THEN datetime('now') ELSE NULL END,
                CASE WHEN ? THEN NULL ELSE datetime('now') END)
            """,
            (
                site,
                trigger_key,
                trigger_label,
                action_key,
                action_label,
                device_ip or "",
                device_name or "",
                task_id or "",
                source,
                1 if ok else 0,
                0 if ok else 1,
                notes[:2000],
                1 if ok else 0,
                1 if ok else 0,
            ),
        )
        sid = cur.lastrowid
        con.commit()
        con.close()
        log.info("agente_skills +1 %s → %s (%s)", trigger_key, action_key, source)
        return int(sid)
    except Exception as e:
        log.debug("agente_skills upsert: %s", e)
        return None


def record_from_human(
    problem: str,
    action: str,
    *,
    device_ip: str = "",
    device_name: str = "",
    task_id: str = "",
    saved_by: str = "",
) -> Optional[int]:
    """L3 — técnico guarda solución."""
    ip = (device_ip or "").strip()
    tid = (task_id or "").upper()
    if tid:
        trigger_key = f"task:{tid}"
        trigger_label = f"Tarea {tid}: {problem[:120]}"
        action_key = f"task:{tid}"
        action_label = action[:200]
    elif ip:
        trigger_key = f"ip:{ip}"
        trigger_label = f"{device_name or ip}: {problem[:120]}"
        action_key = f"human:{action[:40].lower().replace(' ', '_')}"
        action_label = action[:200]
    else:
        trigger_key = f"general:{problem[:40].lower().replace(' ', '_')}"
        trigger_label = problem[:120]
        action_key = "human:documented"
        action_label = action[:200]
    notes = f"saved_by={saved_by}" if saved_by else ""
    return _upsert(
        trigger_key=trigger_key,
        trigger_label=trigger_label,
        action_key=action_key,
        action_label=action_label,
        source="human",
        device_ip=ip,
        device_name=device_name,
        task_id=tid,
        notes=notes,
        ok=True,
    )


def record_from_task(
    task_id: str,
    *,
    trigger_label: str,
    action_label: str,
    device_ip: str = "",
    green_ok: bool = True,
    detail: str = "",
) -> Optional[int]:
    """L4 — Green State tras TASK automática."""
    tid = task_id.upper()
    return _upsert(
        trigger_key=f"task:{tid}",
        trigger_label=trigger_label[:200],
        action_key=f"auto:{tid}",
        action_label=action_label[:200],
        source="auto",
        device_ip=device_ip,
        task_id=tid,
        notes=detail[:500],
        ok=green_ok,
    )


def record_task_feedback(task_id: str, *, worked: bool, notes: str = "") -> Optional[int]:
    """Feedback explícito del técnico sobre una TASK automática."""
    from core import fmt

    tid = task_id.upper()
    title = fmt.TASK_TITLES.get(tid, tid)
    return _upsert(
        trigger_key=f"task:{tid}",
        trigger_label=f"Feedback técnico — {title}",
        action_key=f"feedback:{tid}",
        action_label=notes[:200] if notes else ("Confirmó que funcionó" if worked else "No resolvió"),
        source="human",
        task_id=tid,
        notes=notes[:500],
        ok=worked,
    )


def list_skills(*, device_ip: str = "", task_id: str = "", limit: int = 15) -> List[Dict[str, Any]]:
    init_db()
    site = _site_name()
    q = "SELECT * FROM agente_skills WHERE site=? "
    params: list = [site]
    if device_ip:
        q += "AND device_ip=? "
        params.append(device_ip)
    if task_id:
        q += "AND task_id=? "
        params.append(task_id.upper())
    q += "ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.row_factory = sqlite3.Row
        rows = con.execute(q, params).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_context_block(*, device_ip: str = "", limit: int = 12) -> str:
    """Bloque L5 para inyectar en chat."""
    skills = list_skills(device_ip=device_ip, limit=limit) if device_ip else list_skills(limit=limit)
    if not skills:
        return ""
    lines = ["Skills aprendidas (agente_skills — usar en diagnósticos):"]
    for s in skills:
        ok = s.get("success_count") or 0
        fail = s.get("fail_count") or 0
        src = s.get("source") or "?"
        lines.append(
            f"- [{src}] {s.get('trigger_label', '?')} → {s.get('action_label', '?')} "
            f"(OK:{ok} fail:{fail})"
        )
        if s.get("device_ip"):
            lines.append(f"  IP: {s['device_ip']}")
        if s.get("task_id"):
            lines.append(f"  TASK: {s['task_id']}")
    text = "\n".join(lines)
    return text[:SKILLS_CONTEXT_MAX]


def load_site_excerpt() -> str:
    """Extracto SITE.md del sitio (L5)."""
    for path in SITE_MD_PATHS:
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    raw = f.read(SITE_EXCERPT_MAX + 500)
                if raw.strip():
                    return f"Configuración del sitio (SITE.md):\n{raw[:SITE_EXCERPT_MAX]}"
        except Exception:
            continue
    return ""


def get_learning_context(*, device_ip: str = "") -> str:
    """Skills + SITE + knowledge reciente para L5."""
    parts = []
    site = load_site_excerpt()
    if site:
        parts.append(site)
    skills = get_context_block(device_ip=device_ip)
    if skills:
        parts.append(skills)
    try:
        from core import shomer_api

        if device_ip:
            hist = shomer_api.get_knowledge(ip=device_ip, limit=3)
        else:
            hist = shomer_api.get_knowledge(limit=5)
        if hist:
            lines = ["Soluciones documentadas recientes:"]
            for h in hist:
                lines.append(
                    f"- {h.get('device_name') or h.get('device_ip') or '?'}: "
                    f"{h.get('problem', '')[:80]} → {h.get('action', '')[:80]}"
                )
            parts.append("\n".join(lines))
    except Exception:
        pass
    return "\n\n".join(parts)[: SKILLS_CONTEXT_MAX + SITE_EXCERPT_MAX]
