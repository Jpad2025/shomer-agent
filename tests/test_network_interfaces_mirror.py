"""16 sep 2026: get_network_interfaces caía a "enp4s0" como interfaz espejo
por defecto cuando el sitio no tenía base.mirror_interface configurado --
ese nombre es específico de una máquina, nunca debería ser un default
genérico (norma B.1: no hardcodear topología de cliente). Verificado en
Ópera: la interfaz espejo real de Suricata es enx9c69d33bc55f (confirmada
en su propio suricata.yaml, y activa), pero el .env nunca tuvo el config
puesto -- el default "enp4s0" no coincidía con ninguna interfaz real, así
que "mirror_up" daba False con Suricata funcionando perfectamente.
"""
import pytest

from core import tools


@pytest.fixture()
def interfaces_reales(monkeypatch):
    from core import shomer_api

    monkeypatch.setattr(
        shomer_api, "get_interfaces",
        lambda: [
            {"name": "eno1", "state": "UP"},
            {"name": "enx9c69d33bc55f", "state": "UP"},
            {"name": "docker0", "state": "DOWN"},
        ],
    )


def test_sin_config_no_inventa_una_interfaz(interfaces_reales, monkeypatch):
    from core import shomer_api

    monkeypatch.setattr(shomer_api, "get_config", lambda k: None)
    r = tools.execute("get_network_interfaces", {})
    assert r["mirror_nic"] == "sin configurar"
    assert r["mirror_up"] is None, "sin dato no debe afirmarse ni True ni False"


def test_con_config_real_reporta_arriba_correctamente(interfaces_reales, monkeypatch):
    from core import shomer_api

    monkeypatch.setattr(shomer_api, "get_config", lambda k: "enx9c69d33bc55f")
    r = tools.execute("get_network_interfaces", {})
    assert r["mirror_nic"] == "enx9c69d33bc55f"
    assert r["mirror_up"] is True


def test_interfaz_configurada_que_no_existe_da_false_no_none(interfaces_reales, monkeypatch):
    from core import shomer_api

    monkeypatch.setattr(shomer_api, "get_config", lambda k: "enp4s0")
    r = tools.execute("get_network_interfaces", {})
    assert r["mirror_up"] is False
