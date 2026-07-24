"""Shomer Pulse Correlate — agrupa alertas Infra en Telegram (multi-cliente).

No silencia eventos: los reclasifica (oleada LAN, blip Shomer, caída individual).
"""
from __future__ import annotations

import html as _html
import logging
import os
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("shomer-pulse-correlate")

WAVE_MIN = int(os.environ.get("PULSE_WAVE_MIN_DEVICES", "3"))
BLIP_INFORM_COOLDOWN_SEC = int(os.environ.get("PULSE_BLIP_INFORM_COOLDOWN_SEC", "3600"))
IA_DIAG_COOLDOWN_SEC = int(os.environ.get("IA_DIAGNOSTICO_COOLDOWN_SEC", "21600"))

_blip_inform_last: float = 0.0
_ia_diag_last: Dict[str, float] = {}


def wave_threshold(poll_context: Optional[dict] = None) -> int:
    if poll_context:
        try:
            return max(2, int(poll_context.get("wave_threshold") or WAVE_MIN))
        except (TypeError, ValueError):
            pass
    return WAVE_MIN


def is_blip_poll(poll_context: Optional[dict]) -> bool:
    return bool((poll_context or {}).get("host_network_blip"))


def blip_recent(poll_context: Optional[dict], last_blip: Optional[dict], max_age_sec: int = 180) -> bool:
    if is_blip_poll(poll_context):
        return True
    if not last_blip:
        return False
    ts = last_blip.get("ts") or ""
    try:
        from datetime import datetime, timezone
        t0 = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t0).total_seconds() <= max_age_sec
    except Exception:
        return False


def should_inform_blip(now: Optional[float] = None) -> bool:
    global _blip_inform_last
    now = now or time.time()
    if now - _blip_inform_last < BLIP_INFORM_COOLDOWN_SEC:
        return False
    _blip_inform_last = now
    return True


def format_blip_message(poll_context: dict, last_blip: Optional[dict] = None) -> str:
    ctx = last_blip or poll_context or {}
    n = ctx.get("offline_count") or "?"
    total = ctx.get("total_devices") or "?"
    gw = _html.escape(str(ctx.get("gateway_ip") or "gateway"))
    return (
        "🌐 <b>Microcorte de visibilidad</b> — servidor Shomer\n"
        f"En un ciclo de monitoreo el {gw} y {n}/{total} equipos "
        "parecieron caídos a la vez.\n"
        "<i>Probable corte breve en la red local del Shomer — no implica "
        "caída general del hotel.</i> Los equipos no se marcaron como caídos."
    )


def format_wave_message(devices: List[dict], poll_context: Optional[dict] = None) -> str:
    n = len(devices)
    names = ", ".join(
        _html.escape(str(d.get("name") or d.get("ip"))) for d in devices[:6]
    )
    extra = f" (+{n - 6})" if n > 6 else ""
    batch = (poll_context or {}).get("batch_id") or ""
    batch_line = f"\nRef: <code>{_html.escape(str(batch))}</code>" if batch else ""
    locs = sorted({
        (d.get("location") or "").strip()
        for d in devices
        if (d.get("location") or "").strip()
        and not (d.get("location") or "").strip().lower().startswith("por confirmar")
    })
    loc_hint = ""
    if len(locs) == 1:
        loc_hint = f"\nUbicación común: <b>{_html.escape(locs[0])}</b>"
    elif len(locs) > 1:
        loc_hint = f"\nVarias ubicaciones ({len(locs)}) — posible problema de switch o energía"
    return (
        f"🔴 <b>Oleada LAN</b> — {n} equipos sin respuesta al mismo tiempo\n"
        f"{names}{extra}{loc_hint}\n"
        "<i>Revisar switch/energía upstream antes que cada equipo por separado.</i>"
        f"{batch_line}"
    )


def format_wave_recovery(devices: List[dict]) -> str:
    n = len(devices)
    names = ", ".join(
        _html.escape(str(d.get("name") or d.get("ip"))) for d in devices[:5]
    )
    extra = f" (+{n - 5})" if n > 5 else ""
    return (
        f"🟢 <b>Oleada recuperada</b> — {n} equipos respondiendo de nuevo\n"
        f"{names}{extra}"
    )


def format_ewma_degrading(ev: dict) -> str:
    name = _html.escape(str(ev.get("name") or ev.get("ip") or "?"))
    ip = _html.escape(str(ev.get("ip") or ""))
    ewma_lat = ev.get("ewma_latency_ms")
    baseline = ev.get("baseline_latency_ms")
    ewma_loss = ev.get("ewma_loss_pct")
    reason = _html.escape(str(ev.get("reason") or "latencia o pérdida en tendencia"))
    lat_line = ""
    if ewma_lat is not None:
        lat_line = f"Latencia EWMA: <b>{ewma_lat:.0f} ms</b>"
        if baseline is not None:
            lat_line += f" (normal ~{baseline:.0f} ms)"
    loss_line = ""
    if ewma_loss is not None and float(ewma_loss) > 0:
        loss_line = f" · Pérdida EWMA: <b>{float(ewma_loss):.0f}%</b>"
    return (
        f"⚠️ <b>Pulse — degradando</b> — {name} (<code>{ip}</code>)\n"
        f"{lat_line}{loss_line}\n"
        f"{reason}\n"
        "<i>Equipo aún responde — revisar antes de que caiga del todo.</i>"
    )


def format_ewma_recovered(ev: dict) -> str:
    name = _html.escape(str(ev.get("name") or ev.get("ip") or "?"))
    return (
        f"🟢 <b>Pulse — estable</b> — {name}\n"
        "<i>Métricas de latencia/pérdida volvieron a la normalidad.</i>"
    )


_PULSE_EWMA_ALERT_LAST: Dict[str, float] = {}
PULSE_EWMA_ALERT_COOLDOWN_SEC = int(os.environ.get("INFRA_PULSE_ALERT_COOLDOWN_SEC", "1800"))


def ewma_alert_allowed(ip: str, now: Optional[float] = None) -> bool:
    now = now or time.time()
    last = _PULSE_EWMA_ALERT_LAST.get(ip, 0.0)
    if now - last < PULSE_EWMA_ALERT_COOLDOWN_SEC:
        return False
    _PULSE_EWMA_ALERT_LAST[ip] = now
    return True


def ia_diagnostico_allowed(ip: str, now: Optional[float] = None) -> bool:
    """Un diagnóstico IA por equipo cada IA_DIAGNOSTICO_COOLDOWN_SEC (default 6 h)."""
    now = now or time.time()
    last = _ia_diag_last.get(ip, 0.0)
    if now - last < IA_DIAG_COOLDOWN_SEC:
        return False
    _ia_diag_last[ip] = now
    return True
