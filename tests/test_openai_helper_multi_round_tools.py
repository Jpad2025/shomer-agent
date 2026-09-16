"""16 sep 2026: el ciclo de function-calling ejecutaba UNA sola ronda de
tools y forzaba texto final -- aunque el propio system prompt dice "nunca
encadenes más de 2 tools", el código solo permitía 1. Verificado en
producción: "¿cuánto tráfico tiene el switch principal?" necesita 2 pasos
reales (encontrar el switch por nombre, después consultar su SNMP) y el
modelo quedaba a mitad de camino -- contestaba "voy a consultarlo" sin
haber podido dar el segundo paso.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core import openai_helper


def _tool_call(id_, name, args):
    return SimpleNamespace(
        id=id_,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _resp(finish_reason, content="", tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content, tool_calls=tool_calls),
        )],
        usage=None,
    )


@pytest.fixture()
def fake_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(openai_helper, "_get_client", lambda: client)
    monkeypatch.setattr(openai_helper, "_tools", MagicMock(
        TOOLS=[], execute=lambda name, args: {"ok": True, "tool": name, "args": args}
    ))
    return client


def test_dos_rondas_de_tools_se_completan(fake_client):
    """find_infra_device -> get_infra_snmp -> respuesta final. El caso real
    que fallaba: quedarse a mitad de camino en la primera ronda."""
    respuestas = [
        _resp("tool_calls", tool_calls=[_tool_call("1", "find_infra_device", {"query": "switch principal"})]),
        _resp("tool_calls", tool_calls=[_tool_call("2", "get_infra_snmp", {"ip": "192.168.0.212"})]),
        _resp("stop", content="El switch tiene 3 puertos activos y 12 Mbps de tráfico."),
    ]
    fake_client.chat.completions.create.side_effect = respuestas

    out = openai_helper.chat([{"role": "user", "content": "¿cuánto tráfico tiene el switch principal?"}])

    assert out == "El switch tiene 3 puertos activos y 12 Mbps de tráfico."
    assert fake_client.chat.completions.create.call_count == 3


def test_una_sola_ronda_sigue_funcionando(fake_client):
    """Caso común: una sola tool alcanza -- no debe forzar una segunda
    ronda innecesaria si el modelo ya respondió texto."""
    respuestas = [
        _resp("tool_calls", tool_calls=[_tool_call("1", "get_wan_status", {})]),
        _resp("stop", content="El internet está bien."),
    ]
    fake_client.chat.completions.create.side_effect = respuestas

    out = openai_helper.chat([{"role": "user", "content": "¿cómo está el internet?"}])

    assert out == "El internet está bien."
    assert fake_client.chat.completions.create.call_count == 2


def test_no_encadena_una_tercera_ronda(fake_client):
    """Tope real de 2 rondas: si el modelo pide una tercera tool, la
    tercera llamada debe forzar texto (use_tools=False), nunca una cuarta."""
    respuestas = [
        _resp("tool_calls", tool_calls=[_tool_call("1", "tool_a", {})]),
        _resp("tool_calls", tool_calls=[_tool_call("2", "tool_b", {})]),
        _resp("stop", content="Respuesta final tras el tope de 2 rondas."),
    ]
    fake_client.chat.completions.create.side_effect = respuestas

    out = openai_helper.chat([{"role": "user", "content": "pregunta compleja"}])

    assert out == "Respuesta final tras el tope de 2 rondas."
    assert fake_client.chat.completions.create.call_count == 3
    # La 3ra llamada (la que fuerza el cierre) no debe pedir tools.
    tercer_llamado_kwargs = fake_client.chat.completions.create.call_args_list[2].kwargs
    assert "tools" not in tercer_llamado_kwargs


def test_sin_tool_calls_devuelve_texto_directo(fake_client):
    respuestas = [_resp("stop", content="Hola, en qué ayudo.")]
    fake_client.chat.completions.create.side_effect = respuestas

    out = openai_helper.chat([{"role": "user", "content": "hola"}])

    assert out == "Hola, en qué ayudo."
    assert fake_client.chat.completions.create.call_count == 1
