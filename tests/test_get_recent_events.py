"""16 sep 2026: get_recent_events() apuntaba a "event_log" con columnas
"node_ip"/"details" que nunca existieron (las reales de esa tabla son
ip_address/description) -- daba un error de SQL crudo al chat. Peor:
"event_log" está vacía desde siempre (0 filas), reemplazada hace tiempo
por "status_events" -- ni corrigiendo los nombres de columna esta tool
hubiera devuelto nunca datos reales.
"""
import sqlite3

import pytest

from core import shomer_api


@pytest.fixture()
def db_con_eventos(tmp_path, monkeypatch):
    db_path = tmp_path / "network_monitor_test.db"
    con = sqlite3.connect(str(db_path))
    con.executescript(
        """
        CREATE TABLE status_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, source TEXT NOT NULL, ip TEXT NOT NULL,
            name TEXT DEFAULT '', device_type TEXT DEFAULT 'generic',
            prev_status TEXT NOT NULL, status TEXT NOT NULL, reason TEXT DEFAULT ''
        );
        INSERT INTO status_events (ts, source, ip, name, prev_status, status, reason)
        VALUES ('2026-09-15 22:29:33', 'infra', '192.168.0.243', 'Impresora Bixolon',
                'online', 'offline', 'sin respuesta ping');
        """
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


def test_get_recent_events_no_revienta_y_trae_datos_reales(db_con_eventos):
    r = shomer_api.get_recent_events(limit=5)
    assert "error" not in r
    assert r["total"] == 1
    ev = r["events"][0]
    assert ev["ip"] == "192.168.0.243"
    assert ev["event_type"] == "online→offline"
    assert ev["details"] == "sin respuesta ping"
