# Catálogo — herramientas del chat libre (function calling)

**Fecha:** 18 sep 2026 · **Fuente de verdad real:** `core/tools.py` (`TOOLS` + `execute()`)
**Audiencia:** Juan Pablo + ingeniería USB (Cursor, Claude Code, cualquier IA)
**Objetivo:** referencia rápida de qué puede consultar/hacer el chat en lenguaje natural — sin tener que leer 1200+ líneas de `tools.py` para saber si algo ya existe antes de agregarlo de nuevo.

> Este documento describe QUÉ hace cada herramienta y CUÁNDO el modelo la usa.
> El detalle exacto (parámetros, formato de respuesta) siempre vive en el código —
> si algo acá no coincide con `core/tools.py`, el código manda. Actualizar este
> archivo cuando se agregue/cambie una tool es responsabilidad de quien la toca.

Al 18 sep 2026: **35 herramientas** reales, agrupadas por sistema.

---

## Estado general / servidor

| Tool | Qué trae | Cuándo la usa el modelo |
|------|----------|--------------------------|
| `get_system_status` | Nodos Guardian, Infra (con `low_toner_count`), CPU/RAM/temp del servidor, IPs bloqueadas | Estado general, "¿hay problemas?", tóner bajo |
| `get_disk_usage` | Particiones y % de uso | Espacio en disco |
| `get_services_status` | Estado de los servicios systemd de Shomer | "¿el servicio X está corriendo?" |
| `get_service_journal` | Últimas líneas de log de un servicio | Diagnóstico de un servicio puntual |
| `get_host_journal_signals` | Señales del journal del sistema operativo (OOM, panics, etc.) | Fallas raras a nivel SO |
| `get_server_logs` | Log crudo de un servicio Shomer vía SSH | Debug profundo |
| `get_network_interfaces` | NICs del servidor, incluida la de espejo Hunter (`mirror_nic`) | "¿está funcionando el espejo?" |
| `get_panel_users` | Usuarios reales del panel web (username + rol) | "¿quién tiene acceso al panel?" |

## Guardian (WiFi / APs)

| Tool | Qué trae | Cuándo la usa el modelo |
|------|----------|--------------------------|
| `get_guardian_nodes` | Lista completa: nombre, IP, estado, clientes conectados | AP específico o vista general de nodos |
| `ping_device` | Ping puntual a una IP | Verificar conectividad ahora mismo |

## Infra (todo lo que no es AP: switches, servidores, cámaras, POS, router)

| Tool | Qué trae | Cuándo la usa el modelo |
|------|----------|--------------------------|
| `get_infra_devices` | Lista completa Inframonitor | Vista general o conteo de caídos |
| `find_infra_device` | Busca por nombre/ubicación, ordenado por especificidad | **Usar SIEMPRE primero** si no se tiene la IP exacta (ver `shomer_api.find_infra_devices_by_query`) |
| `get_infra_device` | Detalle de un equipo por IP | Cuando ya se tiene la IP exacta |
| `get_infra_snmp` | Puertos, tráfico, errores por switch | "¿cuánto tráfico tiene el switch X?" |
| `get_top_fallas` | Ranking real de qué equipo se cayó más veces (cuenta `status_events`) | "¿cuál equipo falla más?" — **no confundir con `get_chronic_tickets`** |
| `get_chronic_tickets` | Problemas RECURRENTES aún sin resolver, con recordatorio activo | "¿qué problemas crónicos hay abiertos?" |
| `get_recent_events` | Últimos eventos reales (Guardian + Infra) desde `status_events` | Historial reciente de caídas/recuperaciones |

## WAN / Internet

| Tool | Qué trae | Cuándo la usa el modelo |
|------|----------|--------------------------|
| `get_wan_status` | Internet del SERVIDOR Shomer (quorum WAN) | "¿el servidor perdió internet?" |
| `get_internet_huespedes` | Internet REAL del hotel, medido desde el gateway (sesiones, pérdida de paquetes, historial) | "¿cómo está el internet hoy/de los huéspedes?" — **no es lo mismo que `get_wan_status`** |
| `get_firewall_summary` | Resumen del firewall (reglas, estado) | Consultas de firewall |

## Hunter (seguridad)

| Tool | Qué trae | Cuándo la usa el modelo |
|------|----------|--------------------------|
| `get_hunter_alerts` | Stats + historial reciente (incluye `total_blocks_historico`) | "¿cuántos ataques ha detenido Shomer?" |
| `get_blocked_ips` | IPs bloqueadas ACTIVAS ahora mismo | Lista general de bloqueos vigentes |
| `check_ip_hunter` | Estado real de UNA ip puntual: bloqueada ahora + historial | **Usar SIEMPRE** antes de decir "amenaza real" o "falso positivo" de una IP concreta |
| `explain_hunter_alert` | Traduce una firma Suricata a lenguaje humano | Alertas técnicas crudas |

## Impresoras

| Tool | Qué trae | Cuándo la usa el modelo |
|------|----------|--------------------------|
| `get_printer_status` | Estado de una impresora por IP | Detalle de una impresora ya identificada (usar `find_infra_device` primero si no se tiene la IP) |
| `get_print_queue_status` | Cola de impresión | "¿por qué no imprime?" |
| `clear_print_queue` | Limpia la cola (acción real) | Cola atascada, confirmado por el técnico |

## Backups (Protector)

| Tool | Qué trae | Cuándo la usa el modelo |
|------|----------|--------------------------|
| `get_backup_status` | Estado de backups por equipo | "¿los backups están corriendo bien?" |

## Tracker (inventario de red)

| Tool | Qué trae | Cuándo la usa el modelo |
|------|----------|--------------------------|
| `get_tracker_summary` | Total de equipos descubiertos, distribución de SO, recientes | "¿cuántos equipos hay?", inventario general |
| `get_network_audit_findings` | Hallazgos de la última auditoría de red, incluido cuándo fue el último escaneo | "¿cuándo fue el último escaneo?" |
| `run_network_audit_scan` | Dispara un escaneo nuevo (acción real) | Pedido explícito de re-escanear |

## Cerebro y memoria del sitio

| Tool | Qué trae | Cuándo la usa el modelo |
|------|----------|--------------------------|
| `get_cerebro_findings` | Últimos hallazgos correlacionados (causa común entre varios equipos) | "¿por qué fallaron varios equipos juntos?", "¿qué está pasando en la red?" |
| `get_agente_skills` | Skills aprendidas del sitio: qué solución funcionó antes para un equipo/tarea | Antecedentes de un equipo o TASK-* |
| `consultar_memoria` | Memoria operativa (`/guardar`): última solución, consejo físico-vs-reboot, falsos positivos conocidos | **Usar SIEMPRE** al diagnosticar un equipo concreto antes de sugerir reboot o bloqueo |
| `search_manual` | Busca en el manual de campo en vivo (instalación, checklist, errores típicos) | Preguntas de "cómo hacer X" |

---

## Reglas que aplican a TODAS las tools (ver `_SYSTEM_BASE` en `core/groq_helper.py`)

- Máximo 2 tools encadenadas por respuesta (`MAX_TOOL_ROUNDS` en `openai_helper.py`).
- Nunca decir "no tengo esa información" sin haber llamado la tool que sí la trae.
- Nunca decir "procedo a hacer X" sin que una tool real lo haya ejecutado y confirmado éxito.
- Nunca mezclar datos de un equipo con los de otro de nombre parecido (ver `find_infra_devices_by_query`, ordena por especificidad, pero dos equipos con nombre similar NUNCA son el mismo).
- El formato DIAGNÓSTICO/CAUSA/ACCIÓN es para diagnósticos reales, no para toda pregunta que mencione un equipo — un mensaje vago sin equipo/síntoma concreto se responde en una línea natural pidiendo detalles.

## Historial de esta semana (16–18 sep 2026)

Se agregaron 6 tools nuevas (`get_cerebro_findings`, `get_chronic_tickets`,
`get_top_fallas`, `get_internet_huespedes`, `get_panel_users`,
`check_ip_hunter`) y se corrigieron 8 bugs reales de datos/identidad de
equipo/formato — ver `CHANGELOG.md` v1.51.0 a v1.58.0 para el detalle de
cada uno con el caso real que lo motivó.
