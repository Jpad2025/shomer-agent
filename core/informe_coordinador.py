"""Informe periódico para el coordinador de soporte.

Separa dos trabajos que hoy se mezclan en un mismo canal:

- El **técnico** actúa: recibe alertas por Telegram, ahora mismo, para hacer algo.
- El **coordinador** supervisa: necesita saber qué lleva días sin resolverse y
  qué exige una visita, no enterarse de cada evento.

Por eso esto NO repite las alertas del día. Se arma con lo que ya quedó
registrado —tickets crónicos abiertos, respaldos, internet de los huéspedes,
seguridad— y responde a una sola pregunta: *qué sigue pendiente*.

Todo sale de hechos guardados. Si un dato no está disponible se dice que no
está, nunca se rellena con un supuesto: un informe que inventa es peor que no
tener informe, porque se decide sobre él.

Configuración (por sitio, en el `.env` — nada de esto se comparte entre hoteles):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
    SUPPORT_EMAIL_FROM, SUPPORT_EMAIL_TO
    INFORME_COORDINADOR_CADA      'diario' | 'semanal'  (por defecto: semanal)
    INFORME_COORDINADOR_HORA      hora local 0-23       (por defecto: 7)
    INFORME_COORDINADOR_DIA       0=lunes … 6=domingo   (solo si es semanal)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("shomer-informe")

SIN_DATO = "sin dato"


def _cfg(clave: str, defecto: str) -> str:
    return (os.environ.get(clave) or defecto).strip()


def cada() -> str:
    v = _cfg("INFORME_COORDINADOR_CADA", "semanal").lower()
    return "diario" if v.startswith("d") else "semanal"


def hora() -> int:
    try:
        return max(0, min(23, int(_cfg("INFORME_COORDINADOR_HORA", "7"))))
    except ValueError:
        return 7


def dia_semana() -> int:
    try:
        return max(0, min(6, int(_cfg("INFORME_COORDINADOR_DIA", "0"))))
    except ValueError:
        return 0


def destinatario() -> str:
    return _cfg("SUPPORT_EMAIL_TO", "")


def configurado() -> bool:
    """Sin servidor de correo y sin destinatario no hay informe que enviar."""
    return bool(_cfg("SMTP_HOST", "") and destinatario())


# ── Recolección ──────────────────────────────────────────────────────────────

def _dias_desde(texto: Optional[str]) -> Optional[int]:
    if not texto:
        return None
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(str(texto)[:19], formato)
            return max(0, (datetime.now() - d).days)
        except ValueError:
            continue
    return None


def _pendientes_cronicos() -> List[Dict[str, Any]]:
    """Lo que lleva días abierto: el corazón del informe."""
    try:
        from core import chronic_tickets
        abiertos = chronic_tickets.list_open() or []
    except Exception as e:
        log.debug("informe: tickets: %s", e)
        return []
    salida = []
    for t in abiertos:
        nombre = str(t.get("entity_name") or t.get("ip") or "?")
        # Los hallazgos del cerebro traen la lista entera de equipos en el
        # nombre. Recortada a la mitad no se entiende y encima engaña: parece
        # que el problema es del primero de la lista. Se resume por lo que es.
        if nombre.startswith("🧠"):
            equipos = [e.strip() for e in nombre.lstrip("🧠 ").split(",") if e.strip()]
            primeros = ", ".join(equipos[:3])
            resto = f" y {len(equipos) - 3} más" if len(equipos) > 3 else ""
            nombre = f"Causa común entre {len(equipos)} equipos: {primeros}{resto}"
        elif len(nombre) > 90:
            nombre = nombre[:87] + "…"
        # La columna es opened_at; created_at queda como alternativa por si una
        # instalación vieja la trae con el otro nombre.
        salida.append({
            "nombre": nombre,
            "ip": t.get("ip") or "",
            "fuente": t.get("fuente") or "",
            "dias": _dias_desde(t.get("opened_at") or t.get("created_at")),
        })
    return salida


def _senas_del_equipo() -> Dict[str, Dict[str, str]]:
    """Ubicación y MAC por IP, para los equipos que hay que ir a buscar.

    12 sep 2026: dos datáfonos figuraban como "ubicación por confirmar" y el
    técnico iba a tener que buscarlos a ojo por el hotel. Shomer ya tenía sus
    MAC —50 de 51 equipos las tienen, las recoge el propio sondeo— pero el dato
    no aparecía en ningún lado donde alguien fuera a mirarlo. Con la MAC se
    identifica el aparato físico por la etiqueta de su parte de atrás, que es
    la diferencia entre una visita útil y una de reconocimiento.
    """
    try:
        from core import shomer_api
        equipos = shomer_api.get_infra_devices() or []
    except Exception as e:
        log.debug("informe: señas: %s", e)
        return {}
    salida = {}
    for d in equipos:
        ip = str(d.get("ip") or "")
        if not ip:
            continue
        ubic = str(d.get("location") or "").strip()
        salida[ip] = {
            "ubicacion": ubic,
            "mac": str(d.get("mac") or "").strip(),
            "sin_ubicacion": (not ubic) or ubic.lower().startswith("por confirmar"),
        }
    return salida


def _respaldos() -> Dict[str, Any]:
    try:
        from core import shomer_api
        equipos = shomer_api.get_backup_devices() or []
        nube = shomer_api.get_last_b2_sync()
    except Exception as e:
        log.debug("informe: respaldos: %s", e)
        return {}
    atrasados = []
    for d in equipos:
        dias = _dias_desde(d.get("last_backup_at"))
        if dias is None or dias >= 2:
            atrasados.append({"nombre": d.get("name") or d.get("ip"), "dias": dias})
    return {"total": len(equipos), "atrasados": atrasados,
            "nube_dias": _dias_desde(nube), "nube": nube}


def _internet_huespedes(horas: int) -> Dict[str, Any]:
    try:
        from core import shomer_api
        return shomer_api.get_wan_hotel_historial(horas) or {}
    except Exception as e:
        log.debug("informe: internet: %s", e)
        return {}


def _seguridad() -> Dict[str, Any]:
    try:
        from core import shomer_api
        bloqueadas = shomer_api.get_blocked_ips()
        return {"bloqueadas": len(bloqueadas) if bloqueadas is not None else None}
    except Exception as e:
        log.debug("informe: seguridad: %s", e)
        return {}


# ── Redacción ────────────────────────────────────────────────────────────────

def _linea_dias(dias: Optional[int]) -> str:
    if dias is None:
        return "sin fecha de inicio registrada"
    if dias == 0:
        return "abierto hoy"
    if dias == 1:
        return "abierto desde ayer"
    return f"abierto hace {dias} días"


def construir(sitio: str = "", periodo_horas: int = 168) -> str:
    """El informe en texto plano — se lee igual en cualquier cliente de correo."""
    cronicos = _pendientes_cronicos()
    senas = _senas_del_equipo()
    resp = _respaldos()
    net = _internet_huespedes(periodo_horas)
    seg = _seguridad()

    dias = max(1, periodo_horas // 24)
    encabezado = f"Informe de pendientes — {sitio or 'Shomer'}"
    partes = [
        encabezado,
        "=" * len(encabezado),
        f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Período cubierto: últimos {dias} día(s)",
        "",
        "Esto NO son las alertas del día: es lo que sigue pendiente.",
        "",
    ]

    # 1. Pendientes
    partes.append("1) LO QUE SIGUE SIN RESOLVERSE")
    if not cronicos:
        partes.append("   Nada pendiente. Ningún equipo quedó con un problema abierto.")
    else:
        partes.append(f"   {len(cronicos)} asunto(s) abiertos:")
        for c in cronicos:
            ip = f" ({c['ip']})" if c["ip"] else ""
            partes.append(f"   • {c['nombre']}{ip} — {_linea_dias(c['dias'])}")
            s = senas.get(c["ip"]) or {}
            if s.get("ubicacion") and not s.get("sin_ubicacion"):
                partes.append(f"     Ubicación: {s['ubicacion']}")
            elif s.get("mac"):
                partes.append(
                    f"     Sin ubicación registrada. Identificarlo por su MAC: {s['mac']}"
                )
        partes.append("")
        partes.append("   Estos no se resuelven solos: requieren revisión en sitio.")
    partes.append("")

    # 2. Respaldos
    partes.append("2) RESPALDOS")
    if not resp:
        partes.append(f"   {SIN_DATO} — no se pudo consultar el estado de respaldos.")
    else:
        partes.append(f"   Equipos con respaldo configurado: {resp.get('total', 0)}")
        if resp.get("atrasados"):
            for a in resp["atrasados"]:
                cuando = (f"hace {a['dias']} días" if a["dias"] is not None
                          else "sin respaldo registrado")
                partes.append(f"   • ATRASADO: {a['nombre']} — último {cuando}")
        else:
            partes.append("   Todos al día.")
        nd = resp.get("nube_dias")
        if nd is None:
            partes.append("   Copia en la nube: sin registro de la última subida.")
        elif nd >= 2:
            partes.append(f"   ATENCIÓN: la última subida a la nube fue hace {nd} días.")
        else:
            partes.append("   Copia en la nube: al día.")
    partes.append("")

    # 3. Internet de los huéspedes
    partes.append("3) INTERNET DE LOS HUÉSPEDES")
    lecturas = int(net.get("lecturas") or 0)
    if lecturas == 0:
        partes.append("   Sin comprobaciones registradas en el período.")
        partes.append("   Eso NO significa que estuviera bien: significa que no se midió.")
    else:
        malas = int(net.get("con_problemas") or 0)
        partes.append(f"   {lecturas - malas} de {lecturas} comprobaciones sin problema.")
        smin, smax = net.get("sesiones_min"), net.get("sesiones_max")
        if smin is not None and smax is not None:
            partes.append(f"   Uso: entre {smin} y {smax} sesiones de tráfico simultáneas.")
        for motivo in (net.get("problemas") or [])[:5]:
            partes.append(f"   • {motivo}")
    partes.append("")

    # 4. Seguridad
    partes.append("4) SEGURIDAD")
    n = seg.get("bloqueadas")
    if n is None:
        partes.append(f"   {SIN_DATO} — no se pudo consultar el bloqueo.")
    else:
        partes.append(f"   {n} dirección(es) de internet bloqueadas por amenaza.")
        partes.append("   No requiere acción: se bloquean solas al detectarse.")
    partes.append("")
    partes.append("-- ")
    partes.append("Shomer Sentinel. Informe automático; los datos salen del registro")
    partes.append("del propio sistema. Si algo no se pudo consultar, se dice, no se supone.")
    return "\n".join(partes)


def asunto(sitio: str = "") -> str:
    cronicos = _pendientes_cronicos()
    n = len(cronicos)
    marca = f"{n} pendiente(s)" if n else "sin pendientes"
    return f"[Shomer] {sitio or 'Informe'} — {marca}"


def enviar(sitio: str = "", periodo_horas: int = 168) -> bool:
    """Devuelve True solo si el correo salió de verdad."""
    if not configurado():
        log.info("informe coordinador: SMTP o destinatario sin configurar — no se envía")
        return False
    try:
        from core.incident_escalation import _send_email_sync
        _send_email_sync(asunto(sitio), construir(sitio, periodo_horas))
        log.info("informe coordinador enviado a %s", destinatario())
        return True
    except Exception as e:
        log.warning("informe coordinador: error al enviar: %s", e)
        return False


def toca_ahora(ahora: Optional[datetime] = None, ultimo_envio: Optional[str] = None) -> bool:
    """¿Toca enviarlo en este momento?

    Se comprueba contra el último envío real para que un reinicio del agente no
    dispare un informe repetido ni se salte el de la semana.
    """
    ahora = ahora or datetime.now()
    if ahora.hour != hora():
        return False
    if cada() == "semanal" and ahora.weekday() != dia_semana():
        return False
    clave = ahora.strftime("%Y-%m-%d") if cada() == "diario" else ahora.strftime("%G-W%V")
    return clave != (ultimo_envio or "")


def clave_periodo(ahora: Optional[datetime] = None) -> str:
    ahora = ahora or datetime.now()
    return ahora.strftime("%Y-%m-%d") if cada() == "diario" else ahora.strftime("%G-W%V")
