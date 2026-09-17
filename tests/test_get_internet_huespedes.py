"""16 sep 2026: get_wan_hotel()/get_wan_hotel_historial() existen hace tiempo
en shomer_api.py -- miden el internet REAL de los huéspedes desde el
gateway/router del hotel, algo completamente distinto de get_wan_status
(que solo mide si el SERVIDOR Shomer navega). Nunca se expusieron al chat:
un técnico preguntando "cómo está el internet de los huéspedes hoy" solo
tenía acceso al estado del servidor, que puede estar sano mientras el
hotel real está caído (u ocurrir al revés).
"""
from unittest.mock import patch

from core import tools


def test_trae_estado_actual_y_resumen_de_historial():
    actual = {
        "wan_arriba": True, "sesiones": 1382, "hotspot": 10,
        "perdida": {"8.8.8.8": 0, "1.1.1.1": 0}, "problemas": [],
    }
    historial = {"lecturas": 29, "ok": 29, "con_problemas": 0}
    with patch("core.shomer_api.get_wan_hotel", return_value=actual), \
         patch("core.shomer_api.get_wan_hotel_historial", return_value=historial):
        r = tools.execute("get_internet_huespedes", {})

    assert r["ahora_mismo"]["internet_arriba"] is True
    assert r["ahora_mismo"]["sesiones_activas"] == 1382
    assert r["historial"]["lecturas"] == 29
    assert r["historial"]["mensaje"] is None


def test_cero_lecturas_no_se_reporta_como_todo_bien():
    """El caso real que motivó el docstring de get_wan_hotel_historial:
    'lecturas: 0' es 'nadie midió', no 'todo estuvo bien' -- si el handler
    lo dejara pasar en silencio, el chat podría decir 'sin problemas'
    cuando en realidad nadie chequeó nada esas horas."""
    with patch("core.shomer_api.get_wan_hotel", return_value={}), \
         patch("core.shomer_api.get_wan_hotel_historial",
               return_value={"lecturas": 0, "ok": 0, "con_problemas": 0}):
        r = tools.execute("get_internet_huespedes", {})

    assert r["historial"]["lecturas"] == 0
    assert "no confirmado" in r["historial"]["mensaje"].lower()


def test_horas_personalizadas_se_pasan_a_la_api():
    with patch("core.shomer_api.get_wan_hotel", return_value={}) as m1, \
         patch("core.shomer_api.get_wan_hotel_historial", return_value={"lecturas": 5}) as m2:
        tools.execute("get_internet_huespedes", {"horas": 6})

    m2.assert_called_once_with(6)
