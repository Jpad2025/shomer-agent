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


def _mismo_sintoma(devices: List[dict]) -> bool:
    """True si todos muestran prácticamente la misma latencia.

    Diez equipos distintos que de golpe marcan 534, 535 y 538 ms no tienen diez
    problemas: tienen uno solo, compartido. Lo que varía entre ellos es ruido de
    medición, no diferencias reales.
    """
    lats = [float(d["ewma_latency_ms"]) for d in devices
            if d.get("ewma_latency_ms") is not None]
    if len(lats) < 2:
        return False
    return (max(lats) - min(lats)) <= max(20.0, 0.15 * max(lats))


def format_ewma_wave_degrading(devices: List[dict],
                               poll_context: Optional[dict] = None) -> str:
    """Una oleada de degradación es UN hecho, no N avisos.

    12 sep 2026, caso real: 10 equipos —servidores, switches, impresora y el
    propio router— avisaron "degradando" en 40 segundos, todos con 534-538 ms
    contra su normal de ~349 ms, y volvieron a la normalidad 3 minutos después.
    20 mensajes para un solo evento.

    El delator estaba en la lista: el gateway. Si sube la latencia del router,
    sube la de todo lo que pasa por él — mandar al técnico a revisar diez
    equipos es mandarlo al lugar equivocado diez veces.
    """
    n = len(devices)
    ctx = poll_context or {}
    nombres = ", ".join(
        _html.escape(str(d.get("name") or d.get("ip"))) for d in devices[:6]
    )
    extra = f" (+{n - 6})" if n > 6 else ""

    lats = [float(d["ewma_latency_ms"]) for d in devices
            if d.get("ewma_latency_ms") is not None]
    bases = [float(d["baseline_latency_ms"]) for d in devices
             if d.get("baseline_latency_ms") is not None]
    medida = ""
    if lats:
        if _mismo_sintoma(devices):
            medida = f"\nTodos alrededor de <b>{sum(lats)/len(lats):.0f} ms</b>"
            if bases:
                medida += f", contra ~{sum(bases)/len(bases):.0f} ms habitual"
        else:
            medida = f"\nLatencias entre {min(lats):.0f} y {max(lats):.0f} ms"

    gw = str(ctx.get("gateway_ip") or "").strip()
    ips = {str(d.get("ip") or "") for d in devices}
    if gw and gw in ips:
        causa = (f"\n<b>El router ({_html.escape(gw)}) está en la lista</b>: todo lo que "
                 "pasa por él hereda su latencia. Revisar el router primero.")
    elif _mismo_sintoma(devices):
        causa = ("\nMisma latencia en equipos distintos = <b>una causa compartida</b> "
                 "(enlace, switch o router), no un problema en cada uno.")
    else:
        causa = "\nRevisar qué tienen en común antes que cada equipo por separado."

    return (
        f"⚠️ <b>Red más lenta</b> — {n} equipos a la vez\n"
        f"{nombres}{extra}{medida}{causa}\n"
        "<i>Siguen respondiendo: es lentitud, no caída.</i>"
    )


def format_ewma_wave_recovered(devices: List[dict]) -> str:
    n = len(devices)
    nombres = ", ".join(
        _html.escape(str(d.get("name") or d.get("ip"))) for d in devices[:5]
    )
    extra = f" (+{n - 5})" if n > 5 else ""
    return (
        f"🟢 <b>Red normalizada</b> — los {n} equipos volvieron a su latencia habitual\n"
        f"{nombres}{extra}"
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
