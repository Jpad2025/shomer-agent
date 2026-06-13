"""
Bot Telegram del Agente Shomer — reescritura limpia.
- Formato HTML en todos los mensajes del bot.
- Respuestas Groq en Markdown (Llama genera Markdown por defecto).
- Sin duplicados: _estado_impl / _equipos_impl compartidos.
- Bugs corregidos: msg_photo con try/except, cb_restaurar eliminado,
  rate-limit aplica también cuando el bot está pausado.
"""
import os
import random
import logging
import asyncio
from functools import partial
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

from core.groq_helper import explain as _groq_explain
from core import llm_router as _llm
from core import memory as _memory
from core import maintenance as _mnt
from core import device_manager as dm
from core import shomer_api
from core import monitor
from core import access as acc
from core import repair
from core import changelog
from core.identity import SITE_NAME
from core import fmt
from core import learning as _learning

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
for _s in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11"):
    logging.getLogger(_s).setLevel(logging.WARNING)
log = logging.getLogger("shomer-agent")

TELEGRAM_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT   = os.environ.get("TELEGRAM_CHAT_ID", "")
BOT_AUTO_REBOOT = os.environ.get("BOT_AUTO_REBOOT", "true").lower() != "false"
_FACTORY_IP     = os.environ.get("SHOMER_FACTORY_IP", "192.168.0.205")
PM              = "HTML"  # parse_mode global — mensajes del bot (HTML)

# Monitores automáticos — etiquetas compartidas entre /ayuda y /salud monitores
MONITOR_LABELS = {
    "watch_hunter":            "Hunter — amenazas contenidas (bloqueo)",
    "watch_devices":           "Equipos registrados en el agente",
    "daily_summary":           "Resumen diario (7:00 AM)",
    "watch_resources":         "CPU y RAM del servidor",
    "watch_backups":           "Backups atrasados",
    "watch_wan_outage":        "Caída de internet (WAN)",
    "watch_disk":              "Espacio en disco",
    "watch_pipeline":          "Hunter — detección Suricata (pipeline)",
    "watch_services":          "Servicios Guardian / Tools / Nginx",
    "watch_guardian_nodes":    "Estado de APs y nodos",
    "preventive_reboot":       "Reinicio preventivo nocturno (4:00 AM)",
    "weekly_backup":           "Backup semanal del sistema (Dom 2:00)",
    "watch_protector_retry":   "Reintentos de backup fallido",
    "watch_hunter_verify":     "Hunter — verificación de bloqueos",
    "watch_docker":            "Container del agente",
    "watch_connectivity":      "Conectividad del servidor",
    "watch_groq":              "Conexión Groq (monitores y resúmenes)",
    "watch_openai":            "Conexión OpenAI (chat interactivo)",
    "watch_security":          "Firewall Linux / OpenWrt",
    "watch_mikrotik_security": "Firewall MikroTik",
    "auto_unblock":            "Desbloqueo automático de IPs",
    "watch_network_audit":     "Riesgos de red pendientes",
    "watch_protector_sample":  "Revisión aleatoria de backups",
    "watch_log_truncate":      "Limpieza de logs grandes",
    "watch_infra_equipment":   "Infra — caídas y recuperaciones",
    "watch_infra_printer":     "Infra — tóner y papel",
    "watch_infra_service":     "Infra — servicio TCP desconectado",
    "watch_infra_snmp":        "Infra — puertos SNMP DOWN",
    "watch_infra_flap":        "Infra — flapping (cable/PoE)",
    "watch_active_threats":    "Hunter — resumen IPs contenidas",
}

MONITOR_GROUPS = [
    ("👁️ Guardian", ["watch_guardian_nodes", "watch_devices", "preventive_reboot"]),
    ("🎯 Hunter", [
        "watch_hunter", "watch_pipeline", "watch_hunter_verify",
        "watch_security", "watch_mikrotik_security", "auto_unblock",
        "watch_network_audit", "watch_active_threats",
    ]),
    ("🛡️ Protector", ["watch_backups", "watch_protector_retry", "watch_protector_sample", "weekly_backup"]),
    ("🏗️ Infra", [
        "watch_infra_equipment", "watch_infra_printer", "watch_infra_service",
        "watch_infra_snmp", "watch_infra_flap",
    ]),
    ("🖥️ Servidor", [
        "watch_services", "watch_disk", "watch_resources", "watch_wan_outage",
        "watch_connectivity", "watch_log_truncate",
    ]),
    ("🤖 Bot / IA", ["watch_docker", "watch_openai", "watch_groq", "daily_summary"]),
]

_GREETINGS = {
    "hola", "holas", "buenos dias", "buenos días", "buen dia", "buen día",
    "buenas tardes", "buenas noches", "buenas", "hey", "hi", "hello",
    "saludos", "qué tal", "que tal", "ey", "cómo estás", "como estas",
    "cómo van", "como van", "qué hay", "que hay",
}

_GREETING_RESPONSES = [
    "<b>Hola, soy Shomer Sentinel</b> — tu IA de red, estoy para ayudarte.\nEscribime tu consulta o usá /consultas para ver qué podés preguntar.",
    "<b>Hola</b> — Shomer activo y monitoreando tu red.\n/salud · /equipos · /alertas",
    "Shomer aquí, tu IA de red. ¿En qué te ayudo?\n/consultas · /salud · texto libre",
    "<b>Hola, soy Shomer</b> — tu asistente IA, siempre activo.\nProbá /salud o escribime tu consulta.",
]

_IDENTITY_WORDS = {
    "quien eres", "quién eres", "que eres", "qué eres",
    "que haces", "qué haces", "para que sirves", "para qué sirves",
    "que es shomer", "qué es shomer", "presentate",
    "cómo funcionas", "como funcionas", "que puedes", "qué puedes",
    "que puedes hacer", "qué puedes hacer", "para que eres", "para qué eres",
    "cual es tu funcion", "cuál es tu función", "cual es tu rol", "cuál es tu rol",
}

_IDENTITY_RESPONSE = (
    "<b>Soy Shomer Sentinel</b> — tu asistente IA de red.\n\n"
    "Monitoreo tu red en tiempo real y te ayudo a resolver problemas:\n"
    "  🖥️ <b>Servidor</b> — CPU, RAM, disco, servicios\n"
    "  👁️ <b>Equipos de red</b> — APs, switches, caídas y reboots automáticos\n"
    "  🎯 <b>Seguridad</b> — Hunter protege la red; bloqueos y riesgos con guía de remediación\n"
    "  🛡️ <b>Backups</b> — estado de respaldos y alertas si fallan\n\n"
    "Podés escribirme en texto libre — uso datos reales del sistema para responder.\n"
    "Usá /consultas para ver ejemplos de preguntas · /ayuda para comandos."
)

def _save_reply_text(kid: int, nombre: str, meta: dict, *, ip_line: bool = True) -> str:
    suffix = _learning.feedback_suffix(meta)
    name_part = f" para <b>{fmt.e(nombre)}</b>" if ip_line else ""
    return (
        f"💾 Solución guardada (#{kid}){name_part}.\n"
        f"El sistema la tendrá en cuenta en próximos diagnósticos.{suffix}"
    )


def _resolve_device_name(ip: str) -> str:
    """Nombre legible para knowledge — Guardian, agente o Infra."""
    for n in shomer_api.get_guardian_nodes() or []:
        nip = n.get("ip") or n.get("ip_address")
        if nip == ip:
            return n.get("name", ip) or ip
    dev = dm.get_device(ip)
    if dev:
        return dev.get("name", ip) or ip
    infra = shomer_api.get_infra_device(ip)
    if infra:
        return infra.get("name", ip) or ip
    return ip


def _save_knowledge_markup(ip: str, *, reboot_quick: bool = True) -> InlineKeyboardMarkup:
    """Botones post-acción — callback corto (límite 64 B de Telegram)."""
    if reboot_quick:
        row = [
            InlineKeyboardButton("💾 Reinicio resolvió", callback_data=f"save_know:r:{ip}"),
            InlineKeyboardButton("📝 Otra causa", callback_data=f"save_know:o:{ip}"),
        ]
    else:
        row = [
            InlineKeyboardButton("💾 Guardar solución", callback_data=f"save_know:o:{ip}"),
        ]
    return InlineKeyboardMarkup([
        row,
        [InlineKeyboardButton("No guardar", callback_data="save_know:x:0")],
    ])


def _is_greeting(text: str) -> bool:
    t = text.lower().strip().rstrip("!?. ")
    return any(kw in t for kw in _GREETINGS) and len(t.split()) <= 5


def _is_identity_question(text: str) -> bool:
    t = text.lower().strip().rstrip("?!. ")
    return any(kw in t for kw in _IDENTITY_WORDS) and len(t.split()) <= 10


# ── Helpers internos ──────────────────────────────────────────────────────────

async def _guard(update: Update) -> str | None:
    """Retorna 'tecnico' si el chat está autorizado, si no None."""
    level = acc.get_level(update)
    if level == "none":
        log.warning("Mensaje ignorado de user=%s chat=%s",
                    update.effective_user.id if update.effective_user else "?",
                    update.effective_chat.id if update.effective_chat else "?")
        msg = getattr(update, "message", None)
        if msg:
            try:
                await msg.reply_text(
                    "⛔ Chat no autorizado para este bot.\n"
                    "Verifica que <code>TELEGRAM_CHAT_ID</code> coincida con este chat.",
                    parse_mode=PM,
                )
            except Exception:
                pass
        return None
    return level


async def _typing(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await ctx.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )
    except Exception:
        pass


async def _typing_q(query, ctx) -> None:
    try:
        await ctx.bot.send_chat_action(
            chat_id=query.message.chat_id, action=ChatAction.TYPING
        )
    except Exception:
        pass


# ── /ayuda ────────────────────────────────────────────────────────────────────

def _ayuda_text() -> str:
    monitor_lines = []
    for group_title, names in MONITOR_GROUPS:
        monitor_lines.append(f"<b>{group_title}</b>")
        for n in names:
            monitor_lines.append(f"  • {fmt.e(MONITOR_LABELS.get(n, n))}")
        monitor_lines.append("")

    return (
        f"{fmt.SEP_WIDE}\n"
        f"<b>Shomer Sentinel — Comandos</b>\n"
        f"{fmt.SEP_WIDE}\n\n"

        f"<b>🤖 General</b>\n"
        f"/consultas — ejemplos de texto libre\n"
        f"/ayuda — esta lista\n"
        f"/nuevo — limpiar historial del chat con IA\n"
        f"<i>Texto libre</i> — escribí tu pregunta sin comando\n\n"

        f"<b>🖥️ Servidor Shomer</b>\n"
        f"/salud — CPU, RAM, disco, servicios, WAN, Guardian, Infra, Hunter\n"
        f"/monitores — estado de cada monitor automático (también /salud monitores)\n"
        f"/resumen — reporte del día con IA (también /salud resumen)\n\n"

        f"<b>👁️ Guardian</b> (APs, routers, WiFi)\n"
        f"/equipos — nodos Guardian + equipos del agente\n"
        f"/diagnostico &lt;ip&gt; — ping, estado, uptime, fallos\n"
        f"/diagnostico &lt;ip&gt; reparar — diagnóstico + reparación automática\n"
        f"/reboot &lt;ip&gt; — reiniciar AP o equipo (<i>/reiniciar</i> igual)\n"
        f"/clientes &lt;ip&gt; — dispositivos WiFi conectados al AP\n"
        f"/modo on|off — pausar reboots automáticos (<i>/mantenimiento</i> igual)\n"
        f"<i>Alias:</i> /guardian_equipos · /guardian_diagnostico · /guardian_reiniciar · "
        f"/guardian_clientes · /guardian_mantenimiento\n\n"

        f"<b>🏗️ Infra</b> (cámaras, switches, servidores, impresoras, NAS)\n"
        f"/infra — lista todos los equipos Infra\n"
        f"/infra &lt;ip&gt; — conexión: ping, TCP, SNMP, tóner (impresoras)\n"
        f"/puertos &lt;ip&gt; — puertos SNMP UP/DOWN, tráfico y errores (switch/router/server)\n"
        f"Panel web: Infraestructura — agregar equipos y comunidad SNMP\n\n"

        f"<b>🎯 Hunter</b> (seguridad, firewall)\n"
        f"/alertas — últimas alertas y IPs bloqueadas\n"
        f"/bloquear &lt;ip&gt; — bloquear IP en firewall\n"
        f"/desbloquear &lt;ip&gt; — liberar IP bloqueada\n"
        f"<i>Alias:</i> /hunter_alertas · /hunter_bloquear · /hunter_desbloquear\n\n"

        f"<b>🛡️ Protector</b> (backups)\n"
        f"Panel web <code>/backups</code> — programar, sync B2, restaurar\n"
        f"Texto libre: <i>¿cuándo fue el último backup?</i> · <i>¿falló algún backup?</i>\n\n"

        f"<b>🔍 Tracker</b> (inventario)\n"
        f"Panel web <code>/inventory</code> — escaneo, fichas, export Excel\n\n"

        f"<b>📋 Historial y soluciones</b>\n"
        f"/guardar &lt;ip&gt; &lt;descripción&gt; — guardar qué pasó y cómo se resolvió\n"
        f"/historial — últimos cambios del bot (bloqueos, reboots…)\n"
        f"/revertir &lt;id&gt; — deshacer bloqueo/desbloqueo (ver /historial)\n"
        f"<i>Alias:</i> /shomer_historial · /shomer_revertir · /shomer_nueva_consulta\n\n"

        f"<b>🛠️ Instalación</b>\n"
        f"/instalar — guía paso a paso del sitio\n"
        f"/usuario — crear usuario de servicio shomer (Linux/Mac/Windows)\n"
        f"/verificar — checklist final de instalación\n"
        f"/agregar &lt;ip&gt; &lt;nombre&gt; [vendor] — equipo extra en el agente\n"
        f"/eliminar &lt;ip&gt; — quitar equipo del agente\n"
        f"<i>Alias:</i> /diag · /reiniciar · /mantenimiento · /guardian_* · /hunter_* · /shomer_salud\n\n"

        f"<b>📡 Monitores automáticos</b> (alertan solos — /monitores o /salud monitores)\n"
        + "\n".join(monitor_lines)
        + f"<i>Los monitores Infra avisan: equipo caído, tóner bajo, TCP caído, puerto SNMP DOWN, "
        f"flapping de cable/PoE.</i>\n"
    )


def _consultas_text() -> str:
    return (
        f"{fmt.SEP_WIDE}\n"
        f"💬 <b>Qué podés preguntarme</b> (texto libre)\n"
        f"{fmt.SEP_WIDE}\n\n"
        f"Escribí como hablarías con un colega — busco datos reales del sistema.\n\n"
        f"<b>🏗️ Infra</b> (cámaras, switches, servidores, impresoras)\n"
        f"• Comandos: <code>/infra</code> · <code>/infra 192.168.1.57</code> · <code>/puertos 192.168.1.10</code>\n"
        f"• ¿Está online la cámara del lobby?\n"
        f"• ¿Cuánto tóner le queda a la impresora de caja 1?\n"
        f"• ¿Qué equipos Infra están caídos?\n"
        f"• ¿El switch de recepción tiene puertos caídos?\n\n"
        f"<b>👁️ Guardian</b> (APs, WiFi)\n"
        f"• ¿Cuántos APs están online?\n"
        f"• ¿Por qué está caído el AP recepción?\n"
        f"• Diagnóstico del <code>192.168.1.210</code>\n\n"
        f"<b>🎯 Hunter</b> (seguridad)\n"
        f"• ¿Hay IPs contenidas por Hunter?\n"
        f"• ¿Qué riesgos de red hay pendientes?\n"
        f"• Última actividad de seguridad\n\n"
        f"<b>🛡️ Protector</b> (backups)\n"
        f"• ¿Cuándo fue el último backup?\n"
        f"• ¿Algún backup falló anoche?\n\n"
        f"<b>🖥️ Servidor Shomer</b>\n"
        f"• ¿Cómo va el disco y la RAM?\n"
        f"• ¿Están activos Guardian y Suricata?\n"
        f"• ¿Tenemos internet en el servidor?\n\n"
        f"<b>📋 Historial</b>\n"
        f"• ¿Qué hicimos la última vez con la cámara .57?\n"
        f"• Después de resolver, usá /guardar para que lo recuerde.\n\n"
        f"<i>Comandos directos: /salud · /equipos · /infra · /puertos &lt;ip&gt; · /alertas</i>"
    )


async def cmd_ayuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    await update.message.reply_text(_ayuda_text(), parse_mode=PM)


async def cmd_consultas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    await update.message.reply_text(_consultas_text(), parse_mode=PM)


# ── /equipos — impl compartida ────────────────────────────────────────────────

async def _equipos_impl(message, ctx, level: str):
    await ctx.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)

    sections = []

    _STATUS_LABEL = {
        "online":      "En línea",
        "offline":     "Sin respuesta",
        "degraded":    "Señal débil",
        "no-internet": "Sin internet",
        "unknown":     "Desconocido",
    }
    nodes = shomer_api.get_guardian_nodes()
    if nodes:
        lines = []
        for n in nodes:
            ip     = n.get("ip") or n.get("ip_address", "?")
            nombre = n.get("name", ip)
            st     = n.get("status", "?")
            icon   = fmt.status_icon(st)
            st_label = _STATUS_LABEL.get(st, st)
            lines.append(
                f"  {icon} <b>{fmt.e(nombre)}</b> <code>{fmt.e(ip)}</code> — {fmt.e(st_label)}"
            )
        sections.append(fmt.section("👁️", "Guardian — equipos monitoreados", lines))

    devices = dm.list_devices()
    if devices:
        lines = []
        for d in devices:
            icon = fmt.status_icon(d.get("status", "unknown"))
            role = " <i>(no reiniciar)</i>" if d.get("no_reboot") else ""
            lines.append(
                f"  {icon} <code>{fmt.e(d['ip'])}</code> — {fmt.e(d['name'])} "
                f"({fmt.e(d.get('vendor_hint','?'))}){role}"
            )
        sections.append(fmt.section("🔌", "Agente — equipos registrados", lines))

    if not sections:
        await message.reply_text(
            "No hay equipos registrados todavía.\nUsá /agregar para añadir el primero.", parse_mode=PM
        )
        return

    header = f"{fmt.SEP_WIDE}\n👁️ <b>EQUIPOS — {fmt.e(SITE_NAME)}</b>\n{fmt.SEP_WIDE}"
    texto  = header + "\n\n" + f"\n\n{fmt.SEP}\n\n".join(sections)
    await message.reply_text(texto, parse_mode=PM)


async def cmd_equipos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    await _equipos_impl(update.message, ctx, acc.get_level(update))


# ── /infra y /puertos — Inframonitor ─────────────────────────────────────────

_INFRA_TYPE_LABEL = {
    "switch": "Switch", "server": "Servidor", "camera": "Cámara",
    "printer": "Impresora", "pos": "POS", "nas": "NAS",
    "router": "Router", "ups": "UPS", "controller": "Controlador",
    "generic": "Equipo",
}

_INFRA_ICONS = {
    "switch": "🔀", "server": "🖥️", "camera": "📷", "printer": "🖨️",
    "pos": "🧾", "nas": "💾", "router": "🌐", "ups": "🔋",
    "controller": "🎛️", "generic": "📡",
}


def _infra_icon(dtype: str) -> str:
    return _INFRA_ICONS.get((dtype or "generic").lower(), "📡")


def _infra_status_label(st: str) -> str:
    return {"online": "En línea", "offline": "Sin respuesta"}.get(st or "", st or "?")


def _tcp_label(tcp_ok, port) -> str:
    if tcp_ok is None:
        return ""
    if tcp_ok in (1, True):
        return f"TCP:{port or '?'} ✓"
    return f"TCP:{port or '?'} ✗"


async def _infra_list_impl(message, ctx) -> None:
    await ctx.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    snap = shomer_api.get_infra_snapshot()
    devices = snap.get("devices") or []
    if not devices:
        await message.reply_text(
            "🏗️ No hay equipos en Infra.\n"
            "Agregalos en el panel → <b>Infraestructura</b> (<code>/infra</code> web).",
            parse_mode=PM,
        )
        return

    online = [d for d in devices if d.get("status") == "online"]
    offline = [d for d in devices if d.get("status") != "online"]
    lines = [
        f"  {'✅' if online else '⚠️'} <b>{len(online)}/{len(devices)}</b> en línea",
    ]
    if snap.get("outages_24h"):
        lines.append(f"  ⚠️ {snap['outages_24h']} caída(s) distintas en 24 h")

    def _row(d: dict) -> str:
        ip = d.get("ip", "?")
        name = d.get("name", ip)
        dtype = d.get("device_type", "generic")
        icon = _infra_icon(dtype)
        st_icon = fmt.status_icon(d.get("status", "unknown"))
        lat = d.get("latency_ms")
        lat_txt = f" · {lat:.0f} ms" if lat is not None else ""
        tcp = _tcp_label(d.get("tcp_ok"), d.get("tcp_port"))
        snmp = ""
        if d.get("snmp_ok") == 1:
            snmp = " · SNMP ✓"
        elif d.get("snmp_ok") == 0:
            snmp = " · SNMP ✗"
        extra = f" · {tcp}" if tcp else ""
        return (
            f"  {st_icon} {icon} <b>{fmt.e(name)}</b> <code>{fmt.e(ip)}</code>"
            f" — {fmt.e(_INFRA_TYPE_LABEL.get(dtype, dtype))}{lat_txt}{extra}{snmp}"
        )

    if offline:
        lines.append("")
        lines.append("<b>Caídos:</b>")
        for d in sorted(offline, key=lambda x: (x.get("location") or "", x.get("name") or "")):
            lines.append(_row(d))

    if online:
        lines.append("")
        lines.append("<b>En línea:</b>")
        for d in sorted(online, key=lambda x: (x.get("location") or "", x.get("name") or "")):
            lines.append(_row(d))

    lines.append("")
    lines.append("<i>Detalle: /infra &lt;ip&gt; · Puertos SNMP: /puertos &lt;ip&gt;</i>")

    header = f"{fmt.SEP_WIDE}\n🏗️ <b>INFRA — {fmt.e(SITE_NAME)}</b>\n{fmt.SEP_WIDE}"
    await message.reply_text(header + "\n\n" + "\n".join(lines), parse_mode=PM)


async def _infra_detail_impl(message, ctx, ip: str) -> None:
    await ctx.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    dev = shomer_api.get_infra_device(ip)
    if not dev:
        await message.reply_text(
            f"❌ <code>{fmt.e(ip)}</code> no está en Infra.\n"
            f"Verificá la IP o agregalo en el panel Infraestructura.",
            parse_mode=PM,
        )
        return

    dtype = dev.get("device_type", "generic")
    name = dev.get("name", ip)
    st = dev.get("status", "?")
    lines = [
        f"  {fmt.status_icon(st)} <b>Estado:</b> {fmt.e(_infra_status_label(st))}",
        f"  {_infra_icon(dtype)} <b>Tipo:</b> {fmt.e(_INFRA_TYPE_LABEL.get(dtype, dtype))}",
    ]
    if dev.get("location"):
        lines.append(f"  📍 <b>Ubicación:</b> {fmt.e(dev['location'])}")
    if dev.get("latency_ms") is not None:
        lines.append(f"  ⏱️ <b>Latencia:</b> <code>{dev['latency_ms']:.1f} ms</code>")
    if dev.get("state_duration"):
        lines.append(f"  🕐 <b>En este estado:</b> {fmt.e(dev['state_duration'])}")

    if dev.get("tcp_port"):
        tcp_ok = dev.get("tcp_ok")
        tcp_icon = "✅" if tcp_ok in (1, True) else ("❌" if tcp_ok in (0, False) else "⚪")
        lines.append(
            f"  🔌 <b>Puerto TCP {dev['tcp_port']}:</b> {tcp_icon}"
        )

    snmp_ok = dev.get("snmp_ok")
    if snmp_ok is not None:
        lines.append(f"  📡 <b>SNMP:</b> {'✓ responde' if snmp_ok == 1 else '✗ sin respuesta'}")

    down_ports = dev.get("snmp_down_ports") or []
    if down_ports:
        names = ", ".join(fmt.e(p.get("name", "?")) for p in down_ports[:6])
        extra = f" (+{len(down_ports) - 6} más)" if len(down_ports) > 6 else ""
        lines.append(f"  ⚠️ <b>Puertos DOWN:</b> {names}{extra}")

    pr = dev.get("printer") or {}
    if pr:
        if pr.get("toner_pct") is not None:
            lines.append(f"  🖨️ <b>Tóner:</b> <code>{pr['toner_pct']}%</code>")
        if pr.get("paper_current") is not None:
            lines.append(
                f"  📄 <b>Papel:</b> <code>{pr['paper_current']}</code>"
                + (f" / {pr['paper_max']}" if pr.get("paper_max") else "")
            )
        if pr.get("status"):
            lines.append(f"  🖨️ <b>Estado impresora:</b> {fmt.e(pr['status'])}")

    hint = shomer_api.knowledge_hint(ip)
    if hint:
        lines.append(f"  📋 <b>Antecedente:</b> <i>{fmt.e(hint)}</i>")

    if snmp_ok == 1 and dtype in ("switch", "router", "server", "nas"):
        lines.append(f"\n  ➡️ Puertos y tráfico: <code>/puertos {fmt.e(ip)}</code>")

    texto = fmt.card("🏗️", f"Infra — {name}", [f"<code>{fmt.e(ip)}</code>", ""] + lines)
    await message.reply_text(texto, parse_mode=PM)


async def _infra_puertos_impl(message, ctx, ip: str) -> None:
    await ctx.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    dev = shomer_api.get_infra_device(ip)
    if not dev:
        await message.reply_text(
            f"❌ <code>{fmt.e(ip)}</code> no está en Infra.", parse_mode=PM,
        )
        return

    result = shomer_api.get_infra_snmp(ip)
    if not result.get("success"):
        detail = result.get("detail") or "Sin datos SNMP"
        await message.reply_text(
            f"📡 <b>SNMP — {fmt.e(dev.get('name', ip))}</b>\n"
            f"<code>{fmt.e(ip)}</code>\n\n"
            f"❌ {fmt.e(detail)}\n\n"
            f"<i>Verificá comunidad SNMP en el panel Infra y que UDP 161 llegue desde el Shomer.</i>",
            parse_mode=PM,
        )
        return

    data = result.get("data") or {}
    ifaces = data.get("interfaces") or []
    up = [i for i in ifaces if i.get("oper") == "up"]
    down = [i for i in ifaces if i.get("oper") == "down"]
    err = [i for i in ifaces if (i.get("in_errors", 0) + i.get("out_errors", 0)) > 0]

    lines = [
        f"  <b>Modelo:</b> {fmt.e((data.get('sys_descr') or '—')[:80])}",
        f"  <b>Hostname:</b> <code>{fmt.e(data.get('sys_name') or '—')}</code>",
        f"  <b>Uptime:</b> {fmt.e(data.get('sys_uptime') or '—')}",
        f"  <b>Puertos:</b> {len(up)} UP · {len(down)} DOWN"
        + (f" · {len(err)} con errores" if err else ""),
        "",
    ]

    show = sorted(ifaces, key=lambda i: (0 if i.get("oper") == "down" else 1, i.get("name") or ""))
    for i in show[:18]:
        oper = i.get("oper", "?")
        oicon = "🟢" if oper == "up" else ("🔴" if oper == "down" else "⚪")
        speed = i.get("speed_mbps")
        spd = f"{speed}M" if speed else "—"
        rx = i.get("rx_mbps")
        tx = i.get("tx_mbps")
        traf = ""
        if rx is not None or tx is not None:
            traf = f" ↓{rx or 0:.2f} ↑{tx or 0:.2f} Mbps"
        errs = i.get("in_errors", 0) + i.get("out_errors", 0)
        err_tag = f" ⚠️{errs}" if errs else ""
        lines.append(
            f"  {oicon} <code>{fmt.e(i.get('name', '?'))}</code> {spd}{traf}{err_tag}"
        )

    if len(ifaces) > 18:
        lines.append(f"  <i>…y {len(ifaces) - 18} puertos más — panel web /infra</i>")

    name = result.get("name") or dev.get("name", ip)
    texto = fmt.card("🔀", f"Puertos SNMP — {name}", [f"<code>{fmt.e(ip)}</code>", ""] + lines)
    await message.reply_text(texto, parse_mode=PM)


async def cmd_infra(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    args = ctx.args or []
    if not args:
        await _infra_list_impl(update.message, ctx)
    else:
        await _infra_detail_impl(update.message, ctx, args[0])


async def cmd_puertos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "🔀 <b>Puertos SNMP</b> — estado de interfaces en switch, router o servidor.\n\n"
            "Uso: <code>/puertos &lt;ip&gt;</code>\n"
            "Ejemplo: <code>/puertos 192.168.1.10</code>\n\n"
            "El equipo debe estar en Infra con comunidad SNMP configurada.",
            parse_mode=PM,
        )
        return
    await _infra_puertos_impl(update.message, ctx, ctx.args[0])


# ── /alertas — impl compartida ────────────────────────────────────────────────

async def _alertas_impl(message, ctx, level: str):
    await ctx.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)

    data   = shomer_api.get_hunter_alerts(15)
    alerts = (data.get("alerts", data) if isinstance(data, dict) else data) or []

    if not alerts:
        await message.reply_text(
            fmt.alert_card("HUNTER", ["✅ Sin actividad sospechosa reciente — vigilancia activa."], "ok"),
            parse_mode=PM,
        )
        return

    def _sig_label(sig: str) -> str:
        s = sig.lower()
        if any(w in s for w in ("scan", "nmap", "sweep", "probe")):
            return "Escaneo de red"
        if any(w in s for w in ("brute", "ssh", "rdp", "login", "auth", "password")):
            return "Intento de acceso no autorizado"
        if any(w in s for w in ("exploit", "overflow", "injection", "shellcode")):
            return "Intento de ataque al sistema"
        if any(w in s for w in ("malware", "trojan", "botnet", "c2", "c&c")):
            return "Malware / comunicación sospechosa"
        if any(w in s for w in ("dos", "flood", "ddos", "syn")):
            return "Ataque de saturación (DoS)"
        return "Actividad sospechosa"

    lines    = []
    seen_ips = []
    for a in alerts[:15]:
        ip  = a.get("src_ip") or a.get("ip", "?")
        sig = a.get("alert_signature") or a.get("signature", "")
        sev = str(a.get("severity", "?"))
        ts  = (a.get("timestamp") or a.get("ts", ""))[:16].replace("T", " ")
        icon = "🔴" if sev in ("1", "2") else ("🟠" if sev in ("3", "4") else "🟡")
        label = _sig_label(sig)
        lines.append(f"  {icon} <code>{fmt.e(ip)}</code> — {label}")
        if ts:
            lines.append(f"     <i>{fmt.e(ts)}</i>")
        if ip not in seen_ips and ip != "?":
            seen_ips.append(ip)

    blocked = {item["ip"] for item in (shomer_api.get_blocked_ips() or [])}
    buttons = []
    for ip in seen_ips[:5]:
        if ip not in blocked:
            buttons.append([fmt.btn(f"🚫 Bloquear {ip}", f"block_confirm:{ip}")])

    texto = fmt.card("🛡️", "Hunter — actividad reciente", lines)
    kb    = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply_text(texto, parse_mode=PM, reply_markup=kb)


async def cmd_alertas(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    await _alertas_impl(update.message, ctx, acc.get_level(update))


# ── /salud ────────────────────────────────────────────────────────────────────

def _agent_container_running() -> bool:
    """True si el agente corre. Dentro del container no hay CLI docker — asumir activo."""
    import os
    import subprocess

    if os.path.exists("/.dockerenv"):
        return True
    try:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", "shomer-agent"],
            capture_output=True, text=True, timeout=3,
        )
        return r.stdout.strip().lower() == "true"
    except Exception:
        return True  # host sin docker CLI — el bot respondió, está vivo


async def _salud_impl(message, ctx, level: str):
    await ctx.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)

    parts = []

    # Recursos servidor
    metrics = shomer_api.get_server_metrics()
    if metrics and metrics.get("success"):
        now_m = metrics["now"]
        cpu   = round(now_m.get("cpu", 0), 1)
        ram   = round(now_m.get("ram", 0), 1)
        temp  = now_m.get("temp", "?")
        cpu_i = "✅" if cpu < 75 else ("⚠️" if cpu < 88 else "🔴")
        ram_i = "✅" if ram < 80 else ("⚠️" if ram < 90 else "🔴")
        parts.append(
            fmt.section("💻", "Recursos", [
                f"  {cpu_i} <b>CPU:</b> <code>{cpu}%</code>   "
                f"{ram_i} <b>RAM:</b> <code>{ram}%</code>   🌡 <code>{fmt.e(temp)}°C</code>"
            ])
        )
    else:
        parts.append(fmt.section("💻", "Recursos", ["  <i>métricas no disponibles</i>"]))

    # Servicios
    svc_status = repair.check_services()
    svc_lines  = []
    for key, state in svc_status.items():
        icon = "✅" if state == "active" else "❌"
        svc_lines.append(f"  {icon} {fmt.e(repair.SERVICES[key]['label'])}")
    parts.append(fmt.section("⚙️", "Servicios", svc_lines))

    # Disco
    disk = shomer_api.get_disk_usage()
    if disk.get("ok") and disk.get("partitions"):
        d_lines = []
        for p in disk["partitions"]:
            pct  = p["pct"]
            icon = "✅" if pct < 75 else ("⚠️" if pct < 90 else "🔴")
            d_lines.append(
                f"  {icon} <code>{fmt.e(p['mount'])}</code> "
                f"<b>{pct}%</b> — {fmt.e(p['free_gb'])} GB libres"
            )
        parts.append(fmt.section("💾", "Disco", d_lines))

    # Guardian
    nodes = shomer_api.get_guardian_nodes()
    if nodes:
        online = sum(1 for n in nodes if n.get("status") == "online")
        g_icon = "✅" if online == len(nodes) else ("⚠️" if online > 0 else "🔴")
        g_lines = [f"  {g_icon} <b>{online}/{len(nodes)}</b> APs online"]
        for n in nodes:
            if n.get("status") != "online":
                st = n.get("status", "?")
                g_lines.append(
                    f"  🔴 {fmt.e(n.get('name', n.get('ip', '?')))} — "
                    f"{fmt.e(fmt.guardian_label(st))}"
                )
        parts.append(fmt.section("📡", "Guardian", g_lines))

    # Bot / mantenimiento automático
    from core import auto_tasks
    from core import triage as triage_mod

    active_tasks = sum(
        1 for tid in auto_tasks.TASK_CATALOG
        if auto_tasks.get_task_mode(tid) != "off"
    )
    bot_lines = fmt.auto_tasks_summary_technician(active_tasks, triage_mod.is_enabled())
    if not _agent_container_running():
        bot_lines = ["  🔴 Agente Shomer detenido — contactá soporte USB"]
    bot_lines.extend(_llm.status_lines())
    parts.append(fmt.section("🤖", "Bot / IA", bot_lines))

    # Infraestructura (panel /infra)
    infra = shomer_api.get_infra_summary()
    if infra.get("total"):
        i_lines = [
            f"  {'✅' if not infra.get('offline') else '⚠️'} "
            f"<b>{infra['online']}/{infra['total']}</b> equipos online"
        ]
        if infra.get("outages_24h"):
            i_lines.append(f"  ⚠️ {infra['outages_24h']} caída(s) distintas en 24 h")
        types = infra.get("by_type") or {}
        if types:
            type_txt = ", ".join(
                f"{v} {k}" for k, v in sorted(types.items(), key=lambda x: -x[1])
            )
            i_lines.append(f"  📋 {fmt.e(type_txt)}")
        for d in infra.get("offline", [])[:6]:
            i_lines.append(
                f"  🔴 {fmt.e(d.get('name', d.get('ip')))} "
                f"({fmt.e(d.get('device_type', '?'))})"
            )
        extra = len(infra.get("offline", [])) - 6
        if extra > 0:
            i_lines.append(f"  <i>…y {extra} más caídos — panel Infraestructura</i>")
        if infra.get("low_toner"):
            i_lines.append(f"  🖨️ {len(infra['low_toner'])} impresora(s) con tóner bajo")
        parts.append(fmt.section("🏗️", "Infraestructura", i_lines))

    # Hunter
    pipeline = shomer_api.get_pipeline_health()
    blocked  = shomer_api.get_blocked_ips()
    h_lines  = []
    if pipeline:
        ok_p = pipeline.get("overall_ok", False)
        h_lines.append(
            f"  {'✅' if ok_p else '🟠'} Detección Hunter — "
            f"<b>{'Activa' if ok_p else 'Sin tráfico espejo — panel Hunter → Pipeline'}</b>"
        )
    if blocked:
        n_b = len(blocked)
        h_lines.append(
            f"  🛡️ <b>{n_b}</b> IP(s) contenida(s) — red protegida"
        )
    if h_lines:
        parts.append(fmt.section("🛡️", "Hunter", h_lines))

    # Internet (WAN)
    wan = shomer_api.get_wan_status()
    if wan and wan.get("success") is not False:
        st = wan.get("status", "unknown")
        if st == "online":
            wan_txt = "✅ Conectado a internet"
        elif st == "offline":
            elapsed = wan.get("fail_elapsed_sec")
            suffix = f" — caído hace {elapsed // 60} min" if elapsed else ""
            wan_txt = f"🔴 Sin internet{suffix} — verificar router y proveedor"
        else:
            wan_txt = "⚪ Estado desconocido"
        parts.append(fmt.section("🌐", "Conexión a internet", [f"  {wan_txt}"]))

    # Red (NICs)
    ifaces = shomer_api.get_interfaces()
    if ifaces:
        i_lines = []
        for iface in ifaces:
            st   = iface.get("state", "?")
            icon = "🟢" if st == "UP" else ("🔴" if st == "DOWN" else "⚪")
            i_lines.append(f"  {icon} <code>{fmt.e(iface['name'])}</code> — {fmt.e(st)}")
        parts.append(fmt.section("🔌", "Cables de red", i_lines))

    header = f"{fmt.SEP_WIDE}\n🏥 <b>SALUD — {fmt.e(SITE_NAME)}</b>\n{fmt.SEP_WIDE}"
    texto  = header + "\n\n" + f"\n\n{fmt.SEP}\n\n".join(parts)
    await message.reply_text(texto, parse_mode=PM)


async def _monitores_impl(message, level: str):
    from core.monitor import get_monitor_status
    import time as _t

    now = _t.time()
    status = get_monitor_status()
    sections = []

    def _line_for(name: str) -> str:
        label = MONITOR_LABELS.get(name, name)
        entry = status.get(name)
        if not entry:
            return f"  ⚪ {label} — <i>sin datos aún</i>"
        if entry.get("error"):
            return fmt.monitor_line(label, "", error=entry["error"])
        last_ok = entry.get("last_ok")
        ago = f"hace {int((now - last_ok) / 60)}m" if last_ok else "?"
        alert_tag = ""
        if entry.get("last_alert"):
            am = int((now - entry["last_alert"]) / 60)
            alert_tag = f"alerta hace {am}m" if am < 60 else f"alerta hace {am // 60}h"
        return fmt.monitor_line(label, ago, alert_tag)

    for group_title, names in MONITOR_GROUPS:
        sections.append(fmt.section("", group_title, [_line_for(n) for n in names]))

    await message.reply_text(
        fmt.card("📡", "Monitores automáticos", sections), parse_mode=PM,
    )


async def _resumen_impl(message, level: str):
    from core.groq_helper import explain
    fecha = datetime.now().strftime("%d/%m/%Y")
    hora  = datetime.now().strftime("%H:%M")
    ctx_data = shomer_api.summary_text()
    devices  = dm.list_devices()
    if devices:
        online = sum(1 for d in devices if d.get("status") == "online")
        ctx_data += f"\n\nEquipos agente: {online}/{len(devices)} online"
    resumen = explain(
        "Genera un reporte del estado actual de la red para un técnico de campo. "
        "Incluí: estado general (OK o con problemas), equipos Infra caídos si hay, "
        "amenazas activas, riesgos de red, estado de las IAs (OpenAI y Groq), "
        "y una recomendación concreta si algo requiere atención. Máximo 8 líneas.",
        ctx_data,
    )
    ia_footer = "\n".join(_llm.status_lines())
    await message.reply_text(
        fmt.card("📊", "Reporte del Día — Shomer Sentinel", [
            f"📅 {fecha} · 🕐 {hora}",
            "",
            resumen,
            "",
            ia_footer,
        ]),
        parse_mode=PM,
    )


async def cmd_salud(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    sub = (ctx.args[0].lower() if ctx.args else "")
    try:
        if sub == "monitores":
            await _monitores_impl(update.message, level)
        elif sub in ("resumen", "reporte"):
            await _resumen_impl(update.message, level)
        else:
            await _salud_impl(update.message, ctx, level)
    except Exception as e:
        log.exception("cmd_salud error: %s", e)
        try:
            await update.message.reply_text(
                "⚠️ No pude completar /salud en este momento.\n"
                "➡️ Reintentá en unos segundos. Si persiste, revisá conexión a internet del servidor.",
                parse_mode=PM,
            )
        except Exception:
            pass


async def cmd_monitores(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    try:
        await _monitores_impl(update.message, level)
    except Exception as e:
        log.exception("cmd_monitores error: %s", e)
        await update.message.reply_text(
            "⚠️ No pude cargar los monitores. Reintentá con /salud monitores.",
            parse_mode=PM,
        )


async def cmd_resumen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    try:
        await _resumen_impl(update.message, level)
    except Exception as e:
        log.exception("cmd_resumen error: %s", e)
        await update.message.reply_text(
            "⚠️ No pude generar el resumen. Reintentá con /salud resumen.",
            parse_mode=PM,
        )


# ── /diagnostico — revisar un equipo (antes: ping, info, fix por separado) ───

def _try_remediate_ip(ip: str) -> tuple[bool, list[str], str | None]:
    """Remediación segura: reboot nodo caído, limpieza disco, restart servicios."""
    lines: list[str] = []
    action: str | None = None
    ping = dm.ping_device(ip)
    nodes = shomer_api.get_guardian_nodes() or []
    node = next(
        (n for n in nodes if n.get("ip") == ip or n.get("ip_address") == ip), None,
    )
    st = (node or {}).get("status")

    if node and st in ("offline", "no-internet") and not ping.get("ok"):
        lines.append("  ➡️ <b>Reparación:</b> reiniciando equipo…")
        ok, detail = shomer_api.reboot_guardian_node(ip)
        if ok:
            lines.append("  ✅ Reinicio enviado — vuelve en ~60 s.")
            return True, lines, "reboot"
        lines.append(f"  ❌ No se pudo reiniciar: {fmt.e(str(detail))}")
        return False, lines, None

    disk = shomer_api.get_disk_usage()
    if disk.get("ok"):
        root = next((p for p in disk.get("partitions", []) if p.get("mount") == "/"), None)
        if root and root.get("pct", 0) > 90:
            lines.append(f"  ➡️ <b>Reparación:</b> disco en {root['pct']}% — limpieza…")
            results = repair.run_safe_cleanup()
            freed = sum(r.get("freed_mb", 0) for r in results)
            lines.append(f"  ✅ Limpieza OK — liberados ~{freed:.0f} MB.")
            return True, lines, "disk"

    restarted = []
    for key in repair.failing_services():
        if key in ("guardian", "tools", "nginx"):
            ok, _ = repair.restart_service(key)
            if ok:
                restarted.append(repair.SERVICES[key]["label"])
    if restarted:
        lines.append(f"  ✅ Servicios reiniciados: {', '.join(restarted)}")
        return True, lines, "service"

    lines.append("  ℹ️ No hay reparación automática aplicable.")
    return False, lines, None


async def _diag_impl(message, ctx, level: str, ip: str, *, remediate: bool = False):
    await ctx.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
    lines = []
    ping = dm.ping_device(ip)
    icon = "✅" if ping["ok"] else "🔴"
    lines.append(f"  {icon} <b>Ping:</b> {fmt.e(ping['message'])}")

    nodes = shomer_api.get_guardian_nodes()
    node = next(
        (n for n in (nodes or []) if n.get("ip") == ip or n.get("ip_address") == ip), None,
    )
    _ST_ES = {
        "online": "En línea", "offline": "Sin respuesta — revisar físicamente",
        "degraded": "Señal débil", "no-internet": "Sin internet en el AP",
        "unknown": "Desconocido",
    }
    nombre = ip
    if node:
        st = node.get("status", "?")
        nombre = node.get("name", ip)
        lines.append(f"  {fmt.status_icon(st)} <b>Guardian:</b> {fmt.e(_ST_ES.get(st, st))}")
    else:
        lines.append("  ⚪ <b>Guardian:</b> no está en la lista de nodos")

    data = shomer_api.get_node_failures(ip)
    if data:
        fails = data.get("failures", 0)
        f_i = "✅" if fails == 0 else ("⚠️" if fails < 3 else "🔴")
        f_txt = str(fails)
        if 0 < fails < 5:
            f_txt += " (Guardian reinicia al llegar a 5)"
        elif fails >= 5:
            f_txt += " — reinicio automático próximo"
        lines.append(f"  {f_i} <b>Alertas:</b> {fmt.e(f_txt)}")
        if data.get("last_reboot_ago") is not None:
            h, m = divmod(data["last_reboot_ago"] // 60, 60)
            lines.append(f"  🔄 <b>Último reinicio:</b> hace <code>{h}h {m}m</code>")

    snmp_community = (node or {}).get("snmp_community", "shomer2026") or "shomer2026"
    if ping["ok"]:
        uptime = shomer_api.get_snmp_uptime(ip, snmp_community)
        if uptime:
            lines.append(f"  ⏱️ <b>Uptime:</b> <code>{fmt.e(uptime)}</code>")
        info = dm.get_info(ip)
        if info.get("ok"):
            vendor = info["data"].get("vendor", "?")
            raw = (info["data"].get("raw") or "")[:200]
            lines.append(f"  ℹ️ <b>Equipo:</b> {fmt.e(vendor)}")
            if raw:
                lines.append(f"  <code>{fmt.e(raw)}</code>")

    if shomer_api.get_maintenance():
        lines.append("  🔧 <b>Mantenimiento activo</b> — reboots auto pausados")

    rem_action = None
    rem_ok = False
    if remediate:
        rem_ok, rem_lines, rem_action = _try_remediate_ip(ip)
        lines.extend(rem_lines)

    if node and node.get("status") in ("offline", "no-internet") and not remediate:
        lines.append("\n  ➡️ <b>Qué hacer:</b> reiniciar o usar reparación automática.")

    texto = fmt.card("🔍", f"Diagnóstico — {nombre}", lines)
    kb_rows = []
    if node and node.get("status") in ("offline", "no-internet") and BOT_AUTO_REBOOT:
        kb_rows.append([fmt.btn(f"⚡ Reiniciar {nombre}", f"reboot_confirm:{ip}")])
    if not remediate:
        kb_rows.append([fmt.btn("🔧 Reparar automático", f"diag_fix:{ip}")])
    kb = InlineKeyboardMarkup(kb_rows) if kb_rows else None
    await message.reply_text(texto, parse_mode=PM, reply_markup=kb)
    if remediate and rem_ok and rem_action == "reboot":
        await message.reply_text(
            f"¿El reinicio de <b>{fmt.e(nombre)}</b> resolvió el problema?\n"
            f"Guardalo para que Shomer lo recuerde la próxima vez:",
            parse_mode=PM,
            reply_markup=_save_knowledge_markup(ip),
        )


async def cmd_diagnostico(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    if not ctx.args:
        await update.message.reply_text(
            "🔍 <b>Diagnóstico de equipo</b>\n\n"
            "Revisa si responde, estado en Guardian, alertas, uptime y firmware.\n"
            "Reparación: <code>/diagnostico &lt;ip&gt; reparar</code>\n\n"
            "Ejemplo: <code>/diagnostico 192.168.1.210</code>",
            parse_mode=PM,
        )
        return
    ip = ctx.args[0]
    remediate = len(ctx.args) > 1 and ctx.args[1].lower() in ("reparar", "fix", "arreglar")
    await _diag_impl(update.message, ctx, level, ip, remediate=remediate)


# ── /reiniciar ────────────────────────────────────────────────────────────────

async def cmd_reiniciar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    if not ctx.args:
        await update.message.reply_text(
            "⚡ <b>Guardian Reiniciar</b> — reinicia un AP de forma remota.\n\n"
            "El equipo estará fuera de línea ~60 segundos. Se pedirá confirmación antes de ejecutar.\n\n"
            "Escribí la IP del AP que querés reiniciar:\n"
            "<code>/reboot 192.168.1.10</code>",
            parse_mode=PM,
        )
        return
    ip     = ctx.args[0]
    dev    = dm.get_device(ip)
    nombre = dev["name"] if dev else ip

    if dev and dev.get("no_reboot"):
        await update.message.reply_text(
            f"⛔ <b>{fmt.e(nombre)}</b> no se puede reiniciar desde aquí.\n"
            f"Este equipo es crítico para la red y tiene protección de reinicio activa.",
            parse_mode=PM,
        )
        return

    await update.message.reply_text(
        f"⚡ ¿Reiniciar <b>{fmt.e(nombre)}</b>?\n"
        f"El equipo perderá señal por unos 60 segundos mientras arranca.",
        parse_mode=PM,
        reply_markup=fmt.kb(
            [fmt.btn("✅ Sí, reiniciar", f"reboot_confirm:{ip}"),
             fmt.btn("❌ Cancelar", "reboot_cancel")]
        ),
    )


async def cb_reboot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    level = acc.get_level(update)

    if query.data == "reboot_cancel":
        await query.edit_message_text("Entendido — no se reinició nada.")
        return

    ip = query.data.split(":", 1)[1]
    nombre = _resolve_device_name(ip)
    await query.edit_message_text(
        f"⏳ Enviando orden de reinicio a <b>{fmt.e(nombre)}</b>...", parse_mode=PM
    )
    changelog.log_change(
        query.from_user.id, level, "reboot", ip,
        details="Reinicio manual via bot", reverse_data=None
    )
    shomer_api.log_technician_action(query.from_user.id, "reboot", ip, nombre)
    # Intentar via Guardian API primero (tiene credenciales SSH/SNMP configuradas)
    ok, msg = shomer_api.reboot_guardian_node(ip)
    if not ok:
        # Fallback: equipo registrado solo en devices.json del agente
        result = dm.reboot_device(ip)
        ok, msg = result["ok"], result["message"]
    if ok:
        await query.edit_message_text(
            f"✅ <b>{fmt.e(nombre)}</b> se está reiniciando.\n"
            f"Debería volver en línea en unos 60 segundos.\n\n"
            f"Cuando vuelva, indicá si el reinicio resolvió el problema:",
            parse_mode=PM,
            reply_markup=_save_knowledge_markup(ip),
        )
    else:
        await query.edit_message_text(
            f"❌ No se pudo reiniciar <b>{fmt.e(nombre)}</b>.\n"
            f"➡️ Verificá que el equipo esté encendido y que Shomer tenga acceso a la red.",
            parse_mode=PM,
        )


async def cmd_guardar_conocimiento(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/shomer_guardar <ip> <descripcion del problema y solución>"""
    if not await _guard(update):
        return
    args = ctx.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "📝 <b>Guardar solución</b>\n\n"
            "Uso: <code>/shomer_guardar &lt;ip&gt; &lt;descripcion&gt;</code>\n\n"
            "Ejemplo:\n"
            "<code>/shomer_guardar 192.168.1.10 AP caído por sobrecalentamiento, se movió el equipo y volvió.</code>",
            parse_mode=PM,
        )
        return
    ip   = args[0]
    desc = " ".join(args[1:])
    dev  = dm.get_device(ip)
    nombre = dev["name"] if dev else ip
    meta = shomer_api.save_knowledge(
        ip, nombre,
        problem=desc,
        action=desc,
        saved_by=str(update.effective_user.id),
    )
    await update.message.reply_text(
        _save_reply_text(meta["kid"], nombre, meta),
        parse_mode=PM,
    )


async def cb_save_knowledge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Callback: guarda solución rápida o abre flujo para nota custom (save_know:TIPO:IP)."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        return
    _, tipo, ip = parts[0], parts[1], parts[2]

    if tipo == "x":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    nombre = _resolve_device_name(ip)
    uid = str(query.from_user.id)

    if tipo == "r":
        meta = shomer_api.save_knowledge(
            ip, nombre,
            problem="Equipo sin respuesta / caído",
            action="Reinicio remoto — equipo volvió en línea",
            saved_by=uid,
        )
        await query.edit_message_text(
            _save_reply_text(meta["kid"], nombre, meta),
            parse_mode=PM,
        )
    elif tipo == "u":
        meta = shomer_api.save_knowledge(
            ip, nombre,
            problem="IP bloqueada por error — tráfico legítimo",
            action="Desbloqueo manual — falso positivo confirmado por técnico",
            saved_by=uid,
        )
        await query.edit_message_text(
            f"💾 Falso positivo guardado (#{meta['kid']}) para <code>{fmt.e(ip)}</code>"
            f"{_learning.feedback_suffix(meta)}",
            parse_mode=PM,
        )
    else:
        ctx.user_data["pending_knowledge"] = {"ip": ip, "nombre": nombre}
        await query.edit_message_text(
            f"📝 Describí qué pasó con <b>{fmt.e(nombre)}</b> y cómo se resolvió.\n\n"
            f"Ejemplo: <i>Cámara sin PoE — switch piso 1 reiniciado y volvió.</i>",
            parse_mode=PM,
        )


async def cb_save_task_feedback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Feedback post-TASK automática — save_task:TIPO:TASK-ID."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        return
    _, tipo, tid = parts[0], parts[1], parts[2].upper()

    if tipo == "x":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    uid = str(query.from_user.id)
    title = fmt.TASK_TITLES.get(tid, tid)

    if tipo == "y":
        from core import agente_skills

        sid = agente_skills.record_task_feedback(tid, worked=True)
        _learning.record_human_confirmation(tid, "task_feedback")
        await query.edit_message_text(
            f"✅ Gracias — registrado que <b>{fmt.e(title)}</b> funcionó."
            f"{f' 🧠 Skill #{sid}.' if sid else ''}",
            parse_mode=PM,
        )
    elif tipo == "n":
        from core import agente_skills

        sid = agente_skills.record_task_feedback(tid, worked=False)
        await query.edit_message_text(
            f"📝 Anotado — <b>{fmt.e(title)}</b> no resolvió el problema."
            f"{f' Skill #{sid}.' if sid else ''}\n"
            f"➡️ Revisá /salud o escalá a soporte USB si persiste.",
            parse_mode=PM,
        )
    else:
        ctx.user_data["pending_knowledge"] = {
            "ip": "",
            "nombre": title,
            "task_id": tid,
            "is_task": True,
        }
        await query.edit_message_text(
            f"📝 Describí qué pasó con <b>{fmt.e(title)}</b> y si ayudó o no.\n\n"
            f"Ejemplo: <i>Disco /var al 88% — limpieza bajó a 76%, panel estable.</i>",
            parse_mode=PM,
        )


async def cmd_aprobar_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Developer — promueve TASK-* a approved en este sitio."""
    dev_id = os.environ.get("AGENT_DEVELOPER_ID", "").strip()
    if dev_id and str(update.effective_user.id) != dev_id:
        await update.message.reply_text("⛔ Solo developer USB.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Uso: <code>/aprobar_task TASK-001</code>\n"
            "Promueve una tarea del catálogo a modo <b>approved</b> en este Shomer.",
            parse_mode=PM,
        )
        return
    tid = args[0].upper()
    from core import auto_tasks

    if tid not in auto_tasks.TASK_CATALOG:
        await update.message.reply_text(f"❌ {fmt.e(tid)} no existe en el catálogo.", parse_mode=PM)
        return
    if auto_tasks.set_task_mode(tid, "approved", updated_by=str(update.effective_user.id)):
        label = auto_tasks.TASK_CATALOG.get(tid, tid)
        await update.message.reply_text(
            f"✅ <b>{fmt.e(tid)}</b> — {fmt.e(label)} → modo <b>approved</b> en este sitio.",
            parse_mode=PM,
        )
    else:
        await update.message.reply_text("❌ No se pudo actualizar el modo.", parse_mode=PM)


async def cmd_skills(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Lista skills aprendidas (agente_skills)."""
    if not await _guard(update):
        return
    from core import agente_skills

    ip = ctx.args[0].strip() if ctx.args else ""
    skills = agente_skills.list_skills(device_ip=ip, limit=12)
    if not skills:
        await update.message.reply_text(
            "🧠 Aún no hay skills aprendidas.\n"
            "Usá los botones <b>Guardar solución</b> tras resolver incidentes.",
            parse_mode=PM,
        )
        return
    lines = ["🧠 <b>Skills aprendidas</b>", ""]
    for s in skills:
        lines.append(
            f"• <b>{fmt.e(s.get('trigger_label', '?')[:60])}</b>\n"
            f"  → {fmt.e(s.get('action_label', '?')[:80])}\n"
            f"  <i>OK:{s.get('success_count', 0)} · origen:{fmt.e(s.get('source', '?'))}</i>"
        )
    await update.message.reply_text("\n".join(lines)[:4000], parse_mode=PM)


# ── /clientes ─────────────────────────────────────────────────────────────────

async def cmd_clientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    if not ctx.args:
        await update.message.reply_text(
            "👥 <b>Guardian Clientes</b> — muestra los dispositivos WiFi conectados a un AP.\n\n"
            "Escribí la IP del AP que querés consultar:\n"
            "<code>/clientes 192.168.1.10</code>",
            parse_mode=PM,
        )
        return
    ip = ctx.args[0]
    await update.message.reply_text(
        f"⏳ Consultando clientes en <code>{fmt.e(ip)}</code>...", parse_mode=PM
    )
    result = dm.get_clients(ip)
    if result["ok"]:
        clients = result["data"].get("clients", [])
        count   = result["data"].get("count", len(clients))
        if clients:
            lines = [f"  • <code>{fmt.e(c.get('ip','?'))}</code> — {fmt.e(c.get('mac','?'))} {fmt.e(c.get('hostname',''))}"
                     for c in clients[:20]]
            await update.message.reply_text(
                fmt.card("👥", f"Clientes en {ip} ({count})", lines), parse_mode=PM
            )
        else:
            await update.message.reply_text(
                f"📊 <code>{fmt.e(ip)}</code>: {fmt.e(result['message'])}", parse_mode=PM
            )
    else:
        await update.message.reply_text(
            f"❌ No se pudo consultar <code>{fmt.e(ip)}</code>.\n"
            f"➡️ El AP debe estar en línea. Verificá con /diagnostico.",
            parse_mode=PM,
        )


# ── /agregar ──────────────────────────────────────────────────────────────────

async def cmd_agregar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    if len(ctx.args or []) < 2:
        await update.message.reply_text(
            "➕ <b>Agregar equipo</b> — registra un equipo en el agente para monitorearlo.\n\n"
            "Usa las credenciales globales configuradas en el sistema (usuario de servicio).\n\n"
            "<b>Uso:</b> <code>/agregar &lt;ip&gt; &lt;nombre&gt; [vendor] [puerto]</code>\n\n"
            "Vendors disponibles:\n"
            "<code>mikrotik  ubiquiti  aruba  cisco  tplink_eap  linux  openwrt</code>\n\n"
            "Ejemplos:\n"
            "<code>/agregar 192.168.1.10 AP-Lobby ubiquiti</code>\n"
            "<code>/agregar 192.168.1.20 Switch-Piso1 cisco</code>",
            parse_mode=PM,
        )
        return
    args   = ctx.args
    ip     = args[0]
    name   = args[1]
    vendor = args[2] if len(args) > 2 else ""
    port   = int(args[3]) if len(args) > 3 else 22
    # Usar credenciales de servicio globales configuradas en Shomer
    user = shomer_api.get_config("base.service_user") or "shomer"
    pwd  = shomer_api.get_config("base.service_password") or ""

    dm.add_device(ip, name, user, pwd, vendor, port)
    changelog.log_change(
        update.effective_user.id, level, "add_device", ip,
        details=f"nombre={name} vendor={vendor}",
        reverse_data={"type": "remove_device", "ip": ip},
    )
    await update.message.reply_text(
        fmt.card("✅", f"Equipo registrado — {name}", [
            fmt.row_code("🌐", "IP", ip),
            fmt.row("🔌", "Vendor", vendor or "auto-detect"),
            fmt.row("🔢", "Puerto", str(port)),
            "<i>⏳ Probando conexión...</i>",
        ]),
        parse_mode=PM,
    )
    result = dm.ping_device(ip)
    if result["ok"]:
        await update.message.reply_text(
            f"✅ <b>{fmt.e(name)}</b> está en línea y accesible.", parse_mode=PM
        )
    else:
        await update.message.reply_text(
            f"⚠️ <b>{fmt.e(name)}</b> no respondió todavía.\n"
            f"➡️ Verificá que esté encendido. Probalo con /diagnostico <code>{fmt.e(ip)}</code>",
            parse_mode=PM,
        )


# ── /eliminar ─────────────────────────────────────────────────────────────────

async def cmd_eliminar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    if not ctx.args:
        await update.message.reply_text(
            f"Uso: /eliminar <code>192.168.1.1</code>", parse_mode=PM
        )
        return
    ip      = ctx.args[0]
    old_dev = dm.get_device(ip)
    dev_name = old_dev.get("name", ip) if old_dev else ip
    if dm.remove_device(ip):
        changelog.log_change(
            update.effective_user.id, level, "remove_device", ip,
            details=f"nombre={dev_name}",
            reverse_data={"type": "add_device", "device": old_dev} if old_dev else None,
        )
        await update.message.reply_text(
            f"✅ <b>{fmt.e(dev_name)}</b> fue quitado del monitoreo.", parse_mode=PM
        )
    else:
        await update.message.reply_text(
            f"❌ No encontré <code>{fmt.e(ip)}</code> en la lista.\n"
            f"➡️ Verificá la IP con /equipos.",
            parse_mode=PM,
        )


# ── /desbloquear / /bloquear ──────────────────────────────────────────────────

async def cmd_desbloquear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    if not ctx.args:
        await update.message.reply_text(
            "🔓 <b>Hunter Desbloquear</b> — libera una IP que fue bloqueada en el firewall.\n\n"
            "Usá /alertas para ver las IPs bloqueadas actualmente.\n\n"
            "Escribí la IP que querés liberar:\n"
            "<code>/hunter_desbloquear 192.168.1.45</code>",
            parse_mode=PM,
        )
        return
    ip = ctx.args[0]
    await update.message.reply_text(
        f"⏳ Liberando la IP <code>{fmt.e(ip)}</code>...", parse_mode=PM
    )
    ok, msg = shomer_api.unblock_ip(ip)
    if ok:
        changelog.log_change(
            update.effective_user.id, level, "unblock", ip,
            details="Desbloqueo manual via bot",
            reverse_data={"type": "block", "ip": ip},
        )
        shomer_api.log_technician_action(update.effective_user.id, "unblock", ip)
        await update.message.reply_text(
            f"✅ La IP <code>{fmt.e(ip)}</code> fue liberada — ya puede acceder a internet con normalidad.\n\n"
            f"¿Fue un falso positivo? Guardalo para futuras alertas Hunter:",
            parse_mode=PM,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💾 Falso positivo", callback_data=f"save_know:u:{ip}"),
                    InlineKeyboardButton("📝 Describir", callback_data=f"save_know:o:{ip}"),
                ],
                [InlineKeyboardButton("No guardar", callback_data="save_know:x:0")],
            ]),
        )
    else:
        await update.message.reply_text(
            f"❌ No se pudo liberar <code>{fmt.e(ip)}</code>.\n"
            f"➡️ Revisá el estado del firewall en el panel o contactá soporte.",
            parse_mode=PM,
        )


async def cmd_bloquear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    if not ctx.args:
        await update.message.reply_text(
            "🔒 <b>Hunter Bloquear</b> — bloquea una IP en el firewall del cliente.\n\n"
            "La IP quedará sin acceso a la red hasta que la liberes con /hunter_desbloquear.\n"
            "Se pedirá confirmación antes de ejecutar.\n\n"
            "Escribí la IP que querés bloquear:\n"
            "<code>/hunter_bloquear 192.168.1.45</code>",
            parse_mode=PM,
        )
        return
    ip = ctx.args[0]
    await update.message.reply_text(
        f"🔒 ¿Bloqueamos la IP <code>{fmt.e(ip)}</code>?\n"
        f"Quedará sin acceso a internet hasta que la liberes manualmente.",
        parse_mode=PM,
        reply_markup=fmt.kb(
            [fmt.btn("✅ Sí, bloquear", f"block_confirm:{ip}"),
             fmt.btn("❌ Cancelar", "block_cancel")]
        ),
    )


async def cb_block(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    level = acc.get_level(update)

    if query.data == "block_cancel":
        await query.edit_message_text("Entendido — no se bloqueó nada.")
        return

    ip = query.data.split(":", 1)[1]
    await query.edit_message_text(
        f"⏳ Aplicando bloqueo a <code>{fmt.e(ip)}</code>...", parse_mode=PM
    )
    ok, msg = shomer_api.block_ip(ip)
    if ok:
        changelog.log_change(
            query.from_user.id, level, "block", ip,
            details="Bloqueo manual via bot",
            reverse_data={"type": "unblock", "ip": ip},
        )
        shomer_api.log_technician_action(query.from_user.id, "block", ip)
        await query.edit_message_text(
            f"✅ La IP <code>{fmt.e(ip)}</code> fue bloqueada.\n"
            f"Para liberarla: /hunter_desbloquear {fmt.e(ip)}\n\n"
            f"¿Querés guardar el motivo del bloqueo?",
            parse_mode=PM,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💾 Guardar motivo", callback_data=f"save_know:o:{ip}")],
                [InlineKeyboardButton("No guardar", callback_data="save_know:x:0")],
            ]),
        )
    else:
        await query.edit_message_text(
            f"❌ No se pudo bloquear <code>{fmt.e(ip)}</code>.\n"
            f"➡️ Verificá que el firewall esté configurado en el panel Hunter.",
            parse_mode=PM,
        )


# ── /historial ────────────────────────────────────────────────────────────────

async def cmd_historial(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    rows = changelog.get_recent(10)
    if not rows:
        await update.message.reply_text("📋 No hay cambios registrados aún.")
        return

    _ACTION_LABEL = {
        "block":         "🔒 Bloqueo de IP",
        "unblock":       "🔓 Desbloqueo de IP",
        "reboot":        "⚡ Reinicio de equipo",
        "add_device":    "➕ Equipo agregado",
        "remove_device": "🗑️ Equipo eliminado",
        "restart_guardian": "🔧 Reinicio Guardian",
        "restart_tools":    "🔧 Reinicio Tools",
        "restart_nginx":    "🔧 Reinicio Nginx",
        "disk_cleanup":     "🗑️ Limpieza de disco",
        "restore":          "📦 Restauración de backup",
    }
    lines = []
    for r in rows:
        cid, ts, ulevel, action, target, details, reverted = r
        estado    = " ↩️ deshecho" if reverted else ""
        act_label = _ACTION_LABEL.get(action, fmt.e(action))
        lines.append(
            f"  <code>#{cid}</code> [{fmt.e(ts[5:16])}] {act_label} "
            f"— <code>{fmt.e(target)}</code>{fmt.e(estado)}"
        )
        if details and details != "None":
            lines.append(f"     <i>{fmt.e(details[:60])}</i>")

    await update.message.reply_text(
        fmt.card("📜", f"Cambios recientes — {SITE_NAME}", lines), parse_mode=PM
    )


# ── /revertir ─────────────────────────────────────────────────────────────────

async def cmd_revertir(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text(
            "↩️ Indicá el número del cambio que querés deshacer.\n"
            "Lo encontrás en /historial.\n\n"
            "Ejemplo: <code>/shomer_revertir 5</code>",
            parse_mode=PM,
        )
        return
    change_id = int(ctx.args[0])

    if level == "tecnico":
        row = changelog.get_change_full(change_id)
        if not row:
            await update.message.reply_text(
                "❌ No encontré ese número de cambio. Verificá el ID en /historial.",
                parse_mode=PM,
            )
            return
        _, _, action, target, _, _, owner_id = row
        if str(update.effective_user.id) != str(owner_id):
            await update.message.reply_text(
                "⛔ Solo podés deshacer cambios que hiciste vos mismo.", parse_mode=PM
            )
            return
        if action not in ("block", "unblock"):
            await update.message.reply_text(
                "⛔ Solo podés deshacer bloqueos y desbloqueos.\n"
                "Para otros cambios contactá a soporte USB.",
                parse_mode=PM,
            )
            return

    await update.message.reply_text(f"⏳ Deshaciendo cambio #{change_id}...")
    ok, msg = changelog.revert(change_id)
    if ok:
        await update.message.reply_text(
            f"✅ Cambio #{change_id} deshecho correctamente. Todo volvió al estado anterior.",
            parse_mode=PM,
        )
    else:
        await update.message.reply_text(
            f"❌ No se pudo deshacer el cambio #{change_id}.\n➡️ {fmt.e(msg)}",
            parse_mode=PM,
        )


# ── /instalar — Wizard ────────────────────────────────────────────────────────

INSTALL_STEPS = [
    {
        "title": "1/10 — Este bot es tu herramienta de campo",
        "text": (
            "👁️ <b>Estás hablando con el agente Shomer</b>\n\n"
            "Este bot es tu asistente durante toda la instalación y después de ella. "
            "Te avisa si algo falla, te deja reiniciar APs y revisar el estado del sistema "
            "sin necesidad de abrir el panel.\n\n"
            "📋 <b>Lo que vas a necesitar en papel (te lo entrega USB):</b>\n"
            f"  • IP de fábrica: <code>{_FACTORY_IP}</code>\n"
            "  • Usuario inicial: <code>root</code>\n"
            "  • Contraseña inicial: <code>shomer2026</code>\n\n"
            "📱 <b>Tu Chat ID de Telegram</b> — lo vas a necesitar en el paso 6.\n"
            "Para verlo: escríbele a <b>@userinfobot</b> en Telegram y te lo muestra.\n"
            "Anótalo ahora.\n\n"
            "<i>Cuando estés listo presiona ➡️ Siguiente.</i>"
        ),
    },
    {
        "title": "2/10 — Verificar hardware",
        "text": (
            "🖥️ <b>Confirmar que el mini PC tiene 2 puertos de red</b>\n\n"
            "Conecta teclado y monitor al mini PC y ejecuta:\n"
            "<pre>ip link show</pre>\n"
            "Debes ver <b>al menos 2 interfaces</b> además del loopback (<code>lo</code>):\n"
            "  • Una para conectar al switch del cliente (gestión)\n"
            "  • Otra para recibir el tráfico espejo (Hunter)\n\n"
            "⚠️ Si solo aparece una interfaz, para aquí y llama a <b>soporte USB</b>."
        ),
    },
    {
        "title": "3/10 — Cableado físico",
        "text": (
            "🔌 <b>Conectar los cables de red</b>\n\n"
            "  • <b>Puerto de gestión</b> → cable al switch principal del cliente\n"
            "  • <b>Puerto espejo</b> → cable al puerto SPAN del switch\n\n"
            "El puerto SPAN duplica todo el tráfico de la red hacia el Shomer para que "
            "Hunter pueda detectar amenazas.\n\n"
            "<i>¿Todavía no tienes acceso al switch? Conecta solo el puerto de gestión "
            "y configura el SPAN después. El resto de la instalación puede continuar.</i>"
        ),
    },
    {
        "title": "4/10 — Primer acceso al panel",
        "text": (
            "🌐 <b>Abrir el panel por primera vez</b>\n\n"
            "Conecta tu laptop al mismo switch y abre en el navegador:\n"
            f"<pre>https://{_FACTORY_IP}</pre>\n"
            "<i>Acepta el aviso de certificado — es normal en el primer acceso.</i>\n\n"
            "Ingresa con:\n"
            "  • Usuario: <code>root</code>\n"
            "  • Contraseña: <code>shomer2026</code>\n\n"
            "El panel te lleva directo al <b>wizard de instalación</b>. "
            "Completa los 3 pasos que aparecen:\n\n"
            "  1️⃣ Escanea la red → selecciona las IPs del cliente → guarda\n"
            "  2️⃣ Elige la zona horaria del sitio\n"
            "  3️⃣ Crea el usuario administrador del cliente\n\n"
            "Al terminar, el Shomer queda con la IP definitiva del sitio.\n"
            "⚠️ <b>Anota esa IP nueva</b> — la necesitas para todo lo que sigue."
        ),
    },
    {
        "title": "5/10 — Verificar que arrancó bien",
        "text": (
            "✔️ <b>Check automático — aquí mismo en Telegram</b>\n\n"
            "Reconecta tu laptop con la nueva IP del Shomer, luego escribe "
            "<b>aquí en este mismo chat</b>:\n"
            "<pre>/verificar</pre>\n"
            "El bot se conecta al servidor y te muestra el resultado:\n"
            "  ✅ Verde → OK\n"
            "  ⚠️ Naranja → revisar antes de continuar\n\n"
            "También abre el panel en el navegador con la nueva IP y confirma "
            "que los módulos cargan sin pantalla de error.\n\n"
            "<i>Si algo sale en rojo, copia el mensaje y mándalo a soporte USB.</i>"
        ),
    },
    {
        "title": "6/10 — Módulos y contraseña del panel",
        "text": (
            "🔒 <b>Activar módulos y cambiar contraseña</b>\n\n"
            "En el panel: <b>Administración</b>\n\n"
            "1️⃣ <b>Módulos:</b> activa solo los que el cliente contrató\n"
            "  • Guardian — monitoreo de red (siempre activo)\n"
            "  • Hunter — detección de intrusos\n"
            "  • 🔍 Tracker — inventario de equipos\n"
            "  • 🛡️ Protector — respaldos automáticos\n\n"
            "2️⃣ <b>Contraseña:</b> cambia la contraseña de <code>root</code> por una segura\n\n"
            "⚠️ No continúes con la contraseña de fábrica — cualquiera en la red "
            "del cliente podría entrar al panel."
        ),
    },
    {
        "title": "7/10 — Guardian: registrar los APs y Telegram",
        "text": (
            "🛡️ <b>Agregar los APs y routers del cliente</b>\n\n"
            "En el panel: <b>Guardian → Nodos → Agregar nodo</b>\n\n"
            "Por cada AP o router ingresa:\n"
            "  • IP del equipo\n"
            "  • Usuario y contraseña de acceso\n"
            "  • Tipo de reboot (SSH para routers, SNMP para TP-Link EAP)\n\n"
            "Presiona <b>Probar conexión</b> → debe aparecer <code>online</code> en verde.\n\n"
            "📱 <b>Configurar Telegram en Guardian:</b>\n"
            "Panel → <b>Guardian → Configuración → Chat ID</b>\n"
            "Ingresa el Chat ID que anotaste en el paso 1 y presiona <b>Probar</b>.\n"
            "Debes recibir un mensaje de prueba <b>aquí en este mismo chat</b>."
        ),
    },
    {
        "title": "8/10 — Hunter: confirmar el espejo",
        "text": (
            "🦁 <b>Verificar que Hunter ve el tráfico</b>\n\n"
            "En el panel: <b>Hunter → Pipeline</b>\n\n"
            "Si el puerto SPAN del switch está bien conectado, el pipeline "
            "debe mostrar estado <b>activo</b> y comenzar a aparecer alertas.\n\n"
            "Prueba rápida: desde cualquier PC de la red del cliente, abre "
            "un navegador o haz un ping. Espera 1-2 minutos y recarga Hunter.\n\n"
            "Si el pipeline aparece vacío o sin actividad:\n"
            "  • Verifica que el cable del puerto espejo está bien conectado\n"
            "  • Confirma con el cliente que el SPAN está configurado en su switch\n"
            "  • Llama a soporte USB si no logras verlo activo"
        ),
    },
    {
        "title": "9/10 — 🛡️ Protector: equipos de respaldo",
        "text": (
            "🛡️ <b>Configurar backups automáticos</b>\n\n"
            "<i>Solo si el cliente contrató el módulo Protector.</i>\n\n"
            "En el panel: <b>🛡️ Protector → Agregar dispositivo</b>\n\n"
            "Por cada equipo a respaldar:\n"
            "  • Nombre del equipo y su IP\n"
            "  • Tipo: <b>SSH</b> (Linux/Mac) o <b>SMB</b> (Windows)\n"
            "  • Usuario y contraseña del equipo\n\n"
            "Presiona <b>Probar conexión</b> → verde = listo.\n"
            "Activa el <b>horario automático</b> para que el backup corra solo cada noche.\n\n"
            "☁️ Si el cliente tiene respaldo en la nube: ingresa las credenciales "
            "B2 en <b>🛡️ Protector → Configuración B2</b> y presiona <b>Probar</b>."
        ),
    },
    {
        "title": "10/10 — Check final de entrega",
        "text": (
            "✅ <b>Criterios de aprobación antes de entregar</b>\n\n"
            "☐ /verificar muestra todo en verde\n"
            "☐ Módulos contratados visibles y sin errores en el panel\n"
            "☐ Guardian: al menos un AP en <code>online</code>\n"
            "☐ Telegram: recibiste el mensaje de prueba de Guardian\n"
            "☐ Hunter: pipeline activo (si tiene SPAN)\n"
            "☐ 🛡️ Protector: backup de prueba exitoso (si aplica)\n"
            "☐ Contraseña de fábrica cambiada\n\n"
            "📸 <i>Toma una foto del panel con los módulos activos para el archivo de entrega.</i>\n\n"
            "🎉 <b>Instalación completa.</b>\n"
            "Deja anotado al cliente: IP del Shomer, usuario y teléfono de soporte USB."
        ),
    },
]


def _instalar_keyboard(step: int) -> InlineKeyboardMarkup:
    buttons = []
    if step > 0:
        buttons.append(fmt.btn("⬅️ Anterior", f"instalar:{step-1}"))
    if step < len(INSTALL_STEPS) - 1:
        buttons.append(fmt.btn("➡️ Siguiente", f"instalar:{step+1}"))
    else:
        buttons.append(fmt.btn("✅ Instalación completa", "instalar_done"))
    return InlineKeyboardMarkup([buttons])


def _instalar_text(step_n: int) -> str:
    step = INSTALL_STEPS[step_n]
    return (
        f"{fmt.SEP_WIDE}\n"
        f"📋 <b>Guía de instalación Shomer Sentinel</b>\n"
        f"{fmt.SEP_WIDE}\n\n"
        f"<b>{fmt.e(step['title'])}</b>\n\n"
        f"{step['text']}"
    )


async def cmd_usuario(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    txt = (
        f"👤 <b>Crear usuario de servicio Shomer</b>\n"
        f"─────────────────────\n"
        f"Este usuario se crea en cada equipo (PC/Mac/servidor) antes de registrarlo "
        f"en Tracker y Protector. El nombre y contraseña deben coincidir con lo que configuraste "
        f"en el panel → Instalación → Usuario de servicio.\n\n"
        f"Elige el sistema operativo del equipo:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🐧 Linux",   callback_data="usuario:linux")],
        [InlineKeyboardButton("🍎 macOS",   callback_data="usuario:mac")],
        [InlineKeyboardButton("🪟 Windows", callback_data="usuario:windows")],
    ])
    await update.message.reply_text(txt, parse_mode=PM, reply_markup=kb)


async def cb_usuario(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    level = acc.get_level(update)
    if not level:
        return
    _, os_key = query.data.split(":", 1)

    if os_key == "linux":
        txt = (
            f"🐧 <b>Linux — crear usuario shomer</b>\n"
            f"─────────────────────\n"
            f"Ejecuta en el equipo objetivo:\n\n"
            f"<pre>sudo adduser shomer</pre>\n"
            f"Cuando pida contraseña, escribe la misma que configuraste en el panel.\n\n"
            f"Luego crea la carpeta de backup:\n"
            f"<pre>mkdir -p /home/shomer/backups</pre>\n\n"
            f"Si necesitas que acceda a carpetas del sistema, agrégalo al grupo:\n"
            f"<pre>sudo usermod -aG sudo shomer</pre>\n"
            f"<i>✅ Verificar: <code>id shomer</code></i>"
        )
    elif os_key == "mac":
        txt = (
            f"🍎 <b>macOS — crear usuario shomer</b>\n"
            f"─────────────────────\n"
            f"<b>Opción 1 — Interfaz gráfica:</b>\n"
            f"Preferencias del sistema → Usuarios y grupos → <b>+</b> → tipo Estándar → nombre: <code>shomer</code>\n\n"
            f"<b>Opción 2 — Terminal:</b>\n"
            f"<pre>sudo dscl . -create /Users/shomer\n"
            f"sudo dscl . -create /Users/shomer UserShell /bin/bash\n"
            f"sudo dscl . -create /Users/shomer RealName shomer\n"
            f"sudo dscl . -create /Users/shomer UniqueID 502\n"
            f"sudo dscl . -create /Users/shomer PrimaryGroupID 20\n"
            f"sudo dscl . -passwd /Users/shomer TU_CONTRASENA\n"
            f"sudo mkdir -p /Users/shomer/backups\n"
            f"sudo chown shomer /Users/shomer/backups</pre>\n"
            f"Habilita SSH: Preferencias → Compartir → <b>Inicio de sesión remoto ✓</b>\n"
            f"<i>✅ Verificar: <code>ssh shomer@IP_MAC</code></i>"
        )
    else:
        txt = (
            f"🪟 <b>Windows — crear usuario shomer</b>\n"
            f"─────────────────────\n"
            f"En CMD como Administrador:\n"
            f"<pre>net user shomer TU_CONTRASENA /add</pre>\n\n"
            f"Crear carpeta de backup y compartirla:\n"
            f"<pre>mkdir C:\\backups</pre>\n"
            f"Clic derecho en <code>C:\\backups</code> → Propiedades → Compartir → nombre del share: <code>backups</code>\n"
            f"Permisos: usuario <code>shomer</code> con control total.\n\n"
            f"<b>Active Directory:</b> crea el usuario en el AD con la misma contraseña — se aplica a todos los equipos del dominio automáticamente.\n\n"
            f"<i>✅ Verificar desde el Shomer: ping al equipo Windows y credenciales en Tracker → Credenciales.</i>"
        )
    await query.edit_message_text(txt, parse_mode=PM)


async def cmd_instalar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await _guard(update):
        return
    await update.message.reply_text(
        _instalar_text(0), parse_mode=PM, reply_markup=_instalar_keyboard(0)
    )


async def cb_instalar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "instalar_done":
        await query.edit_message_text(
            f"{fmt.SEP_WIDE}\n✅ <b>Guía de instalación finalizada.</b>\n{fmt.SEP_WIDE}\n\n"
            f"Repetir un paso: /instalar\n"
            f"Chequeo del equipo: /verificar\n"
            f"Soporte: contacto <b>USB</b> según contrato del sitio.",
            parse_mode=PM,
        )
        return
    step_n = int(query.data.split(":")[1])
    await query.edit_message_text(
        _instalar_text(step_n), parse_mode=PM, reply_markup=_instalar_keyboard(step_n)
    )


# ── /mantenimiento ────────────────────────────────────────────────────────────

async def _mantenimiento_set(message, on: bool):
    ok = shomer_api.set_maintenance(on)
    if ok:
        if on:
            await message.reply_text(
                fmt.card("🔧", "Mantenimiento ACTIVADO", [
                    "Guardian sigue monitoreando pero <b>no reiniciará APs</b> automáticamente.",
                    "<i>Desactívalo cuando termines.</i>",
                ]),
                parse_mode=PM,
                reply_markup=fmt.kb([fmt.btn("✅ Desactivar cuando termine", "maint:off")]),
            )
        else:
            await message.reply_text(
                fmt.alert_card("Mantenimiento desactivado",
                               ["Guardian reanuda reboots automáticos normalmente."], "ok"),
                parse_mode=PM,
            )
    else:
        await message.reply_text("❌ No se pudo cambiar el modo de mantenimiento. Avisá a soporte si persiste.")


async def cmd_mantenimiento(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    if ctx.args and ctx.args[0].lower() in ("on", "off"):
        await _mantenimiento_set(update.message, ctx.args[0].lower() == "on")
        return
    activo = shomer_api.get_maintenance()
    estado = "🔧 <b>ACTIVO</b> — reboots automáticos pausados" if activo else "✅ <b>Inactivo</b> — reboots normales"
    boton  = fmt.btn("✅ Desactivar mantenimiento", "maint:off") if activo \
             else fmt.btn("🔧 Activar mantenimiento", "maint:on")
    await update.message.reply_text(
        fmt.card("🔧", "Modo mantenimiento", [
            estado,
            "<i>Activarlo siempre que vayas a trabajar físicamente en los equipos.</i>",
        ]),
        parse_mode=PM,
        reply_markup=fmt.kb([boton]),
    )


async def cb_mantenimiento(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not await _guard(update):
        return
    on = query.data.split(":")[1] == "on"
    await query.edit_message_reply_markup(reply_markup=None)
    await _mantenimiento_set(query.message, on)


async def cb_salud(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    level = acc.get_level(update)
    if not level:
        return
    action = query.data.split(":", 1)[1]
    msg = query.message
    if action == "monitores":
        await _monitores_impl(msg, level)
    elif action == "resumen":
        await _typing_q(query, ctx)
        await _resumen_impl(msg, level)


async def cb_diag_fix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ Reparando…")
    level = acc.get_level(update)
    if not level:
        return
    ip = query.data.split(":", 1)[1]
    await query.edit_message_reply_markup(reply_markup=None)
    await _diag_impl(query.message, ctx, level, ip, remediate=True)


# ── cb_repair ────────────────────────────────────────────────────────────────

async def cb_dismiss(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Quita botones tras 'Entendido' en alertas consolidadas."""
    query = update.callback_query
    await query.answer("✅ Registrado")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


async def cb_repair(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    level = await _guard(update)
    if not level:
        return
    action = query.data.split(":", 1)[1]

    if action == "cancel":
        await query.edit_message_text("❌ Reparación cancelada.")

    elif action.startswith("zombie_"):
        port = int(action.split("_")[1])
        await query.edit_message_text(f"⏳ Liberando el puerto {port}...")
        ok, out = repair.kill_zombie(port)
        changelog.log_change(query.from_user.id, level, "kill_zombie", f":{port}", out[:80])
        if ok:
            await query.edit_message_text(
                f"✅ Puerto {port} liberado correctamente.", parse_mode=PM
            )
        else:
            await query.edit_message_text(
                f"❌ No se pudo liberar el puerto {port}.\n➡️ Avisá a soporte USB.",
                parse_mode=PM,
            )

    elif action == "suricata":
        await query.edit_message_text("⏳ Reiniciando el sistema de detección de amenazas...")
        ok, out = repair.restart_suricata()
        await asyncio.sleep(4)
        pipeline = shomer_api.get_pipeline_health()
        pipeline_ok = (pipeline or {}).get("overall_ok")
        changelog.log_change(query.from_user.id, level, "restart_suricata", "suricata", out[:80])
        if ok and pipeline_ok:
            await query.edit_message_text(
                "✅ Sistema de detección reiniciado y funcionando correctamente.", parse_mode=PM
            )
        elif ok:
            await query.edit_message_text(
                "⚠️ Reiniciado pero aún no recibe datos. Esperá 1-2 minutos y verificá con /salud.",
                parse_mode=PM,
            )
        else:
            await query.edit_message_text(
                "❌ No se pudo reiniciar. ➡️ Avisá a soporte USB.", parse_mode=PM
            )

    elif action.startswith("disk_"):
        rule_id = action[5:]
        rule    = next((r for r in repair.DISK_CLEANUP_RULES if r["id"] == rule_id), None)
        label   = rule["label"] if rule else rule_id
        await query.edit_message_text(f"⏳ Ejecutando limpieza: {fmt.e(label)}...", parse_mode=PM)
        ok, out = repair.run_cleanup_rule(rule_id)
        disk    = shomer_api.get_disk_usage()
        free    = disk.get("free_gb", "?") if disk and disk.get("ok") else "?"
        changelog.log_change(query.from_user.id, level, "disk_cleanup", rule_id, out[:80])
        if ok:
            await query.edit_message_text(
                f"✅ {fmt.e(label)} completado. Disco libre ahora: <code>{fmt.e(free)} GB</code>",
                parse_mode=PM,
            )
        else:
            await query.edit_message_text(
                f"❌ {fmt.e(label)} falló. ➡️ Avisá a soporte USB.", parse_mode=PM
            )

    elif action in repair.SERVICES:
        label = repair.SERVICES[action]["label"]
        await query.edit_message_text(f"⏳ Reiniciando {fmt.e(label)}...", parse_mode=PM)
        ok, out = repair.restart_service(action)
        changelog.log_change(query.from_user.id, level, f"restart_{action}", action, out[:80])
        await asyncio.sleep(3)
        status       = repair.check_services()
        nuevo_estado = status.get(action, "?")
        if ok and nuevo_estado == "active":
            await query.edit_message_text(
                f"✅ <b>{fmt.e(label)}</b> reiniciado y funcionando.", parse_mode=PM
            )
        else:
            await query.edit_message_text(
                f"❌ <b>{fmt.e(label)}</b> sigue sin responder.\n➡️ Avisá a soporte USB.",
                parse_mode=PM,
            )

    else:
        await query.edit_message_text("❓ Acción no reconocida.")


# ── /verificar ────────────────────────────────────────────────────────────────

async def cmd_verificar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    await _typing(update, ctx)
    check    = shomer_api.run_install_check()
    results  = check["results"]
    ok_count = check["ok"]
    total    = check["total"]
    warnings = check["warnings"]

    resumen_icon = "✅" if warnings == 0 else "⚠️"
    resumen_txt  = f"Todo OK — {ok_count}/{total}" if warnings == 0 \
                   else f"{ok_count}/{total} OK — {warnings} pendiente(s)"

    lines = []
    failing = [r for r in results if not r["ok"]]
    passing = [r for r in results if r["ok"]]

    if failing:
        lines.append("<b>Requiere atención:</b>")
        for r in failing:
            detail = f"\n     <i>{fmt.e(r['detail'])}</i>" if r.get("detail") else ""
            lines.append(f"  ⚠️ {fmt.e(r['label'])}{detail}")
        lines.append("")

    lines.append("<b>Completado:</b>")
    for r in passing:
        detail = f" — <i>{fmt.e(r['detail'])}</i>" if r.get("detail") else ""
        lines.append(f"  ✅ {fmt.e(r['label'])}{detail}")

    lines.append(f"\n<i>{fmt.e(resumen_txt)}</i>")

    await update.message.reply_text(
        fmt.card(resumen_icon, f"Verificación — {SITE_NAME}", lines), parse_mode=PM
    )


# ── /nuevo ────────────────────────────────────────────────────────────────────

async def cmd_nuevo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return
    _memory.clear_history(update.effective_user.id)
    await update.message.reply_text(
        "✅ Conversación borrada. El asistente empieza desde cero con tu próxima consulta.",
        parse_mode=PM,
    )


# ── Lenguaje natural ──────────────────────────────────────────────────────────

async def msg_natural(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    level = await _guard(update)
    if not level:
        return

    text    = update.message.text or ""
    user_id = update.effective_user.id

    # Si hay un incidente pendiente de describir, guardarlo directamente
    if ctx.user_data.get("pending_knowledge"):
        pk = ctx.user_data.pop("pending_knowledge")
        if pk.get("is_task") and pk.get("task_id"):
            from core import agente_skills

            tid = pk["task_id"]
            sid = agente_skills.record_task_feedback(tid, worked=True, notes=text)
            meta = shomer_api.save_knowledge(
                "", pk.get("nombre", tid),
                problem=text,
                action=text,
                saved_by=str(user_id),
            )
            _learning.record_human_confirmation(tid, "task_describe")
            await update.message.reply_text(
                f"💾 Guardado (#{meta['kid']}) — {fmt.e(pk.get('nombre', tid))}."
                f"{_learning.feedback_suffix(meta)}"
                f"{f' 🧠 Skill #{sid}.' if sid else ''}",
                parse_mode=PM,
            )
        else:
            meta = shomer_api.save_knowledge(
                pk["ip"], pk["nombre"],
                problem=text,
                action=text,
                saved_by=str(user_id),
            )
            await update.message.reply_text(
                _save_reply_text(meta["kid"], pk["nombre"], meta),
                parse_mode=PM,
            )
        return

    # Rate-limit siempre, incluso cuando el bot está pausado
    if not _mnt.check_user_rate(user_id):
        await update.message.reply_text("⏳ Esperá unos segundos antes de enviar otro mensaje.")
        return

    # Modo mantenimiento global (solo bloquea texto libre, no comandos)
    if _mnt.is_paused():
        await update.message.reply_text(
            "🛠️ <b>Asistente en pausa</b> — cuota Groq en enfriamiento.\n"
            "<i>Usa /salud · /alertas mientras tanto.</i>",
            parse_mode=PM,
        )
        return

    # Preguntas de identidad → respuesta fija sin LLM
    if _is_identity_question(text):
        await update.message.reply_text(_IDENTITY_RESPONSE, parse_mode=PM)
        return

    # Saludos → respuesta corta sin Groq
    if _is_greeting(text):
        resp = random.choice(_GREETING_RESPONSES)
        await update.message.reply_text(resp, parse_mode=PM)
        return

    # Lenguaje natural con tool calling y memoria
    await _typing(update, ctx)
    _memory.add_message(user_id, "user", text, level)
    history = _memory.get_history(user_id)

    loop = asyncio.get_running_loop()
    try:
        respuesta = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                partial(_llm.chat, history, level=level, user_id=user_id),
            ),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        respuesta = "⏱ La consulta tardó demasiado. Intenta de nuevo con una pregunta más concreta."
    except Exception as ex:
        log.warning("Groq ejecutor: %s", ex)
        respuesta = "⚠️ No pude contactar el asistente. Usa /salud · /ayuda."

    respuesta = (respuesta or "").strip() or \
        "Sin respuesta del asistente. Usa /salud para datos del servidor."

    _memory.add_message(user_id, "assistant", respuesta, level)
    # Groq genera Markdown — enviarlo con parse_mode Markdown
    await update.message.reply_text(respuesta[:4096], parse_mode="Markdown")


# ── Arranque ──────────────────────────────────────────────────────────────────

def run():
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )

    # Comandos — nombres cortos (sin prefijo de módulo)
    for cmd, fn in [
        # Global
        ("ayuda",          cmd_ayuda),
        ("consultas",      cmd_consultas),
        # Servidor
        ("salud",          cmd_salud),
        ("monitores",      cmd_monitores),
        ("resumen",        cmd_resumen),
        ("historial",      cmd_historial),
        ("revertir",       cmd_revertir),
        ("nuevo",          cmd_nuevo),
        ("guardar",        cmd_guardar_conocimiento),
        ("skills",         cmd_skills),
        ("aprobar_task",   cmd_aprobar_task),
        # Red
        ("equipos",        cmd_equipos),
        ("infra",          cmd_infra),
        ("puertos",        cmd_puertos),
        ("diagnostico",    cmd_diagnostico),
        ("diag",           cmd_diagnostico),
        ("reboot",         cmd_reiniciar),
        ("reiniciar",      cmd_reiniciar),
        ("clientes",       cmd_clientes),
        ("modo",           cmd_mantenimiento),
        ("mantenimiento",  cmd_mantenimiento),
        # Seguridad
        ("alertas",        cmd_alertas),
        ("bloquear",       cmd_bloquear),
        ("desbloquear",    cmd_desbloquear),
        # Instalación
        ("instalar",       cmd_instalar),
        ("usuario",        cmd_usuario),
        ("verificar",      cmd_verificar),
        ("eliminar",       cmd_eliminar),
        ("agregar",        cmd_agregar),
        # Aliases compatibilidad (nombres anteriores siguen funcionando)
        ("shomer_salud",           cmd_salud),
        ("shomer_monitores",       cmd_monitores),
        ("shomer_resumen",         cmd_resumen),
        ("shomer_historial",       cmd_historial),
        ("shomer_revertir",        cmd_revertir),
        ("shomer_nueva_consulta",  cmd_nuevo),
        ("guardian_equipos",       cmd_equipos),
        ("infra_equipos",          cmd_infra),
        ("infra_puertos",          cmd_puertos),
        ("guardian_diagnostico",   cmd_diagnostico),
        ("guardian_reiniciar",     cmd_reiniciar),
        ("guardian_clientes",      cmd_clientes),
        ("guardian_mantenimiento", cmd_mantenimiento),
        ("hunter_alertas",         cmd_alertas),
        ("hunter_bloquear",        cmd_bloquear),
        ("hunter_desbloquear",     cmd_desbloquear),
        ("instalar_usuario",       cmd_usuario),
        ("instalar_verificar",     cmd_verificar),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Callbacks
    app.add_handler(CallbackQueryHandler(cb_salud,           pattern="^salud:"))
    app.add_handler(CallbackQueryHandler(cb_diag_fix,        pattern="^diag_fix:"))
    app.add_handler(CallbackQueryHandler(cb_reboot,          pattern="^reboot_"))
    app.add_handler(CallbackQueryHandler(cb_mantenimiento,   pattern="^maint:"))
    app.add_handler(CallbackQueryHandler(cb_instalar,        pattern="^instalar"))
    app.add_handler(CallbackQueryHandler(cb_repair,          pattern="^repair:"))
    app.add_handler(CallbackQueryHandler(cb_dismiss,         pattern="^dismiss:"))
    app.add_handler(CallbackQueryHandler(cb_block,           pattern="^block_"))
    app.add_handler(CallbackQueryHandler(cb_usuario,         pattern="^usuario:"))
    app.add_handler(CallbackQueryHandler(cb_save_knowledge,  pattern="^save_know:"))
    app.add_handler(CallbackQueryHandler(cb_save_task_feedback, pattern="^save_task:"))

    # Mensajes
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_natural))

    log.info("Agente Shomer iniciado — chat único — sitio: %s", SITE_NAME)

    async def post_init(application):
        monitor.start_all(application.bot)
        await application.bot.set_my_commands([
            BotCommand("consultas", "Ejemplos de texto libre"),
            BotCommand("ayuda", "Lista completa de comandos"),
            BotCommand("salud", "Estado del servidor Shomer"),
            BotCommand("monitores", "Monitores automáticos activos"),
            BotCommand("resumen", "Reporte del día con IA"),
            BotCommand("equipos", "Guardian — APs y nodos"),
            BotCommand("diagnostico", "Revisar IP (+ reparar)"),
            BotCommand("diag", "Atajo de /diagnostico"),
            BotCommand("reboot", "Reiniciar equipo por IP"),
            BotCommand("reiniciar", "Igual que /reboot"),
            BotCommand("clientes", "WiFi conectados a un AP"),
            BotCommand("modo", "Mantenimiento on/off"),
            BotCommand("mantenimiento", "Igual que /modo"),
            BotCommand("infra", "Infra — lista o detalle por IP"),
            BotCommand("puertos", "SNMP — puertos switch/server"),
            BotCommand("alertas", "Hunter — alertas y bloqueos"),
            BotCommand("bloquear", "Bloquear IP en firewall"),
            BotCommand("desbloquear", "Liberar IP bloqueada"),
            BotCommand("guardar", "Guardar solución en historial"),
            BotCommand("skills", "Skills aprendidas del sitio"),
            BotCommand("historial", "Cambios recientes del bot"),
            BotCommand("revertir", "Deshacer bloqueo/desbloqueo"),
            BotCommand("instalar", "Guía instalación del sitio"),
            BotCommand("verificar", "Checklist post-instalación"),
            BotCommand("usuario", "Crear usuario shomer por OS"),
            BotCommand("agregar", "Registrar equipo en agente"),
            BotCommand("eliminar", "Quitar equipo del agente"),
            BotCommand("nuevo", "Limpiar chat con IA"),
        ])

    async def _error_handler(update, context):
        from telegram.error import NetworkError, TimedOut
        if isinstance(context.error, (NetworkError, TimedOut)):
            log.warning("Telegram conectividad temporal: %s", context.error)
        else:
            log.error("Error no manejado: %s", context.error, exc_info=context.error)

    app.add_error_handler(_error_handler)
    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)
