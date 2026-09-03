# Changelog — Shomer Agent

Formato libre, una entrada por release. La versión activa vive en `VERSION`
(consultable también con `/version` en el bot). Fecha = cuando se desplegó
en Ópera (maestro), no cuando se escribió el código.

## 1.1.9 — 2026-09-03

- **Usar el aprendizaje acumulado (`agente_skills`) en más lugares**, no solo como contexto
  invisible de la IA: `/diagnostico <ip>` y `/criticidad <ip>` ahora muestran el historial de
  soluciones ya confirmadas para ese equipo; el resumen matutino agrega una sección de
  "patrones confirmados" (equipos con 3+ arreglos remotos confirmados — candidatos a revisión
  física, no solo celebrar que el auto-fix funciona). Se descartó explícitamente cualquier
  skill ligada a una TASK-* automática (ej. auditoría de backups) para no confundir una tarea
  rutinaria exitosa con un equipo que sigue fallando.
- **Fix: el resumen matutino podía mandarse dos veces** si el bot se reiniciaba justo dentro de
  la ventana 07:00-07:02 (pasó hoy mismo, en vivo, desplegando este mismo cambio). El día del
  último envío ahora se guarda también en disco (`bot_state` en `knowledge.db`), no solo en
  memoria — sobrevive a un reinicio. Mismo fix aplicado al resumen de las 22:00.

## 1.1.8 — 2026-09-03

- **UX del bot: más fácil de usar sin memorizar comandos** (pedido Juan Pablo tras revisar el
  estado del bot). Cuatro cambios:
  1. Botones "🔍 Ver detalle" en las listas de `/equipos` e `/infra` para cada equipo con
     problema — ya no hay que copiar la IP a mano para diagnosticar.
  2. Comando `/menu` — botones grandes por categoría (WiFi, Infra, Seguridad, Servidor,
     Reporte, Ayuda), navegación sin escribir nada.
  3. Teclado fijo de accesos rápidos (Salud, Equipos, Alertas, Menú) que aparece tras el primer
     saludo o `/ayuda` y queda pegado abajo del chat.
  4. `/start` — no existía; alguien nuevo que tocaba "Iniciar" en Telegram no recibía nada.
     También se reforzó el texto libre como primera opción en `/ayuda` (antes la lista de
     comandos aparecía antes que la opción de simplemente preguntar).

## 1.1.7 — 2026-09-03

- **Resumen matutino: backup + inventario, y limpieza de comentarios editoriales.**
  Se agregó backup local + última subida a B2 (Protector) y último inventario (Tracker) al
  resumen de las 07:00. `app/api/backups.py` (network_monitor) ahora guarda
  `protector.last_b2_sync_at` al terminar el sync — antes esa confirmación solo se mandaba por
  Telegram y no quedaba en ningún lado consultable.
  Se quitaron 3 comentarios editoriales que se habían colado en el texto de reportes reales
  ("nunca se liberan solas", explicación de MAC-reconcile, instrucciones de `ethtool` en el
  mensaje de NIC) — un reporte debe traer datos limpios, no explicaciones del asistente. La
  línea de Hunter ahora trae la fecha de la IP bloqueada más antigua, en vez de solo un número
  sin contexto temporal.
- **Bot de Telegram: 3 mejoras pedidas tras revisar el estado del bot.**
  1. Se quitaron 21 alias legacy (`shomer_*`, `guardian_*`, `hunter_*`, `infra_*`,
     `instalar_*`) que duplicaban comandos ya existentes sin aportar nada — quedan los nombres
     cortos y los alias genuinamente útiles (`/diag`, `/reiniciar`, `/mantenimiento`,
     `/autobloqueo`).
  2. `/revertir` ahora también deshace cambios de modo mantenimiento y de tipo de equipo
     (antes solo bloqueos/desbloqueos de Hunter y agregar/quitar equipo).
  3. Comando nuevo `/criticidad <ip> [tipo]` — ver o cambiar el tipo/criticidad de negocio de
     un equipo Infra desde Telegram (antes solo desde el panel web), reutilizando el endpoint
     `PATCH /infra/devices/{id}` de la Tarea pendiente 2 opción 4.

## 1.1.6 — 2026-09-02

- **Telegram separado por hotel/cliente, nunca compartido:** se encontró que shomer243 y
  shomer245 usaban el mismo bot que shomer205 (clonado por `fleet_sync.sh` sin regenerar
  token), y los 4 sitios (Ópera incluida) mandaban a un mismo chat personal. Se crearon 3 bots
  nuevos vía BotFather y 4 grupos de Telegram separados, cada uno verificado con mensaje de
  prueba real antes de dar por hecho el cambio.
- **Tarea pendiente 2 (parte 2), opciones 1, 3 y 4** (`core/monitor.py`, commits `0f7fb28` y
  `c9e7e1e`): completa el trabajo de la 1.1.4 (que solo registraba, no cambiaba nada).
  - Opción 1: si el auto-reboot de Guardian funciona, ya no interrumpe (solo si sigue caído
    a los 3 min).
  - Opción 3: patrón crónico (5+ ocurrencias) deja de interrumpir en tiempo real — antes solo
    acortaba el texto del mensaje, ahora no manda nada, queda en `eventos_filtrados`.
  - Opción 4 (solo Inframonitor): criticidad de negocio por `device_type` —
    `pos`/`router`/`server`/`controller`/`switch` avisan ya; `printer` no-POS y `camera`
    esperan al resumen. Configurable con `INFRA_CRITICAL_DEVICE_TYPES`. Incluye fix de
    consistencia: la recuperación de un equipo cuya caída se silenció tampoco avisa (antes
    hubiera mandado un "recuperado" de algo que nunca se avisó como caído).
  - Opción 2 evaluada y descartada — se solapaba con 3+4+6 y aplicarla tal cual habría
    apagado el aviso inmediato de un router/gateway caído, que la opción 4 marca como crítico.
  Ver `PENDIENTES_LAB.md` § Tarea pendiente 2 para el detalle completo de las 6 opciones.

## 1.1.5 — 2026-08-27

- **Fix: `pattern_analysis` perdía hallazgos por JSON truncado** (`core/pattern_analysis.py`):
  el LLM cortaba la respuesta a mitad de un array JSON (~4 veces/24h en producción) y se
  descartaba el lote completo. `_salvage_truncated_json_array()` nuevo rescata los objetos ya
  completos antes del corte, en vez de perderlos todos. También se acortó el prompt para
  reducir la frecuencia del corte.
- **Fix: `/agregar` crasheaba en silencio con puerto no numérico** (`core/bot.py`,
  `cmd_agregar`): faltaba validar `args[3]` antes de `int(args[3])` — el error solo quedaba en
  logs, sin respuesta al usuario en Telegram. Ahora responde con el error claro antes de
  intentar convertir.

## 1.1.4 — 2026-08-16

- **Tarea pendiente 2 (parte 1):** nueva tabla `eventos_filtrados` en
  `knowledge.db` + `incident_escalation.record_filtered_event()` — registra
  cada "recuperado" que se suprime por `is_flapping` (3 puntos en
  `monitor.py`: Guardian y las 2 rutas de recuperación de Inframonitor), sin
  tocar la decisión de avisar (diff solo agrega líneas). Objetivo: separar
  "qué pasó" de "si se avisó" para auditar después sin reconstruir logs a
  mano. Ver `PENDIENTES_LAB.md` § Tarea pendiente 2. Complementa el registro
  del lado de network_monitor (blip gateway/masivo) hecho el mismo día.

## 1.1.3 — 2026-08-13

- **`watch_infra` ahora usa escalamiento crónico (paso 5 del mapa)** — hasta
  ahora esta protección solo la tenía Guardian (wifi); switches, impresoras,
  cámaras y datáfonos mandaban un mensaje completo por cada caída de un
  mismo equipo flapeando, sin agrupar (el mismo problema que tuvo OFC-COCINA
  en Guardian, Sesión 71, pero nunca arreglado del lado de Inframonitor).
  `core/monitor.py::watch_infra`: la caída individual (no-oleada) ahora pasa
  por `incident_escalation.handle_event()`; las dos rutas de recuperación
  individual ahora chequean `is_flapping()` antes de avisar "recuperado".
  No toca la detección de oleada (Pulse Correlate) — eso ya agrupaba bien.

## 1.1.2 — 2026-08-13

- **Solo comentarios, sin cambio de comportamiento.** Se agregaron marcas
  "Mapa de decisión de alertas (CLAUDE.md), paso N" en `core/monitor.py`
  (chequeo de patrón crónico paso 7, `incident_escalation`/`is_flapping`
  pasos 5-6) y en el docstring de `core/incident_escalation.py` — para que
  el código mismo indique en qué parte del mapa está cada pieza, en vez de
  tener que reconstruir el orden leyendo 3 archivos cada vez. Pedido
  explícito de Juan Pablo tras revisar 2 meses de ajustes de sensibilidad.

## 1.1.1 — 2026-08-13

- **Fix: "Nodo recuperado" repetido en equipos flapeando** (`core/monitor.py`
  `watch_guardian_nodes` + `core/incident_escalation.py`): el aviso de
  recuperación se mandaba en cada blip, sin pasar por la ventana de
  agregación que ya protege el lado de las caídas — un solo AP flapeando
  (OFC-COCINA `.113`) generó 44 de 54 mensajes Telegram en 24h. Nueva
  `incident_escalation.is_flapping(ip)` (true si el incidente ya acumuló
  2+ eventos en la ventana activa); `watch_guardian_nodes` la usa para
  suprimir recuperaciones repetidas — la primera se sigue avisando normal.

## 1.1.0 — 2026-08-10

- **Escalamiento de incidentes recurrentes** (`core/incident_escalation.py`):
  agrupa fallas repetidas del mismo equipo en una ventana de 1h en vez de
  mandar un mensaje por caída. Digest con 2 botones ("lo resuelvo ahora" /
  "próxima visita") + `/silenciar <ip> <duración>` a medida. Escala a
  Telegram del coordinador + correo (SMTP opcional) solo tras 24h sin
  respuesta — plazo largo porque el técnico de campo no vive en el sitio.
- **Resumen 08:00 enriquecido**: suma CPU/RAM/disco/estado de servicios en
  una línea, cerrando el pedido de un solo mensaje matutino.
- **`tools/fleet_sync.sh`**: propagación de código a toda la flota por
  rsync sobre SSH (no depende de que el sitio tenga salida a GitHub).
  Preserva cambios locales sin commitear con `git stash` antes de
  sobrescribir — nunca los descarta en silencio.
- **`tools/fleet_hosts.txt`** + **`/version`** + verificación post-deploy
  con rollback automático — ver README de `tools/`.

## 1.0.0 — línea base

Todo lo documentado en `CLAUDE.md` hasta la Sesión 69 (5 ago 2026): Guardian,
Hunter, Tracker, Protector, bot con 26+ monitores, digest VPN, alertas
compactas para flappers crónicos.
