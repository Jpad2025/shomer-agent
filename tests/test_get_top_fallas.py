"""16 sep 2026: verificado en producción -- preguntar "cuál es el equipo
que más se ha caído este mes" contestaba con el ticket crónico más VIEJO
(chronic_tickets, ordenado por opened_at), no el que más veces cayó. El
peor real (Terminal Ingenico .136, 40 caídas en 30 días reales) ni se
mencionaba, porque no existía ninguna tool que contara caídas -- solo
tickets abiertos/cerrados. get_top_fallas cuenta caídas reales de
status_events, que es una pregunta completamente distinta.
"""
import sqlite3

import pytest

from core import shomer_api, tools


@pytest.fixture()
def db_con_caidas(tmp_path, monkeypatch):
    db_path = tmp_path / "network_monitor_test.db"
    con = sqlite3.connect(str(db_path))
    con.executescript(
        """
        CREATE TABLE status_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, ip TEXT NOT NULL, name TEXT DEFAULT '',
            status TEXT NOT NULL
        );
        """
    )
    # Ingenico .136: 3 caídas reales. AP X: 1 caída. Un evento viejo (>30 días) no cuenta.
    con.executemany(
        "INSERT INTO status_events (ts, ip, name, status) VALUES (?,?,?,?)",
        [
            ("datetime('now')", "192.168.0.136", "Terminal Ingenico .136", "offline"),
            ("datetime('now')", "192.168.0.136", "Terminal Ingenico .136", "offline"),
            ("datetime('now')", "192.168.0.136", "Terminal Ingenico .136", "offline"),
            ("datetime('now')", "192.168.0.144", "AP OFC-GERENCIA", "offline"),
        ],
    )
    # Los valores de arriba insertaron el texto literal "datetime('now')" -- corregir con UPDATE real.
    con.execute("UPDATE status_events SET ts = datetime('now')")
    con.execute(
        "INSERT INTO status_events (ts, ip, name, status) VALUES "
        "(datetime('now','-40 days'), '192.168.0.136', 'Terminal Ingenico .136', 'offline')"
    )
    con.commit()
    con.close()

    real_connect = sqlite3.connect

    def _fake_connect(uri_str, *a, **kw):
        if "network_monitor.db" in uri_str:
            return real_connect(str(db_path), *a, **{k: v for k, v in kw.items() if k != "uri"})
        return real_connect(uri_str, *a, **kw)

    monkeypatch.setattr(shomer_api._sq, "connect", _fake_connect)
    yield


def test_get_top_fallas_cuenta_caidas_reales_ordenadas(db_con_caidas):
    r = shomer_api.get_top_fallas(dias=30)
    assert "error" not in r
    assert r["equipos"][0]["ip"] == "192.168.0.136"
    assert r["equipos"][0]["caidas"] == 3
    assert r["equipos"][1]["ip"] == "192.168.0.144"
    assert r["equipos"][1]["caidas"] == 1


def test_get_top_fallas_no_cuenta_caidas_fuera_de_la_ventana(db_con_caidas):
    """La caída de hace 40 días no debe sumar dentro de una ventana de 30."""
    r = shomer_api.get_top_fallas(dias=30)
    ingenico = next(e for e in r["equipos"] if e["ip"] == "192.168.0.136")
    assert ingenico["caidas"] == 3  # no 4


def test_tool_get_top_fallas_mensaje_honesto_sin_datos(tmp_path, monkeypatch):
    db_path = tmp_path / "vacia.db"
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE status_events (id INTEGER PRIMARY KEY, ts TEXT, ip TEXT, name TEXT, status TEXT)"
    )
    con.commit()
    con.close()

    real_connect = sqlite3.connect

    def _fake_connect(uri_str, *a, **kw):
        if "network_monitor.db" in uri_str:
            return real_connect(str(db_path), *a, **{k: v for k, v in kw.items() if k != "uri"})
        return real_connect(uri_str, *a, **kw)

    monkeypatch.setattr(shomer_api._sq, "connect", _fake_connect)
    r = tools.execute("get_top_fallas", {})
    assert r["total"] == 0
    assert "mensaje" in r
