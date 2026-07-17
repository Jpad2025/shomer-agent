"""Journal filtrado para diagnóstico IA — solo fallas de servicios Shomer.

No indexa el journal completo. Extrae un recorte corto (≤ ~2–3 KB) cuando
hay un fallo de servidor, para pasarlo a explain()/chat sin ruido.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("shomer-journal-context")

# Servicios del servidor Shomer (no equipos del hotel)
JOURNAL_UNITS: Dict[str, str] = {
    "guardian": "shomer-guardian.service",
    "poller": "shomer-inframonitor-poller.service",
    "tools": "shomer-tools.service",
    "suricata": "suricata.service",
    "redis": "redis-server.service",
    "nginx": "nginx.service",
    "docker": "docker.service",
}

JOURNAL_LABELS: Dict[str, str] = {
    "guardian": "Guardian (API)",
    "poller": "Inframonitor poller",
    "tools": "Tools (Protector/Tracker)",
    "suricata": "Suricata (Hunter)",
    "redis": "Redis",
    "nginx": "Nginx",
    "docker": "Docker",
}

_ERROR_RE = re.compile(
    r"(error|failed|failure|fatal|timeout|oom|killed|panic|"
    r"no space|disk full|refused|traceback|exception|critical)",
    re.I,
)

_MAX_CHARS = 2500
_MAX_LINES = 40
_SINCE = os.environ.get("JOURNAL_CTX_SINCE", "2 hours ago")


def _run_journalctl(args: List[str], timeout: int = 12) -> Tuple[bool, str]:
    """Intenta journalctl local; si falla (container), SSH al host."""
    jctl = shutil.which("journalctl")
    if jctl:
        try:
            r = subprocess.run(
                [jctl, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            out = (r.stdout or "").strip()
            if out:
                return True, out
        except Exception as e:
            log.debug("journalctl local: %s", e)

    # Fallback SSH (mismo patrón que shomer_api / repair)
    ssh = shutil.which("ssh")
    key = "/app/data/agent_restart_key"
    if not ssh or not os.path.exists(key):
        # Host sin container: a veces journalctl existe pero sin permiso
        return False, ""
    ssh_user = os.environ.get("HOST_SSH_USER", "usb_admin")
    remote_cmd = "journalctl " + " ".join(
        f"'{a}'" if any(c in a for c in " |;&") else a for a in args
    )
    try:
        r = subprocess.run(
            [
                ssh, "-i", key,
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=5",
                f"{ssh_user}@127.0.0.1",
                remote_cmd + " 2>&1",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
        out = (r.stdout or r.stderr or "").strip()
        if out and "Permission denied" not in out:
            return True, out
        return False, out
    except Exception as e:
        log.debug("journalctl ssh: %s", e)
        return False, str(e)


def _filter_lines(raw: str, prefer_errors: bool = True) -> List[str]:
    lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return []
    if prefer_errors:
        hits = [ln for ln in lines if _ERROR_RE.search(ln)]
        if hits:
            # Mantener un poco de contexto: últimas N del total, priorizando errores
            tail = lines[-_MAX_LINES:]
            merged: List[str] = []
            seen = set()
            for ln in hits[-(_MAX_LINES // 2) :] + tail:
                if ln not in seen:
                    seen.add(ln)
                    merged.append(ln)
            lines = merged[-_MAX_LINES:]
        else:
            lines = lines[-_MAX_LINES:]
    else:
        lines = lines[-_MAX_LINES:]
    return lines


def _clip(text: str) -> str:
    if len(text) <= _MAX_CHARS:
        return text
    return text[: _MAX_CHARS - 20] + "\n…[recortado]"


def get_unit_journal(
    unit_key: str,
    *,
    lines: int = _MAX_LINES,
    since: str = _SINCE,
) -> Dict[str, object]:
    """Recorte de journal de un servicio conocido."""
    unit = JOURNAL_UNITS.get(unit_key)
    label = JOURNAL_LABELS.get(unit_key, unit_key)
    if not unit:
        return {"ok": False, "key": unit_key, "label": label, "text": "", "error": "servicio no listado"}

    ok, raw = _run_journalctl(
        ["-u", unit, "--since", since, "-n", str(max(lines, _MAX_LINES)),
         "--no-pager", "--output=short-iso"],
    )
    if not ok or not raw:
        return {"ok": False, "key": unit_key, "label": label, "unit": unit, "text": "", "error": raw or "sin datos"}
    if "-- No entries --" in raw or not raw.strip():
        return {"ok": False, "key": unit_key, "label": label, "unit": unit, "text": "", "error": "sin entradas recientes"}

    filtered = _filter_lines(raw)
    text = _clip("\n".join(filtered))
    return {
        "ok": True,
        "key": unit_key,
        "label": label,
        "unit": unit,
        "text": text,
        "line_count": len(filtered),
    }


def get_host_journal_signals(
    *,
    since: str = _SINCE,
    lines: int = 80,
) -> Dict[str, object]:
    """Journal del host filtrado a señales de disco/OOM/reinicio (no todo el sistema)."""
    queries = [
        ["-b", "-0", "--since", since, "-n", str(lines),
         "--no-pager", "--output=short-iso", "-p", "err..alert"],
        ["--since", since, "-n", str(lines),
         "--no-pager", "--output=short-iso",
         "-u", "shomer-guardian.service",
         "-u", "shomer-inframonitor-poller.service",
         "-u", "shomer-tools.service",
         "-u", "suricata.service",
         "-u", "redis-server.service"],
        ["--since", since, "-n", str(lines), "--no-pager", "--output=short-iso"],
    ]
    raw = ""
    for args in queries:
        ok, candidate = _run_journalctl(args)
        if ok and candidate and "-- No entries --" not in candidate:
            raw = candidate
            break
    if not raw:
        return {"ok": False, "text": "", "error": "sin señales recientes"}

    interesting = [
        ln for ln in raw.splitlines()
        if (_ERROR_RE.search(ln)
            or re.search(r"(reboot|shutdown|started.*shomer|oom|Out of memory|No space)", ln, re.I))
        and "UFW BLOCK" not in ln
    ]
    if not interesting:
        interesting = [ln for ln in raw.splitlines() if "UFW BLOCK" not in ln][-25:]
    text = _clip("\n".join(interesting[-_MAX_LINES:]))
    return {"ok": bool(text), "text": text, "line_count": len(interesting)}


def format_context_block(payload: Dict[str, object], title: str = "Journal filtrado") -> str:
    if not payload.get("ok") or not payload.get("text"):
        err = payload.get("error") or "sin líneas útiles"
        return f"{title}: ({err})"
    label = payload.get("label") or payload.get("unit") or ""
    hdr = f"{title}" + (f" — {label}" if label else "")
    return f"{hdr}:\n{payload['text']}"


def diagnose_with_journal(
    situation: str,
    *,
    unit_key: Optional[str] = None,
    host_signals: bool = False,
) -> str:
    """
    Genera 1–2 frases de causa probable usando journal filtrado + explain().
    Si Groq falla, devuelve el recorte crudo corto (sin inventar).
    """
    chunks: List[str] = []
    if unit_key:
        chunks.append(format_context_block(get_unit_journal(unit_key), "Journal servicio"))
    if host_signals:
        chunks.append(format_context_block(get_host_journal_signals(), "Journal host (señales)"))

    context = "\n\n".join(c for c in chunks if c)
    if not context or "sin " in context.lower() and "Journal" in context and len(context) < 80:
        return ""

    try:
        from core.groq_helper import explain

        prompt = (
            f"Situación: {situation}\n\n"
            "Con SOLO el journal filtrado del contexto, di en máximo 2 frases en español: "
            "causa más probable y qué revisar primero. "
            "Si el journal no alcanza para saberlo, dilo sin inventar."
        )
        return (explain(prompt, context=context, level="tecnico") or "").strip()
    except Exception as e:
        log.debug("diagnose_with_journal: %s", e)
        # Fallback: primeras líneas del journal, sin IA
        snippet = context.split("\n")[1:4]
        return " · ".join(s.strip() for s in snippet if s.strip())[:240]
