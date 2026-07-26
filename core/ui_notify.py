"""Mensajes UX para notificaciones automáticas (técnico de campo)."""
from __future__ import annotations

from core import fmt


def task_result_message(task_id: str, result, mode: str) -> str:
    """Genera HTML legible para Telegram — sin jerga interna al técnico."""
    ctx = result.context or {}
    title = fmt.TASK_TITLES.get(task_id, task_id)
    tid = task_id.upper()

    if tid == "TASK-001":
        mount = ctx.get("mount", "/")
        pct_b = ctx.get("pct_before", "?")
        change = fmt.format_disk_change(result.green_detail, pct_b)
        return fmt.action_result(
            "🧹",
            "Mantenimiento — disco",
            happened=f"El disco <code>{fmt.e(mount)}</code> estaba al {pct_b}%",
            action="Limpió logs, temporales y caché del sistema",
            ok=result.green_ok,
            result_line=change if result.green_ok else "El espacio sigue bajo — revisar",
            next_step="" if result.green_ok else "Usá /salud para ver el estado del disco",
        )

    if tid in ("TASK-002", "TASK-003", "TASK-004"):
        label = ctx.get("label", title)
        zombie = ctx.get("zombie_killed")
        action = f"Reinició {label}"
        if zombie:
            action += " (liberó un puerto bloqueado y reinició)"
        return fmt.action_result(
            "🔧",
            "Servicio recuperado",
            happened=f"{label} dejó de responder",
            action=action,
            ok=result.green_ok,
            result_line="Volvió a funcionar normalmente" if result.green_ok else "Sigue sin responder",
            next_step="" if result.green_ok else "Usá /salud — si persiste, contactá soporte USB",
        )

    if tid == "TASK-005":
        # Mantenimiento nocturno: silencio si OK; solo avisar si falló.
        if result.green_ok:
            return ""
        return fmt.action_result(
            "📄",
            "Mantenimiento — logs falló",
            happened="Algunos logs del servidor ocupaban demasiado espacio",
            action="Intentó reducir el tamaño automáticamente",
            ok=False,
            result_line=result.green_detail or "Revisar /var/log/shomer",
            next_step="Usá /salud — si persiste, revisar espacio en disco",
        )

    if tid == "TASK-006":
        lines = ctx.get("lines") or []
        body = "\n".join(lines) if lines else result.green_detail
        ok = result.green_ok
        return fmt.card(
            "✅" if ok else "⚠️",
            "Revisión de backups (solo lectura)",
            [
                "Shomer revisó al azar algunos equipos configurados en Protector:",
                "",
                body,
                "",
                "<i>No se modificó ningún backup — solo informa.</i>",
            ],
        )

    if tid == "TASK-008":
        port = ctx.get("port", "?")
        return fmt.action_result(
            "🔧",
            "Puerto del sistema liberado",
            happened=f"El puerto {port} estaba bloqueado por un proceso huérfano",
            action="Liberó el puerto y reinició el servicio asociado",
            ok=result.green_ok,
            result_line="Servicio operativo" if result.green_ok else "Requiere revisión manual",
            next_step="" if result.green_ok else "Usá /salud",
        )

    if tid == "TASK-009":
        return fmt.action_result(
            "🎯",
            "Detección de amenazas",
            happened="El sistema de detección dejó de recibir datos",
            action="Reinició Suricata",
            ok=result.green_ok,
            result_line="Detección activa nuevamente" if result.green_ok else "Sigue sin datos — revisar cable espejo",
            next_step="" if result.green_ok else "Verificá el cable SPAN en el switch",
        )

    return fmt.alert_card(
        title,
        [result.action, result.green_detail or result.error or ""],
        level="ok" if result.green_ok else "warn",
    )
