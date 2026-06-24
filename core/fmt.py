"""Formato HTML consistente para mensajes Telegram del agente Shomer."""
from html import escape as _esc
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

SEP      = "─────────────────────"
SEP_WIDE = "━━━━━━━━━━━━━━━━━━━━━"

STATUS_ICON: dict[str, str] = {
    "online":      "🟢",
    "offline":     "🔴",
    "no-internet": "🟠",
    "degraded":    "🟡",
    "unknown":     "⚪",
    "active":      "✅",
    "inactive":    "❌",
    "ok":          "✅",
    "error":       "❌",
    "warn":        "⚠️",
    "up":          "🟢",
    "down":        "🔴",
}


def e(text) -> str:
    """Escapa caracteres HTML en contenido dinámico."""
    return _esc(str(text))


def status_icon(status: str) -> str:
    return STATUS_ICON.get((status or "").lower(), "⚪")


# ── Primitivos HTML ───────────────────────────────────────────────────────────

def b(text) -> str:
    return f"<b>{e(text)}</b>"


def code(text) -> str:
    return f"<code>{e(text)}</code>"


def it(text) -> str:
    return f"<i>{e(text)}</i>"


def pre(text) -> str:
    return f"<pre>{e(text)}</pre>"


# ── Bloques estructurados ─────────────────────────────────────────────────────

def card(icon: str, title: str, lines: list[str]) -> str:
    """
    Tarjeta con separador grueso:
    ━━━━━━━━━━━━━━━━━━━━━
    ⚡ TÍTULO
    ━━━━━━━━━━━━━━━━━━━━━
    línea 1 ...
    """
    prefix = f"{icon} " if icon else ""
    body = "\n".join(lines)
    return f"{SEP_WIDE}\n{prefix}<b>{e(title)}</b>\n{SEP_WIDE}\n{body}"


def section(icon: str, title: str, lines: list[str]) -> str:
    """Bloque sin separador grueso — para secciones dentro de un mensaje mayor."""
    prefix = f"{icon} " if icon else ""
    body = "\n".join(lines)
    return f"{prefix}<b>{e(title)}</b>\n{body}"


def alert_card(title: str, lines: list[str], level: str = "warn") -> str:
    icons = {"warn": "⚠️", "critical": "🔴", "ok": "✅", "info": "ℹ️", "security": "🔐"}
    return card(icons.get(level, "⚠️"), title, lines)


def row(icon: str, label: str, value) -> str:
    """Fila: ícono  Label: valor"""
    return f"  {icon} <b>{e(label)}:</b> {e(value)}"


def row_code(icon: str, label: str, value) -> str:
    """Fila con valor monoespaciado."""
    return f"  {icon} <b>{e(label)}:</b> <code>{e(value)}</code>"


# ── Helpers teclado inline ───────────────────────────────────────────────────

def kb(*rows: list) -> InlineKeyboardMarkup:
    """Construye InlineKeyboardMarkup desde filas de botones."""
    return InlineKeyboardMarkup(list(rows))


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def btn_url(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, url=url)


# ── UX — alertas y acciones automáticas (técnico de campo) ───────────────────

GUARDIAN_STATUS: dict[str, str] = {
    "online":      "En línea",
    "offline":     "Sin respuesta",
    "degraded":    "Señal débil",
    "no-internet": "Sin internet",
    "unknown":     "Desconocido",
}

TASK_TITLES: dict[str, str] = {
    "TASK-001": "Limpieza de disco",
    "TASK-002": "Reinicio del panel (Guardian)",
    "TASK-003": "Reinicio de Tracker/Protector",
    "TASK-004": "Reinicio del acceso web (Nginx)",
    "TASK-005": "Limpieza de logs del servidor",
    "TASK-006": "Revisión de backups",
    "TASK-007": "Alerta de backup atrasado",
    "TASK-008": "Liberación de puerto bloqueado",
    "TASK-009": "Reinicio de detección de amenazas",
    "TASK-010": "Reinicio de AP (prohibido)",
}

MODE_LABEL_DEV: dict[str, str] = {
    "off": "apagado",
    "learning": "en prueba",
    "approved": "automático",
}


def guardian_label(status: str) -> str:
    return GUARDIAN_STATUS.get((status or "").lower(), status or "?")


def format_disk_change(detail: str, pct_before=None) -> str:
    """Convierte '85%→71%' en texto legible."""
    if "→" in str(detail):
        parts = str(detail).split("→", 1)
        try:
            before = parts[0].replace("%", "").strip()
            after = parts[1].replace("%", "").strip()
            return f"Quedó al {after}% (antes {before}%)"
        except Exception:
            pass
    if pct_before is not None:
        return f"Antes {pct_before}% — ahora {detail}"
    return str(detail)


def action_result(
    icon: str,
    title: str,
    *,
    happened: str,
    action: str,
    ok: bool,
    result_line: str,
    next_step: str = "",
) -> str:
    """Alerta compacta: emoji + evento — detalle en una línea."""
    detail = f"{happened} · {result_line}"
    if next_step and not ok:
        detail += f" · {next_step}"
    return alert_line(icon, title, detail, raw=True)


def triage_digest(entity_key: str, body: str, severity: str = "info") -> str:
    """Consolida avisos del triage — una línea por evento, sin tarjetas extra."""
    del entity_key, severity
    return body.strip()


def monitor_line(label: str, ago: str, alert_tag: str = "", *, error: str = "") -> str:
    if error:
        return f"  🔴 {label}\n      <code>{e(error[:80])}</code>"
    tag = f" · {alert_tag}" if alert_tag else ""
    return f"  ✅ {label} — {e(ago)}{tag}"


def alert_line(icon: str, event: str, detail: str = "", *, raw: bool = False) -> str:
    """
    Formato estándar de alerta (una línea):
    🔴 Equipo Infra caído — Cámara Lobby (192.168.1.57)
    """
    if detail:
        body = detail if raw else e(detail)
        return f"{icon} <b>{e(event)}</b> — {body}"
    return f"{icon} <b>{e(event)}</b>"


_CRIT_ICON = {"crítico": "🚨", "critico": "🚨", "alto": "🟠", "medio": "🟡", "info": "ℹ️"}


def executive_alert(criticidad: str, servicio: str, impacto: str,
                     accion_automatica: str = "", sugerencia: str = "") -> str:
    """
    Formato ejecutivo obligatorio para alertas con impacto real al usuario final:
    🚨 CRÍTICO - Hunter
    • Impacto: Piso 3 sin WiFi
    • Acción Automática: Hunter bloqueó IP en MikroTik
    • Sugerencia al Técnico: revisar el AP del piso 3 físicamente
    """
    icon = _CRIT_ICON.get(criticidad.strip().lower(), "⚠️")
    lines = [f"{icon} <b>{e(criticidad.upper())}</b> - {e(servicio)}",
             f"• Impacto: {e(impacto)}"]
    if accion_automatica:
        lines.append(f"• Acción Automática: {e(accion_automatica)}")
    if sugerencia:
        lines.append(f"• Sugerencia al Técnico: {e(sugerencia)}")
    return "\n".join(lines)


def host(name: str, ip: str = "") -> str:
    """Nombre legible + IP opcional: Cámara Lobby (192.168.1.57)"""
    if ip:
        return f"{e(name)} (<code>{e(ip)}</code>)"
    return e(name)


def port_label(port) -> str:
    return f"<code>{e(port)}</code>"


def auto_tasks_summary_technician(active_count: int, triage_on: bool) -> list[str]:
    lines = ["  ✅ Agente Shomer activo"]
    if triage_on:
        lines.append("  ✅ Alertas consolidadas — menos mensajes repetidos")
    if active_count > 0:
        lines.append(f"  ✅ Mantenimiento automático activo ({active_count} tareas)")
    else:
        lines.append("  ⚪ Mantenimiento automático desactivado")
    return lines
