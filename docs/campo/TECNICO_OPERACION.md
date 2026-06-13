# Shomer Sentinel — Guía de operación para técnico de campo
# Versión: junio 2026 | Idioma: español operacional

Este documento es para el técnico que instala y opera el sistema.
NO contiene información de código ni arquitectura interna.

---

## ¿Qué es Shomer?

Un servidor físico (mini PC) instalado en la red del cliente.
Desde un navegador web controlas todo: `https://IP-DEL-SHOMER:8443`

Tiene cuatro funciones:

| Lo que ves en el panel | Para qué sirve |
|------------------------|----------------|
| **Guardian** | Vigilar que los AP y routers estén encendidos y con internet. Reinicia automáticamente si detecta caída sostenida. |
| **Tracker** | Inventario de equipos (IP, MAC, software, usuario logueado). Ficha con monitor integrado (portátil/All-in-One) y monitores externos. |
| **Hunter** | Detecta ataques y tráfico sospechoso. Permite bloquear IPs desde el panel. |
| **Protector** | Backups automáticos de equipos del cliente (Windows, Mac, Linux) a disco local y nube. |

---

## Estados que verás en Guardian

| Color / Estado | Qué significa | Qué hacer |
|----------------|---------------|-----------|
| 🟢 Online | El equipo está bien, con internet | Nada |
| 🔴 Offline | No responde desde la LAN | Verificar cable/energía del equipo |
| 🟠 No-internet | Equipo responde LAN pero sin WAN | Verificar router/ISP del cliente |
| 🟡 Degraded | Calidad de conexión baja, funciona parcial | Monitorear, no reiniciar todavía |

---

## Reinicio automático — cuándo ocurre

Guardian reinicia un AP automáticamente solo si se cumplen TODAS estas condiciones:
1. El equipo lleva offline o sin-internet **3 ciclos consecutivos** (~5 minutos)
2. No se reinició en las últimas **6 horas** (cooldown)
3. El servidor Shomer tiene internet en ese momento
4. No está en modo mantenimiento

Si el AP reinicia solo: es normal, Guardian hizo su trabajo.

---

## Cosas frecuentes y qué hacer

### El panel no carga
1. Verificar que el servidor Shomer está encendido (luz/ping)
2. Intentar `http://IP-SHOMER:8000` directamente (sin HTTPS)
3. Si no responde: reiniciar el servidor físicamente
4. Contactar soporte si sigue sin responder tras 5 minutos

### Un AP aparece offline pero físicamente está prendido
1. Verificar que el cable de red del AP llega al switch correcto
2. Verificar que el AP tiene la misma IP que Guardian espera (puede haber cambiado por DHCP)
3. Desde Guardian → nodo → "Descubrir" para re-escanear
4. Si sigue igual: SSH al AP manualmente y verificar conectividad

### Hunter con MikroTik RouterOS (sin OpenWrt)

Shomer agrega la IP a la lista `shomer-blocked` en el router. **Eso solo no bloquea** hasta que exista una regla DROP en el firewall del MikroTik (se hace **una vez** en el hotel, manual o desde panel en laboratorio).

- Panel Hunter → Firewall → *Verificar regla DROP*
- En producción (Hotel Ópera): aplicación **manual** en Winbox/terminal — ver doc `HUNTER_MIKROTIK_ROUTEROS.md`
- El bot **no** repite avisos cada 6 h por una IP ya bloqueada; solo avisa bloqueos **nuevos**

### Hunter bloqueó una IP que no debería
1. Panel → Hunter → lista de bloqueados
2. Seleccionar la IP → Desbloquear
3. Reportar al developer qué IP y por qué se desbloqueó

### El backup de un equipo falló
1. Panel → Protector → ver el equipo con error
2. Verificar que el equipo cliente está encendido y accesible
3. Botón "Probar conexión" en el equipo
4. Si falla: verificar credenciales (usuario/contraseña del equipo cliente)
5. Lanzar backup manual con botón "Backup ahora"

---

## Inframonitor — vigilancia de switches, routers, firewalls y servidores

Además de los APs que maneja Guardian, el sistema tiene **Inframonitor** para vigilar cualquier equipo de red por ping y, si tiene SNMP activo, con datos detallados.

El bot puede responder preguntas como:

> "¿Cómo está el switch del piso 1?"
> "¿Cuántos puertos activos tiene el switch 192.168.1.10?"
> "¿Hay errores en los puertos del firewall?"

**Con SNMP activo el bot reporta:**
- Modelo y firmware del equipo
- Uptime — cuánto lleva encendido
- Estado de cada puerto: UP / DOWN
- Tráfico en Mbps por puerto
- Errores de cable — si hay errores en un puerto, puede ser cable dañado

**Sin SNMP** el bot solo confirma si el equipo responde ping y cuánta latencia tiene.

**Alertas automáticas:** si cualquier equipo Inframonitor cae o se recupera, el bot envía aviso igual que con los APs. Pero NO reinicia — solo informa.

---

## Bot Telegram — comandos disponibles

**Sin `/start`** — entrada: `/consultas`, `/ayuda` o texto libre.

Texto libre: OpenAI (si está en `.env`) o Groq como respaldo. **Monitores automáticos** (26 tareas): alertan solos en el chat.

| Comando | Qué hace |
|---------|----------|
| `/consultas` | Ejemplos de qué preguntar en texto libre |
| `/ayuda` | Lista completa de comandos y monitores |
| `/salud` | Estado del servidor (CPU, RAM, disco, servicios, Guardian, Infra, Hunter, WAN) |
| `/salud monitores` | Estado de cada monitor automático |
| `/salud resumen` | Reporte del día con IA |
| `/equipos` | APs Guardian y equipos del agente |
| `/diagnostico <IP>` | Ping, estado, uptime, fallos |
| `/diagnostico <IP> reparar` | Diagnóstico + reparación automática si aplica |
| `/reboot <IP>` | Reiniciar equipo — pide confirmación (`/reiniciar` igual) |
| `/clientes <IP>` | Dispositivos WiFi conectados al AP |
| `/modo on` / `/modo off` | Pausar reboots automáticos — Telegram al activar/desactivar (`/mantenimiento` igual) |
| `/alertas` | Alertas Hunter e IPs bloqueadas |
| `/bloquear <IP>` | Bloquear IP en firewall |
| `/desbloquear <IP>` | Liberar IP bloqueada |
| `/guardar <IP> <texto>` | Guardar solución para futuras alertas |
| `/historial` | Últimos cambios desde el bot |
| `/revertir <id>` | Deshacer bloqueo/desbloqueo |
| `/instalar` | Guía de instalación paso a paso |
| `/usuario` | Crear usuario de servicio `shomer` |
| `/verificar` | Checklist final de instalación |
| `/agregar <IP> <nombre> [vendor]` | Equipo extra en el agente |
| `/eliminar <IP>` | Quitar equipo del agente |
| `/nuevo` | Limpiar historial del chat con IA |

| `/infra` | Lista equipos Infra (cámaras, switches, servidores, impresoras) |
| `/infra <IP>` | Detalle: ping, TCP, SNMP, tóner, antecedentes guardados |
| `/puertos <IP>` | Puertos SNMP UP/DOWN, tráfico y errores (switch/router/server) |

Panel web **Infraestructura** — agregar equipos y comunidad SNMP. Monitores Infra alertan: caída/recuperación · tóner/papel · TCP caído · SNMP DOWN · flapping cable/PoE.

---

## Procesos del servidor que verás si accedes al sistema

Estos procesos son normales y deben estar corriendo:

| Nombre | Estado esperado |
|--------|-----------------|
| shomer-guardian | activo |
| shomer-tools | activo |
| nginx | activo |
| shomer-health-watchdog.timer | activo |
| Suricata | activo (puede usar CPU alto en momentos de tráfico — es normal) |

Si alguno no está activo, reportar a soporte.

---

## Qué NO tocar en campo

- Archivos de configuración del servidor (preguntar a soporte antes)
- La base de datos del sistema
- Los servicios del sistema por línea de comando
- Credenciales del servidor (están en un archivo seguro, no modificar)
- El firewall del servidor (UFW)

---

## Contacto soporte

Cualquier situación que no esté en esta guía: reportar al developer por Telegram.
Incluir: descripción del problema, IP del equipo afectado, hora aproximada.
