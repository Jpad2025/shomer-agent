"""Contexto corto Hunter (Suricata/Wazuh) para IA — sin leer eve.json completo.

Misma idea que journal_context: recorte limpio → 1–2 frases.
Las firmas ya se humanizan en hunter_labels; aquí añadimos si es ruido,
si hay que tocar el hotel, y si la IP es interna.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import time
from typing import Any, Dict, Optional

log = logging.getLogger("shomer-hunter-context")

_AI_COOLDOWN_SEC = int(os.environ.get("HUNTER_AI_COOLDOWN_SEC", "25"))
_last_ai_ts = 0.0

# Firmas de listas masivas: no gastar IA; respuesta fija
_LIST_NOISE = re.compile(
    r"(CINS.*Poor Reputation|Dshield|Spamhaus|ET DROP)",
    re.I,
)
_CRITICAL_NEED_AI = re.compile(
    r"(EXPLOIT|MALWARE|TROJAN|RANSOM|CNC|BOTNET)",
    re.I,
)


def _is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip.strip()).is_private
    except Exception:
        return False


def build_alert_snippet(
    ip: str,
    signature: str = "",
    *,
    severity: int = 3,
    firewall_blocked: bool = True,
    block_count: int = 1,
    blocked_by: str = "auto",
) -> Dict[str, Any]:
    """Datos limpios para prompt / Telegram (sin log crudo)."""
    from core.hunter_labels import humanize_hunter_signature

    h = humanize_hunter_signature(signature)
    private = _is_private(ip)
    return {
        "ip": ip,
        "private": private,
        "scope": "interna (hotel)" if private else "externa (internet)",
        "title": h.get("title") or "Amenaza",
        "detail": h.get("detail") or "",
        "risk": h.get("risk") or "medio",
        "action_default": h.get("action") or "",
        "technical": (signature or "")[:160],
        "severity": int(severity or 3),
        "firewall_blocked": bool(firewall_blocked),
        "block_count": int(block_count or 1),
        "blocked_by": blocked_by or "auto",
        "list_noise": bool(_LIST_NOISE.search(signature or "")),
        "needs_ai": bool(
            private
            or _CRITICAL_NEED_AI.search(signature or "")
            or not h.get("technical")
            or (h.get("risk") == "critico")
        ),
    }


def _fixed_hint(snippet: Dict[str, Any]) -> str:
    if snippet.get("private"):
        return (
            "La IP es interna del hotel: no es un ataque de internet. "
            "Hay que identificar qué equipo es y revisar malware o uso no autorizado."
        )
    if snippet.get("list_noise") and not snippet.get("needs_ai"):
        return (
            "Es una lista de reputación en internet (bloqueo preventivo). "
            "El hotel no tiene que hacer nada salvo que sea un proveedor legítimo."
        )
    if snippet.get("risk") == "bajo":
        return (
            "Riesgo bajo — a menudo ruido de operador/VPN. "
            "Confirmar en Hunter antes de alarmar en sitio."
        )
    return ""


def diagnose_hunter_block(
    ip: str,
    signature: str = "",
    *,
    severity: int = 3,
    firewall_blocked: bool = True,
    block_count: int = 1,
    blocked_by: str = "auto",
    force_ai: bool = False,
) -> str:
    """
    1–2 frases: ¿ruido o amenaza? ¿acción en el hotel?
    Usa IA solo cuando aporta (crítico / IP interna / firma rara); si no, texto fijo.
    """
    global _last_ai_ts
    snippet = build_alert_snippet(
        ip, signature,
        severity=severity,
        firewall_blocked=firewall_blocked,
        block_count=block_count,
        blocked_by=blocked_by,
    )

    fixed = _fixed_hint(snippet)
    use_ai = force_ai or snippet.get("needs_ai")
    if not use_ai and fixed:
        return fixed

    now = time.time()
    if use_ai and (now - _last_ai_ts) < _AI_COOLDOWN_SEC and not force_ai:
        return fixed or (
            f"{snippet['title']}: bloqueo ya aplicado. "
            + ("Revisar equipo interno." if snippet["private"] else "Sin acción en sitio.")
        )

    ctx = (
        f"IP: {snippet['ip']} ({snippet['scope']})\n"
        f"Título: {snippet['title']}\n"
        f"Detalle: {snippet['detail']}\n"
        f"Riesgo: {snippet['risk']} · severidad_regla={snippet['severity']}\n"
        f"Firewall_bloqueó: {snippet['firewall_blocked']} · origen={snippet['blocked_by']}\n"
        f"Veces: {snippet['block_count']}\n"
        f"Regla: {snippet['technical']}\n"
        f"Guía base: {snippet['action_default']}"
    )
    try:
        from core.groq_helper import explain

        _last_ai_ts = now
        prompt = (
            "Eres Hunter de Shomer en un hotel. Con SOLO estos datos del bloqueo, "
            "responde en máximo 2 frases en español: "
            "1) si es ruido de internet o amenaza real, "
            "2) si el técnico del hotel debe hacer algo o no. "
            "No inventes IPs ni servicios que no estén en el texto."
        )
        out = (explain(prompt, context=ctx, level="tecnico") or "").strip()
        return out or fixed
    except Exception as e:
        log.debug("diagnose_hunter_block: %s", e)
        return fixed or snippet.get("action_default") or ""
