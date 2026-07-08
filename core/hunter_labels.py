"""Traduce firmas Suricata/ET — copia ligera para el agente (ver app/api/hunter_signature_labels.py)."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_RULE_PATTERNS: List[Tuple[re.Pattern, str, str, str, str]] = [
    (re.compile(r"ET CINS.*Poor Reputation", re.I), "IP con mala reputación (lista CINS)",
     "Dirección reportada por inteligencia de amenazas.", "alto",
     "Shomer ya la bloqueó. No requiere acción en el hotel si no hay quejas."),
    (re.compile(r"ET DROP.*Dshield", re.I), "IP en lista negra DShield",
     "Fuente asociada a ataques reportados.", "alto",
     "Bloqueo preventivo. Revisar solo si es proveedor legítimo."),
    (re.compile(r"ET DROP.*Spamhaus", re.I), "IP en lista Spamhaus DROP",
     "Dirección conocida por spam o malware.", "alto",
     "Bloqueo automático correcto."),
    (re.compile(r"ET DROP", re.I), "IP en lista negra de amenazas",
     "Tráfico desde dirección marcada como peligrosa.", "alto",
     "Shomer bloqueó el acceso."),
    (re.compile(r"ET P2P.*eMule", re.I), "Tráfico P2P sospechoso (eMule)",
     "Posible equipo comprometido o file-sharing.", "medio",
     "Identificar equipo interno y revisar."),
    (re.compile(r"ET SCAN", re.I), "Escaneo de puertos",
     "Reconocimiento de red detectado.", "alto", "Bloqueo recomendado si IP externa."),
    (re.compile(r"ET EXPLOIT", re.I), "Intento de explotación",
     "Patrón de ataque contra servicio vulnerable.", "critico",
     "Verificar parches; mantener bloqueo."),
    (re.compile(r"IKEv2|IKE", re.I), "Tráfico VPN IKEv2 en WAN",
     "Suele ser operador móvil — a menudo falso positivo.", "bajo",
     "Evaluar antes de bloquear."),
]

_RISK_ICON = {"critico": "🔴", "alto": "🟠", "medio": "🟡", "bajo": "🟢", "info": "ℹ️"}
_RISK_LABEL = {"critico": "CRÍTICO", "alto": "ALTO", "medio": "MEDIO", "bajo": "BAJO", "info": "INFO"}


def humanize_hunter_signature(signature: Optional[str]) -> Dict[str, Any]:
    technical = (signature or "").strip()
    if not technical:
        return {
            "title": "Amenaza de red detectada",
            "detail": "Tráfico sospechoso hacia o desde internet.",
            "risk": "medio", "risk_label": "MEDIO", "risk_icon": "🟡",
            "action": "Confirmar en panel Hunter.", "technical": "",
        }
    for pat, title, detail, risk, action in _RULE_PATTERNS:
        if pat.search(technical):
            return {
                "title": title, "detail": detail, "risk": risk,
                "risk_label": _RISK_LABEL.get(risk, "MEDIO"),
                "risk_icon": _RISK_ICON.get(risk, "🟡"),
                "action": action, "technical": technical,
            }
    if technical.upper().startswith("ET "):
        return {
            "title": "Amenaza detectada por Hunter",
            "detail": "Regla Suricata en tráfico WAN del hotel.",
            "risk": "medio", "risk_label": "MEDIO", "risk_icon": "🟡",
            "action": "Revisar en panel Hunter.", "technical": technical,
        }
    return {
        "title": "Evento de seguridad", "detail": technical[:200],
        "risk": "medio", "risk_label": "MEDIO", "risk_icon": "🟡",
        "action": "Confirmar en panel Hunter.", "technical": technical,
    }


def short_impact_line(signature: Optional[str], ip: str) -> str:
    """Una línea para executive_alert del bot."""
    h = humanize_hunter_signature(signature)
    return f"{h['title']} — IP {ip} ({h['risk_label'].lower()})"
