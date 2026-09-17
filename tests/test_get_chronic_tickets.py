"""16 sep 2026: chronic_tickets.py existe hace tiempo (rastrea problemas
RECURRENTES con recordatorios, ej. 'AP HAB 103 lleva N días cayéndose') pero
nunca se expuso al chat -- ninguna tool lo llamaba. Un técnico preguntando
"qué problemas crónicos hay" o "qué sigue pendiente" no tenía forma de que
el chat le contestara con esta lista real, aunque el dato ya existía.
"""
import importlib
import sqlite3

import pytest

from core import tools


@pytest.fixture()
def con_tickets(temp_db_path):
    from core import chronic_tickets

    importlib.reload(chronic_tickets)
    con = sqlite3.connect(temp_db_path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS chronic_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT, entity_name TEXT, fuente TEXT,
            opened_at TEXT, status TEXT, closed_at TEXT, last_reminder_at TEXT
        )
        """
    )
    con.execute(
        "INSERT INTO chronic_tickets (ip, entity_name, fuente, opened_at, status) "
        "VALUES (?,?,?,?,?)",
        ("192.168.0.243", "Impresora POS Bixolon .243", "watch_infra",
         "2026-09-04 03:22:33", "open"),
    )
    con.execute(
        "INSERT INTO chronic_tickets (ip, entity_name, fuente, opened_at, status, closed_at) "
        "VALUES (?,?,?,?,?,?)",
        ("192.168.0.148", "AP HAB 103", "watch_guardian_nodes",
         "2026-09-01 00:00:00", "closed", "2026-09-02 00:00:00"),
    )
    con.commit()
    con.close()


def test_get_chronic_tickets_solo_trae_los_abiertos(con_tickets):
    r = tools.execute("get_chronic_tickets", {})
    assert r["total"] == 1
    t = r["tickets_abiertos"][0]
    assert "Bixolon" in t["equipo_o_grupo"]
    assert t["ip_principal"] == "192.168.0.243"
    assert t["dias_abierto"] is not None


def test_sin_tickets_abiertos_da_mensaje_honesto(temp_db_path):
    from core import chronic_tickets

    importlib.reload(chronic_tickets)
    r = tools.execute("get_chronic_tickets", {})
    assert r["total"] == 0
    assert "mensaje" in r


def test_quita_el_emoji_del_cerebro_del_nombre(temp_db_path):
    """Los tickets abiertos por el cerebro guardan el nombre con un prefijo
    🧠 -- no debe llegar así de crudo a la respuesta del chat."""
    from core import chronic_tickets

    importlib.reload(chronic_tickets)
    con = sqlite3.connect(temp_db_path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS chronic_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT, entity_name TEXT, fuente TEXT,
            opened_at TEXT, status TEXT, closed_at TEXT, last_reminder_at TEXT
        )
        """
    )
    con.execute(
        "INSERT INTO chronic_tickets (ip, entity_name, fuente, opened_at, status) "
        "VALUES (?,?,?,?,?)",
        ("192.168.0.133", "🧠 SW Amalfi (Piso 1), NVR Hikvision 1", "cerebro",
         "2026-09-06 14:52:41", "open"),
    )
    con.commit()
    con.close()

    r = tools.execute("get_chronic_tickets", {})
    assert not r["tickets_abiertos"][0]["equipo_o_grupo"].startswith("🧠")
