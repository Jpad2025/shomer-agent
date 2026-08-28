"""Vigilante de análisis — busca correlaciones reales sobre la memoria unificada
(memoria_central.py), citando evidencia (timestamps reales), no especulación.

Diseño clave: el CONTEO de ocurrencias por entidad lo hace código determinístico
(_candidates_from_memoria), nunca el LLM. El LLM solo describe/sugiere sobre
candidatos ya verificados — si propone una entidad que no está en la lista de
candidatos reales, se descarta. Esto evita que "invente" patrones.

No toca agente_skills.py (eso sigue siendo el lookup exacto trigger→acción).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import defaultdict
from typing import Any, Dict, List

log = logging.getLogger("shomer-pattern-analysis")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")
MEMORIA_DB = os.environ.get("MEMORIA_DB_PATH", "/app/data/memoria.db")
LOOKBACK_HOURS = int(os.environ.get("PATTERN_LOOKBACK_HOURS", "72"))
MIN_OCURRENCIAS = int(os.environ.get("PATTERN_MIN_OCURRENCIAS", "3"))
MAX_CANDIDATES = int(os.environ.get("PATTERN_MAX_CANDIDATES", "8"))
# Sesion 61 cont. 3 (25 jun 2026) -- antes cada corrida insertaba una fila nueva por
# entidad aunque ya hubiera un patron 'activo' identico detectado horas antes (visto
# real en Opera: el mismo flapping de un AP redetectado 6 veces en 24h sin que el
# sistema "recordara" haberlo visto). Si hay un patron activo de la misma entidad
# dentro de esta ventana, se actualiza (sube ocurrencias, refresca fecha) en vez de
# duplicar -- asi el chat (get_active_patterns) no repite el mismo hallazgo como si
# fuera nuevo cada vez.
PATTERN_DEDUP_HOURS = int(os.environ.get("PATTERN_DEDUP_HOURS", "24"))

_PROMPT_TEMPLATE = (
    "Sos un analista de soporte IT. Te doy candidatos PRE-DETECTADOS (ya agrupados "
    "y contados por código, no por vos) de equipos con eventos repetidos en las "
    "últimas {hours}h en la red de un sitio. Para cada candidato, escribí: qué "
    "está pasando, el impacto probable, y qué debería revisar un técnico. "
    "NO agregues candidatos nuevos — describí únicamente los de la lista. Si un "
    "candidato no es realmente preocupante (ej. parpadeos de 30-60s que se "
    "recuperan solos), decilo así tal cual, no lo infles a algo grave. "
    "Sé breve: máximo una frase corta por campo — la respuesta debe entrar "
    "completa dentro del límite de tokens de salida. "
    "Responde ÚNICAMENTE JSON válido, lista de objetos: "
    '{{"entidad": "...", "patron_descripcion": "...", "impacto": "...", '
    '"sugerencia_tecnica": "..."}}.\n\n'
    "Candidatos (entidad → ocurrencias y muestra de eventos):\n{candidatos}"
)


def init_db() -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS patrones_detectados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patron_descripcion TEXT NOT NULL,
                impacto TEXT DEFAULT '',
                sugerencia_tecnica TEXT DEFAULT '',
                fecha_deteccion TEXT DEFAULT (datetime('now')),
                estado TEXT DEFAULT 'activo'
            )
            """
        )
        cols = {r[1] for r in con.execute("PRAGMA table_info(patrones_detectados)").fetchall()}
        if "entidad" not in cols:
            con.execute("ALTER TABLE patrones_detectados ADD COLUMN entidad TEXT DEFAULT ''")
        if "ocurrencias" not in cols:
            con.execute("ALTER TABLE patrones_detectados ADD COLUMN ocurrencias INTEGER DEFAULT 0")
        if "evidencia" not in cols:
            con.execute("ALTER TABLE patrones_detectados ADD COLUMN evidencia TEXT DEFAULT ''")
        try:
            con.execute("ALTER TABLE patrones_detectados ADD COLUMN tendencia TEXT DEFAULT ''")
        except Exception:
            pass  # ya existe
        con.commit()
        con.close()
    except Exception as e:
        log.warning("pattern_analysis init: %s", e)


init_db()


def _candidates_from_memoria() -> Dict[str, List[Dict[str, Any]]]:
    """Agrupa memoria_incidentes por entidad — conteo real, no especulación del LLM."""
    try:
        con = sqlite3.connect(MEMORIA_DB)
        rows = con.execute(
            "SELECT ts, source, entity_ip, entity_name, event, detail FROM memoria_incidentes "
            "WHERE ts > datetime('now', ?) "
            "AND source IN ('guardian', 'infra') "
            "AND event LIKE '%→offline' "
            "ORDER BY ts DESC",
            (f"-{LOOKBACK_HOURS} hours",),
        ).fetchall()
        con.close()
    except Exception as e:
        log.debug("pattern_analysis: memoria no disponible: %s", e)
        return {}
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ts, source, ip, name, event, detail in rows:
        key = name or ip or source
        groups[key].append({"ts": ts, "source": source, "event": event, "detail": detail, "entity_ip": ip})
    return groups


def _tendencia_entidad(entity_ip: str, entity_name: str) -> dict:
    """Compara caídas de esta semana vs la anterior. Detecta degradación."""
    import sqlite3
    try:
        con = sqlite3.connect(MEMORIA_DB)
        # caídas últimos 7 días
        c7 = con.execute(
            "SELECT COUNT(*) FROM memoria_incidentes "
            "WHERE source IN ('guardian','infra') AND event LIKE '%→offline' "
            "AND (entity_ip=? OR entity_name=?) "
            "AND ts > datetime('now','-7 days')",
            (entity_ip, entity_name),
        ).fetchone()[0]
        # caídas semana anterior (día 7 a 14)
        c14 = con.execute(
            "SELECT COUNT(*) FROM memoria_incidentes "
            "WHERE source IN ('guardian','infra') AND event LIKE '%→offline' "
            "AND (entity_ip=? OR entity_name=?) "
            "AND ts > datetime('now','-14 days') AND ts <= datetime('now','-7 days')",
            (entity_ip, entity_name),
        ).fetchone()[0]
        con.close()
    except Exception as e:
        log.debug("tendencia no disponible: %s", e)
        return {"semana_actual": 0, "semana_previa": 0, "tendencia": "n/a"}
    if c14 == 0 and c7 == 0:
        tend = "estable"
    elif c14 == 0:
        tend = "nuevo" if c7 >= 3 else "estable"
    elif c7 > c14 * 1.5:
        tend = "degradando"
    elif c7 < c14 * 0.5:
        tend = "mejorando"
    else:
        tend = "estable"
    return {"semana_actual": c7, "semana_previa": c14, "tendencia": tend}


def _salvage_truncated_json_array(text: str) -> List[Dict[str, Any]]:
    """Recupera los objetos completos de un array JSON `[{...}, {...}, ...]`
    cortado a mitad de camino (típico cuando la salida del LLM choca contra
    max_tokens). Cuenta llaves respetando strings/escapes y corta justo
    después del último `}` de nivel superior antes de intentar json.loads
    de nuevo. Si no hay ningún objeto completo, devuelve []."""
    text = text.strip()
    if not text.startswith("["):
        return []
    depth = 0
    in_string = False
    escape = False
    last_complete_end = None
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_complete_end = i
    if last_complete_end is None:
        return []
    salvaged = text[: last_complete_end + 1] + "]"
    try:
        data = json.loads(salvaged)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def run_pattern_detection_sync() -> List[Dict[str, Any]]:
    """Síncrono a propósito — se llama desde asyncio.to_thread() en el watcher."""
    from core import groq_helper

    groups = _candidates_from_memoria()
    candidatos = {k: v for k, v in groups.items() if len(v) >= MIN_OCURRENCIAS}
    if not candidatos:
        log.info(
            "pattern_analysis: sin candidatos con >= %d ocurrencias en %dh",
            MIN_OCURRENCIAS, LOOKBACK_HOURS,
        )
        return []

    top = sorted(candidatos.items(), key=lambda kv: len(kv[1]), reverse=True)[:MAX_CANDIDATES]
    candidatos_payload = {k: {"ocurrencias": len(v), "eventos": v[:10]} for k, v in top}

    prompt = _PROMPT_TEMPLATE.format(
        hours=LOOKBACK_HOURS,
        # 6000 -> 2500: un solo payload grande + 1200 tokens de salida excedía el
        # tope tokens/min del plan free (429). Con 2500/600 entra sin chocar.
        candidatos=json.dumps(candidatos_payload, ensure_ascii=False)[:2500],
    )
    # _call_groq directo, NO explain() -- explain() está pensado para alertas cortas
    # (tope fijo de 600 tokens para nivel developer) e inyecta system prompt + reglas
    # de comportamiento + apéndice de doc, todo irrelevante para esta tarea de JSON
    # estructurado. Con varios candidatos reales (sitio en producción, no el lab) la
    # respuesta se truncaba a mitad de un string JSON -- json.loads fallaba siempre
    # ahí, nunca en el lab porque solo hay 1-2 candidatos y entra corto igual.
    messages = [
        {
            "role": "system",
            "content": (
                "Sos un analista de soporte IT. Respondé ÚNICAMENTE con JSON válido "
                "(una lista de objetos), sin texto adicional, sin bloques de código "
                "markdown, sin explicación fuera del JSON."
            ),
        },
        {"role": "user", "content": prompt},
    ]
    out = groq_helper._call_groq(messages, max_tokens=600, background=True)

    # background=True: si Groq no pudo (límite del plan free), _call_groq devuelve
    # "" o un mensaje con ⏳/❌/⚠️. Eso NO es JSON: antes se registraba como
    # "respuesta no es JSON válido" (ruido). Ahora se trata como "sin hallazgos".
    if not out or out.lstrip()[:1] in ("⏳", "❌", "⚠️"):
        log.info("pattern_analysis: Groq sin respuesta útil (límite/plan free) — se omite este ciclo")
        return []

    cleaned = out.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").lstrip("json").strip()
    try:
        hallazgos = json.loads(cleaned)
        if not isinstance(hallazgos, list):
            return []
    except Exception as e:
        # Con varios candidatos reales (producción) la respuesta a veces se corta
        # a mitad de un string por el tope de max_tokens -- en vez de descartar
        # todo el lote, rescatamos los objetos que sí quedaron completos antes
        # del corte (ver _salvage_truncated_json_array).
        hallazgos = _salvage_truncated_json_array(cleaned)
        if hallazgos:
            log.info(
                "pattern_analysis: respuesta JSON truncada -- rescatados %d hallazgo(s) completos",
                len(hallazgos),
            )
        else:
            log.warning("pattern_analysis: respuesta no es JSON válido (%s): %s", e, out[:200])
            return []

    guardados = []
    actualizados = 0
    con = sqlite3.connect(KNOWLEDGE_DB)
    for h in hallazgos:
        entidad = (h.get("entidad") or "").strip()
        desc = (h.get("patron_descripcion") or "").strip()
        if not desc or entidad not in candidatos:
            log.debug("pattern_analysis: descartado (entidad fuera de candidatos reales): %r", entidad)
            continue
        ocurrencias = len(candidatos[entidad])
        evidencia = json.dumps([e["ts"] for e in candidatos[entidad][:20]], ensure_ascii=False)
        impacto = (h.get("impacto") or "").strip()
        sugerencia = (h.get("sugerencia_tecnica") or "").strip()
        ent_ip = ""
        for ev in candidatos[entidad]:
            ent_ip = ev.get("entity_ip") or ent_ip
        _tend = _tendencia_entidad(ent_ip, entidad)
        tendencia = _tend["tendencia"]

        existente = con.execute(
            "SELECT id FROM patrones_detectados WHERE entidad=? AND estado='activo' "
            "AND fecha_deteccion > datetime('now', ?) ORDER BY fecha_deteccion DESC LIMIT 1",
            (entidad, f"-{PATTERN_DEDUP_HOURS} hours"),
        ).fetchone()

        if existente:
            con.execute(
                "UPDATE patrones_detectados SET ocurrencias=?, patron_descripcion=?, "
                "impacto=?, sugerencia_tecnica=?, evidencia=?, tendencia=?, fecha_deteccion=datetime('now') "
                "WHERE id=?",
                (ocurrencias, desc, impacto, sugerencia, evidencia, tendencia, existente[0]),
            )
            actualizados += 1
        else:
            con.execute(
                "INSERT INTO patrones_detectados "
                "(entidad, ocurrencias, patron_descripcion, impacto, sugerencia_tecnica, evidencia, tendencia) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entidad, ocurrencias, desc, impacto, sugerencia, evidencia, tendencia),
            )
            guardados.append(h)
    con.commit()
    con.close()
    if guardados or actualizados:
        log.info(
            "pattern_analysis: %d hallazgo(s) nuevo(s), %d actualizado(s) (mismo patrón, no duplicado)",
            len(guardados), actualizados,
        )
    return guardados


def get_pattern_for_entity(entity_ip: str = "", entity_name: str = "") -> dict:
    """Devuelve patrón activo + tendencia de UNA entidad, para enriquecer alertas en vivo."""
    if not entity_ip and not entity_name:
        return {}
    name = entity_name
    if entity_ip and not name:
        try:
            con = sqlite3.connect(MEMORIA_DB)
            row = con.execute(
                "SELECT entity_name FROM memoria_incidentes WHERE entity_ip=? "
                "AND entity_name != '' ORDER BY ts DESC LIMIT 1",
                (entity_ip,),
            ).fetchone()
            con.close()
            if row:
                name = row[0]
        except Exception:
            pass
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        row = con.execute(
            "SELECT entidad, ocurrencias, tendencia, sugerencia_tecnica FROM patrones_detectados "
            "WHERE estado='activo' AND (entidad=? OR entidad=?) "
            "ORDER BY fecha_deteccion DESC LIMIT 1",
            (name or entity_ip, entity_ip),
        ).fetchone()
        con.close()
    except Exception:
        return {}
    if not row:
        return {}
    return {"entidad": row[0], "ocurrencias": row[1], "tendencia": row[2], "sugerencia": row[3]}


def alert_suffix(entity_ip: str = "", entity_name: str = "") -> str:
    """Línea corta para anexar a una alerta de Telegram si la entidad está degradando."""
    p = get_pattern_for_entity(entity_ip, entity_name)
    if not p:
        return ""
    if p.get("tendencia") == "degradando":
        return (
            chr(10)
            + f"⚠️ Patrón: {p['ocurrencias']} caídas/semana y subiendo. {p.get('sugerencia', '')}"
        ).rstrip()
    return ""


def get_active_patterns(limit: int = 5) -> str:
    """Bloque de texto para inyectar en el chat de OpenAI (L5)."""
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        rows = con.execute(
            "SELECT entidad, ocurrencias, patron_descripcion, impacto, sugerencia_tecnica, tendencia "
            "FROM patrones_detectados WHERE estado='activo' "
            "ORDER BY CASE WHEN tendencia='degradando' THEN 0 ELSE 1 END, fecha_deteccion DESC LIMIT ?",
            (limit,),
        ).fetchall()
        con.close()
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["Patrones detectados (con evidencia real — usar solo si es relevante a la pregunta):"]
    for entidad, ocurrencias, desc, impacto, sug, tend in rows:
        flag = " ⚠️DEGRADANDO" if tend == "degradando" else ""
        etiqueta = f"{entidad}, {ocurrencias}x{flag}" if entidad else "general"
        lines.append(f"- [{etiqueta}] {desc} | Impacto: {impacto} | Sugerencia: {sug}")
    return "\n".join(lines)
