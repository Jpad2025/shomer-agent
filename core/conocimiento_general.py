"""conocimiento_general -- base de conocimiento tecnico VALIDADO, generico
para cualquier cliente (no especifico de Hotel Opera).

Distinto de agente_skills.py (aprendizaje PROPIO de este sitio, por equipo
especifico: "el AP .140 se arreglo con reinicio 4 veces"). Esto es lo que
cualquier ingeniero de soporte con experiencia ya sabe de redes, hardware,
software y sistemas de hospitalidad -- util desde el primer dia en un sitio
nuevo, antes de que acumule su propio historial.

Fuentes (sesion 81 cont., 4 sep 2026, investigado con Juan Pablo antes de
sembrar -- no inventado):
  - CompTIA Network+ (N10-009): cableado, switching, WAN, WiFi, metodologia
  - CompTIA A+ Core 1 (220-1201): hardware, dispositivos moviles, nube/virt.
  - CompTIA A+ Core 2 (220-1202): sistemas operativos, seguridad, software
  - Industria hotelera (Shiji Insights, BringIT): fallas reales de
    integracion PMS<->POS -- "conectado" en pantalla no implica que el flujo
    de datos real funcione, hay que probar con una transaccion real
  - Comunidad tecnica (foros MikroTik/UniFi): incompatibilidades documentadas
    reales al mezclar esas marcas (VLAN/trunk)

Cada regla queda con `aprobado_por` -- nada entra como "validado" sin
aprobacion humana, para que la IA nunca "aprenda" algo falso como si fuera
universal. El campo `confianza` sube/baja con el tiempo segun se confirme o
no en la practica (mecanismo de retroalimentacion -- fase futura, no
implementada aun: hoy solo se siembra y se puede consultar).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Optional

log = logging.getLogger("shomer-conocimiento-general")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")


def init_db_teoria() -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS conocimiento_teoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dominio TEXT NOT NULL,
                concepto TEXT NOT NULL,
                explicacion TEXT NOT NULL,
                relevancia_diagnostica TEXT NOT NULL,
                fuente TEXT NOT NULL,
                aprobado_por TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_teoria_dominio ON conocimiento_teoria(dominio)"
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("conocimiento_teoria init: %s", e)


def init_db() -> None:
    try:
        con = sqlite3.connect(KNOWLEDGE_DB)
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS conocimiento_general (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dominio TEXT NOT NULL,
                patron TEXT NOT NULL,
                causa_probable TEXT NOT NULL,
                recomendacion TEXT NOT NULL,
                fuente TEXT NOT NULL,
                confianza TEXT DEFAULT 'alta',
                veces_confirmado INTEGER DEFAULT 0,
                veces_refutado INTEGER DEFAULT 0,
                aprobado_por TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_conocimiento_dominio ON conocimiento_general(dominio)"
        )
        con.commit()
        con.close()
    except Exception as e:
        log.warning("conocimiento_general init: %s", e)


# ── Semilla -- conocimiento validado, generico, sin nada especifico de Opera ──


# ── Semilla -- conocimiento validado, generico, sin nada especifico de Opera ──
#
# 12 sep 2026: este contenido (263 conceptos de teoria + 173 reglas, ~5000
# lineas) vivia como literales de Python en este archivo. Es CONTENIDO
# (texto validado con fuentes citadas), no logica -- separarlo a JSON deja
# el codigo que de verdad hace algo (abajo: sembrar, consultar, formatear
# para el prompt) legible sin desplazarse por miles de lineas de texto, y
# permite revisar/editar el contenido sin tocar sintaxis de Python.
#
# La ruta es relativa a este archivo (Path(__file__).parent), no al
# directorio de trabajo del proceso que lo importa -- el agente arranca
# desde distintos lugares segun el contexto (contenedor, prueba, consola).

import json as _json
from pathlib import Path as _Path

_DATA_DIR = _Path(__file__).resolve().parent / "data"


def _cargar_json(nombre: str) -> list[dict[str, str]]:
    """Sin el archivo, devuelve vacio y lo dice -- no rompe el arranque del
    agente por un problema de contenido, que es reparable, no una falla de
    monitoreo real."""
    ruta = _DATA_DIR / nombre
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception as e:
        log.warning("conocimiento_general: no se pudo cargar %s: %s", ruta, e)
        return []


_SEED_TEORIA: list[dict[str, str]] = _cargar_json("conocimiento_teoria.json")
_SEED_RULES: list[dict[str, str]] = _cargar_json("conocimiento_reglas.json")

def seed_if_empty(aprobado_por: str = "") -> int:
    """Siembra la tabla SOLO si está vacía -- idempotente, seguro de llamar
    en cada arranque sin duplicar filas."""
    init_db()
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        count = con.execute("SELECT COUNT(*) FROM conocimiento_general").fetchone()[0]
        if count > 0:
            return 0
        for r in _SEED_RULES:
            con.execute(
                "INSERT INTO conocimiento_general "
                "(dominio, patron, causa_probable, recomendacion, fuente, aprobado_por) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["dominio"], r["patron"], r["causa_probable"], r["recomendacion"],
                 r["fuente"], aprobado_por),
            )
        con.commit()
        log.info("conocimiento_general: sembradas %d reglas iniciales", len(_SEED_RULES))
        return len(_SEED_RULES)
    finally:
        con.close()


def list_rules(dominio: str = "", limit: int = 200) -> list[dict[str, Any]]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    try:
        if dominio:
            rows = con.execute(
                "SELECT * FROM conocimiento_general WHERE dominio=? ORDER BY id LIMIT ?",
                (dominio, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM conocimiento_general ORDER BY dominio, id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def dominios() -> list[str]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        rows = con.execute(
            "SELECT DISTINCT dominio FROM conocimiento_general ORDER BY dominio"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def seed_teoria_if_empty(aprobado_por: str = "") -> int:
    """Siembra la tabla de teoría SOLO si está vacía -- idempotente."""
    init_db_teoria()
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        count = con.execute("SELECT COUNT(*) FROM conocimiento_teoria").fetchone()[0]
        if count > 0:
            return 0
        for t in _SEED_TEORIA:
            con.execute(
                "INSERT INTO conocimiento_teoria "
                "(dominio, concepto, explicacion, relevancia_diagnostica, fuente, aprobado_por) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t["dominio"], t["concepto"], t["explicacion"],
                 t["relevancia_diagnostica"], t["fuente"], aprobado_por),
            )
        con.commit()
        log.info("conocimiento_teoria: sembrados %d conceptos iniciales", len(_SEED_TEORIA))
        return len(_SEED_TEORIA)
    finally:
        con.close()


def list_teoria(dominio: str = "", limit: int = 300) -> list[dict[str, Any]]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    try:
        if dominio:
            rows = con.execute(
                "SELECT * FROM conocimiento_teoria WHERE dominio=? ORDER BY id LIMIT ?",
                (dominio, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM conocimiento_teoria ORDER BY dominio, id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def dominios_teoria() -> list[str]:
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        rows = con.execute(
            "SELECT DISTINCT dominio FROM conocimiento_teoria ORDER BY dominio"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


# ── Fase 2 (sesión 81 cont., 6 sep 2026): conectar al razonamiento del cerebro ──
# Mapa palabra clave -> dominio, basado en los nombres REALES de equipos que
# ya existen en Ópera (ver infra_devices) -- "SW " para switches, "AP " para
# UniFi, "Bixolon"/"Hikvision"/"ZK"/"Ingenico" para las marcas confirmadas en
# el inventario real. Determinístico por diseño (código decide qué dominios
# aplican, no el LLM) -- mismo principio anti-alucinación que pattern_analysis.py.
_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mikrotik":                 ("mikrotik",),
    "wan":                      ("mikrotik", "router", "gateway"),
    "switching":                ("sw ", "sw-", "sw1", "sw2", "sw3", "switch"),
    "cableado":                 ("sw ", "switch", "ap "),
    "unifi":                    ("ap ", "unifi"),
    "wifi":                     ("ap ",),
    "impresoras_termicas_pos":  ("bixolon", "pos"),
    "impresoras_inkjet":        ("epson", "wf-", "workforce"),
    "impresoras":               ("imp ", "impresora"),
    "hikvision":                ("hikvision", "nvr"),
    "camaras_cctv":             ("camara", "cámara", "nvr"),
    "zkteco":                   ("zk", "biometrico", "biométrico"),
    "control_acceso":           ("biometrico", "biométrico", "control de acceso"),
    "ingenico":                 ("ingenico", "terminal pago", "datafono", "datáfono"),
    "hardware":                 ("srv", "servidor"),
    "windows_ad":               ("srvad", "dominio"),
    "bases_datos":              ("srvzeus", "pms", "base de datos"),
    "pms_integracion":          ("pms", "zeus", "pos"),
    "sistemas_operativos":      ("srv", "servidor", "laptop", "notebook", "workstation"),
    "dispositivos_moviles":     ("tablet", "celular", "móvil", "movil", "smartphone"),
}


def _normalizar_texto(s: str) -> str:
    """Sin acentos y en minúsculas -- igual que shomer_api.py, para que
    "lenta"/"lentitud" o "caído"/"caido" no dependan de tildes exactas."""
    import unicodedata
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


_PALABRAS_VACIAS_SINTOMA = frozenset({
    "de", "del", "la", "el", "los", "las", "que", "con", "sin", "en", "un",
    "una", "esta", "estan", "como", "pasa", "hay", "tiene", "todo", "toda",
    "todos", "todas", "por", "para", "and", "the", "sera", "será", "que",
    "no", "se", "puso", "momento", "otro", "algun", "algún", "reviso",
})


def _reglas_por_similitud_texto(texto: str, con: sqlite3.Connection,
                                 excluir_ids: set[int], max_n: int) -> list[dict]:
    """16 sep 2026: _matching_domains solo reconoce nombres de marca/equipo
    ("switch", "bixolon", "ingenico") -- una pregunta sin marca como "toda
    la red se puso lenta y no hay nada caído en el panel" no matcheaba
    NINGÚN dominio, aunque existe una regla casi idéntica en 'switching'
    ("Toda la red se pone lenta de golpe sin ningún equipo reportado como
    caído -> loop de red"). Verificado en producción: esa pregunta exacta
    hizo que el chat ignorara la regla real y culpara a un AP caído sin
    relación, contradiciendo la propia premisa de la pregunta. Este
    complemento matchea por PALABRAS del síntoma contra el campo `patron`
    de cada regla, no solo por nombre de marca -- determinístico igual,
    solo que compara contra el texto libre en vez de una lista fija de
    keywords."""
    q = _normalizar_texto(texto)
    palabras_q = {p for p in q.split() if len(p) >= 4 and p not in _PALABRAS_VACIAS_SINTOMA}
    if not palabras_q:
        return []
    candidatas = con.execute(
        "SELECT * FROM conocimiento_general WHERE id NOT IN "
        f"({','.join('?' * len(excluir_ids)) if excluir_ids else '-1'})",
        tuple(excluir_ids),
    ).fetchall()
    puntuadas = []
    for row in candidatas:
        r = dict(row)
        patron_norm = _normalizar_texto(r.get("patron", ""))
        palabras_r = {p for p in patron_norm.split() if len(p) >= 4}
        overlap = len(palabras_q & palabras_r)
        if overlap >= 2:
            puntuadas.append((overlap, r))
    puntuadas.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in puntuadas[:max_n]]


def _matching_domains(entity_names: list[str], strict: bool = False) -> set[str]:
    """`strict=True` no aplica el fallback a 'metodologia' -- pensado para
    texto libre de chat (7 sep 2026), donde un saludo o pregunta no técnica
    no debe inyectar conocimiento igual (costo de tokens desperdiciado). El
    fallback default (strict=False) sigue igual para cerebro: un cluster de
    equipos siempre es una situación técnica real, así que algo genérico es
    mejor que nada."""
    texto = " | ".join((n or "").lower() for n in entity_names)
    dominios_match = {
        dominio for dominio, kws in _DOMAIN_KEYWORDS.items()
        if any(kw in texto for kw in kws)
    }
    if strict:
        return dominios_match
    return dominios_match or {"metodologia"}


def matching_domains(entity_names: list[str]) -> list[str]:
    """Wrapper público -- para que brain.py guarde qué dominios se usaron en
    una conclusión y pueda retroalimentar la confianza cuando se confirme."""
    return sorted(_matching_domains(entity_names))


def registrar_confirmacion(dominios: list[str]) -> int:
    """Fase 4 (6 sep 2026): cerrar el ciclo de aprendizaje -- cuando un
    ticket que el cerebro abrió se cierra (se confirmó que la causa era
    correcta), sube veces_confirmado en las reglas de esos dominios. No es
    atribución perfecta (no sabemos cuál regla EXACTA usó el LLM, solo qué
    dominios se le ofrecieron), pero es una señal real y determinística,
    no una suposición."""
    if not dominios:
        return 0
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        placeholders = ",".join("?" * len(dominios))
        cur = con.execute(
            f"UPDATE conocimiento_general SET veces_confirmado = veces_confirmado + 1, "
            f"updated_at = datetime('now') WHERE dominio IN ({placeholders})",
            dominios,
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def registrar_refutacion(dominios: list[str]) -> int:
    """Contraparte de registrar_confirmacion -- para cuando se sepa que la
    causa que se dio NO era la correcta (ej. el ticket se reabre pronto)."""
    if not dominios:
        return 0
    con = sqlite3.connect(KNOWLEDGE_DB)
    try:
        placeholders = ",".join("?" * len(dominios))
        cur = con.execute(
            f"UPDATE conocimiento_general SET veces_refutado = veces_refutado + 1, "
            f"updated_at = datetime('now') WHERE dominio IN ({placeholders})",
            dominios,
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def find_relevant(entity_names: list[str], max_reglas: int = 6, max_teoria: int = 4,
                   strict: bool = False) -> tuple[list[dict], list[dict]]:
    """Reglas + teoría relevante para un grupo de entidades, por nombre.
    Determinístico (coincidencia de palabra clave), nunca decidido por el LLM.

    16 sep 2026: se agrega un segundo paso de matching por SÍNTOMO (palabras
    del texto contra el campo `patron` de cada regla), porque el match por
    dominio/marca se queda ciego ante preguntas sin nombre de equipo. Ver
    _reglas_por_similitud_texto -- caso real que lo motivó."""
    dominios_match = _matching_domains(entity_names, strict=strict)
    con = sqlite3.connect(KNOWLEDGE_DB)
    con.row_factory = sqlite3.Row
    try:
        reglas: list[dict] = []
        teoria: list[dict] = []
        for d in dominios_match:
            reglas.extend(dict(r) for r in con.execute(
                "SELECT * FROM conocimiento_general WHERE dominio=? LIMIT 3", (d,)
            ).fetchall())
            teoria.extend(dict(r) for r in con.execute(
                "SELECT * FROM conocimiento_teoria WHERE dominio=? LIMIT 2", (d,)
            ).fetchall())
        if len(reglas) < max_reglas:
            texto = " | ".join((n or "") for n in entity_names)
            ids_ya = {r["id"] for r in reglas}
            extra = _reglas_por_similitud_texto(
                texto, con, ids_ya, max_reglas - len(reglas)
            )
            reglas.extend(extra)
        return reglas[:max_reglas], teoria[:max_teoria]
    finally:
        con.close()


def format_for_prompt(entity_names: list[str], strict: bool = False) -> str:
    """Bloque de texto compacto para inyectar en el prompt del cerebro --
    solo lo relevante a las entidades del cluster actual, no las 212 enteras."""
    reglas, teoria = find_relevant(entity_names, strict=strict)
    if not reglas and not teoria:
        return ""
    partes = ["Conocimiento técnico validado relevante (usar si aplica, no forzar si no encaja):"]
    for r in reglas:
        partes.append(
            f"- [regla/{r['dominio']}] {r['patron']} → {r['causa_probable']} → {r['recomendacion']}"
        )
    for t in teoria:
        partes.append(
            f"- [teoría/{t['dominio']}] {t['concepto']}: {t['relevancia_diagnostica']}"
        )
    return "\n".join(partes)


init_db()
init_db_teoria()
