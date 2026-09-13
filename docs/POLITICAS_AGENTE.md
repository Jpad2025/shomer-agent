# Shomer Agent — Matriz de políticas y rollout por sitio

**Versión:** 1.2 · **Fecha:** 13 sep 2026 · **Verificado contra código real** (no es un plan, es lo que corre hoy)  
**Audiencia:** ingeniería USB + técnico de campo  
**Relacionado:** `BEHAVIOR.md`, `core/triage.py`, `core/auto_tasks.py`, `core/learning.py`, `knowledge.db`, `AGENTE_historico.md`

Este documento define **qué puede hacer el bot solo**, **qué puede aprender**, **qué nunca**, y **cómo está configurado hoy en Hotel Ópera**. La versión 1.1 (10 jun 2026) era un plan de activación gradual escrito *antes* de construir nada; esta versión describe el sistema **ya construido y en producción**, verificado línea por línea contra `core/auto_tasks.py`, `core/triage.py`, `core/learning.py` y el `.env` real de Ópera el 13 sep 2026. El plan original y las fases de rollout quedaron archivadas en `AGENTE_historico.md`.

---

## 1. Principio rector

> **No es un agente que "toma el control". Es un conjunto de tareas parametrizadas, cada una con dueño, umbral y modo (observar / aprendizaje / auto aprobado).**

**La IA (Groq/OpenAI) redacta alertas y resume — no inventa acciones nuevas.** Solo ejecuta tareas del catálogo §3.6 cuyo `task_id` esté habilitado para ese sitio.

Cuatro capas de automatización (no mezclar):

| Capa | Dueño | Ejemplos | Dónde se configura |
|------|-------|----------|-------------------|
| **A — Shomer core** | Panel `:8000` / Guardian / Hunter | Auto-reboot AP (Guardian poller), auto-bloqueo IP (Suricata→Wazuh→API→iptables/RouterOS) | BD `system_state`, panel Guardian/Hunter |
| **B — Bot monitores** | `core/monitor.py` + `repair.py` | 41 monitores automáticos (ver `/monitores`) | Código + umbrales fijos |
| **C — Triage** | `core/triage.py` | Agrupa alertas en ventana `BOT_TRIAGE_WINDOW_SEC` → 1 mensaje Telegram | `BOT_TRIAGE_ENABLED` |
| **D — Catálogo autónomo** | `core/auto_tasks.py` + `knowledge.db` | Tareas §3.6 (TASK-001…010) con modo por sitio | `BOT_AUTO_TASKS_CONFIG` |

**Guardian reboots y Hunter firewall NO pasan por el catálogo del bot** — son Capa A. El bot solo **informa** (con triage) o expone comandos manuales con confirmación (`/reboot`, `/bloquear`); no compite con Guardian ni con Hunter.

---

## 1.1 Modos de autonomía por tarea (verificado en `core/auto_tasks.py`)

Cada tarea del catálogo tiene su propio modo en `BOT_AUTO_TASKS_CONFIG` (JSON en `.env`) o en la tabla `auto_task_modes` de `knowledge.db` (override post-`/aprobar_task`, con prioridad sobre el `.env`):

| Modo | Comportamiento real (código) |
|------|-------------------------------|
| **`off`** | `maybe_run()` corta antes de ejecutar. Cero acción — solo lo que ya alertaba antes de existir el catálogo. |
| **`learning`** | **Ejecuta primero, igual que `approved`** → espera Green State (`AUTO_TASK_VERIFY_SEC`, hoy 30 s) → Telegram con el resultado y, si `BOT_LEARN_SUPERVISED=1`, botones 👍/👎/📝 para calificar. Acumula estadísticas en `auto_task_stats`. |
| **`approved`** | Idéntico a `learning` en la ejecución — la única diferencia real es que ya pasó la revisión de USB y normalmente no se pide feedback tarea por tarea. |

**No existe un gate de aprobación previa a la ejecución para ninguna tarea del catálogo.** Esto corrige la v1.1: ahí se documentaba una fase futura `authorize` (botón "Ejecutar/Omitir" antes de correr) — nunca se implementó (ver `AGENTE_historico.md`). Hoy la única frontera real es **`off` vs. no-`off`**: si una tarea no está en `off`, corre sola cuando se cumple su trigger, y el técnico se entera después por Telegram (con opción de calificar si `BOT_LEARN_SUPERVISED=1`).

Las acciones que sí requieren un tap **antes** de ejecutarse (reboot de AP desde el bot, bloquear/desbloquear IP manual, limpiar cola de impresión) **no son tareas del catálogo** — son comandos de Telegram con confirmación inline, implementados directamente en `core/bot.py`, fuera de `auto_tasks.py`. Ver §3.4 y `CATALOGO_TASK.md` §1.

**Promoción `learning` → `approved`:** developer manual, comando **`/aprobar_task TASK-00X`** (implementado, `core/bot.py:cmd_aprobar_task`), o edición directa de `BOT_AUTO_TASKS_CONFIG` + reinicio del contenedor. Tras 5 Green State OK consecutivos el sistema sugiere la promoción por Telegram al chat developer (`AGENT_DEVELOPER_CHAT_ID`) — nunca promueve solo.

---

## 2. Capas de acción (T0–T4) — clasificación de diseño, no un mecanismo de ejecución

Esta tabla clasifica **qué tan sensible es una acción** para decidir si algún día puede entrar al catálogo automático y en qué modo debe empezar — no describe un botón que exista en tiempo de ejecución para T2/T3 (ver §1.1). Extiende los niveles T1–T3 de `BEHAVIOR.md`.

| Nivel | Nombre | Ejemplos | ¿Puede terminar en `approved` (auto sin botón)? | ¿Puede aprender (`agente_skills`)? |
|------|--------|----------|----------------------------------------------------|----------------------------------------|
| **T0** | Solo observar | Consultas tools, logs, ping, SNMP GET | No aplica — no ejecuta nada | No aplica |
| **T1** | Remediación segura sobre el propio Shomer | Reiniciar guardian/tools/nginx; limpieza disco *safe*; kill zombie puerto | Sí — así están hoy TASK-001…005, 008 | Sí, tras N éxitos |
| **T2** | Remediación reversible sobre red del cliente | Reboot AP/nodo; bloquear/desbloquear IP Hunter | No — queda **siempre** como comando manual con confirmación, nunca entra al catálogo | Sí, patrón informativo |
| **T3** | Remediación sensible | Restart Suricata, escaneo de auditoría de red, modo mantenimiento | Depende del caso: restart Suricata (TASK-009) sí se promovió a `approved` por decisión explícita de JP tras piloto; nmap/auditoría sigue manual | Solo patrón, no auto salvo excepción documentada |
| **T4** | Prohibido automático | Restore backup, prune Restic, docker prune, UFW, credenciales, borrar inventario | Nunca — bloqueado en código (TASK-010) o inexistente en el catálogo | Nunca |

**Regla de oro:** T2 nunca entra al catálogo (reboot AP y bloqueo/desbloqueo de IP quedan para siempre como comandos manuales de Capa A/bot, no como TASK-*). T4 está fuera del catálogo por diseño. La única "promoción" real que puede darse es T1→`approved` y, caso por caso con aprobación explícita, T3→`approved` (ya ocurrió con TASK-009).

---

## 3. Matriz completa — acciones

### 3.1 Infraestructura del propio Shomer (servidor appliance) — estado real Ópera, 13 sep 2026

| Acción | Nivel | Modo Ópera hoy | Aprende skill | Green State (30 s) |
|--------|------|----------|---------------|-------------------|
| `restart_service(guardian)` — TASK-002 | T1 | **`approved`** | ✅ | TCP :8000 OK |
| `restart_service(tools)` — TASK-003 | T1 | **`approved`** | ✅ | TCP :8001 OK |
| `restart_service(nginx)` — TASK-004 | T1 | **`approved`** | ✅ | TCP :80 OK |
| `kill_zombie_port(8000/8001)` — TASK-008 | T1 | **`approved`** | ✅ | Puerto libre + servicio up |
| `restart_suricata` — TASK-009 | T3 (promovida) | **`approved`** | ✅ patrón | `systemctl is-active suricata` |
| Limpieza disco *safe* — TASK-001 | T1 | **`approved`** | ✅ | Disco bajó ≥2 % o <80 % |
| Truncar logs >50 MB — TASK-005 | T1 | **`approved`** | ✅ | Archivo < 15 MB |
| Limpieza disco *warn* (docker prune, restic prune) | T4 | ❌ no existe en catálogo | ❌ | — |
| Reiniciar container `shomer-agent` | T2 | Manual (fuera del catálogo) | ❌ | — |

### 3.2 Red del cliente — Guardian / APs

| Acción | Dueño | Bot rol | Auto reboot AP |
|--------|-------|---------|----------------|
| **Reboot automático AP** (umbrales, cooldown) | **Capa A — Guardian poller** `:8000` | Solo alerta triage + botón manual | ✅ Ya parametrizado en panel Guardian |
| Reboot desde botón Telegram (`/reboot`) | Bot manual | Confirmación obligatoria | ❌ Nunca entra al catálogo (T2) |
| Alerta caída / recuperación / degradado | Capa C — triage | Informar | — |
| Reboot preventivo 04:00 (`preventive_reboot`) | Capa B — monitor | Monitor registrado, evaluado por sitio | Opcional |

**El "ruido de Guardian" se reduce con triage (Capa C), no dando al bot control de reboots.** Los reboots automáticos siguen igual que siempre — `guardian.fail_threshold`, `guardian.cooldown_sec`, `shomer_maintenance`.

**Equipos con `no_reboot: true`:** Guardian no reinicia; bot no ofrece botón (ej. firewall Hunter).

### 3.3 Hunter / seguridad

| Acción | Dueño | Bot rol |
|--------|-------|---------|
| **Auto-bloqueo IP** (severidad, excepciones, subnets) | **Capa A — Hunter** Suricata→Wazuh→`POST /remedies/block`→iptables/RouterOS | Solo explica alerta (T0) |
| Bloqueo/desbloqueo manual (`/bloquear`, `/desbloquear`, `/liberar`) | Bot manual | Confirmación / listado — nunca entra al catálogo (T2) |
| Sync firewall tras reboot router | Capa A + panel | Manual, T2 |
| Auto-desbloqueo (`BOT_AUTO_UNBLOCK_HOURS`) | Capa B — monitor | Configurado en 0 en Ópera hoy |

**El auto-bloqueo NUNCA se mueve al catálogo del agente** — es Python determinista con validación de IP y circuit breaker SSH, no una TASK-*.

### 3.4 Tracker / Protector / consultas

| Acción | Nivel | Auto | Aprende |
|--------|------|------|---------|
| Tools de **consulta** (function calling, solo lectura) | T0 | Chat, sin restricción | ❌ |
| `run_network_audit_scan` (nmap) | T3 | Manual, developer | ❌ auto |
| Limpiar cola de impresión | T2 | Botón | ✅ patrón |
| Backup manual Protector | T3 | Botón | ❌ |
| Restore / descarga tarball agente | T4 | ❌ developer manual | ❌ |

### 3.5 Inframonitor

| Acción | Nivel | Auto | Notas |
|--------|------|------|-------|
| Alerta equipo offline/online | T0 | — | Solo monitoreo, **sin reboot** |
| SNMP consulta | T0 | — | Solo lectura |

---

### 3.6 Catálogo de tareas autónomas (Capa D) — estado real, `core/auto_tasks.py` + `.env` Ópera 13 sep 2026

| ID | Tarea | Trigger | Green State | Modo Ópera (real, verificado) | Notas |
|----|-------|---------|--------------|-------------------------------|-------|
| **TASK-001** | Limpieza disco *safe* (journal, logs Shomer >7d, /tmp, apt) | Disco ≥ 85 % | Uso < 80 % o −2 % | **`approved`** | |
| **TASK-002** | Restart `shomer-guardian` | TCP :8000 down | :8000 OK 30 s | **`approved`** | |
| **TASK-003** | Restart `shomer-tools` | TCP :8001 down | :8001 OK | **`approved`** | |
| **TASK-004** | Restart `nginx` | TCP :80 down | :80 OK | **`approved`** | |
| **TASK-005** | Truncar `*.log` > 50 MB → 10 MB | Cron 03:00 | Archivo < 15 MB | **`approved`** | Sin borrar — truncate, reversible |
| **TASK-006** | Auditoría muestral Protector — 3 equipos al azar/semana | Cron dom 06:00 | Todos OK o alerta lista | **`approved`** | Solo lectura, nunca ejecuta backup |
| **TASK-007** | Verificar último backup < 26 h | `watch_backups` | Ya alerta — informe unificado | **`approved`** | Solo informa, no remedia |
| **TASK-008** | Kill zombie puerto 8000/8001 | Puerto ocupado huérfano | Servicio up | **`approved`** | |
| **TASK-009** | Reiniciar Suricata | Pipeline degradado + suricata inactive | `systemctl active` | **`approved`** | Promovida de T3 tras piloto — decisión JP |
| **TASK-010** | Reboot AP vía API Guardian | — | — | **`off` — bloqueado también en código** (`_task_010_blocked`) | Lo hace Guardian Capa A; el catálogo la rechaza siempre, sin importar el modo configurado |

**Único item genuinamente en `off` hoy: TASK-010**, y ni siquiera depende de la config — `run_task()` la rechaza incondicionalmente. Todo lo demás del catálogo está `approved` en Ópera.

**Añadir tarea nueva (TASK-011+):** fila en `CATALOGO_TASK.md` + implementación en `auto_tasks.py` + revisión USB — nunca "la IA descubrió una tool".

---

## 4. Aprendizaje

Tablas en `knowledge.db` (verificadas: `auto_task_runs`, `auto_task_stats`, `auto_task_modes` existen y se usan en `core/auto_tasks.py`):

| Fuente | Qué aporta |
|--------|------------|
| Green State 30 s post-ejecución | Éxito técnico objetivo |
| Telegram post-acción | "Ejecuté TASK-001, disco 86 %→74 %" |
| Botón 👍/👎/📝 (`save_task:*`) o `/guardar` | Confirmación humana semántica → `human_confirmations` |
| Developer `/aprobar_task TASK-00X` | Pasa `learning` → `approved` en ese sitio (BD `auto_task_modes`, tiene prioridad sobre `.env`) |

**Condiciones sugeridas para promover `learning` → `approved`:**

| Criterio | Valor sugerido |
|----------|----------------|
| Éxitos Green State consecutivos | ≥ 5 (`AUTO_TASK_SUGGEST_PROMOTE_AFTER`) |
| Confirmaciones humanas opcionales | ≥ 1 (acelera, no obligatorio) |
| Fallos en `learning` (7 días) | 0 |
| Aprobación explícita | Developer vía `/aprobar_task` |

**Lo que NO hace el modo aprendizaje:** elegir tools al azar, promover T2/T4 a auto, tocar red del cliente sin pasar por comando manual con confirmación.

---

## 5. Qué NO puede aprender ni ejecutar solo (nunca) — verificado sin excepciones en código

- Restore de backup (Protector o tarball agente)
- `restic prune`, `docker image prune`
- Cambiar credenciales, JWT, UFW, netplan, rutas
- Borrar equipos de inventario o snapshots
- Reboot de equipos con `no_reboot: true`
- Modificar configuración Hunter/firewall del cliente sin confirmación manual
- Reboot de AP — TASK-010 bloqueada en código sin importar la config (`_task_010_blocked`)
- Ejecutar tools no listadas en el allowlist del router de chat
- Inventar `task_id` en runtime — solo los definidos en `TASK_CATALOG`

---

## 6. Variables `.env` reales (verificado contra `core/*.py`, 13 sep 2026)

```env
# ── Triage (Capa C) ──
BOT_TRIAGE_ENABLED=1
BOT_TRIAGE_WINDOW_SEC=15
BOT_TRIAGE_CRITICAL_SEC=5
BOT_TRIAGE_USE_GROQ=1          # opcional — usa Groq para redactar el resumen agrupado

# ── Catálogo autónomo (Capa D) — modo POR TAREA, no existe modo global ──
# JSON: {"TASK-001":"approved", ..., "TASK-010":"off"} — off | learning | approved
BOT_AUTO_TASKS_CONFIG={"TASK-001":"approved","TASK-002":"approved","TASK-003":"approved","TASK-004":"approved","TASK-005":"approved","TASK-006":"approved","TASK-007":"approved","TASK-008":"approved","TASK-009":"approved","TASK-010":"off"}

# ── Guardian / Hunter — NO cambia el rol del bot ──
BOT_AUTO_REBOOT=false          # botón manual AP — Guardian Capa A sigue con su auto-reboot
BOT_AUTO_UNBLOCK_HOURS=0

# ── Aprendizaje ──
BOT_LEARN_SUPERVISED=1         # botones 👍/👎/📝 tras cada TASK y cada remediación
BOT_LEARN_AUTONOMOUS=1         # guarda skill automática tras Green State OK
BOT_AUTO_SAFE_ONLY=1           # si está en 1, el aprendizaje automático solo confía en tareas T1

# ── Umbrales del catálogo ──
AUTO_TASK_VERIFY_SEC=30
AUTO_TASK_COOLDOWN_SEC=900
AUTO_TASK_SUGGEST_PROMOTE_AFTER=5
```

**Corrección respecto a la v1.1:** esa versión documentaba `BOT_AUTONOMOUS_MODE=off|learning|approved` como interruptor global. Esa variable **no existe en el código** — nunca se implementó así. Ver `AGENTE_historico.md`.

---

## 7. Estado real hoy (reemplaza los rollouts L0-L6 / O0-O7 de la v1.1)

El rollout gradual documentado en la v1.1 (archivado en `AGENTE_historico.md`) ya se
cumplió y se superó. Estado actual, sin fases pendientes:

- **Lab:** triage activo, catálogo disponible para pruebas — sin tráfico real que dispare la mayoría de las tareas (disco ~30 %, servicios estables).
- **Ópera (producción):** triage activo, aprendizaje supervisado y autónomo activos, **9 de 10 tareas del catálogo en `approved`** (todo salvo TASK-010, bloqueada por diseño). No queda ninguna fase de rollout pendiente para las tareas ya existentes.
- **Próximo hotel nuevo:** repetir el mismo camino que Ópera — empezar en `off`/`learning` por tarea, seguir criterios de promoción de §4, nunca copiar directamente el `.env` de Ópera con todo en `approved` sin pasar por el piloto local.

---

## 8. Rollback rápido

Si algo sale mal:

```bash
# En /storage/shomer-agent/.env — volver a baseline
BOT_TRIAGE_ENABLED=0
BOT_LEARN_SUPERVISED=0
BOT_LEARN_AUTONOMOUS=0
BOT_AUTO_TASKS_CONFIG={}
BOT_AUTO_REBOOT=false

cd /storage/shomer-agent && sudo docker compose restart
```

El bot vuelve al comportamiento pre-triage (monitores → Telegram directo). No se borra `agente_skills` ni `knowledge.db` — queda para cuando se reactive.

---

## 9. Eventos críticos — bypass triage

Estos eventos no esperan la ventana normal (`BOT_TRIAGE_WINDOW_SEC`) — usan `BOT_TRIAGE_CRITICAL_SEC` (5 s) o envío inmediato:

| Evento | Origen |
|--------|--------|
| WAN servidor caída | `watch_wan_outage` |
| Pipeline Hunter degradado (primera transición) | `watch_pipeline` |
| Disco >92 % | `watch_disk` |
| Servicio guardian+tools caídos simultáneos | `watch_services` |

---

## 10. Resumen — qué controla quién

| Problema | Quién lo resuelve hoy | Qué añade el agente |
|----------|----------------------|----------------------|
| AP caído → reboot | **Guardian** (Capa A) | Triage: 1 Telegram claro |
| IP atacante → firewall | **Hunter** (Capa A) | Bot explica, no bloquea solo |
| Disco 85 % → limpiar logs | **TASK-001**, `approved` | Reporte post-acción + skill |
| Guardian/tools/nginx caído | **TASK-002/003/004**, `approved` | Reporte post-acción |
| Backups sin verificar muestra | **TASK-006**, `approved` | Solo informa, nunca ejecuta backup |
| Técnico guarda "esto funcionó" | `incident_knowledge` + `agente_skills` | Correlaciona con la TASK-* correspondiente |

*USB Ingeniería — política viva. Reescrita el 13 sep 2026 sobre verificación real de código, reemplaza la v1.1 (10 jun 2026, archivada en `AGENTE_historico.md`).*
