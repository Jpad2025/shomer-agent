"""brain.py -- motor de correlacion y razonamiento unificado ("cerebro" de Shomer).

Contexto (sesion 81, 4 sep 2026): hasta hoy, cada sistema (Guardian, Hunter,
Infra, chronic_tickets, pattern_analysis) decidia y avisaba por su cuenta, sin
ver el cuadro completo -- de ahi salieron varios de los huecos cerrados en la
sesion anterior (duplicados, bypass de supresion cronica, etc). watch_memoria_sync
ya sincronizaba Guardian+Infra+auto_task a una bitacora comun (memoria_incidentes
en memoria.db) con la intencion explicita de que "todo el razonamiento futuro
lea de ahi" (ver su docstring) -- pero nada leia de ahi para razonar de verdad,
solo pattern_analysis.py, y ese agrupa por ENTIDAD individual (un mismo AP que
cae varias veces), nunca CRUZA sistemas ni entidades distintas.

Este modulo es la pieza que faltaba:
  1. Agrupa eventos por PROXIMIDAD TEMPORAL sin importar el sistema de origen
     (ej.: 4 APs y un switch caen en el mismo minuto -> probablemente la misma
     causa de fondo, no 5 problemas distintos).
  2. Cruza cada equipo del grupo con su aprendizaje REAL (agente_skills: cuantas
     veces un reinicio remoto funciono/fallo en ESE equipo, si ya es un patron
     cronico conocido, si ya hay un ticket abierto) -- aprendizaje ACTIVO como
     insumo de una decision, no solo contexto pasivo pegado al chat.
  3. Le pide a un modelo de razonamiento (mas fuerte que el del chat rapido,
     ver BRAIN_MODEL) una hipotesis de causa raiz + recomendacion respaldada
     por esa evidencia -- nunca inventada: los conteos y hechos los calcula
     codigo deterministico (mismo principio que pattern_analysis.py), el modelo
     solo describe/recomienda sobre datos ya verificados.

No reemplaza ninguna alerta existente: Guardian/Hunter/Infra siguen avisando
exactamente igual que hoy. Esto es una capa ADICIONAL que solo habla cuando
encuentra algo realmente correlacionado o con patron fuerte -- y solo interrumpe
por Telegram si la urgencia es media o alta, para no sumar mas ruido.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

log = logging.getLogger("shomer-brain")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")
MEMORIA_DB = os.environ.get("MEMORIA_DB_PATH", "/app/data/memoria.db")

BRAIN_ENABLED = os.environ.get("BRAIN_ENABLED", "1").strip().lower() in ("1", "true", "yes")
BRAIN_MODEL = os.environ.get("BRAIN_MODEL", "gpt-4o").strip()
BRAIN_INTERVAL_MIN = int(os.environ.get("BRAIN_INTERVAL_MIN", "5"))
CLUSTER_WINDOW_MIN = int(os.environ.get("BRAIN_CLUSTER_WINDOW_MIN", "10"))
MAX_EVENTS_IN_PROMPT = 20
MAX_ENTITIES_IN_PROMPT = 10

_SEVERITY_RANK = {"critical": 3, "warn": 2, "info": 1}


def _init_db() -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS brain_conclusions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT DEFAULT (datetime('now')),
                entities TEXT NOT NULL,
                sources TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                urgency TEXT NOT NULL,
                evidence_count INTEGER DEFAULT 0,
                engine TEXT DEFAULT '',
                sent_telegram INTEGER DEFAULT 0
            )
            """
        )
        cols = {r[1] for r in con.execute("PRAGMA table_info(brain_conclusions)").fetchall()}
        if "entity_ips" not in cols:
            con.execute("ALTER TABLE brain_conclusions ADD COLUMN entity_ips TEXT DEFAULT ''")
        if "ticket_id" not in cols:
            con.execute("ALTER TABLE brain_conclusions ADD COLUMN ticket_id INTEGER")
        con.execute(
            "CREATE TABLE IF NOT EXISTS brain_state (key TEXT PRIMARY KEY, value TEXT)"
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("brain init: %s", e)


_init_db()


def _get_state(key: str, default: str = "") -> str:
    con = sqlite3.connect(KNOWLEDGE_DB)
    row = con.execute("SELECT value FROM brain_state WHERE key=?", (key,)).fetchone()
    con.close()
    return row[0] if row else default


def _set_state(key: str, value: str) -> None:
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.execute(
        "INSERT INTO brain_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    con.commit()
    con.close()


def _new_events() -> list[dict]:
    """Eventos nuevos desde el ultimo ciclo -- ya unificados por memoria_central
    (Guardian + Infra + Hunter). Se excluye auto_task: son ejecuciones internas
    ya evaluadas por agente_skills, no incidentes de red a correlacionar."""
    last_id = int(_get_state("last_incident_id", "0") or 0)
    con = sqlite3.connect(MEMORIA_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, ts, source, entity_ip, entity_name, device_type, event, detail, severity "
        "FROM memoria_incidentes WHERE id > ? AND source != 'auto_task' ORDER BY id ASC LIMIT 500",
        (last_id,),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _parse_ts(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except Exception:
            continue
    return None


def _cluster_by_time(events: list[dict], window_min: int) -> list[list[dict]]:
    """Agrupa por brecha temporal (no por entidad) -- si dos eventos caen a
    menos de window_min uno del otro, sin importar de que sistema vengan,
    quedan en el mismo grupo a evaluar como posible causa comun."""
    parsed = []
    for e in events:
        ts = _parse_ts(e["ts"])
        if ts:
            parsed.append((ts, e))
    parsed.sort(key=lambda x: x[0])
    clusters: list[list[dict]] = []
    current: list[dict] = []
    last_ts = None
    for ts, e in parsed:
        if current and last_ts and (ts - last_ts) > timedelta(minutes=window_min):
            clusters.append(current)
            current = []
        current.append(e)
        last_ts = ts
    if current:
        clusters.append(current)
    return clusters


def _cluster_severity(cluster: list[dict]) -> str:
    best = "info"
    for e in cluster:
        sev = e.get("severity") or "info"
        if _SEVERITY_RANK.get(sev, 1) > _SEVERITY_RANK.get(best, 1):
            best = sev
    return best


def _cluster_entities(cluster: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for e in cluster:
        key = e.get("entity_ip") or e.get("entity_name") or e.get("source")
        if key not in seen:
            seen[key] = {
                "ip": e.get("entity_ip") or "",
                "name": e.get("entity_name") or key,
                "source": e.get("source"),
            }
    return list(seen.values())


def _entity_learning_context(ip: str) -> dict:
    """Datos DETERMINISTICOS (no LLM) de aprendizaje activo por equipo --
    esto es lo que hace que la recomendacion este respaldada, no adivinada."""
    out: dict = {"skills": [], "chronic": None, "ticket_open": False}
    if not ip:
        return out
    try:
        from core import agente_skills
        for s in agente_skills.list_skills(device_ip=ip, limit=5):
            out["skills"].append({
                "accion": s.get("action_label"),
                "ok": s.get("success_count") or 0,
                "fail": s.get("fail_count") or 0,
                "fuente": s.get("source"),
            })
    except Exception:
        pass
    try:
        from core import pattern_analysis
        pat = pattern_analysis.get_pattern_for_entity(entity_ip=ip)
        if pat:
            out["chronic"] = pat
    except Exception:
        pass
    try:
        from core import chronic_tickets
        for t in chronic_tickets.list_open():
            if t.get("ip") == ip:
                out["ticket_open"] = True
                break
    except Exception:
        pass
    return out


def _should_escalate_to_llm(cluster: list[dict], entities: list[dict]) -> bool:
    """Filtro de costo/ruido: no todo grupo de eventos merece gastar el modelo
    pago -- solo lo que tiene chance real de ser un hallazgo util."""
    sev = _cluster_severity(cluster)
    if len(entities) >= 2 and sev in ("warn", "critical"):
        return True
    if len(entities) == 1 and sev == "critical":
        return True
    if len(entities) == 1 and sev == "warn":
        ctx = _entity_learning_context(entities[0]["ip"])
        if ctx["chronic"] or ctx["skills"]:
            return True
    return False


_SYSTEM_PROMPT = (
    "Sos el motor de razonamiento central de Shomer, sistema de monitoreo de "
    "redes de hoteles. Recibis un grupo de eventos REALES que ocurrieron cerca "
    "en el tiempo, posiblemente de sistemas distintos (Guardian=WiFi/APs, "
    "Infra=switches/camaras/impresoras/servidores, Hunter=seguridad perimetral "
    "de red). Tambien recibis el historial de aprendizaje real de cada equipo "
    "involucrado: cuantas veces un reinicio remoto funciono o fallo en ESE "
    "equipo especifico, si ya es un patron cronico conocido, si ya hay un "
    "pendiente/ticket abierto para el. Todos los numeros que recibis ya fueron "
    "contados por codigo, no los inventaste vos -- no agregues cifras que no "
    "esten en el contexto. Tu trabajo: dar UNA hipotesis de causa raiz que "
    "explique el grupo completo si comparten una causa comun (ej. un switch "
    "upstream que tira varios equipos), o aclarar que no estan relacionados si "
    "no la comparten. Da una recomendacion concreta y accionable para el "
    "tecnico, respaldada en la evidencia real (ej.: 'reinicio remoto ya "
    "funciono 4 de 4 veces en este equipo -> intentalo primero' o 'nunca ha "
    "funcionado remoto, revision fisica'). Si la evidencia es debil, decilo "
    "asi, no lo infles a algo grave. Se BREVE: maximo 1-2 frases cortas por "
    "campo -- la respuesta completa debe entrar dentro del limite de tokens "
    "de salida, una respuesta cortada a mitad de camino no sirve de nada. "
    "Responde SOLO JSON, sin texto extra, sin bloques de codigo: "
    '{"correlacionados": true|false, "causa_raiz": "...", "recomendacion": "...", '
    '"urgencia": "alta|media|baja", "resumen": "..."}'
)


def _call_openai_reasoning(user_prompt: str) -> str | None:
    try:
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            return None
        client = OpenAI(api_key=key, timeout=30.0, max_retries=1)
        resp = client.chat.completions.create(
            model=BRAIN_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=900,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        try:
            from core import memory as _memory
            usage = getattr(resp, "usage", None)
            if usage:
                tokens = int(getattr(usage, "total_tokens", 0) or 0)
                if tokens:
                    _memory.record_tokens(
                        tokens, model=BRAIN_MODEL, endpoint="brain",
                        provider="openai", user_id="brain",
                    )
        except Exception:
            pass
        return resp.choices[0].message.content
    except Exception as e:
        log.warning("brain: OpenAI (%s) fallo: %s -- fallback a Groq", BRAIN_MODEL, e)
        return None


def _call_groq_reasoning(user_prompt: str) -> str | None:
    try:
        from core import groq_helper
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        out = groq_helper._call_groq(messages, max_tokens=900, background=True)
        if not out or out.lstrip()[:1] in ("⏳", "❌", "⚠️"):
            return None
        return out
    except Exception as e:
        log.warning("brain: Groq fallback tambien fallo: %s", e)
        return None


def _salvage_truncated_object(text: str) -> dict | None:
    """Recupera campos de un objeto JSON cortado a mitad de camino (típico
    cuando la salida choca contra max_tokens) -- mismo problema que
    pattern_analysis.py resuelve para listas, aquí para un solo objeto: si
    algún campo quedó completo antes del corte, se rescata en vez de perder
    todo el hallazgo (visto real en producción el 4 sep con un cluster grande)."""
    import re
    campos = {}
    for campo in ("causa_raiz", "recomendacion", "urgencia", "resumen"):
        m = re.search(rf'"{campo}"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
        if m:
            campos[campo] = m.group(1).replace('\\"', '"').replace("\\n", " ")
    if "causa_raiz" not in campos and "recomendacion" not in campos:
        return None
    campos.setdefault("causa_raiz", "(respuesta cortada -- ver recomendación)")
    campos.setdefault("recomendacion", "(respuesta cortada -- revisar manualmente)")
    campos.setdefault("urgencia", "media")
    campos.setdefault("resumen", "Hallazgo recuperado de una respuesta truncada.")
    return campos


def _call_reasoning_model(user_prompt: str) -> dict | None:
    raw = _call_openai_reasoning(user_prompt)
    engine = "openai"
    if raw is None:
        raw = _call_groq_reasoning(user_prompt)
        engine = "groq"
    if raw is None:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").lstrip("json").strip()
    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            return None
        data["_engine"] = engine
        return data
    except Exception as e:
        salvaged = _salvage_truncated_object(cleaned)
        if salvaged:
            log.info("brain: respuesta truncada -- campos rescatados parcialmente")
            salvaged["_engine"] = engine
            return salvaged
        log.warning("brain: respuesta no es JSON valido (%s): %s", e, raw[:200])
        return None


def _is_duplicate(con: sqlite3.Connection, entities_str: str, hours: int = 2) -> bool:
    row = con.execute(
        "SELECT 1 FROM brain_conclusions WHERE entities=? AND ts > datetime('now', ?) LIMIT 1",
        (entities_str, f"-{hours} hours"),
    ).fetchone()
    return bool(row)


def _bootstrap_if_needed() -> bool:
    """Primera vez que corre el cerebro: memoria_incidentes ya tiene meses de
    historia (Guardian/Infra/Hunter llevan tiempo sincronizando). Sin esto, el
    primer ciclo intentaria analizar miles de eventos viejos contra el modelo
    pago -- caro e inutil. Arranca escuchando desde AHORA, no desde el origen."""
    if _get_state("last_incident_id", "") != "":
        return False
    con = sqlite3.connect(MEMORIA_DB)
    row = con.execute("SELECT MAX(id) FROM memoria_incidentes").fetchone()
    con.close()
    max_id = row[0] if row and row[0] else 0
    _set_state("last_incident_id", str(max_id))
    log.info("brain: primer arranque -- inicia desde id=%d (sin reprocesar historia)", max_id)
    return True


def run_cycle() -> list[dict]:
    """Sincrono a proposito -- se llama desde asyncio.to_thread() en el watcher
    (mismo patron que pattern_analysis.run_pattern_detection_sync)."""
    if _bootstrap_if_needed():
        return []
    events = _new_events()
    if not events:
        return []
    max_id = max(e["id"] for e in events)
    clusters = _cluster_by_time(events, CLUSTER_WINDOW_MIN)
    conclusiones: list[dict] = []
    con = sqlite3.connect(KNOWLEDGE_DB)
    for cluster in clusters:
        entities = _cluster_entities(cluster)
        if not _should_escalate_to_llm(cluster, entities):
            continue
        # Máximo MAX_ENTITIES_IN_PROMPT entidades con contexto completo -- un
        # grupo grande (ej. caída masiva de 30 eventos) no necesita el detalle
        # de aprendizaje de cada una para que el modelo entienda la causa común.
        entities_for_context = entities[:MAX_ENTITIES_IN_PROMPT]
        contexto_entidades = {ent["name"]: _entity_learning_context(ent["ip"]) for ent in entities_for_context}
        # Eventos acotados por CANTIDAD (no por caracteres) -- cortar el JSON a
        # ciegas con [:N] rompe la estructura y le manda al modelo datos
        # corruptos como si fueran "hechos reales" (bug real visto en producción
        # el 4 sep: un grupo de 30 eventos truncado a mitad de un string generó
        # una respuesta también truncada e inutilizable).
        eventos_incluidos = cluster[:MAX_EVENTS_IN_PROMPT]
        omitidos = len(cluster) - len(eventos_incluidos)
        payload = {
            "eventos": [
                {
                    "ts": e["ts"], "fuente": e["source"],
                    "entidad": e.get("entity_name") or e.get("entity_ip"),
                    "evento": e["event"], "detalle": (e.get("detail") or "")[:150],
                    "severidad": e.get("severity"),
                }
                for e in eventos_incluidos
            ],
            "eventos_omitidos_por_espacio": omitidos,
            "aprendizaje_por_entidad": contexto_entidades,
        }
        user_prompt = "Datos reales del incidente:\n" + json.dumps(payload, ensure_ascii=False)
        result = _call_reasoning_model(user_prompt)
        if not result:
            log.warning("brain: sin respuesta del modelo para grupo de %d evento(s)", len(cluster))
            continue

        urgencia = str(result.get("urgencia") or "baja").lower()
        if urgencia not in ("alta", "media", "baja"):
            urgencia = "baja"
        entities_str = ", ".join(e["name"] for e in entities)
        ips_str = ",".join(e["ip"] for e in entities if e["ip"])
        sources_str = ", ".join(sorted({e["source"] for e in cluster}))
        is_dup = _is_duplicate(con, entities_str)

        cur = con.execute(
            "INSERT INTO brain_conclusions "
            "(entities, sources, root_cause, recommendation, urgency, evidence_count, engine, entity_ips) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entities_str, sources_str,
                str(result.get("causa_raiz") or "")[:1000],
                str(result.get("recomendacion") or "")[:1000],
                urgencia, len(cluster), result.get("_engine") or "", ips_str,
            ),
        )
        conclusion_id = cur.lastrowid
        con.commit()  # cerrar esta transacción ANTES de que chronic_tickets abra
                      # su propia conexión de escritura -- sin esto, sqlite tira
                      # "database is locked" (bug real encontrado al probar).

        # Protagonismo real (sesion 81 cont., pedido explicito de Juan Pablo):
        # un hallazgo de varios equipos con urgencia alta abre un pendiente de
        # verdad -- mismo sistema que ya usa /pendientes -- en vez de vivir
        # solo como un mensaje de Telegram que se pierde en el historial. Asi
        # el cerebro queda dentro del flujo de trabajo real, no aparte de el.
        ticket_id = None
        if urgencia == "alta" and len(entities) >= 2 and not is_dup:
            try:
                from core import chronic_tickets
                anchor_ip = entities[0]["ip"] or f"cerebro-{conclusion_id}"
                nombre_ticket = f"🧠 {entities_str[:150]}"
                ticket_id, _nuevo = chronic_tickets.get_or_create(anchor_ip, nombre_ticket, "cerebro")
                con.execute(
                    "UPDATE brain_conclusions SET ticket_id=? WHERE id=?",
                    (ticket_id, conclusion_id),
                )
                con.commit()
            except Exception as e:
                log.warning("brain: no se pudo abrir pendiente para hallazgo #%d: %s", conclusion_id, e)
        conclusiones.append({
            "id": conclusion_id,
            "entities": entities_str,
            "sources": sources_str,
            "root_cause": result.get("causa_raiz") or "",
            "recommendation": result.get("recomendacion") or "",
            "urgency": urgencia,
            "resumen": result.get("resumen") or "",
            "evidence_count": len(cluster),
            "_dup": is_dup,
            "_engine": result.get("_engine"),
            "ticket_id": ticket_id,
        })
    con.close()
    _set_state("last_incident_id", str(max_id))
    return conclusiones


def format_telegram(c: dict) -> str:
    icon = {"alta": "🔴", "media": "🟡", "baja": "🟢"}.get(c["urgency"], "🧠")
    lines = [
        f"🧠 <b>Cerebro Shomer</b> {icon} — hallazgo correlacionado",
        f"<b>Equipos:</b> {c['entities']}",
        f"<b>Sistemas:</b> {c['sources']}",
        f"<b>Causa probable:</b> {c['root_cause']}",
        f"<b>Recomendación:</b> {c['recommendation']}",
        f"<i>Basado en {c['evidence_count']} evento(s) correlacionados</i>",
    ]
    if c.get("ticket_id"):
        lines.append(f"🎫 Abierto como pendiente #{c['ticket_id']} — ver /pendientes")
    return "\n".join(lines)


def recently_covered(ip: str, minutes: int = 20) -> dict | None:
    """¿Este equipo ya salió en un hallazgo del cerebro hace poco? Lo usan los
    watchers individuales (Guardian/Infra) para no repetir una alerta aparte
    de algo que el cerebro ya explicó -- protagonismo real, no solo un mensaje
    de más al lado de los de siempre."""
    if not ip:
        return None
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT id, root_cause, ticket_id FROM brain_conclusions "
        "WHERE (',' || entity_ips || ',') LIKE ? AND ts > datetime('now', ?) "
        "ORDER BY ts DESC LIMIT 1",
        (f"%,{ip},%", f"-{minutes} minutes"),
    ).fetchone()
    con.close()
    return dict(row) if row else None


def mark_sent(conclusion_id: int) -> None:
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.execute("UPDATE brain_conclusions SET sent_telegram=1 WHERE id=?", (conclusion_id,))
    con.commit()
    con.close()


def list_recent(limit: int = 5) -> list[dict]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM brain_conclusions ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
