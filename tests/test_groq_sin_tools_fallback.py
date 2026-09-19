"""18 sep 2026: el tier gratis de Groq tiene 8,000 tokens/minuto -- el
esquema de las 35 tools ya pesa ~4,400 tokens, más el system prompt y las
reglas de comportamiento (~3,400 más) dejan casi sin espacio para la
conversación real. Verificado en producción: una pregunta real de Juan
Pablo (que ya estaba en fallback por tope de OpenAI) mandó 10,766 tokens a
Groq -- rechazada con 413, el chat terminó en "modo local" total sin
ninguna respuesta de IA.

Además, quitar `tools` del payload NO alcanzaba por sí solo: el propio
texto de `_SYSTEM_BASE` menciona nombres literales de tools por todos
lados (necesario para guiar tool-calling real), y el modelo de Groq
(`openai/gpt-oss-20b`) igual intentaba emitir una llamada a tool aunque no
se le hubiera dado ningún esquema -- Groq rechazaba esa respuesta mal
formada (400 tool_use_failed). De ahí `_SYSTEM_SIN_TOOLS`: un prompt corto
sin nombres de tools para este modo.
"""
from unittest.mock import MagicMock, patch

from core import groq_helper as gh


def test_chat_sin_tools_por_default_no_manda_esquema_de_tools():
    fake_client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.choices[0].message.content = "Todo bien por acá."
    fake_resp.usage = None
    fake_client.chat.completions.create.return_value = fake_resp

    with patch.object(gh, "_get_client", return_value=fake_client), \
         patch.object(gh, "_check_budget_before_call", return_value=None):
        out = gh.chat([{"role": "user", "content": "¿cómo va todo?"}])

    assert out == "Todo bien por acá."
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs


def test_chat_sin_tools_usa_el_prompt_corto_sin_nombres_de_tools():
    fake_client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.choices[0].message.content = "ok"
    fake_resp.usage = None
    fake_client.chat.completions.create.return_value = fake_resp

    with patch.object(gh, "_get_client", return_value=fake_client), \
         patch.object(gh, "_check_budget_before_call", return_value=None):
        gh.chat([{"role": "user", "content": "hola"}])

    kwargs = fake_client.chat.completions.create.call_args.kwargs
    system_msg = kwargs["messages"][0]["content"]
    assert system_msg == gh._SYSTEM_SIN_TOOLS
    # Ningún nombre de tool real debe colarse en lo que se manda a Groq sin tools.
    for nombre_tool in ("get_system_status", "find_infra_device", "get_infra_device"):
        assert nombre_tool not in system_msg


def test_usar_tools_true_sigue_mandando_el_esquema_completo():
    """No romper el caso Groq-como-primario con un tier que sí soporte más
    de 8k TPM -- pasar usar_tools=True debe seguir dando tool-calling real."""
    fake_client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.choices[0].finish_reason = "stop"
    fake_resp.choices[0].message.content = "respuesta con tools"
    fake_resp.usage = None
    fake_client.chat.completions.create.return_value = fake_resp

    with patch.object(gh, "_get_client", return_value=fake_client), \
         patch.object(gh, "_check_budget_before_call", return_value=None):
        gh.chat([{"role": "user", "content": "hola"}], usar_tools=True)

    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "tools" in kwargs
    assert kwargs["tool_choice"] == "auto"


def test_respuesta_vacia_sin_tools_da_mensaje_honesto_no_none():
    fake_client = MagicMock()
    fake_resp = MagicMock()
    fake_resp.choices[0].message.content = ""
    fake_resp.usage = None
    fake_client.chat.completions.create.return_value = fake_resp

    with patch.object(gh, "_get_client", return_value=fake_client), \
         patch.object(gh, "_check_budget_before_call", return_value=None):
        out = gh.chat([{"role": "user", "content": "hola"}])

    assert out and "diagnostico" in out.lower()
