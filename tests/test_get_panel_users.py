"""17 sep 2026: /auth/users (panel de network_monitor) existe hace tiempo
pero nunca se exponía al chat -- "quién tiene acceso al panel" o "cuántos
usuarios hay" no tenía forma de responderse con datos reales.
"""
from unittest.mock import patch

from core import tools


def test_trae_usuarios_reales_con_su_rol():
    reales = [
        {"id": 23, "username": "admin", "role": "admin"},
        {"id": 163, "username": "root", "role": "admin"},
        {"id": 992, "username": "tecnico1", "role": "operator"},
        {"id": 1474, "username": "mauricio", "role": "operator"},
    ]
    with patch("core.shomer_api.get_panel_users", return_value=reales):
        r = tools.execute("get_panel_users", {})

    assert r["total"] == 4
    assert {"usuario": "mauricio", "rol": "operator"} in r["usuarios"]
    assert {"usuario": "root", "rol": "admin"} in r["usuarios"]


def test_sin_respuesta_del_panel_da_mensaje_honesto_no_error():
    with patch("core.shomer_api.get_panel_users", return_value=[]):
        r = tools.execute("get_panel_users", {})

    assert r["total"] == 0
    assert "mensaje" in r
