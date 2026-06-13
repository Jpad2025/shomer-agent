"""
Registro de cambios realizados via bot.
Permite al developer ver historial y revertir acciones donde aplique.
Integridad del sistema: los cambios se loguean ANTES de ejecutarse donde aplique.
"""
import sqlite3
import json
import logging
from datetime import datetime

from core import shomer_api
from core import device_manager as dm

log = logging.getLogger("shomer-changelog")

DB_PATH = "/app/data/changelog.db"


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS changes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT    NOT NULL,
            user_id   TEXT,
            user_level TEXT,
            action    TEXT    NOT NULL,
            target    TEXT,
            details   TEXT,
            reverse_data TEXT,
            reverted  INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def log_change(user_id, user_level: str, action: str,
               target: str = "", details: str = "",
               reverse_data: dict | None = None) -> int:
    """
    Registra un cambio. Retorna el ID del registro.
    reverse_data: dict con instrucciones para revertir, None si no es reversible.
    """
    ts = datetime.now().isoformat(timespec="seconds")
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO changes (ts, user_id, user_level, action, target, details, reverse_data) "
        "VALUES (?,?,?,?,?,?,?)",
        (ts, str(user_id), user_level, action, target, str(details),
         json.dumps(reverse_data) if reverse_data else None)
    )
    conn.commit()
    change_id = cur.lastrowid
    conn.close()
    log.info("Cambio registrado: id=%d action=%s target=%s by=%s", change_id, action, target, user_level)
    return change_id


def get_recent(limit: int = 10) -> list[tuple]:
    """Retorna los últimos N cambios: (id, ts, user_level, action, target, details, reverted)"""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, ts, user_level, action, target, details, reverted "
        "FROM changes ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return rows


def get_change(change_id: int) -> tuple | None:
    conn = _conn()
    row = conn.execute(
        "SELECT id, ts, action, target, reverse_data, reverted FROM changes WHERE id=?",
        (change_id,)
    ).fetchone()
    conn.close()
    return row


def get_change_full(change_id: int) -> tuple | None:
    """Retorna (id, ts, action, target, reverse_data, reverted, user_id)"""
    conn = _conn()
    row = conn.execute(
        "SELECT id, ts, action, target, reverse_data, reverted, user_id FROM changes WHERE id=?",
        (change_id,)
    ).fetchone()
    conn.close()
    return row


def revert(change_id: int) -> tuple[bool, str]:
    """
    Ejecuta la acción inversa del cambio indicado.
    Solo funciona para acciones con reverse_data definida.
    """
    row = get_change(change_id)
    if not row:
        return False, "Cambio no encontrado"

    _, ts, action, target, reverse_data_json, reverted = row

    if reverted:
        return False, "Este cambio ya fue revertido anteriormente"

    if not reverse_data_json:
        return False, f"La acción `{action}` no es reversible automáticamente"

    try:
        rd = json.loads(reverse_data_json)
    except Exception:
        return False, "Datos de reversión corruptos"

    rtype = rd.get("type")

    try:
        if rtype == "unblock":
            ok, msg = shomer_api.unblock_ip(rd["ip"])
        elif rtype == "block":
            ok, msg = shomer_api.block_ip(rd["ip"])
        elif rtype == "remove_device":
            ok = dm.remove_device(rd["ip"])
            msg = "Equipo eliminado del agente" if ok else "No se encontró el equipo"
        elif rtype == "add_device":
            d = rd["device"]
            dm.add_device(
                d["ip"], d["name"], d.get("user", ""), d.get("password", ""),
                d.get("vendor_hint", ""), d.get("port", 22)
            )
            ok, msg = True, "Equipo re-agregado al agente"
        else:
            return False, f"Tipo de reversión desconocido: {rtype}"
    except Exception as e:
        return False, f"Error ejecutando reversión: {e}"

    if ok:
        conn = _conn()
        conn.execute("UPDATE changes SET reverted=1 WHERE id=?", (change_id,))
        conn.commit()
        conn.close()

    return ok, msg
