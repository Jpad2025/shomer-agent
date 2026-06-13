# Protocolo — cambios al agente Telegram (comandos, TASK-*, tools)

**Versión:** 1.1 · **Fecha:** 11 jun 2026  
**Audiencia:** Juan Pablo + ingeniería USB (Cursor, Claude Code, cualquier IA)  
**Objetivo:** agregar o cambiar comportamiento del bot **sin romper producción** ni duplicar documentación contradictoria.

---

## 1. Mapa de archivos — qué es cada cosa

| Archivo / dato | Dónde | Quién lo usa | Qué va ahí |
|----------------|-------|--------------|------------|
| **`CLAUDE.md`** | `/opt/network_monitor/CLAUDE.md` | Dev USB (Cursor / Claude Code) | Arquitectura Shomer, normas, estado producto, bitácora sesiones. **No** config de un hotel concreto |
| **`SITE.md`** | `/opt/network_monitor/SITE.md` **en cada Shomer** | Técnico en sitio + dev | Red, VLANs, SPAN, firewall, contacto, particularidades **de ese cliente** |
| **`CATALOGO_TASK.md`** | `/storage/shomer-agent/docs/` | Dev + ops | TASK-001…010, modos `approved`/`off` por sitio |
| **`POLITICAS_AGENTE.md`** | `/storage/shomer-agent/docs/` | Dev + ops | Matriz T0–T4, Capas A–D, rollout |
| **`PROTOCOLO_CAMBIOS_AGENTE.md`** | `/storage/shomer-agent/docs/` | Dev (este doc) | Checklist al tocar bot |
| **`BEHAVIOR.md`** | `/storage/shomer-agent/` (+ `docs/campo/`) | LLM del bot | Cómo debe pensar/responder la IA |
| **`TECNICO_OPERACION.md`** | idem | LLM + técnico | Lenguaje operacional simple |
| **`MANUAL_CAMPO_AGENTE.md`** | `docs/campo/` | Técnico campo | Comandos, flujos instalación |
| **`SOPORTE_TECNICO.md`** | `docs/campo/` | Soporte USB | Procedimientos largos |
| **`.env` agente** | `/storage/shomer-agent/.env` | Runtime | Tokens, `BOT_AUTO_TASKS_CONFIG` — **único por sitio, nunca al repo** |
| **`knowledge.db`** | `/storage/shomer-agent/data/` | Bot + panel `/gestion` | `incident_knowledge`, `auto_task_stats`, acciones técnico |
| **`conversations.db`** | `/storage/shomer-agent/data/` | Bot chat IA | Historial chat por usuario (`core/memory.py`) — **no es un .md** |
| **`core/*.py`** | `/storage/shomer-agent/core/` | Runtime | Código fuente — montado en container sin rebuild |

### ⚠️ No confundir “memory”

| Nombre | Qué es |
|--------|--------|
| **`memory.py`** | Código Python — SQLite `conversations.db` (chat OpenAI/Groq) |
| **`knowledge.db`** | Aprendizaje operativo — soluciones guardadas + stats TASK-* |
| **`memory.md`** | **No existe** en el proyecto — no crear salvo doc humano opcional |

### Docs que el bot lee (texto libre / developer)

Montar en `docker-compose.yml` según sitio. En lab pueden incluir `CLAUDE.md`; en hotel cliente normalmente **solo** `TECNICO_OPERACION.md` + `BEHAVIOR.md` + manuales campo.

---

## 2. Dos herramientas, una fuente de verdad

Trabajás con **Cursor** y a veces **Claude Code** en la misma máquina o en `.205` vs Ópera.

**Reglas:**

1. **Código canónico del agente:** `/storage/shomer-agent/core/` en el Shomer donde desarrollás (lab `.205`).
2. **Despliegue a otros sitios:** `bash /opt/network_monitor/tools/deploy.sh` desde `.205` — no copiar archivos a mano sin deploy.
3. **Antes de cerrar sesión con cualquier IA:** actualizar **una** bitácora en `CLAUDE.md` (Parte AL, AM, …) con 3–5 líneas de qué cambió.
4. **Config por hotel:** solo `SITE.md` + `.env` agente en **ese** servidor — no mezclar en `CLAUDE.md`.
5. Si Cursor y Claude Code tocan lo mismo el mismo día → **git commit local** en `/opt/network_monitor` y/o nota en `CLAUDE.md` para no perder contexto.

---

## 3. Checklist — nueva TASK-* (TASK-011+)

| # | Paso | Archivo |
|---|------|---------|
| 1 | Definir ID, trigger, Green State, capa T0–T4 | `docs/CATALOGO_TASK.md` |
| 2 | Aprobar con USB — **nunca** solo la IA | — |
| 3 | Agregar a `TASK_CATALOG` + handler | `core/auto_tasks.py` |
| 4 | Disparo desde monitor (si aplica) | `core/monitor.py` |
| 5 | Mensaje Telegram legible | `core/ui_notify.py`, `core/fmt.py` (`TASK_TITLES`) |
| 6 | Keywords correlación guardar solución | `core/learning.py` |
| 7 | Modo default `off`; sitio activa en `.env` | `SITE.md` o nota despliegue |
| 8 | **Botones feedback** post-acción (ver §5) | `core/bot.py` o `ui_notify` |
| 9 | Deploy + reiniciar container | `deploy.sh` |
| 10 | Entrada bitácora | `CLAUDE.md` |

**Prohibido:** que el LLM invente un `task_id` en runtime. Solo IDs en `TASK_CATALOG`.

---

## 4. Checklist — nuevo comando Telegram `/foo`

| # | Paso | Archivo |
|---|------|---------|
| 1 | Handler `async def cmd_foo` | `core/bot.py` |
| 2 | Registrar en tupla comandos + `CallbackQueryHandler` si hay botones | `core/bot.py` (`main()`) |
| 3 | Agregar a `set_my_commands` (menú ⋮) | `core/bot.py` |
| 4 | Documentar en `/ayuda` | `core/bot.py` (`_ayuda_text`) |
| 5 | Manuales campo | `docs/campo/SOPORTE_TECNICO.md`, `MANUAL_CAMPO_AGENTE.md` |
| 6 | Si es acción sensible → capa T2/T3 en `POLITICAS_AGENTE.md` | docs |
| 7 | Deploy | `deploy.sh` |

**Aliases:** preferir **un** nombre canónico en menú; alias opcional sin duplicar lógica.

---

## 5. Checklist — nueva tool (function calling IA)

| # | Paso | Archivo |
|---|------|---------|
| 1 | Schema OpenAI/Groq | `core/tools.py` |
| 2 | Implementación | `core/shomer_api.py` o módulo existente |
| 3 | Executor en router chat | `core/tools.py` + `llm_router.py` |
| 4 | Mencionar en `BEHAVIOR.md` si cambia protocolo diagnóstico | `BEHAVIOR.md` |
| 5 | **No** agregar como TASK-* salvo acción autónoma con trigger fijo | — |

---

## 6. Feedback técnico — implementado (L3–L5)

### L3 — Técnico enseña (`BOT_LEARN_SUPERVISED=1`)

| Situación | Botones / comando |
|-----------|-------------------|
| Reboot / recuperación Guardian/Infra | `save_know:r/o/x` |
| Hunter desbloqueo | Falso positivo / Describir |
| TASK automática (001…009) | `save_task:y/n/o/x` |
| Manual | `/guardar <ip> <texto>` |

Destino: `incident_knowledge` + **`agente_skills`** + `human_confirmations` en TASK-*.

### L4 — Sistema aprende solo (`BOT_LEARN_AUTONOMOUS=1`)

Tras cada TASK con Green State OK → fila en `agente_skills` (source=`auto`).  
Solo TASK T1 si `BOT_AUTO_SAFE_ONLY=1`.

### L5 — Chat usa lo aprendido

- `llm_router` inyecta skills + SITE.md + knowledge reciente en cada chat.
- Tool **`get_agente_skills`** (function calling).
- Comando **`/skills`** — lista skills al técnico.

### Comandos developer

- **`/aprobar_task TASK-001`** — promueve a `approved` (BD `auto_task_modes`).
- Telegram a `AGENT_DEVELOPER_CHAT_ID` tras 5 Green OK en modo `learning`.

---

## 7. Config Ópera — TASK approved (referencia)

```bash
BOT_LEARN_SUPERVISED=1
BOT_AUTO_TASKS_CONFIG={"TASK-001":"approved","TASK-002":"approved","TASK-003":"approved","TASK-004":"approved","TASK-005":"approved","TASK-006":"approved","TASK-008":"approved","TASK-009":"approved","TASK-007":"off","TASK-010":"off"}
```

Copiar a `/storage/shomer-agent/.env` en **shomer-hotelopera** → `sudo docker compose up -d`.

Registrar en **`SITE.md` de Ópera** (sección Agente) — no en `CLAUDE.md`.

---

## 8. Orden de lectura para IA nueva en el proyecto

1. `CLAUDE.md` Parte N (agente) + Partes AL/AN/AO  
2. `docs/CATALOGO_TASK.md`  
3. `docs/POLITICAS_AGENTE.md`  
4. **Este protocolo**  
5. `SITE.md` del servidor donde se trabaja  
6. Código: `bot.py` → `monitor.py` → `auto_tasks.py`

---

## 9. Bitácora reciente (11 jun 2026 — Sesión 53)

| Cambio | Archivos | Deploy |
|--------|----------|--------|
| Anti-spam Hunter bot | `core/monitor.py` — `watch_active_threats`, `watch_network_audit`, `watch_hunter_verify` | Ópera + labs vía `deploy.sh` |
| Fix APs duplicados Guardian↔Infra | `core/monitor.py` — `watch_infra` ignora `ap`; recuperado solo si hubo alerta | Ópera |
| Hunter RouterOS verify DROP | `app/api/casador_support_firewall.py`, `hunter.html`, `HUNTER_MIKROTIK_ROUTEROS.md` | Ópera manual DROP; lab auto opcional |

---

*Actualizar versión de este protocolo cuando cambie el flujo de deploy o se implemente modo `authorize`.*
