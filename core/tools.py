"""
Tool calling para Groq — Llama 3.3 70B decide qué función invocar.
El modelo recibe las definiciones y llama la que necesita para responder con datos reales.
"""
import json
import logging
from typing import Any

log = logging.getLogger("shomer-tools")

# ── Definiciones JSON (schema que Groq lee) ───────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_system_status",
            "description": (
                "Estado actual del sistema Shomer: nodos Guardian (online/offline/no-internet), "
                "métricas del servidor (CPU, RAM, temperatura) e IPs bloqueadas. "
                "Usar cuando preguntan por el estado general de la red o si hay problemas."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_guardian_nodes",
            "description": (
                "Lista detallada de todos los APs/nodos monitoreados por Guardian: "
                "nombre, IP, estado, clientes conectados, método de reboot. "
                "Usar cuando preguntan por un AP específico o el estado de los nodos."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ping_device",
            "description": (
                "Hace ping ICMP a una IP y retorna si responde o no. "
                "Usar cuando preguntan si un equipo está encendido o accesible."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {
                        "type": "string",
                        "description": "Dirección IP del dispositivo (ej. 192.168.1.10)",
                    }
                },
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hunter_alerts",
            "description": (
                "Últimas alertas de seguridad detectadas por Suricata/Hunter: "
                "firma del ataque, IP de origen, severidad. "
                "Usar cuando preguntan por alertas, ataques o amenazas."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Número de alertas a retornar (default 5)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_blocked_ips",
            "description": (
                "Lista de IPs bloqueadas actualmente en el firewall por Hunter. "
                "Usar cuando preguntan qué IPs están bloqueadas o si una IP específica está bloqueada."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_disk_usage",
            "description": (
                "Uso de disco del servidor Shomer por partición: porcentaje usado, GB libres. "
                "Usar cuando preguntan por espacio en disco o almacenamiento."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_manual",
            "description": (
                "Consulta el manual único de campo integrado (~operación+soporte/instalación): "
                "hasta ~14000 caracteres de fragmentos pertinentes. "
                "Usar para CÓMO: instalación cableado/wizard, MikroTik espejo SPAN, Guardian, Hunter, "
                "Protector backups, Telegram panel, errores típicos y checklist entrega."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Palabras clave o pregunta; vacío para mezcla intro operación+soporte",
                    }
                },
                "required": [],
            },
        },
    },
    # ── Tools nuevas (ampliación) ────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "get_services_status",
            "description": (
                "Estado de los servicios systemd clave del servidor Shomer: "
                "shomer-guardian, shomer-tools, nginx, suricata, wazuh-manager, redis. "
                "Usar cuando preguntan si algún servicio está caído o con problemas."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_backup_status",
            "description": (
                "Estado del módulo Protector: equipos con backup configurado, "
                "último backup de cada uno (fecha, estado, tamaño). "
                "Usar cuando preguntan por backups o si algún equipo no hizo backup."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_tracker_summary",
            "description": (
                "Resumen del inventario de Tracker: cantidad de equipos encontrados, "
                "últimas IPs descubiertas, estado del último escaneo. "
                "Usar cuando preguntan por el inventario de la red."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_events",
            "description": (
                "Últimos eventos del log de Guardian: reboots de APs, cambios de estado, "
                "alertas de WAN. Muestra qué pasó recientemente en la red. "
                "Usar cuando preguntan qué pasó, si hubo reboots o cuándo fue el último evento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Número de eventos a retornar (default 10, máximo 30)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_server_logs",
            "description": (
                "Últimas líneas del log del servicio Shomer (Guardian o Tools). "
                "Usar cuando hay errores, el servicio está lento, o para diagnóstico técnico."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Servicio a consultar: 'guardian' (default) o 'tools'",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Número de líneas del log (default 30, máximo 80)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_network_interfaces",
            "description": (
                "Estado de las interfaces de red del servidor: cuáles están UP/DOWN, "
                "si la NIC espejo (Hunter) está activa. "
                "Usar cuando hay problemas de red o cuando preguntan por el estado de las NICs."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_firewall_summary",
            "description": (
                "Resumen de actividad del firewall Hunter: IPs bloqueadas actualmente, "
                "bloqueos en las últimas 24h, top IPs atacantes. "
                "Usar cuando preguntan por la seguridad perimetral o amenazas activas."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wan_status",
            "description": (
                "Estado de la conexión a internet del servidor Shomer: "
                "si hay internet, latencia, si ha habido cortes recientes. "
                "Usar cuando reportan problemas de internet o cuando el Guardian dice 'no-internet'."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_infra_devices",
            "description": (
                "Lista todos los equipos monitoreados por Inframonitor: switches, servidores, "
                "routers, firewalls, NAS, cámaras, DVR. Muestra estado online/offline, latencia "
                "y SNMP. Usar para vista general o contar cuántos están caídos."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_infra_device",
            "description": (
                "Detalle de UN equipo Infra por IP: cámara, DVR, impresora, switch, servidor. "
                "Incluye ping, puerto TCP, tóner/papel, puertos SNMP caídos y ubicación. "
                "Usar cuando preguntan por un equipo concreto: '¿está la cámara del lobby?', "
                "'estado del DVR', 'tóner impresora caja 1'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {
                        "type": "string",
                        "description": "IP del equipo en Inframonitor",
                    }
                },
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_infra_snmp",
            "description": (
                "Datos SNMP detallados de un equipo de red: modelo/firmware, uptime del equipo, "
                "hostname configurado, estado de cada puerto (UP/DOWN), velocidad, "
                "tráfico actual en Mbps y errores por puerto. "
                "Usar cuando preguntan cuántos puertos tiene activos un switch, cuánto tráfico pasa, "
                "si hay errores en un cable, o el uptime de un router/firewall."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "IP del equipo en Inframonitor"},
                },
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_printer_status",
            "description": (
                "Estado detallado de una impresora en red: ping, puerto 9100, "
                "tóner (laser HP/Xerox/Canon), papel (térmica/POS Epson TM, comandera). "
                "Detecta automáticamente si es laser (SNMP) o POS/térmica (ESC/POS). "
                "Usar cuando reportan que una impresora no imprime, está sin papel, o sin tóner."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "IP de la impresora"},
                    "snmp_community": {"type": "string", "description": "Comunidad SNMP si es laser (default: public)"},
                },
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_print_queue_status",
            "description": (
                "Consulta el estado de la cola de impresión en un PC Windows. "
                "Muestra trabajos pendientes, atascados o en error. "
                "Usar antes de limpiar la cola para confirmar que hay un problema real. "
                "Las credenciales se obtienen automáticamente de Tracker por IP del PC."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pc_ip": {"type": "string", "description": "IP del PC Windows con la impresora conectada"},
                },
                "required": ["pc_ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_print_queue",
            "description": (
                "Limpia la cola de impresión en un PC Windows reiniciando el servicio Spooler. "
                "Usar cuando la impresora recibe trabajos pero no imprime (cola atascada). "
                "Requiere la IP del PC Windows al que está conectada la impresora."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pc_ip": {"type": "string", "description": "IP del PC Windows con el Spooler"},
                },
                "required": ["pc_ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_network_audit_findings",
            "description": (
                "Hallazgos de auditoría de seguridad de red: puertos y servicios riesgosos detectados "
                "en los activos del Tracker (Telnet, FTP, RDP, bases de datos expuestas, SNMP, etc.). "
                "Cada hallazgo tiene severidad (critico/alto/medio/bajo) y estado (pendiente/en_revision/terminado). "
                "Usar cuando preguntan si hay vulnerabilidades, riesgos de seguridad, puertos abiertos peligrosos, "
                "o el estado de la auditoría de red."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "description": "Filtrar por severidad: critico, alto, medio, bajo (opcional)",
                    },
                    "finding_status": {
                        "type": "string",
                        "description": "Filtrar por estado: pendiente, en_revision, terminado (opcional)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_network_audit_scan",
            "description": (
                "Lanza un escaneo completo de auditoría de red: detecta puertos y servicios riesgosos "
                "en todos los equipos del Tracker (nmap) y verifica actualizaciones de software pendientes "
                "vía SSH en equipos Linux y macOS. Tarda entre 3 y 10 minutos dependiendo de la red. "
                "Usar cuando el técnico pide: 'escanear la red', 'actualizar riesgos', 'buscar vulnerabilidades', "
                "'revisar parches', 're-auditar'. No requiere parámetros."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_agente_skills",
            "description": (
                "Skills aprendidas del sitio (agente_skills): patrones documentados por el técnico "
                "y acciones automáticas TASK-* que funcionaron. Usar cuando preguntan por qué "
                "cayó algo, qué se hizo antes, o antecedentes de un equipo/tarea."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ip": {
                        "type": "string",
                        "description": "Filtrar por IP de equipo (opcional)",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Filtrar por TASK-001…010 (opcional)",
                    },
                },
                "required": [],
            },
        },
    },
]


# ── Ejecutor ──────────────────────────────────────────────────────────────────

def execute(name: str, args: dict) -> Any:
    """Ejecuta la tool y retorna resultado como dict serializable."""
    try:
        if name == "get_system_status":
            from core import shomer_api
            nodes   = shomer_api.get_guardian_nodes() or []
            metrics = shomer_api.get_server_metrics() or {}
            blocked = shomer_api.get_blocked_ips() or []
            now_m   = (metrics.get("now") or {})
            online  = sum(1 for n in nodes if n.get("status") == "online")
            infra   = shomer_api.get_infra_summary()
            return {
                "guardian": {
                    "total": len(nodes),
                    "online": online,
                    "problems": [
                        {"name": n.get("name", n.get("ip")), "status": n.get("status")}
                        for n in nodes if n.get("status") != "online"
                    ],
                },
                "infra": {
                    "total": infra.get("total", 0),
                    "online": infra.get("online", 0),
                    "offline_names": [
                        d.get("name", d.get("ip"))
                        for d in (infra.get("offline") or [])[:8]
                    ],
                    "outages_24h": infra.get("outages_24h", 0),
                    "low_toner_count": len(infra.get("low_toner") or []),
                },
                "server": {
                    "cpu_pct": round(now_m.get("cpu", 0), 1),
                    "ram_pct": round(now_m.get("ram", 0), 1),
                    "temp_c":  now_m.get("temp"),
                },
                "blocked_ips": len(blocked),
            }

        elif name == "get_guardian_nodes":
            from core import shomer_api
            nodes = shomer_api.get_guardian_nodes() or []
            return {"nodes": [
                {
                    "name":          n.get("name", n.get("ip")),
                    "ip":            n.get("ip") or n.get("ip_address"),
                    "status":        n.get("status"),
                    "clients":       n.get("clients"),
                    "reboot_method": n.get("reboot_method"),
                }
                for n in nodes
            ]}

        elif name == "ping_device":
            ip = (args.get("ip") or "").strip()
            if not ip:
                return {"error": "IP requerida"}
            from core import device_manager as dm
            result = dm.ping_device(ip)
            return {"ip": ip, "ok": result["ok"], "message": result["message"]}

        elif name == "get_hunter_alerts":
            from core import shomer_api
            limit = min(int(args.get("limit", 5)), 20)
            return {"alerts": shomer_api.get_hunter_alerts(limit)}

        elif name == "get_blocked_ips":
            from core import shomer_api
            blocked = shomer_api.get_blocked_ips() or []
            return {"blocked": blocked[:20], "total": len(blocked)}

        elif name == "get_disk_usage":
            from core import shomer_api
            return shomer_api.get_disk_usage()

        elif name == "search_manual":
            query = str(args.get("query") or "").strip()
            from core.groq_helper import manual_search_content
            content = manual_search_content(query or "", max_chars=14_000)
            return {
                "query": query or "(intro manuales)",
                "content": content[:14_000],
            }

        elif name == "get_services_status":
            from core import shomer_api
            # Usar system-health que incluye estado de servicios
            data = shomer_api._get("/api/system-health") or {}
            services_list = data.get("services", [])
            # Convertir lista [{name, status}] a dict {name: status}
            if isinstance(services_list, list):
                services = {s.get("name", s.get("unit", "?")): s.get("status", "?")
                            for s in services_list}
            elif isinstance(services_list, dict):
                services = services_list
            else:
                services = {}
            # Fallback: /health solo da redis
            health = shomer_api.get_health() or {}
            return {
                "services": services if services else {"redis": health.get("redis", "?")},
                "redis": health.get("redis", "?"),
                "uptime": data.get("uptime", {}).get("label"),
                "temp_c": (data.get("temperature") or {}).get("celsius"),
            }

        elif name == "get_backup_status":
            from core import shomer_api
            devices = shomer_api.get_backup_devices()
            bh = shomer_api.get_backup_health() or {}
            return {
                "backup_health": bh,
                "devices": [
                    {
                        "name":         d.get("name"),
                        "ip":           d.get("ip"),
                        "last_backup":  d.get("last_backup_at"),
                        "last_status":  d.get("last_status"),
                    }
                    for d in (devices or [])
                ],
                "total": len(devices or []),
            }

        elif name == "get_tracker_summary":
            from core import shomer_api
            data = shomer_api.get_tracker_summary()
            return data

        elif name == "get_recent_events":
            from core import shomer_api
            limit = min(int(args.get("limit", 10)), 30)
            return shomer_api.get_recent_events(limit)

        elif name == "get_server_logs":
            from core import shomer_api
            service = str(args.get("service", "guardian")).lower().strip()
            lines   = min(int(args.get("lines", 30)), 80)
            return shomer_api.get_server_logs(service, lines)

        elif name == "get_network_interfaces":
            from core import shomer_api
            ifaces = shomer_api.get_interfaces()
            mirror_iface = shomer_api.get_config("base.mirror_interface") or "enp4s0"
            return {
                "interfaces": ifaces,
                "mirror_nic": mirror_iface,
                "mirror_up": any(
                    i["name"] == mirror_iface and i["state"] == "UP"
                    for i in ifaces
                ),
            }

        elif name == "get_firewall_summary":
            from core import shomer_api
            blocked = shomer_api.get_blocked_ips() or []
            security = shomer_api.get_firewall_security_log()
            return {
                "blocked_now": len(blocked),
                "blocked_ips": [b.get("ip") for b in blocked[:10]],
                "firewall": security,
            }

        elif name == "get_wan_status":
            from core import shomer_api
            wan = shomer_api.get_wan_status() or {}
            return {
                "internet": wan.get("internet", False),
                "latency_ms": wan.get("latency_ms"),
                "provider": wan.get("provider"),
                "raw": wan,
            }

        elif name == "get_infra_devices":
            from core import shomer_api
            devices = shomer_api.get_infra_devices() or []
            online  = sum(1 for d in devices if d.get("status") == "online")
            offline = sum(1 for d in devices if d.get("status") == "offline")
            return {
                "total": len(devices),
                "online": online,
                "offline": offline,
                "devices": [
                    {
                        "name":       d.get("name"),
                        "ip":         d.get("ip"),
                        "type":       d.get("device_type"),
                        "location":   d.get("location"),
                        "status":     d.get("status"),
                        "latency_ms": d.get("latency_ms"),
                        "uptime_24h": d.get("uptime_24h"),
                        "snmp_ok":    d.get("snmp_ok"),
                    }
                    for d in devices
                ],
            }

        elif name == "get_infra_device":
            import ipaddress
            ip = (args.get("ip") or "").strip()
            if not ip:
                return {"error": "IP requerida"}
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                return {"error": "IP inválida"}
            from core import shomer_api
            dev = shomer_api.get_infra_device(ip)
            if not dev:
                return {"error": "Equipo no encontrado en Infra", "ip": ip}
            pr = dev.get("printer") or {}
            hint = shomer_api.knowledge_hint(ip)
            out = {
                "ip": dev.get("ip"),
                "name": dev.get("name"),
                "type": dev.get("device_type"),
                "location": dev.get("location"),
                "status": dev.get("status"),
                "latency_ms": dev.get("latency_ms"),
                "tcp_port": dev.get("tcp_port"),
                "tcp_ok": dev.get("tcp_ok"),
                "snmp_ok": dev.get("snmp_ok"),
                "snmp_down_ports": dev.get("snmp_down_ports") or [],
                "state_duration": dev.get("state_duration"),
                "prior_solution": hint or None,
            }
            if pr:
                out["printer"] = pr
            return out

        elif name == "get_infra_snmp":
            import ipaddress
            ip = (args.get("ip") or "").strip()
            if not ip:
                return {"error": "IP requerida"}
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                return {"error": "IP inválida"}
            from core import shomer_api
            result = shomer_api.get_infra_snmp(ip)
            if not result.get("success"):
                return {"error": result.get("detail", "Sin datos SNMP"), "ip": ip}
            data = result.get("data", {})
            ifaces = data.get("interfaces", [])
            ports_up   = [i["name"] for i in ifaces if i.get("oper") == "up"]
            ports_down = [i["name"] for i in ifaces if i.get("oper") == "down"]
            err_ports  = [i["name"] for i in ifaces if (i.get("in_errors", 0) + i.get("out_errors", 0)) > 0]
            return {
                "ip":         ip,
                "name":       result.get("name"),
                "snmp_ok":    result.get("snmp_ok"),
                "model":      data.get("sys_descr", "—"),
                "hostname":   data.get("sys_name", "—"),
                "uptime":     data.get("sys_uptime", "—"),
                "ports_total":  len(ifaces),
                "ports_up":     ports_up,
                "ports_down":   ports_down,
                "ports_errors": err_ports,
                "interfaces": [
                    {
                        "name":      i["name"],
                        "oper":      i["oper"],
                        "speed_mbps":i.get("speed_mbps"),
                        "rx_mbps":   i.get("rx_mbps"),
                        "tx_mbps":   i.get("tx_mbps"),
                        "errors":    (i.get("in_errors", 0) + i.get("out_errors", 0)),
                    }
                    for i in ifaces
                ],
            }

        elif name == "get_printer_status":
            ip = (args.get("ip") or "").strip()
            if not ip:
                return {"error": "IP requerida"}
            community = (args.get("snmp_community") or "public").strip()
            from drivers.printer import get_printer_status
            return get_printer_status(ip, snmp_community=community)

        elif name == "get_print_queue_status":
            import ipaddress
            pc_ip = (args.get("pc_ip") or "").strip()
            if not pc_ip:
                return {"error": "IP del PC requerida"}
            try:
                ipaddress.ip_address(pc_ip)
            except ValueError:
                return {"error": "IP inválida"}
            from core import shomer_api
            from drivers.ssh_helper import ssh_run
            creds = shomer_api.get_pc_credentials(pc_ip)
            if not creds["password"]:
                return {"error": "Sin credenciales para este PC", "hint": "Agregar credenciales en Tracker o configurar base.service_user/password en Setup"}
            cmd = 'powershell -Command "Get-PrintJob -PrinterName * | Select-Object PrinterName,JobStatus,Document,@{N=\'Minutos\';E={[math]::Round((Get-Date)-$_.TimeSubmitted).TotalMinutes}} | ConvertTo-Json -Compress" 2>&1'
            ok, out = ssh_run(pc_ip, creds["user"], creds["password"], cmd, timeout=10)
            if not ok:
                return {"pc_ip": pc_ip, "success": False, "error": out[:300], "hint": "Verificar OpenSSH en el PC y credenciales"}
            import json as _json
            try:
                jobs = _json.loads(out.strip()) if out.strip().startswith(("[", "{")) else []
                if isinstance(jobs, dict):
                    jobs = [jobs]
            except Exception:
                jobs = []
            stuck = [j for j in jobs if "Error" in str(j.get("JobStatus", "")) or "Deleting" in str(j.get("JobStatus", ""))]
            return {
                "pc_ip": pc_ip,
                "success": True,
                "total_jobs": len(jobs),
                "stuck_jobs": len(stuck),
                "jobs": jobs[:10],
                "creds_source": creds["source"],
            }

        elif name == "clear_print_queue":
            import ipaddress
            pc_ip = (args.get("pc_ip") or "").strip()
            if not pc_ip:
                return {"error": "IP del PC requerida"}
            try:
                ipaddress.ip_address(pc_ip)
            except ValueError:
                return {"error": "IP inválida"}
            from core import shomer_api
            from drivers.ssh_helper import ssh_run
            creds = shomer_api.get_pc_credentials(pc_ip)
            if not creds["password"]:
                return {
                    "error": "Sin credenciales para este PC",
                    "hint": "Agregar credenciales en Tracker o configurar base.service_user/password en el wizard Setup",
                }
            cmd = (
                "net stop spooler & "
                'del /Q /F /S "%SystemRoot%\\System32\\spool\\PRINTERS\\*" & '
                "net start spooler"
            )
            ok, out = ssh_run(pc_ip, creds["user"], creds["password"], cmd, timeout=15)
            return {
                "pc_ip": pc_ip,
                "success": ok,
                "output": out[:400] if out else "",
                "creds_source": creds["source"],
                "hint": "" if ok else "Verificar que el PC tiene OpenSSH instalado y el usuario tiene permisos",
            }

        elif name == "get_network_audit_findings":
            from core import shomer_api
            severity = (args.get("severity") or "").strip()
            finding_status = (args.get("finding_status") or "").strip()
            data = shomer_api.get_network_audit_findings(severity=severity, finding_status=finding_status)
            findings = []
            if isinstance(data, dict):
                fd = data.get("findings") or {}
                if isinstance(fd, dict):
                    findings = fd.get("findings", [])
                elif isinstance(fd, list):
                    findings = fd
                sm = data.get("summary") or {}
                if isinstance(sm, dict):
                    by_sev = sm.get("by_severity", {})
                    last_scan = sm.get("last_scan")
                    total_active = sm.get("total_active", 0)
                else:
                    by_sev = {}
                    last_scan = None
                    total_active = len(findings)
            else:
                by_sev = {}
                last_scan = None
                total_active = 0
            # Group findings by severity for summary
            criticos = [f for f in findings if f.get("severity") == "critico"]
            altos    = [f for f in findings if f.get("severity") == "alto"]
            pendient = [f for f in findings if f.get("finding_status") == "pendiente"]
            return {
                "total_hallazgos": len(findings),
                "activos": total_active,
                "por_severidad": by_sev,
                "pendientes": len(pendient),
                "criticos_resumen": [
                    {"ip": f.get("ip"), "titulo": f.get("title"), "puerto": f.get("port"), "estado": f.get("finding_status")}
                    for f in criticos[:5]
                ],
                "altos_resumen": [
                    {"ip": f.get("ip"), "titulo": f.get("title"), "puerto": f.get("port"), "estado": f.get("finding_status")}
                    for f in altos[:5]
                ],
                "ultimo_escaneo": last_scan,
                "todos": [
                    {"ip": f.get("ip"), "titulo": f.get("title"), "severidad": f.get("severity"),
                     "puerto": f.get("port"), "estado": f.get("finding_status"), "recomendacion": f.get("recommendation")}
                    for f in findings[:20]
                ],
            }

        elif name == "run_network_audit_scan":
            from core import shomer_api
            result = shomer_api.run_network_audit_scan()
            if result.get("ok"):
                return {
                    "estado":          "completado",
                    "equipos_revisados": result.get("total_hosts", 0),
                    "hallazgos":       result.get("findings_count", 0),
                    "mensaje":         (
                        f"Escaneo completado. Se revisaron {result.get('total_hosts', 0)} equipos "
                        f"y se encontraron {result.get('findings_count', 0)} hallazgos. "
                        "Usá get_network_audit_findings para ver el detalle."
                    ),
                }
            else:
                err = result.get("error", "Error desconocido")
                if result.get("status") == "timeout":
                    return {
                        "estado":  "timeout",
                        "mensaje": "El escaneo está tardando más de 8 minutos. Puede estar corriendo en segundo plano. Verificá en el panel Hunter → Riesgos de Red.",
                    }
                return {"estado": "error", "mensaje": err}

        elif name == "get_incident_history":
            from core import shomer_api
            ip      = args.get("ip", "").strip() or None
            records = shomer_api.get_knowledge(ip=ip, limit=8)
            if not records:
                msg = f"No hay incidentes registrados para {ip}." if ip else "No hay incidentes registrados aún."
                return {"incidentes": [], "mensaje": msg}
            items = []
            for r in records:
                items.append({
                    "equipo":   r.get("device_name") or r.get("device_ip", ""),
                    "ip":       r.get("device_ip", ""),
                    "problema": r.get("problem", ""),
                    "solucion": r.get("action", ""),
                    "fecha":    (r.get("created_at") or "")[:10],
                })
            return {
                "incidentes": items,
                "total":      len(items),
                "mensaje":    f"Se encontraron {len(items)} incidente(s) previo(s)." + (f" Filtrado por IP {ip}." if ip else ""),
            }

        elif name == "get_agente_skills":
            from core import agente_skills

            ip = (args.get("ip") or "").strip()
            task_id = (args.get("task_id") or "").strip().upper()
            skills = agente_skills.list_skills(
                device_ip=ip,
                task_id=task_id,
                limit=15,
            )
            site_excerpt = agente_skills.load_site_excerpt()[:500] if not ip else ""
            items = []
            for s in skills:
                items.append({
                    "trigger": s.get("trigger_label"),
                    "action": s.get("action_label"),
                    "source": s.get("source"),
                    "task_id": s.get("task_id"),
                    "ip": s.get("device_ip"),
                    "ok": s.get("success_count", 0),
                    "fail": s.get("fail_count", 0),
                })
            return {
                "skills": items,
                "total": len(items),
                "site_hint": site_excerpt or None,
                "mensaje": f"{len(items)} skill(s) aprendida(s).",
            }

        return {"error": f"tool desconocida: {name}"}

    except Exception as e:
        log.warning("tools.execute(%s) error: %s", name, e)
        return {"error": str(e)}
