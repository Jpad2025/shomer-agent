"""Modo investigación — reporte profundo de un equipo, sin los límites del
chat rápido (4 líneas / máximo 2 tools de groq_helper._SYSTEM_TECNICO).

La recolección de datos es 100% determinística (Python): perfil real de
Tracker + perfil real de Inframonitor (SNMP/puertos/ubicación) + historial
real de memoria_central + patrones ya detectados. El LLM solo redacta el
reporte sobre lo que ya se juntó — no decide qué datos traer, no puede
inventar evidencia que no le dimos.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

log = logging.getLogger("shomer-investigacion")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")
MEMORIA_DB = os.environ.get("MEMORIA_DB_PATH", "/app/data/memoria.db")
NETWORK_MONITOR_DB = os.environ.get(
    "NETWORK_MONITOR_DB_PATH", "/storage/db/network_monitor.db"
)
# Solo lectura, timeout corto -- nunca debe esperar el lock del poller de
# Inframonitor (corre cada 30s). Si está ocupado, se omite sin reintentar.
INFRA_PROFILE_TIMEOUT_SEC = 2
HISTORY_DAYS = int(os.environ.get("INVESTIGACION_HISTORY_DAYS", "30"))

_PROMPT = (
    "Sos un analista senior de soporte IT investigando un equipo de red. "
    "Tenés: el perfil del equipo (inventario real), su historial de eventos "
    "real de los últimos {days} días, y patrones ya detectados si los hay. "
    "Escribí un reporte de investigación real en español técnico — sin límite "
    "de líneas, sin formato rígido de 3 líneas. Si la evidencia es insuficiente "
    "para concluir algo, decilo explícitamente — NO inventes una causa que no "
    "esté sustentada en los datos. Estructura sugerida:\n"
    "1) Qué es este equipo (resumen del perfil)\n"
    "2) Qué pasó (historial relevante, con fechas reales)\n"
    "3) Diagnóstico — causa más probable, con el nivel de certeza real\n"
    "4) Qué debería revisar el técnico, en orden de prioridad\n\n"
    "PERFIL (Tracker — inventario):\n{perfil}\n\n"
    "PERFIL (Inframonitor — SNMP/puertos/ubicación, si aplica):\n{infra_perfil}\n\n"
    "HISTORIAL ({n_eventos} eventos en los últimos {days} días):\n{historial}\n\n"
    "PATRONES YA DETECTADOS PARA ESTE EQUIPO:\n{patrones}"
)


def _history_for_entity(ip: str, name: str) -> List[Dict[str, Any]]:
    try:
        con = sqlite3.connect(MEMORIA_DB)
        rows = con.execute(
            "SELECT ts, source, event, detail FROM memoria_incidentes "
            "WHERE (entity_ip = ? OR entity_name = ?) AND ts > datetime('now', ?) "
            "ORDER BY ts DESC LIMIT 100",
            (ip, name, f"-{HISTORY_DAYS} days"),
        ).fetchall()
        con.close()
    except Exception as e:
        log.debug("investigacion: memoria no disponible: %s", e)
        return []
    return [{"ts": r[0], "source": r[1], "event": r[2], "detail": r[3]} for r in rows]


def _inframonitor_profile_for_entity(ip: str, name_hint: str = "") -> Optional[Dict[str, Any]]:
    """Perfil real de Inframonitor (tipo/ubicación/SNMP) -- solo lectura.

    mode=ro + timeout corto: en WAL los lectores no bloquean al poller, pero
    igual no esperamos un lock más de INFRA_PROFILE_TIMEOUT_SEC -- si está
    ocupado, se omite la sección en vez de demorar la investigación.
    """
    if not ip and not name_hint:
        return None
    try:
        con = sqlite3.connect(
            f"file:{NETWORK_MONITOR_DB}?mode=ro", uri=True,
            timeout=INFRA_PROFILE_TIMEOUT_SEC,
        )
        row = con.execute(
            "SELECT d.name, d.device_type, d.location, s.status, s.loss_pct, "
            "s.snmp_ok, s.snmp_data, s.checked_at "
            "FROM infra_devices d LEFT JOIN infra_status s ON s.ip = d.ip "
            "WHERE d.ip = ? OR d.name = ?",
            (ip, name_hint),
        ).fetchone()
        con.close()
    except Exception as e:
        log.debug("investigacion: inframonitor no disponible: %s", e)
        return None
    if not row:
        return None

    name, dtype, location, status, loss_pct, snmp_ok, snmp_data_raw, checked_at = row
    profile: Dict[str, Any] = {
        "name": name,
        "device_type": dtype,
        "location": location,
        "status": status,
        "loss_pct": loss_pct,
        "snmp_ok": bool(snmp_ok) if snmp_ok is not None else None,
        "checked_at": checked_at,
    }
    if snmp_data_raw:
        try:
            snmp = json.loads(snmp_data_raw)
            if snmp.get("sys_descr"):
                profile["sys_descr"] = snmp["sys_descr"]
            if snmp.get("sys_uptime"):
                profile["sys_uptime"] = snmp["sys_uptime"]
            interfaces = snmp.get("interfaces") or []
            # Solo los puertos con errores reales -- no listar los limpios,
            # eso es justo lo que el LLM necesita para no quedarse genérico.
            con_errores = sorted(
                (
                    i for i in interfaces
                    if int(i.get("in_err") or 0) + int(i.get("out_err") or 0) > 0
                ),
                key=lambda i: int(i.get("in_err") or 0) + int(i.get("out_err") or 0),
                reverse=True,
            )[:5]
            if con_errores:
                profile["puertos_con_errores"] = [
                    {
                        "puerto": i.get("descr"),
                        "in_err": i.get("in_err"),
                        "out_err": i.get("out_err"),
                        "estado": i.get("oper"),
                    }
                    for i in con_errores
                ]
        except Exception:
            pass
    return profile


def _patterns_for_entity(name: str, ip: str) -> List[Dict[str, Any]]:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        rows = con.execute(
            "SELECT patron_descripcion, impacto, sugerencia_tecnica, ocurrencias "
            "FROM patrones_detectados WHERE entidad IN (?, ?) AND estado='activo'",
            (name, ip),
        ).fetchall()
        con.close()
    except Exception:
        return []
    return [
        {"descripcion": r[0], "impacto": r[1], "sugerencia": r[2], "ocurrencias": r[3]}
        for r in rows
    ]


def investigar(identificador: str) -> str:
    """Síncrono a propósito — se llama desde asyncio.to_thread() en el comando del bot."""
    from core import shomer_api, groq_helper

    perfil = shomer_api.get_device_profile(identificador)
    ip = perfil.get("ip", "") if perfil else identificador
    name = perfil.get("hostname", "") if perfil else ""

    infra_perfil = _inframonitor_profile_for_entity(ip, identificador)
    historial = _history_for_entity(ip, name or identificador)
    patrones = _patterns_for_entity(name or identificador, ip)

    if not perfil and not infra_perfil and not historial:
        return (
            f"No encontré nada en Tracker, Inframonitor ni en el historial para "
            f"'{identificador}'. Verificá la IP/nombre exacto, o que el equipo esté "
            "en el inventario (Tracker → escaneo) o monitoreado (Guardian/Inframonitor)."
        )

    prompt = _PROMPT.format(
        days=HISTORY_DAYS,
        perfil=json.dumps(
            perfil or {"nota": "no está en el inventario de Tracker — puede ser un AP/router/switch sin escanear"},
            ensure_ascii=False,
        )[:2000],
        infra_perfil=json.dumps(
            infra_perfil or {"nota": "no monitoreado por Inframonitor, o no respondió SNMP"},
            ensure_ascii=False,
        )[:2000],
        n_eventos=len(historial),
        historial=json.dumps(historial[:40], ensure_ascii=False)[:4000],
        patrones=json.dumps(patrones, ensure_ascii=False)[:1500] if patrones else "ninguno",
    )
    try:
        # _call_groq directo, NO explain()/chat() — esos fuerzan el límite de
        # 4-10 líneas del chat rápido. Acá necesitamos un reporte real, sin esa
        # restricción — mismo cliente, mismo modelo, presupuesto de tokens propio.
        messages = [
            {
                "role": "system",
                "content": (
                    "Sos Shomer, en modo investigación profunda (no chat rápido de campo). "
                    "Responde en español técnico, sin límite de líneas."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        out = groq_helper._call_groq(messages, max_tokens=1800)
    except Exception as e:
        log.warning("investigacion: error en LLM: %s", e)
        out = ""
    if not out:
        return (
            "Los datos se juntaron bien (perfil + historial + patrones), pero la "
            "redacción del reporte falló o se agotó el presupuesto de Groq. Reintentá en un momento."
        )
    return out
