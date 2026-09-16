"""15 sep 2026: get_wan_status (la tool que usa el chat libre) leía
wan.get("internet", False) -- esa clave nunca existió en la respuesta real
de /api/wan-status (que devuelve "status": "ok"/"down", no "internet").
Resultado: SIEMPRE caía al default False sin importar el estado real.

Verificado en producción: Juan Pablo preguntó "cómo está el internet hoy"
en el chat de Ópera con el WAN genuinamente sano (verificado con
/api/wan-status en vivo: status=ok, sin eventos de caída en la ventana), y
el bot respondió "el servicio de internet está caído" -- un diagnóstico
falso, no un problema de entrega de mensaje.
"""
import pytest

from core import tools


@pytest.fixture()
def wan_ok(monkeypatch):
    from core import shomer_api

    monkeypatch.setattr(
        shomer_api, "get_wan_status",
        lambda: {"success": True, "status": "ok", "fail_elapsed_sec": None, "last_alert_age_sec": None},
    )


@pytest.fixture()
def wan_down(monkeypatch):
    from core import shomer_api

    monkeypatch.setattr(
        shomer_api, "get_wan_status",
        lambda: {"success": True, "status": "down", "fail_elapsed_sec": 340, "last_alert_age_sec": 12},
    )


def test_wan_ok_reporta_internet_true(wan_ok):
    r = tools.execute("get_wan_status", {})
    assert r["internet"] is True
    assert r["estado_wan"] == "ok"


def test_wan_down_reporta_internet_false_con_segundos(wan_down):
    r = tools.execute("get_wan_status", {})
    assert r["internet"] is False
    assert r["estado_wan"] == "down"
    assert r["segundos_caido"] == 340


def test_sin_respuesta_de_la_api_no_dice_internet_caido_por_defecto(monkeypatch):
    """Si la API no responde nada (None/vacío), no hay que afirmar que el
    internet está caído -- 'unknown' es honesto, 'internet: True por
    default' sería inventar el dato bueno tanto como el malo."""
    from core import shomer_api

    monkeypatch.setattr(shomer_api, "get_wan_status", lambda: None)
    r = tools.execute("get_wan_status", {})
    assert r["estado_wan"] == "unknown"
    assert r["internet"] is False
