"""16 sep 2026: no existía ninguna forma de resolver un equipo por nombre o
ubicación -- todas las tools de detalle (get_infra_device, get_printer_status)
piden la IP exacta de entrada, así que el chat tenía que adivinar cuál de la
lista completa de equipos era el correcto.

Caso real en producción: Juan Pablo preguntó "que pasa con la impresora de
recepcion" (192.168.0.240, IMP Recepción WF-M5899, estado real: online) y el
bot respondió con el estado de la Impresora POS Bixolon .243 (192.168.0.243,
esa sí offline) -- un equipo completamente distinto. Con 4 impresoras reales
(recepción, cocina, 2 Bixolon) el modelo eligió mal sin ninguna herramienta
que lo ayudara a resolver el nombre correctamente.
"""
import pytest

from core import shomer_api, tools

_EQUIPOS_REALES = [
    {"ip": "192.168.0.240", "name": "IMP Recepción WF-M5899", "location": "Recepción / Lobby", "status": "online"},
    {"ip": "192.168.0.58", "name": "IMP SCOCINA", "location": "COCINA SCALA", "status": "online"},
    {"ip": "192.168.0.243", "name": "Impresora POS Bixolon .243", "location": "Por confirmar ubicación", "status": "offline"},
    {"ip": "192.168.0.56", "name": "Impresora POS Bixolon .56", "location": "Por confirmar ubicación", "status": "online"},
]


@pytest.fixture()
def equipos(monkeypatch):
    monkeypatch.setattr(shomer_api, "get_infra_devices", lambda: _EQUIPOS_REALES)


def test_recepcion_sin_acento_encuentra_recepcion_con_acento(equipos):
    """El caso real que falló -- Juan Pablo escribió 'recepcion', el equipo
    real se llama 'Recepción' con acento."""
    r = shomer_api.find_infra_devices_by_query("impresora de recepcion")
    assert len(r) == 1
    assert r[0]["ip"] == "192.168.0.240"


def test_no_confunde_recepcion_con_bixolon(equipos):
    r = shomer_api.find_infra_devices_by_query("recepcion")
    ips = [d["ip"] for d in r]
    assert "192.168.0.243" not in ips, "la Bixolon no debe aparecer al buscar recepción"


def test_bixolon_encuentra_las_dos(equipos):
    """Con un nombre que sí coincide con varias, deben aparecer todas --
    es tarea del que llama (o de quien pregunta) desambiguar, no inventar."""
    r = shomer_api.find_infra_devices_by_query("bixolon")
    assert {d["ip"] for d in r} == {"192.168.0.243", "192.168.0.56"}


def test_busqueda_vacia_no_devuelve_todo(equipos):
    assert shomer_api.find_infra_devices_by_query("") == []


def test_tool_find_infra_device_devuelve_el_formato_esperado(equipos):
    r = tools.execute("find_infra_device", {"query": "recepcion"})
    assert r["count"] == 1
    assert r["matches"][0]["ip"] == "192.168.0.240"
    assert r["matches"][0]["status"] == "online"
