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

_PROMPT_TEMPLATE = (
    "Sos un analista de soporte IT. Te doy candidatos PRE-DETECTADOS (ya agrupados "
    "y contados por código, no por vos) de equipos con eventos repetidos en las "
    "últimas {hours}h en la red de un sitio. Para cada candidato, escribí: qué "
    "está pasando, el impacto probable, y qué debería revisar un técnico. "
    "NO agregues candidatos nuevos — describí únicamente los de la lista. Si un "
    "candidato no es realmente preocupante (ej. parpadeos de 30-60s que se "
    "recuperan solos), decilo así tal cual, no lo infles a algo grave. "
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
            "WHERE ts > datetime('now', ?) ORDER BY ts DESC",
            (f"-{LOOKBACK_HOURS} hours",),
        ).fetchall()
        con.close()
    except Exception as e:
        log.debug("pattern_analysis: memoria no disponible: %s", e)
        return {}
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ts, source, ip, name, event, detail in rows:
        key = name or ip or source
        groups[key].append({"ts": ts, "source": source, "event": event, "detail": detail})
    return groups


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
        candidatos=json.dumps(candidatos_payload, ensure_ascii=False)[:6000],
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
    out = groq_helper._call_groq(messages, max_tokens=1200)

    try:
        cleaned = out.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").lstrip("json").strip()
        hallazgos = json.loads(cleaned)
        if not isinstance(hallazgos, list):
            return []
    except Exception as e:
        log.warning("pattern_analysis: respuesta no es JSON válido (%s): %s", e, out[:200])
        return []

    guardados = []
    con = sqlite3.connect(KNOWLEDGE_DB)
    for h in hallazgos:
        entidad = (h.get("entidad") or "").strip()
        desc = (h.get("patron_descripcion") or "").strip()
        if not desc or entidad not in candidatos:
            log.debug("pattern_analysis: descartado (entidad fuera de candidatos reales): %r", entidad)
            continue
        ocurrencias = len(candidatos[entidad])
        evidencia = json.dumps([e["ts"] for e in candidatos[entidad][:20]], ensure_ascii=False)
        con.execute(
            "INSERT INTO patrones_detectados "
            "(entidad, ocurrencias, patron_descripcion, impacto, sugerencia_tecnica, evidencia) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entidad, ocurrencias, desc,
                (h.get("impacto") or "").strip(),
                (h.get("sugerencia_tecnica") or "").strip(),
                evidencia,
            ),
        )
        guardados.append(h)
    con.commit()
    con.close()
    if guardados:
        log.info("pattern_analysis: %d hallazgo(s) nuevo(s) con evidencia real", len(guardados))
    return guardados


def get_active_patterns(limit: int = 5) -> str:
    """Bloque de texto para inyectar en el chat de OpenAI (L5)."""
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        rows = con.execute(
            "SELECT entidad, ocurrencias, patron_descripcion, impacto, sugerencia_tecnica "
            "FROM patrones_detectados WHERE estado='activo' "
            "ORDER BY fecha_deteccion DESC LIMIT ?",
            (limit,),
        ).fetchall()
        con.close()
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["Patrones detectados (con evidencia real — usar solo si es relevante a la pregunta):"]
    for entidad, ocurrencias, desc, impacto, sug in rows:
        etiqueta = f"{entidad}, {ocurrencias}x" if entidad else "general"
        lines.append(f"- [{etiqueta}] {desc} | Impacto: {impacto} | Sugerencia: {sug}")
    return "\n".join(lines)
