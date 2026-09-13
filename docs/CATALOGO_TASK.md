# Catálogo de tareas autónomas — TASK-001…010

**Versión:** 1.2 · **Fecha:** 13 sep 2026 (corregido: TASK-007 ya está `approved`, no `off`)  
**Audiencia:** ingeniería USB + técnico de campo  
**Relacionado:** `POLITICAS_AGENTE.md` (política y estado real completo), `core/auto_tasks.py`, `core/learning.py`, `knowledge.db`

Documento maestro del **catálogo Capa D** del agente Telegram.  
La IA **no inventa tareas** — solo ejecuta IDs de esta lista, cada uno con modo propio por sitio.

> **Nota:** este documento describe el catálogo y la rúbrica de madurez de cada tarea.
> Para el estado real verificado hoy (qué modo tiene cada TASK en Ópera, y por qué la
> fase `authorize` de abajo nunca se implementó) ver `POLITICAS_AGENTE.md` §1.1 y §3.6,
> que es la fuente de verdad actualizada.

---

## 1. Cadena de madurez por tarea (rollout)

Cada TASK-* pasa por **fases ordenadas**. No se salta etapas en hotel cliente.

```
Fase 0 — off          Solo observa y avisa. Cero ejecución.
    ↓
Fase 1 — learning     Piloto en sitio real: ejecuta, espera Green State, reporta por Telegram,
                      acumula estadísticas + correlación con “guardar solución”.
    ↓
Fase 2 — authorize    Propone la acción con botón “Ejecutar / Omitir”. Sin botón = no corre.
                      (Modo recomendado en Ópera tras el piloto — ver §5.)
    ↓
Fase 3 — approved     Automático con aviso después: “Ejecuté TASK-001, disco 86 %→74 %”.
```

### Opinión de diseño (USB)

| Fase | Control | Cuándo usarla |
|------|---------|---------------|
| **off** | Máximo | Sitio nuevo, tarea no validada |
| **learning** | Alto — ejecuta pero informa todo | **Piloto Ópera** — eventos reales (disco, caída servicio, backups) |
| **authorize** | Muy alto — humano aprueba cada vez | Transición hotel: ya vimos que funciona, pero no confiamos 100 % aún |
| **approved** | Operativo — auto + aviso post | Tras ≥5 Green OK + 0 fallos 7 días + decisión USB explícita |

**Importante hoy en código:** existen modos `off`, `learning` y `approved`.  
`learning` **ya ejecuta** (no es simulacro). La fase **`authorize`** (botón antes de cada run) está **documentada aquí como objetivo** — implementación pendiente en `auto_tasks.py` (callback Telegram `task_run:TASK-001`).

**Regla hotel:** nunca promover a `approved` sin haber pasado por piloto (`learning`) en ese sitio o uno equivalente.

---

## 2. Política Hotel Ópera — automático vs con aprobación

El lab `.205` ya no genera eventos útiles (disco ~30 %, servicios estables).  
La **política operativa del catálogo TASK-* en producción** aplica en **Ópera** (`shomer-hotelopera`).

### Principio USB (v1.1)

| Tipo | Modo | Qué incluye |
|------|------|-------------|
| **Automático (`approved`)** | Ejecuta + Green State + aviso Telegram después | Mantenimiento del **propio Shomer** — disco, servicios, logs, zombie, Suricata, informe backups |
| **Solo observar (`off`)** | Avisa, no ejecuta vía catálogo | TASK-010 (Guardian) — único que sigue en `off` hoy |
| **Con aprobación humana** | Botón / comando — **no son TASK** | Reboot AP bot, bloquear/desbloquear Hunter, auditoría nmap, cola impresora, restore, prune, UFW, credenciales |

Guardian (reboot AP automático) y Hunter (auto-bloqueo) siguen en **Capa A** — panel Guardian/Hunter, no en `BOT_AUTO_TASKS_CONFIG`.

### Configuración Ópera producción (`.env`) — verificado 13 sep 2026

```bash
BOT_LEARN_SUPERVISED=1
# Una línea (copiar tal cual):
BOT_AUTO_TASKS_CONFIG={"TASK-001":"approved","TASK-002":"approved","TASK-003":"approved","TASK-004":"approved","TASK-005":"approved","TASK-006":"approved","TASK-007":"approved","TASK-008":"approved","TASK-009":"approved","TASK-010":"off"}
```

| TASK | Modo Ópera | Motivo |
|------|------------|--------|
| TASK-001 | **`approved`** | Limpieza disco safe — solo appliance |
| TASK-002 | **`approved`** | Restart Guardian si :8000 cae |
| TASK-003 | **`approved`** | Restart Tools si :8001 cae |
| TASK-004 | **`approved`** | Restart nginx si :80 cae |
| TASK-005 | **`approved`** | Truncar logs Shomer >50 MB (03:00, reversible) |
| TASK-006 | **`approved`** | Auditoría muestral backups — solo lectura |
| TASK-007 | **`approved`** | Alerta backup >26 h — promovida tras el piloto (era `off` en jun 2026) |
| TASK-008 | **`approved`** | Kill zombie :8000/8001 + restart servicio |
| TASK-009 | **`approved`** | Restart Suricata si pipeline degradado + inactive |
| TASK-010 | `off` | Siempre off — reboot AP = Guardian Capa A, bloqueado también en código |

Tras cambiar `.env`: `cd /storage/shomer-agent && sudo docker compose up -d`.

### Con aprobación humana (fuera del catálogo auto)

| Acción | Por qué no es `approved` |
|--------|--------------------------|
| Reboot AP desde bot Telegram | T2 — afecta equipos del hotel |
| Bloquear / desbloquear IP Hunter | T2 — firewall cliente |
| `run_network_audit_scan` (nmap) | T3 — intrusivo, minutos de duración |
| Clear cola impresora | T2 — toca PC del cliente |
| Restore backup / prune / docker prune | T4 — prohibido auto |
| UFW, credenciales, netplan | T4 — prohibido auto |

Modo **`authorize`** (botón antes de cada run) queda reservado para estas acciones cuando se implemente en código — ver §5.

### Seguimiento en Ópera

Revisar periódicamente en `knowledge.db` → `auto_task_stats` / `auto_task_runs`:

1. Green State OK vs fallos por TASK-ID
2. ¿Falsos positivos o reinicios innecesarios?
3. Si una tarea `approved` falla repetido → bajar a `off` o `learning` hasta revisar

---

## 3. Catálogo TASK-001…010

### Grupo A — Mantenimiento appliance (T1, auto candidatas)

| ID | Nombre | Acción | Trigger | Green State (30 s) | Correlación al guardar |
|----|--------|--------|---------|-------------------|------------------------|
| **TASK-001** | Limpieza disco safe | journal, logs >7d, /tmp, apt | Disco ≥ **85 %** | Uso < 80 % o −2 % | disco, lleno, journal, limpieza, espacio |
| **TASK-002** | Restart Guardian | `systemctl restart shomer-guardian` | TCP **:8000** down | :8000 OK | guardian, 8000, panel |
| **TASK-003** | Restart Tools | `systemctl restart shomer-tools` | TCP **:8001** down | :8001 OK | tools, 8001, tracker, protector |
| **TASK-004** | Restart nginx | `systemctl restart nginx` | TCP **:80** down | :80 OK | nginx, https, 8443, proxy |
| **TASK-005** | Truncar logs Shomer | `*.log` >50 MB → 10 MB | Cron **03:00** | Archivo < 15 MB | log, api.log, truncar |
| **TASK-008** | Kill zombie puerto | kill + restart servicio | :8000/8001 huérfano | Puerto libre + servicio up | zombie, puerto, 8000, 8001 |
| **TASK-009** | Restart Suricata | restart suricata | Pipeline degradado + inactive | `systemctl active` | suricata, pipeline, amenazas, espejo |

### Grupo B — Supervisión (solo informa)

| ID | Nombre | Acción | Trigger | Remedia | Ópera |
|----|--------|--------|---------|---------|-------|
| **TASK-006** | Auditoría muestral Protector | 3 equipos al azar, revisa último backup | Dom **06:00** | ❌ Solo reporta | **`approved`** |
| **TASK-007** | Alerta backup >26 h | Registro unificado | `watch_backups` | ❌ Solo alerta | **`approved`** |

### Grupo D — Prohibidas en catálogo

| ID | Nombre | Motivo |
|----|--------|--------|
| **TASK-010** | Reboot AP | Lo hace **Guardian Capa A** — nunca el catálogo del bot |

---

## 4. Lo que NO es TASK-* (referencia rápida)

| Acción | Capa | ¿Es TASK? |
|--------|------|-----------|
| Auto-reboot AP failsafe | A — Guardian | ❌ |
| Auto-bloqueo IP Hunter | A — Hunter | ❌ |
| Reboot AP botón Telegram | Bot manual T2 | ❌ |
| Bloquear/desbloquear IP | Bot manual T2 | ❌ |
| Escaneo auditoría red (nmap) | Tool T3 | ❌ |
| Clear cola impresora | Tool T2 | ❌ |
| Docker prune / restic prune / restore | T4 prohibido | ❌ Nunca |

---

## 5. Fase `authorize` — propuesta operativa (pendiente código)

Comportamiento deseado para hotel tras piloto `learning`:

```
Monitor detecta: disco 87 %
    → Bot Telegram:
      "⚠️ TASK-001 disponible — limpieza disco safe en /var (87 %)
       [▶ Ejecutar]  [✕ Omitir]"
    → Solo si técnico pulsa Ejecutar → corre TASK-001 → Green State → resultado
```

Ventajas:

- Control total del técnico en cliente real
- Misma acción que `learning`/`approved`, distinto gate
- Puente natural antes de `approved`

Implementación futura: modo `authorize` en `BOT_AUTO_TASKS_CONFIG` + callback `task_auth:TASK-001` en `bot.py`.

---

## 6. Criterios promoción `learning` → `approved`

Decisión **USB**, nunca automática del bot.

| Criterio | Valor sugerido |
|----------|----------------|
| Éxitos Green State consecutivos | ≥ **5** |
| Confirmaciones humanas (`incident_knowledge`) | ≥ **1** (acelera, no obligatorio) |
| Fallos en learning (7 días) | **0** |
| Aprobación explícita | Developer `/aprobar_task TASK-001` o checklist despliegue |

Estadísticas en `knowledge.db` → tablas `auto_task_stats`, `auto_task_runs`.

---

## 7. Tareas futuras (no implementadas)

| ID | Idea | Estado |
|----|------|--------|
| **TASK-011** | Reintentar backup Protector fallido | Propuesta — requiere PR + revisión USB |
| **TASK-012+** | Solo vía PR con fila en este catálogo | — |

---

## 8. Comandos y archivos

| Qué | Dónde |
|-----|-------|
| Registry + handlers | `core/auto_tasks.py` |
| Correlación guardar solución | `core/learning.py` |
| Disparo desde monitores | `core/monitor.py` (`watch_disk`, `watch_services`, crons) |
| Modos por sitio | `.env` → `BOT_AUTO_TASKS_CONFIG` |
| Overrides post-aprobación | BD `auto_task_modes` en `knowledge.db` |
| Política completa | `docs/POLITICAS_AGENTE.md` |

### Ejemplo cambiar modo en Ópera (manual)

```bash
# Editar .env del agente y reiniciar container — ver §2 bloque completo approved
BOT_AUTO_TASKS_CONFIG={"TASK-001":"approved",...,"TASK-009":"approved","TASK-010":"off"}

# Override en BD — vía comando Telegram, ya implementado:
# /aprobar_task TASK-009   (equivale a set_task_mode("TASK-009", "approved", updated_by=<user_id>))
```

---

## 9. Resumen ejecutivo

1. **Catálogo = TASK-001…010** — fijo, no negociable por la IA.
2. **Ópera producción (13 sep 2026):** TASK-001…009 (las 9) en **`approved`** — mantenimiento Shomer automático con aviso post-acción. TASK-007 se promovió después de la v1.1 (era `off` en jun 2026).
3. **Solo TASK-010 en `off`**, y bloqueada también en código sin importar la config. Reboot AP = Capa A (Guardian), no catálogo.
4. **Con aprobación humana:** reboot AP bot, Hunter manual, nmap, impresora, restore/prune/credenciales — nunca entran al catálogo, viven como comandos Telegram con confirmación.
5. **Cadena opcional sitio nuevo:** `off` → `learning` → `approved` — en Ópera USB saltó directo a `approved` en todas las tareas appliance tras el piloto. La fase intermedia `authorize` (§5) nunca se implementó en código.
6. **`/aprobar_task` ya está implementado** (`core/bot.py:cmd_aprobar_task`) — no es un próximo paso pendiente.

---

*Actualizar este archivo cuando se agregue TASK-011+ o el modo `authorize` en código. Para el estado operativo real y verificado, `POLITICAS_AGENTE.md` es la fuente de verdad — este documento es el catálogo de referencia técnica por tarea.*
