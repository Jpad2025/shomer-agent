# Shomer Agent — Matriz de políticas y rollout por sitio

**Versión:** 1.1 · **Fecha:** 10 jun 2026  
**Audiencia:** ingeniería USB + técnico de campo  
**Relacionado:** `BEHAVIOR.md`, `core/triage.py` (Fase 1), `core/repair.py`, `knowledge.db`

Este documento define **qué puede hacer el bot solo**, **qué puede aprender**, **qué nunca**, y **cómo activar cada capa en lab (.205) y en Hotel Ópera paso a paso**.

> **v1.1:** Autonomía por **catálogo de tareas explícitas** + **modo aprendizaje** (no “la IA elige libre”). Separación clara de lo que **ya automatiza Shomer en Python** (Guardian, Hunter) vs lo que añade el **agente Telegram**.

---

## 1. Principio rector

> **No es un agente que “toma el control”. Es un conjunto de tareas parametrizadas, cada una con dueño, umbral y modo (observar / aprendizaje / auto aprobado).**

**La IA (Groq/OpenAI) redacta alertas y resume — no inventa acciones nuevas.** Solo ejecuta tareas del catálogo §3 cuyo `task_id` esté habilitado para ese sitio.

Cuatro capas de automatización (no mezclar):

| Capa | Dueño | Ejemplos | Dónde se configura |
|------|-------|----------|-------------------|
| **A — Shomer core** | Panel `:8000` / Guardian / Hunter | Auto-reboot AP (Guardian poller), auto-bloqueo IP (Suricata→Wazuh→API→iptables/RouterOS) | BD `system_state`, panel Guardian/Hunter |
| **B — Bot monitores (hoy)** | `core/monitor.py` + `repair.py` | Limpieza disco ≥85 %, restart guardian/tools/nginx si caen | Código + umbrales fijos |
| **C — Triage (nuevo)** | `core/triage.py` | Agrupa alertas 15 s → 1 mensaje Telegram | `BOT_TRIAGE_ENABLED` |
| **D — Catálogo autónomo (nuevo)** | `core/auto_tasks.py` + `knowledge.db` | Tareas §3.6 con modo aprendizaje | Por `task_id` y sitio |

**Guardian reboots y Hunter firewall NO pasan por el catálogo del bot** — ya funcionan en Capa A. El bot solo **informa** (con triage) o ofrece **botón** reboot manual; no compite con Guardian.

---

## 1.1 Modos de autonomía (por tarea, no global)

Cada tarea del catálogo tiene su propio modo en `auto_tasks_config` (JSON en `.env` o BD):

| Modo | Comportamiento |
|------|----------------|
| **`off`** | Solo alerta. Cero ejecución. |
| **`learning`** | Ejecuta → espera 30 s → Green State → **Telegram con resultado** + correlaciona con mensajes “guardar solución” / `incident_knowledge`. Acumula estadísticas. **USB decide** si sube a `approved`. |
| **`approved`** | Ejecuta sin preguntar (solo si Green State OK y cooldown). Técnico recibe aviso **después**: “Ejecuté TASK-001, disco 83 %→71 %”. |

**No hay “auto_ejecutar global”.** Tras N éxitos en `learning`, el sistema **sugiere** al developer en Telegram: “TASK-001 llevó 5/5 éxitos — ¿aprobar auto en Ópera?” — nunca promueve solo.

**Correlación con mensajes de solución:** si el técnico guarda “disco lleno → limpieza journal” en `incident_knowledge` o botón *Guardar solución*, el worker de aprendizaje incrementa `human_confirmations` para esa tarea — acelera revisión USB, no activa auto sin humano.

---

## 2. Capas de acción (T0–T4)

Extiende los niveles T1–T3 de `BEHAVIOR.md` para el agente autónomo.

| Capa | Nombre | Ejemplos | Auto sin confirmación | Puede aprender (`agente_skills`) |
|------|--------|----------|----------------------|----------------------------------|
| **T0** | Solo observar | Consultas tools, logs, ping, SNMP GET | ✅ Siempre | ❌ No aplica |
| **T1** | Remediación SAFE | Reiniciar guardian/tools/nginx; limpieza disco *safe*; journal vacuum | ✅ Sí (Fase 2b) | ✅ Sí, tras N éxitos |
| **T2** | Remediación reversible | Reboot AP/nodo; bloquear/desbloquear IP Hunter; suricata restart; clear_print_queue | ❌ Botón obligatorio en hotel | ✅ Sí, pero `auto_ejecutar=0` en Ópera |
| **T3** | Remediación sensible | Backup manual, escaneo auditoría red, modo mantenimiento | ❌ Botón | ⚠️ Solo patrón informativo, nunca auto |
| **T4** | Prohibido auto | Restore backup, prune Restic, docker prune, UFW, credenciales, borrar inventario | ❌ Nunca | ❌ Nunca |

**Regla de oro hotel:** en producción cliente, **T1 auto permitido · T2 siempre con botón · T3/T4 nunca auto**.

---

## 3. Matriz completa — acciones

### 3.1 Infraestructura del propio Shomer (servidor appliance)

| Acción | Capa | Auto lab | Auto Ópera | Aprende skill | Green State (30 s) |
|--------|------|----------|------------|---------------|-------------------|
| `restart_service(guardian)` | T1 | ✅ | Fase O3+ | ✅ | TCP :8000 OK |
| `restart_service(tools)` | T1 | ✅ | Fase O3+ | ✅ | TCP :8001 OK |
| `restart_service(nginx)` | T1 | ✅ | Fase O3+ | ✅ | TCP :80 OK |
| `kill_zombie_port(8000/8001)` | T1 | ✅ | Fase O3+ | ✅ | Puerto libre + servicio up |
| `restart_suricata` | T2 | Botón | Botón | ✅ patrón, no auto | `systemctl is-active suricata` |
| Limpieza disco *safe* (journal, logs, /tmp, apt) | T1 | ✅ | Fase O4+ | ✅ | Disco bajó ≥2 % o <80 % |
| Limpieza disco *warn* (docker prune, restic prune) | T4 | ❌ | ❌ | ❌ | — |
| Reiniciar container `shomer-agent` | T2 | Botón | Botón | ❌ | — |

### 3.2 Red del cliente — Guardian / APs

| Acción | Dueño | Bot rol | Auto reboot AP |
|--------|-------|---------|----------------|
| **Reboot automático AP** (umbrales, cooldown) | **Capa A — Guardian poller** `:8000` | Solo alerta triage + botón manual | ✅ Ya parametrizado en panel Guardian |
| Reboot desde botón Telegram | Capa C/D | T2 — confirmación | ❌ Ópera |
| Alerta caída / recuperación / degradado | Capa C — triage | T0 — informar | — |
| Reboot preventivo 04:00 (`preventive_reboot`) | Capa B — monitor | Evaluar por sitio | Opcional |

**Importante:** el “caos de Guardian” se reduce con **triage (Capa C)**, no dando al bot control de reboots. Los reboots automáticos **siguen igual que hoy** — `guardian.fail_threshold`, `guardian.cooldown_sec`, `shomer_maintenance`.

**Equipos con `no_reboot: true`:** Guardian no reinicia; bot no ofrece botón (ej. firewall Hunter).

### 3.3 Hunter / seguridad

| Acción | Dueño | Bot rol |
|--------|-------|---------|
| **Auto-bloqueo IP** (severidad, excepciones, subnets) | **Capa A — Hunter** Suricata→Wazuh→`POST /remedies/block`→iptables | Solo explica alerta (T0) |
| Bloqueo manual desde Telegram | Capa D | T2 — botón |
| Sync firewall tras reboot router | Capa A + panel | Botón T2 |
| Auto-desbloqueo (`BOT_AUTO_UNBLOCK_HOURS`) | Capa B — monitor | Off en Ópera |

**No mover auto-bloqueo al catálogo del agente** — ya es Python determinista con validación de IP y circuit breaker SSH.

### 3.4 Tracker / Protector / consultas

| Acción | Capa | Auto | Aprende |
|--------|------|------|---------|
| Todas las tools de **consulta** (21 tools actuales) | T0 | N/A chat | ❌ |
| `run_network_audit_scan` | T3 | Botón / developer | ❌ auto |
| `clear_print_queue` | T2 | Botón | ✅ patrón |
| Backup manual Protector | T3 | Botón | ❌ |
| Restore / descarga tarball agente | T4 | ❌ developer manual | ❌ |

### 3.5 Inframonitor

| Acción | Capa | Auto | Notas |
|--------|------|------|-------|
| Alerta equipo offline/online | T0 | — | Solo monitoreo, **sin reboot** |
| SNMP consulta | T0 | — | Solo lectura |

---

### 3.6 Catálogo de tareas autónomas del agente (Capa D)

Solo estas tareas pueden ejecutarse en modo `learning` o `approved`. **Cada fila se habilita por sitio.**

| ID | Tarea | Umbral / trigger | Green State | Modo lab | Modo Ópera (inicial) | Notas |
|----|-------|------------------|-------------|----------|----------------------|-------|
| **TASK-001** | Limpieza disco *safe* (journal, logs Shomer >7d, /tmp, apt) | Disco ≥ **85 %** | Uso < 80 % o −2 % | `approved` | `learning` → luego `approved` | **Ya existe** en `watch_disk` — formalizar en catálogo |
| **TASK-002** | Restart `shomer-guardian` | TCP :8000 down | :8000 OK 30 s | `learning` | `learning` | **Ya existe** en `watch_services` |
| **TASK-003** | Restart `shomer-tools` | TCP :8001 down | :8001 OK | `learning` | `learning` | Idem |
| **TASK-004** | Restart `nginx` | TCP :80 down | :80 OK | `learning` | `learning` | Idem |
| **TASK-005** | Truncar `/var/log/shomer/*.log` > **50 MB** → 10 MB | Por archivo | Archivo < 15 MB | `off` | `learning` | Sin borrar — truncate, reversible |
| **TASK-006** | **Auditoría muestral Protector** — N equipos aleatorios / semana | Cron dom 06:00 | Todos OK o alerta lista | `learning` | `learning` | **Solo lectura**: GET backups health, sin restore |
| **TASK-007** | Verificar último backup < **26 h** (alerta si no) | `watch_backups` | Ya alerta — unificar mensaje vía triage | `off` | `off` | Supervisión, no remedia |
| **TASK-008** | Kill zombie puerto 8000/8001 | Puerto ocupado huérfano | Servicio up | `learning` | `off` | Developer aprueba por sitio |
| **TASK-009** | Reiniciar Suricata | Pipeline degradado + suricata inactive | `systemctl active` | `off` | `off` | T2 — botón primero |
| **TASK-010** | Reboot AP vía API Guardian | — | — | **`off`** | **`off`** | Lo hace **Guardian Capa A**, no el catálogo |

**Añadir tarea nueva:** PR con fila en catálogo + implementación en `auto_tasks.py` + revisión USB — nunca “la IA descubrió una tool”.

#### TASK-006 — Protector muestral (ejemplo supervisado)

```
Cada domingo 06:00 (timezone sitio):
  1. Elegir 3 equipos backup_devices al azar (seed semanal)
  2. Comprobar last_snapshot_id, last_status, edad < 26 h
  3. Modo learning: Telegram "Auditoría muestral — 2/3 OK, falló PC-X — revisar panel"
  4. No ejecuta backup solo — solo reporta
  5. Acumula historial para USB decidir si algún día TASK-011 "reintentar backup fallido"
```

---

## 4. Aprendizaje — modo aprendizaje (no promoción automática)

Tablas en `knowledge.db`:

```sql
-- Catálogo runtime (espejo del §3.6)
auto_task_runs (
  id, task_id, site, triggered_at, mode, params_json,
  green_ok, green_detail, disk_before, disk_after, notified_at
)

-- Estadísticas por sitio (para sugerir promoción a USB)
auto_task_stats (
  task_id, site, runs_total, runs_ok, human_confirmations,
  suggested_promote_at  -- NULL hasta que USB aprueba
)
```

| Fuente | Qué aporta |
|--------|------------|
| Green State 30 s post-ejecución | Éxito técnico objetivo |
| Telegram post-acción | “Ejecuté TASK-001, disco 86 %→74 %” |
| Botón *Guardar solución* / `incident_knowledge` | Confirmación humana semántica |
| Developer `/aprobar_task TASK-001` (futuro) | Pasa `learning` → `approved` en ese sitio |

**Condiciones para pasar `learning` → `approved` (decisión USB, no bot):**

| Criterio | Valor sugerido |
|----------|----------------|
| Éxitos Green State consecutivos | ≥ 5 |
| Confirmaciones humanas opcionales | ≥ 1 (acelera, no obligatorio) |
| Fallos en learning | 0 en últimos 7 días |
| Aprobación explícita | Developer o checklist despliegue |

**Lo que NO hace el modo aprendizaje:** elegir tools al azar, promover T2/T3 a auto, tocar red del cliente sin catálogo.

---

## 5. Qué NO puede aprender ni ejecutar solo (nunca)

- Restore de backup (Protector o tarball agente)
- `restic prune`, `docker image prune`
- Cambiar credenciales, JWT, UFW, netplan, rutas
- Borrar equipos de inventario o snapshots
- Reboot de equipos con `no_reboot: true`
- Modificar configuración Hunter/firewall del cliente sin confirmación
- Auto-reboot AP en **Hotel Ópera** (política fija hasta nueva revisión USB)
- Ejecutar tools no listadas en allowlist del bucle autónomo
- Inventar tools — solo las definidas en código

---

## 6. Variables `.env` por capa

```env
# ── Fase 1: Triage ──
BOT_TRIAGE_ENABLED=0
BOT_TRIAGE_WINDOW_SEC=15
BOT_TRIAGE_CRITICAL_SEC=5

# ── Catálogo autónomo (Capa D) ──
# off = solo alertas | learning = ejecuta y reporta | approved = auto silencioso+aviso post
BOT_AUTONOMOUS_MODE=off
# JSON por sitio — qué TASK-* en qué modo (default todo off salvo TASK-001/002 en learning en lab)
# Ejemplo Ópera inicial: {"TASK-001":"learning","TASK-006":"learning"}
BOT_AUTO_TASKS_CONFIG={}

# ── Guardian / Hunter — NO cambiar rol del bot ──
BOT_AUTO_REBOOT=false          # botón manual AP — Guardian Capa A sigue con su auto-reboot
BOT_AUTO_UNBLOCK_HOURS=0

# ── Aprendizaje supervisado (botones en alertas) ──
BOT_LEARN_SUPERVISED=0         # correlaciona incident_knowledge con TASK-*

# ── Stats ──
AUTO_TASK_VERIFY_SEC=30
AUTO_TASK_COOLDOWN_SEC=900
AUTO_TASK_SUGGEST_PROMOTE_AFTER=5
```

---

## 7. Rollout laboratorio (.205)

| Paso | Qué encender | Validación (mínimo 48 h) |
|------|--------------|---------------------------|
| **L0** | Bot apagado, código desplegado | — |
| **L1** | `BOT_TRIAGE_ENABLED=1` + Guardian piloto | 1 msg por caída AP `.210`; sin pérdida de alertas críticas |
| **L2** | Todos los monitores → triage | `/salud monitores` OK; técnico reporta menos ruido |
| **L3** | `BOT_LEARN_SUPERVISED=1` | Botón enseñar → fila en `agente_skills` |
| **L4** | `BOT_LEARN_AUTONOMOUS=1` + `BOT_AUTO_SAFE_ONLY=1` | Simular stop guardian → auto-restart → Green State → skill |
| **L5** | Fase 3 contexto en chat (topología + skills en prompt) | Pregunta "¿por qué cayó X?" usa datos reales |
| **L6** | Opcional: `BOT_AUTO_REBOOT=true` solo en lab | Reboot `.210` con botón/auto según prueba |

**Criterio de salida lab → Ópera Fase O1:** L1 y L2 estables 72 h sin alertas perdidas.

---

## 8. Rollout Hotel Ópera — paso a paso

**Hostname:** `shomer-hotelopera` · **Tailscale:** `100.103.148.119`  
**Política base:** cliente en producción — conservador.

| Fase | Nombre | `.env` clave | Qué gana el técnico | Riesgo |
|------|--------|--------------|---------------------|--------|
| **O0** | Baseline (hoy) | Triage off, bot como antes | Operación conocida | Ruido Telegram |
| **O1** | Cortafuegos | `BOT_TRIAGE_ENABLED=1` | **1 mensaje claro** por incidente AP/servicio | 15 s delay no críticos |
| **O2** | Triage completo | Todos monitores en triage | Menos spam en disk, pipeline, hunter | Requiere monitoreo 1 semana |
| **O3** | Catálogo modo `learning` | `BOT_AUTO_TASKS_CONFIG={"TASK-002":"learning",...}` | Restart servicios Shomer con reporte post | Solo appliance |
| **O4** | TASK-001 disco `learning` | `"TASK-001":"learning"` | Limpieza logs ≥85 % con aviso resultado | Ya casi existe — formalizar |
| **O5** | TASK-006 Protector muestral | `"TASK-006":"learning"` | Auditoría aleatoria backups — **solo informa** | Cero riesgo red cliente |
| **O6** | Promover tareas a `approved` | USB revisa stats + 5 OK | Auto silencioso TASK-001/002 con aviso después | Una tarea a la vez |
| **O7** | Contexto chat | Prompt + SITE.md | Mejor texto libre | — |

**Ópera — config inicial recomendada (O3):**
```json
{"TASK-001":"learning","TASK-002":"learning","TASK-003":"learning","TASK-004":"learning","TASK-006":"learning"}
```
Todo lo demás `off`. Guardian reboots y Hunter block **sin cambios** (Capa A).

### Qué NO se activa en Ópera (sin revisión USB explícita)

| Variable | Valor fijo Ópera | Motivo |
|----------|------------------|--------|
| `BOT_AUTO_REBOOT` | `false` | Reboot AP afecta huéspedes/recepción |
| `BOT_AUTO_UNBLOCK_HOURS` | `0` | Seguridad — IP desbloqueada solo con criterio humano |
| Auto T2 (reboot AP, block IP) | Off | Solo botón Telegram |
| T4 (prune, restore) | Off | Irreversible |

### Checklist antes de cada fase Ópera

```
☐ Fase anterior estable ≥ 7 días
☐ Técnico del hotel informado (1 línea: qué cambia en Telegram)
☐ Developer puede ver logs: docker compose logs shomer-agent --tail=50
☐ Rollback documentado (ver §9)
☐ shomer_maintenance probado (pausa auto sin apagar alertas)
```

### Calendario sugerido (orientativo)

| Semana | Fase Ópera |
|--------|------------|
| 1 | O1 — triage Guardian + servicios |
| 2 | O2 — triage todos monitores |
| 3–4 | Observación + ajuste ventanas triage |
| 5 | O3 — auto SAFE Shomer |
| 6 | O4 — disco safe (si disco >70 % alguna vez) |
| 7+ | O5 — botones aprendizaje |
| 8+ | O6 — contexto chat |

---

## 9. Rollback rápido

Si algo sale mal en cualquier fase:

```bash
# En /storage/shomer-agent/.env — volver a baseline
BOT_TRIAGE_ENABLED=0
BOT_LEARN_SUPERVISED=0
BOT_AUTONOMOUS_MODE=off
BOT_AUTO_TASKS_CONFIG={}
BOT_AUTO_REBOOT=false

cd /storage/shomer-agent && sudo docker compose restart
```

El bot vuelve al comportamiento **pre-triage** (monitores → Telegram directo). No se borra `agente_skills` — queda para cuando se reactive.

---

## 10. Eventos críticos — bypass triage

Estos eventos **no esperan 15 s** — ventana `BOT_TRIAGE_CRITICAL_SEC` (5 s) o envío inmediato:

| Evento | Origen |
|--------|--------|
| WAN servidor caída | `watch_wan_outage` |
| Pipeline Hunter degradado (primera transición) | `watch_pipeline` |
| Disco >92 % | `watch_disk` |
| Servicio guardian+tools caídos simultáneos | `watch_services` |

---

## 11. Resumen ganancia / pérdida por fase (Ópera)

| Fase | Ganas | Pierdes / trade-off |
|------|-------|---------------------|
| O1–O2 | Telegram legible, menos fatiga | Granularidad instantánea |
| O3–O4 | Shomer se auto-repara de noche | Alguna acción ocurre sin que la veas antes |
| O5 | Bot recuerda qué funcionó en este hotel | 1 tap extra la primera vez por patrón nuevo |
| O6 | Chat más inteligente | Nada operativo — solo UX |

---

## 12. Resumen — qué controla quién

| Problema | Quién lo resuelve hoy | Qué añadimos |
|----------|----------------------|--------------|
| AP caído → reboot | **Guardian** (Capa A) | Triage: 1 Telegram claro |
| IP atacante → firewall | **Hunter** (Capa A) | Bot explica, no bloquea solo |
| Disco 85 % → limpiar logs | **watch_disk** (Capa B) | TASK-001 en catálogo + modo learning |
| Guardian :8000 caído | **watch_services** (Capa B) | TASK-002 en catálogo |
| Backups sin verificar muestra | — | TASK-006 nuevo, solo supervisión |
| Técnico guarda “esto funcionó” | `incident_knowledge` | Correlaciona con TASK-* en learning |

---

## 13. Próximo paso de implementación

1. `core/triage.py` — Fase 1, botones intactos
2. `core/auto_tasks.py` — registry TASK-001…010 + modos off/learning/approved
3. Refactor `watch_disk` / `watch_services` → llaman catálogo (mismo comportamiento, trazabilidad)
4. TASK-006 Protector muestral (solo lectura)
5. **`BOT_AUTO_TASKS_CONFIG={}` por defecto** — Ópera sube tarea a tarea

*USB Ingeniería — política viva. Actualizar al cerrar cada fase Ópera/Lab.*
