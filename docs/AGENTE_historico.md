# Histórico — documentación del agente Telegram (Shomer)

Archivo de respaldo: nada de lo que se saca de `POLITICAS_AGENTE.md`,
`PROTOCOLO_CAMBIOS_AGENTE.md`, `CATALOGO_TASK.md` o `TECNICO_OPERACION.md` se borra —
se mueve aquí cuando queda superado por el estado real del sistema, siguiendo el mismo
criterio usado en `CLAUDE_historico.md` del repo core.

---

## De POLITICAS_AGENTE.md v1.1 (10 jun 2026) — rollout ya completado

Todo lo de abajo era un **plan** de activación gradual escrito el 10 de junio de 2026,
antes de implementar nada. Verificado el 13 sep 2026 contra el código y el `.env` real de
Ópera: **todas las fases se cumplieron y se superaron** — Ópera no está en la fase O3
("catálogo modo learning") que proponía este plan como punto de partida, sino con
9 de las 10 tareas del catálogo ya en `approved` (todas salvo TASK-010, bloqueada por
código). Se conserva el razonamiento original porque documenta *por qué* se decidió
avanzar con cautela tarea por tarea — sigue siendo la referencia de cómo pensar una
futura instalación en un hotel nuevo.

### §7 — Rollout laboratorio (.205), como se escribió originalmente

| Paso | Qué encender | Validación (mínimo 48 h) |
|------|--------------|---------------------------|
| **L0** | Bot apagado, código desplegado | — |
| **L1** | `BOT_TRIAGE_ENABLED=1` + Guardian piloto | 1 msg por caída AP `.210`; sin pérdida de alertas críticas |
| **L2** | Todos los monitores → triage | `/salud monitores` OK; técnico reporta menos ruido |
| **L3** | `BOT_LEARN_SUPERVISED=1` | Botón enseñar → fila en `agente_skills` |
| **L4** | `BOT_LEARN_AUTONOMOUS=1` + `BOT_AUTO_SAFE_ONLY=1` | Simular stop guardian → auto-restart → Green State → skill |
| **L5** | Fase 3 contexto en chat (topología + skills en prompt) | Pregunta "¿por qué cayó X?" usa datos reales |
| **L6** | Opcional: `BOT_AUTO_REBOOT=true` solo en lab | Reboot `.210` con botón/auto según prueba |

### §8 — Rollout Hotel Ópera, como se propuso originalmente

| Fase | Nombre | `.env` clave | Qué gana el técnico | Riesgo |
|------|--------|--------------|---------------------|--------|
| **O0** | Baseline (hoy) | Triage off, bot como antes | Operación conocida | Ruido Telegram |
| **O1** | Cortafuegos | `BOT_TRIAGE_ENABLED=1` | 1 mensaje claro por incidente AP/servicio | 15 s delay no críticos |
| **O2** | Triage completo | Todos monitores en triage | Menos spam en disk, pipeline, hunter | Requiere monitoreo 1 semana |
| **O3** | Catálogo modo `learning` | `BOT_AUTO_TASKS_CONFIG={"TASK-002":"learning",...}` | Restart servicios Shomer con reporte post | Solo appliance |
| **O4** | TASK-001 disco `learning` | `"TASK-001":"learning"` | Limpieza logs ≥85 % con aviso resultado | Ya casi existe — formalizar |
| **O5** | TASK-006 Protector muestral | `"TASK-006":"learning"` | Auditoría aleatoria backups — solo informa | Cero riesgo red cliente |
| **O6** | Promover tareas a `approved` | USB revisa stats + 5 OK | Auto silencioso TASK-001/002 con aviso después | Una tarea a la vez |
| **O7** | Contexto chat | Prompt + SITE.md | Mejor texto libre | — |

Calendario original sugerido (orientativo, nunca se siguió literalmente semana a semana,
pero el orden de fases sí se respetó): O1-O2 primero, luego observación, luego O3-O6.

### §13 original — "Próximo paso de implementación" (10 jun 2026)

Las 5 tareas listadas ahí (crear `triage.py`, crear `auto_tasks.py` con el registry
TASK-001…010, refactorizar `watch_disk`/`watch_services` para llamar al catálogo, TASK-006
de solo lectura, `BOT_AUTO_TASKS_CONFIG={}` por defecto) **ya están hechas** — verificado
en código el 13 sep 2026: `core/triage.py`, `core/auto_tasks.py` con el catálogo completo
y los 3 modos `off/learning/approved`, `watch_disk`/`watch_services` disparando vía
`auto_tasks.maybe_run()`.

### Dato que cambió: no existe un modo global `BOT_AUTONOMOUS_MODE`

La v1.1 documentaba en su §6 una variable `BOT_AUTONOMOUS_MODE=off|learning|approved`
como interruptor **global**. Esa variable **nunca se implementó así** — no aparece en
ningún `core/*.py`. Lo que sí existe y es lo real:

- El modo es **por tarea**, vía `BOT_AUTO_TASKS_CONFIG` (JSON `{"TASK-001":"approved",...}`).
- `BOT_LEARN_SUPERVISED` / `BOT_LEARN_AUTONOMOUS` controlan el aprendizaje (botones de
  feedback y guardado automático de skills), no el modo de ejecución de las tareas.

---

## De CATALOGO_TASK.md — la fase `authorize` (botón antes de cada ejecución)

El catálogo original (10 jun 2026) proponía una **cuarta fase** `authorize` entre
`learning` y `approved`: el bot propondría la tarea con botones "Ejecutar / Omitir" y
solo correría si el técnico apretaba el botón. **Nunca se implementó** — verificado en
código el 13 sep 2026, `core/auto_tasks.py` solo reconoce `off`/`learning`/`approved`
(`_MODES = ("off", "learning", "approved")`). En la práctica, USB decidió saltar
directo de `learning` a `approved` en todas las tareas del catálogo tras observar
resultados, sin necesitar el paso intermedio. Si en el futuro se instala en un hotel
nuevo y se quiere ese paso de cautela extra, hay que implementarlo — hoy no existe.

---

## De PROTOCOLO_CAMBIOS_AGENTE.md v1.1 (11 jun 2026) — bitácora de sesión antigua

### §9 original — Sesión 53 (11 jun 2026)

| Cambio | Archivos | Deploy |
|--------|----------|--------|
| Anti-spam Hunter bot | `core/monitor.py` — `watch_active_threats`, `watch_network_audit`, `watch_hunter_verify` | Ópera + labs vía `deploy.sh` |
| Fix APs duplicados Guardian↔Infra | `core/monitor.py` — `watch_infra` ignora `ap`; recuperado solo si hubo alerta | Ópera |
| Hunter RouterOS verify DROP | `app/api/casador_support_firewall.py`, `hunter.html`, `HUNTER_MIKROTIK_ROUTEROS.md` | Ópera manual DROP; lab auto opcional |

### Herramienta de deploy que menciona la v1.1: `deploy.sh` desde `.205`

El protocolo original asumía que `.205` (lab) era el origen del código y `deploy.sh`
la herramienta de propagación, con Ópera como destino. **Esto se invirtió el 13 sep
2026**: hoy Ópera es el maestro y las herramientas reales son `tools/fleet_sync_core.sh`
(core) / `tools/fleet_sync.sh` (agente) — ver `CLAUDE.md` y `REGLAS_DEPLOY.md` del repo
core para el detalle. Se conserva aquí porque parte del checklist (qué archivo tocar por
tipo de cambio) sigue siendo válida — solo cambió la dirección y la herramienta del
último paso ("deploy").
