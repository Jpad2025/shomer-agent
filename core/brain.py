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
MAX_LIVE_VERIFY = 5  # llamadas de red reales por ciclo -- acota la duración del ciclo
BRAIN_SITE_CONTEXT_MAX = 4000

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
        if "dominios_conocimiento" not in cols:
            con.execute("ALTER TABLE brain_conclusions ADD COLUMN dominios_conocimiento TEXT DEFAULT ''")
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
    # Cómo se comporta de verdad este equipo, según los hechos ya registrados.
    # Es lo que separa una recomendación de manual ("inspeccionar el cableado")
    # de una de sitio ("cae 41 veces al mes y vuelve solo en 30 segundos: es
    # intermitencia, el cable ya se descarta"). No depende de que nadie lo
    # enseñe: las skills de abajo vienen del aporte humano, que casi no ocurre
    # -- 6 acciones en 3 meses, y solo 2 de cada 4 equipos con algún dato.
    try:
        from core import shomer_api as _api
        perfil = _api.get_perfil_equipo(ip)
        if perfil:
            out["comportamiento_real"] = perfil
    except Exception as e:
        log.debug("perfil de equipo en contexto: %s", e)
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


def _verificar_en_vivo(entity: dict) -> dict:
    """Fase 3 (6 sep 2026): comprobar el estado REAL del equipo AHORA, no
    solo confiar en el historial. Hueco real encontrado ese día: un evento
    'offline' de una impresora no dice si es cable, energía o algo puntual
    del equipo (ej. sensor de papel) -- sin esto, la 'causa probable' es una
    suposición educada, no una comprobación. Solo lectura, nunca ejecuta
    ninguna acción."""
    ip = (entity.get("ip") or "").strip()
    name = (entity.get("name") or "").lower()
    if not ip:
        return {}
    try:
        if any(k in name for k in ("bixolon", "imp ", "epson", "wf-", "impresora")):
            from drivers.printer import get_printer_status
            r = get_printer_status(ip)
            return {"tipo": "impresora", "estado_actual": r}
    except Exception as e:
        log.debug("brain: verificación impresora falló para %s: %s", ip, e)
    try:
        from core import shomer_api
        dev = shomer_api.get_infra_device(ip)
        if dev:
            return {"tipo": "infra", "estado_actual": {
                "status": dev.get("status"),
                "latency_ms": dev.get("latency_ms"),
                "tcp_ok": dev.get("tcp_ok"),
                "snmp_ok": dev.get("snmp_ok"),
                "snmp_down_ports": dev.get("snmp_down_ports"),
            }}
    except Exception as e:
        log.debug("brain: verificación infra falló para %s: %s", ip, e)
    try:
        from core import device_manager
        r = device_manager.ping_device(ip)
        return {"tipo": "ping", "estado_actual": r}
    except Exception as e:
        log.debug("brain: verificación ping falló para %s: %s", ip, e)
        return {}


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
    "de red, Protector=copias de seguridad). En 'aprendizaje_por_entidad' cada "
    "equipo puede traer 'comportamiento_real': cuantas veces cayo en el ultimo "
    "mes, en cuanto tiempo suele volver y si vuelve solo. USALO para no dar "
    "recomendaciones de manual. Si un equipo cae seguido y vuelve solo en pocos "
    "minutos, eso NO es un cable suelto ni una falla puntual: es intermitencia, "
    "y decirle al tecnico que revise el cable le hace perder un viaje. Si ademas "
    "varios equipos DISTINTOS del sitio se comportan igual, la causa es "
    "compartida (energia, enlace, equipo troncal) y hay que decirlo asi, no "
    "repartir la culpa entre cada equipo. Al reves, un equipo que casi nunca "
    "falla y hoy no vuelve es el que si merece revision fisica. Recibis tambien "
    "'eventos_que_shomer_no_aviso': transiciones que las reglas de ruido "
    "suprimieron a proposito (blip de gateway, caida masiva del sitio). NO son "
    "fallas ocultas ni un error del sistema: se callaron porque casi siempre son "
    "del propio sitio y no del equipo. Sirven para dimensionar: un equipo con "
    "200 supresiones en 30 dias esta en una red que se cae seguido en conjunto, "
    "asi que una caida suya mas probablemente sea parte de ese patron compartido "
    "que una falla propia -- y si el numero es alto en MUCHOS equipos a la vez, "
    "la causa a investigar es comun (energia, enlace, equipo troncal), no cada "
    "equipo por separado. Al reves: un equipo SIN supresiones que cae es mas "
    "sospechoso de problema propio. No cuentes estos numeros como caidas "
    "reportadas ni los sumes a los eventos del incidente. Un evento 'backup_error' de "
    "Protector sobre la MISMA IP que un equipo que Infra vio caer no son dos "
    "problemas: la copia fallo PORQUE el equipo no estaba disponible, y eso se "
    "dice como una sola causa. Al reves tambien importa: un backup_error sin "
    "ninguna caida de red alrededor apunta al origen (credenciales, permisos, "
    "disco, ruta compartida), no a la red. Tambien recibis el historial de "
    "aprendizaje real de cada equipo "
    "involucrado: cuantas veces un reinicio remoto funciono o fallo en ESE "
    "equipo especifico, si ya es un patron cronico conocido, si ya hay un "
    "pendiente/ticket abierto para el. Todos los numeros que recibis ya fueron "
    "contados por codigo, no los inventaste vos -- no agregues cifras que no "
    "esten en el contexto. Si un equipo tiene 'verificacion_en_vivo', es una "
    "comprobacion real hecha en este mismo instante (no historial viejo) -- "
    "dale MAS peso que a una suposicion general basada solo en el patron del "
    "evento (ej.: un evento generico de 'offline' por si solo NO te dice si "
    "es cable, energia o algo puntual del equipo -- pero si la verificacion "
    "en vivo de una impresora muestra que reporta falta de papel, esa es la "
    "causa real, no una adivinanza). Si no hay verificacion en vivo para un "
    "equipo, decilo explicitamente como limitacion en vez de inventar certeza "
    "que no tenes. Tambien recibis 'topologia_confirmada_por_lldp' -- si trae "
    "datos, es un HECHO verificado (descubierto por SNMP/LLDP real contra el "
    "switch, no una suposicion): esos equipos SI comparten fisicamente el "
    "mismo switch padre. Usalo como la evidencia MAS fuerte posible de causa "
    "comun -- mas fuerte que la sola coincidencia de tiempo. Si dice 'sin "
    "coincidencia', NO asumas que comparten switch solo porque cayeron juntos "
    "en el tiempo -- la coincidencia temporal sola es mas debil que topologia "
    "confirmada, decilo como hipotesis, no como hecho. Ademas recibis 4 "
    "fuentes reales mas: 'cambios_de_ip_recientes' (si trae datos, ese equipo "
    "NO fallo, solo cambio de IP -- no lo trates como una caida real); "
    "'incidentes_seguridad_activos' (alertas de Hunter/IDS ya abiertas para "
    "esa IP -- si hay una, considera que el 'offline' puede ser parte de un "
    "incidente de seguridad, no una falla de hardware); "
    "'riesgos_de_auditoria_pendientes' (ej. 'RDP expuesto' ya documentado "
    "antes -- si aplica a la causa raiz, mencionalo, no lo inventes de cero); "
    "'errores_de_puerto_switches' (contadores SNMP reales de errores de "
    "puerto -- un puerto con miles de errores es evidencia fuerte de cable o "
    "puerto fisico dañado, mas fuerte que 'sospechar del cable' sin datos). "
    "Tambien recibis 'estado_wan' (estado real del quorum de internet en "
    "este instante -- si NO dice 'ok', es la causa raiz mas probable de "
    "cualquier caida masiva simultanea de varios equipos, no trates cada uno "
    "como un incidente separado) y 'fallas_y_reboots_recientes_por_nodo' (si "
    "un equipo reinicio hace poco o acumula fallas, un evento de 'offline' "
    "puede ser solo ese reinicio, no algo nuevo -- no lo trates como ataque o "
    "falla critica sin decir que hay un reboot reciente de por medio; si "
    "'en_mantenimiento' es true, ese equipo esta apagado del monitoreo a "
    "proposito -- NUNCA lo trates como urgente ni sugieras reiniciarlo). "
    "Tambien recibis 'razon_calculada_por_guardian' (el motivo EXACTO que "
    "Guardian ya calculo para el estado actual -- ej. 'ping 8.8.8.8 falla', "
    "'DNS no resuelve' -- usalo en vez de adivinar la causa desde el evento "
    "crudo) y 'ultimo_intento_reinicio_automatico' (si 'sin_ruta_de_red' es "
    "true, Guardian ya intento reiniciar por SSH y fallo porque el equipo no "
    "tiene NINGUNA ruta de red -- en ese caso tu recomendacion debe ser "
    "atencion fisica en sitio, NUNCA sugerir reintentar el reinicio por "
    "software, porque ya sabemos que no puede funcionar). "
    "Todas estas son hechos ya verificados por otro sistema -- si dicen "
    "'ninguno', no inventes que si hay. Tu trabajo: dar UNA "
    "hipotesis de causa raiz que "
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


def _build_messages(user_prompt: str, site_context: str = "") -> list[dict]:
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if site_context:
        messages.append({
            "role": "system",
            "content": "Conocimiento real del sitio (usar si es relevante, "
                       "no inventar más allá de esto):\n" + site_context[:BRAIN_SITE_CONTEXT_MAX],
        })
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _call_openai_reasoning(user_prompt: str, site_context: str = "") -> str | None:
    try:
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            return None
        client = OpenAI(api_key=key, timeout=30.0, max_retries=1)
        resp = client.chat.completions.create(
            model=BRAIN_MODEL,
            messages=_build_messages(user_prompt, site_context),
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


def _call_groq_reasoning(user_prompt: str, site_context: str = "") -> str | None:
    try:
        from core import groq_helper
        messages = _build_messages(user_prompt, site_context)
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


def _call_reasoning_model(user_prompt: str, site_context: str = "") -> dict | None:
    raw = _call_openai_reasoning(user_prompt, site_context)
    engine = "openai"
    if raw is None:
        raw = _call_groq_reasoning(user_prompt, site_context)
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
    # Conocimiento operativo del sitio (4 sep 2026 cont.): SITE.md + EQUIPOS.md
    # + notas de visitas en sitio -- antes el cerebro solo veia hechos crudos
    # de la BD, sin las "mañas conocidas" del hotel. Se carga UNA vez por
    # ciclo (es igual para todos los clusters de esta corrida), no por cluster.
    site_context = ""
    try:
        from core import agente_skills
        site_context = (
            agente_skills.load_site_excerpt() + "\n\n" + agente_skills.load_operational_docs()
        ).strip()
    except Exception as e:
        log.debug("brain: no se pudo cargar conocimiento del sitio: %s", e)
    con = sqlite3.connect(KNOWLEDGE_DB)
    # El cursor (last_incident_id) se avanza SIEMPRE al terminar, incluso si un
    # cluster revienta: antes, cualquier excepcion no capturada dejaba el cursor
    # sin mover y la conexion sqlite abierta, asi que el ciclo siguiente volvia a
    # leer los MISMOS eventos y a pagar las MISMAS llamadas al modelo, en bucle,
    # mientras el evento problematico siguiera ahi. Un solo cluster malo podia
    # dejar al cerebro atascado indefinidamente sin que se notara.
    try:
        _procesar_clusters(
            clusters, con, site_context, conclusiones,
        )
    finally:
        try:
            con.close()
        except Exception:
            pass
        _set_state("last_incident_id", str(max_id))
    return conclusiones


def _procesar_clusters(
    clusters: list, con, site_context: str, conclusiones: list,
) -> None:
    """Cuerpo del ciclo, por cluster. Un cluster que falla no tumba a los demas."""
    for cluster in clusters:
      try:
        entities = _cluster_entities(cluster)
        if not _should_escalate_to_llm(cluster, entities):
            continue
        # Máximo MAX_ENTITIES_IN_PROMPT entidades con contexto completo -- un
        # grupo grande (ej. caída masiva de 30 eventos) no necesita el detalle
        # de aprendizaje de cada una para que el modelo entienda la causa común.
        entities_for_context = entities[:MAX_ENTITIES_IN_PROMPT]
        contexto_entidades = {ent["name"]: _entity_learning_context(ent["ip"]) for ent in entities_for_context}
        # Fase 3 (6 sep 2026): comprobación en vivo, no solo historial --
        # acotada a MAX_LIVE_VERIFY para no alargar el ciclo con llamadas de
        # red reales por cada entidad de un cluster grande.
        for ent in entities_for_context[:MAX_LIVE_VERIFY]:
            verif = _verificar_en_vivo(ent)
            if verif:
                contexto_entidades[ent["name"]]["verificacion_en_vivo"] = verif
        # Eventos acotados por CANTIDAD (no por caracteres) -- cortar el JSON a
        # ciegas con [:N] rompe la estructura y le manda al modelo datos
        # corruptos como si fueran "hechos reales" (bug real visto en producción
        # el 4 sep: un grupo de 30 eventos truncado a mitad de un string generó
        # una respuesta también truncada e inutilizable).
        eventos_incluidos = cluster[:MAX_EVENTS_IN_PROMPT]
        omitidos = len(cluster) - len(eventos_incluidos)
        # Fase 5 (6 sep 2026): topología real (LLDP/SNMP, ver shomer_topology.py
        # en network_monitor) en vez de solo coincidencia de tiempo -- si 2+
        # entidades del cluster comparten el mismo switch padre REAL descubierto,
        # se lo decimos explícito al modelo como hecho verificado, no conjetura.
        topologia_confirmada: list[dict] = []
        try:
            from core import shomer_api
            ips_cluster = [ent["ip"] for ent in entities if ent.get("ip")]
            padres = shomer_api.get_topology_parents(ips_cluster)
            por_padre: dict[str, list[str]] = {}
            for ip, info in padres.items():
                por_padre.setdefault(info["parent_ip"], []).append(ip)
            for parent_ip, hijos in por_padre.items():
                if len(hijos) >= 2:
                    info0 = padres[hijos[0]]
                    topologia_confirmada.append({
                        "switch_padre": info0["parent_name"],
                        "equipos_afectados_en_ese_switch": len(hijos),
                    })
        except Exception as e:
            log.debug("brain: topología no disponible para este cluster: %s", e)

        # Fase 6 (7 sep 2026): tres fuentes reales más, mismo principio que la
        # Fase 5 -- hechos ya verificados por otro sistema, no algo que el
        # modelo deba adivinar desde los eventos crudos.
        cambios_de_ip: list[dict] = []
        incidentes_seguridad: list[dict] = []
        riesgos_pendientes: list[dict] = []
        errores_puerto: list[dict] = []
        try:
            from core import shomer_api
            ips_cluster = [ent["ip"] for ent in entities if ent.get("ip")]

            # ¿Alguna entidad "offline" en realidad solo cambió de IP?
            for ent in entities_for_context:
                if not ent.get("ip"):
                    continue
                cambio = shomer_api.get_recent_ip_change(ent["ip"])
                if cambio:
                    cambios_de_ip.append({
                        "equipo": ent["name"],
                        "ip_vieja": cambio.get("ip_vieja"),
                        "ip_nueva": cambio.get("ip_nueva"),
                        "hace": cambio.get("ts"),
                    })

            incidentes_seguridad = [
                {"ip": i["ip"], "alerta": i["alert_signature"], "severidad": i["severity"]}
                for i in shomer_api.get_hunter_incidents(ips_cluster)
            ]

            riesgos_pendientes = [
                {"ip": f["ip"], "hallazgo": f["title"], "severidad": f["severity"]}
                for f in shomer_api.get_pending_audit_findings(ips_cluster)
            ]

            # Errores de puerto solo para switches/routers que SÍ están en este
            # cluster, y solo puertos con errores reales (no inflar con puertos sanos).
            if ips_cluster:
                todos_los_switches = shomer_api.get_switch_port_errors()
                for sw in todos_los_switches:
                    if sw["ip"] not in ips_cluster:
                        continue
                    malos = [p for p in sw["ports"] if p["in_errors"] > 0 or p["out_errors"] > 0]
                    if malos:
                        errores_puerto.append({"switch": sw["name"], "puertos_con_error": malos[:5]})
        except Exception as e:
            log.debug("brain: contexto adicional (Fase 6) no disponible: %s", e)

        # Fase 7 (7 sep 2026): estado real del WAN (quorum en Redis, ver
        # shomer_guardian_server_health.py) y fallas/reboots acumulados por
        # nodo (Redis failures:{ip}/last_reboot:{ip}) -- sin esto el modelo
        # puede confundir "medio sitio cayó porque se cayó el WAN" con N
        # incidentes independientes, o "nodo reinició hace 5 min" con un
        # ataque nuevo.
        estado_wan = "desconocido"
        fallas_nodo: list[dict] = []
        razones_guardian: list[dict] = []
        intentos_reinicio: list[dict] = []
        try:
            from core import shomer_api
            wan = shomer_api.get_wan_status()
            if wan.get("success"):
                estado_wan = wan.get("status") or "desconocido"

            for ent in entities_for_context:
                if not ent.get("ip"):
                    continue
                f = shomer_api.get_node_failures(ent["ip"])
                if (
                    f.get("failures")
                    or f.get("en_mantenimiento")
                    or (f.get("last_reboot_ago") is not None and f["last_reboot_ago"] < 86400)
                ):
                    fallas_nodo.append({
                        "equipo": ent["name"],
                        "fallas_acumuladas": f.get("failures") or 0,
                        "ultimo_reboot_hace_seg": f.get("last_reboot_ago"),
                        "en_mantenimiento": f.get("en_mantenimiento") or False,
                        "ciclos_offline_seguidos": f.get("offline_streak") or 0,
                    })

                # Fase 8 (7 sep 2026): razon real ya calculada por Guardian
                # (classify_health) y resultado del ultimo intento de
                # reinicio automatico -- ver investigacion 7 sep sobre por
                # que la mayoria de los AUTO-REBOOT fallan (sin ruta de red,
                # no es bug de credenciales).
                razon = shomer_api.get_last_status_reason(ent["ip"])
                if razon.get("reason"):
                    razones_guardian.append({
                        "equipo": ent["name"], "estado": razon.get("status"),
                        "razon": razon["reason"],
                    })
                intento = shomer_api.get_last_reboot_attempt(ent["ip"])
                if intento:
                    intentos_reinicio.append({
                        "equipo": ent["name"], "exito": intento.get("ok"),
                        "sin_ruta_de_red": intento.get("sin_ruta_de_red"),
                        "mensaje": intento.get("msg"),
                    })
        except Exception as e:
            log.debug("brain: contexto adicional (Fase 7/8) no disponible: %s", e)

        # Fase 9 (7 sep 2026): contexto del CICLO del poller de Inframonitor.
        # El poller ya decide, con el gateway en la mano, si una tanda de
        # caidas fue una oleada del propio sitio (host_network_blip / caida
        # masiva) y cuantas transiciones suprimio -- pero eso no le llegaba al
        # cerebro, que veia N eventos sueltos y podia concluir "fallo el switch
        # X" cuando en realidad cayeron 20 equipos a la vez con el gateway
        # sano. Ese dato existia en el codigo pero NUNCA se escribia en Redis
        # (NameError silencioso en cada ciclo, corregido en esta misma
        # auditoria), asi que esta es la primera vez que el cerebro puede
        # usarlo. Relevante para la causa raiz aun abierta de las caidas
        # sincronizadas (Sesiones 70-72).
        # Fase 10 (11 sep 2026): lo que Shomer DECIDIO NO avisar de estos equipos.
        # Las reglas de ruido suprimen transiciones que casi siempre son del sitio
        # y no del equipo, lo cual esta bien para no inundar Telegram -- pero dejaba
        # al cerebro razonando sobre una fraccion de lo ocurrido: en Opera, 30 dias
        # = 854 eventos avisados contra 7.592 suprimidos. Sin esto un equipo al que
        # se le callaron 200 caidas se ve igual que uno sano. Va AGREGADO por equipo,
        # no evento por evento: inyectar 7.592 eventos lo haria escalar por volumen.
        eventos_suprimidos: dict | str = "sin datos"
        try:
            from core import shomer_api

            sup = shomer_api.get_suppressed_events(
                [e["ip"] for e in entities_for_context if e.get("ip")], days=30
            )
            if sup:
                eventos_suprimidos = {
                    next((e["name"] for e in entities_for_context if e.get("ip") == ip), ip): {
                        "suprimidos_30d": d["total"],
                        "por_motivo": d["por_motivo"],
                        "ultimo": d["ultimo"],
                    }
                    for ip, d in sup.items()
                }
        except Exception as e:
            log.debug("brain: eventos suprimidos (Fase 10) no disponible: %s", e)

        contexto_ciclo_infra: dict | str = "sin datos del poller"
        try:
            from core import pulse_correlate as _pulse
            from core import shomer_api

            snap = shomer_api.get_infra_snapshot()
            pctx = snap.get("poll_context") or {}
            lblip = snap.get("last_blip") or {}
            if pctx:
                total = pctx.get("total_devices") or 0
                caidos = pctx.get("offline_count") or 0
                es_blip = _pulse.is_blip_poll(pctx)
                blip_cerca = _pulse.blip_recent(pctx, lblip)
                contexto_ciclo_infra = {
                    "equipos_caidos_en_el_mismo_ciclo": caidos,
                    "equipos_monitoreados": total,
                    "gateway": pctx.get("gateway_ip") or "",
                    "estado_gateway_en_ese_momento": pctx.get("gateway_status") or "desconocido",
                    "clasificado_como_corte_transitorio_del_sitio": es_blip,
                    "transiciones_suprimidas_por_esa_regla": pctx.get("blip_skip_count") or 0,
                    "hubo_corte_transitorio_hace_poco": blip_cerca,
                }
                if caidos >= max(2, int(pctx.get("wave_threshold") or 3)):
                    contexto_ciclo_infra["lectura"] = (
                        f"{caidos} de {total} equipos cayeron en el mismo ciclo con el "
                        f"gateway {pctx.get('gateway_status') or 'desconocido'} -- evaluar causa "
                        "compartida (energia, switch troncal, oleada del sitio) antes que "
                        "N fallas independientes"
                    )
                elif es_blip:
                    contexto_ciclo_infra["lectura"] = (
                        "el poller clasifico este ciclo como corte transitorio de red del "
                        "propio Shomer -- NO atribuir la caida al equipo"
                    )
        except Exception as e:
            log.debug("brain: contexto de ciclo Infra (Fase 9) no disponible: %s", e)

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
            "topologia_confirmada_por_lldp": topologia_confirmada or "sin coincidencia -- no asumir switch compartido",
            "cambios_de_ip_recientes": cambios_de_ip or "ninguno -- no asumir que un offline es solo cambio de IP",
            "incidentes_seguridad_activos": incidentes_seguridad or "ninguno",
            "riesgos_de_auditoria_pendientes": riesgos_pendientes or "ninguno",
            "errores_de_puerto_switches": errores_puerto or "ninguno",
            "estado_wan": estado_wan,
            "fallas_y_reboots_recientes_por_nodo": fallas_nodo or "ninguno -- no asumir reinicio reciente",
            "razon_calculada_por_guardian": razones_guardian or "sin datos",
            "ultimo_intento_reinicio_automatico": intentos_reinicio or "ninguno",
            "contexto_del_ciclo_de_inframonitor": contexto_ciclo_infra,
            "eventos_que_shomer_no_aviso": eventos_suprimidos,
        }
        user_prompt = "Datos reales del incidente:\n" + json.dumps(payload, ensure_ascii=False)
        # Fase 2 (6 sep 2026): conocimiento técnico validado (redes/hardware/
        # marcas reales -- ver conocimiento_general.py) relevante a ESTE grupo
        # de equipos específico, no las 212 entradas completas cada vez.
        conocimiento_txt = ""
        dominios_usados: list[str] = []
        try:
            from core import conocimiento_general
            nombres = [ent["name"] for ent in entities]
            conocimiento_txt = conocimiento_general.format_for_prompt(nombres)
            dominios_usados = conocimiento_general.matching_domains(nombres)
        except Exception as e:
            log.debug("brain: conocimiento_general no disponible: %s", e)
        contexto_completo = "\n\n".join(p for p in (site_context, conocimiento_txt) if p)
        result = _call_reasoning_model(user_prompt, site_context=contexto_completo)
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
            "(entities, sources, root_cause, recommendation, urgency, evidence_count, engine, entity_ips, dominios_conocimiento) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entities_str, sources_str,
                str(result.get("causa_raiz") or "")[:1000],
                str(result.get("recomendacion") or "")[:1000],
                urgencia, len(cluster), result.get("_engine") or "", ips_str,
                ",".join(dominios_usados),
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
      except Exception as e:
        # Un cluster que falla se registra y se sigue con el resto: antes,
        # cualquier error aca abortaba el ciclo entero y dejaba sin evaluar
        # los clusters siguientes, ademas de atascar el cursor.
        log.warning("brain: cluster descartado por error: %s", e, exc_info=True)
        continue


# Frases con las que el modelo indica que NO encontró una causa común. Son
# conclusiones válidas y se guardan, pero no justifican interrumpir: avisar
# "no encontré nada" es ruido puro para alguien que atiende tres hoteles.
_SIN_HALLAZGO = (
    "no comparten",
    "no hay evidencia",
    "no hay indicios",
    "sin relacion",
    "sin relación",
    "no existe una causa",
    "no se observa una causa",
    "eventos independientes",
    "son independientes",
    "no estan relacionados",
    "no están relacionados",
)


def aporta_algo(c: dict) -> tuple[bool, str]:
    """¿Esta conclusión merece interrumpir al técnico, o solo repite?

    El cerebro existe para CORRELACIONAR: explicar que varios hechos sueltos son
    uno solo. Cuando no hace eso, su mensaje llega después de que el monitor del
    equipo ya avisó, diciendo lo mismo con otras palabras — y el técnico recibe
    el mismo hecho dos veces.

    Medido sobre las 50 conclusiones reales de Ópera: 32 eran de un solo equipo
    (64%, o sea sin correlación alguna) y 11 concluían que no había relación
    entre los eventos (22%). Eso es la mayor parte de su ruido.

    Se guarda igual en brain_conclusions y sigue consultable; lo único que
    cambia es si interrumpe.
    """
    causa = (c.get("root_cause") or "").strip().lower()
    if any(f in causa for f in _SIN_HALLAZGO):
        return False, "el propio análisis concluye que no hay causa común"

    entidades = [e for e in (c.get("entities") or "").split(",") if e.strip()]
    if len(entidades) < 2:
        return False, (
            "es un solo equipo: el monitor que lo vigila ya avisó, "
            "acá no hay correlación que aportar"
        )

    return True, ""


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
