"""core/memory.py -- historial de chat + topes de gasto de OpenAI.

Este módulo falla en silencio por diseño (cada función atrapa su propia
excepción y sigue). Eso está bien para no tumbar el chat, pero significa que
si alguien rompe check_token_budget() o check_openai_caps(), nada se entera:
o el bot deja de responder pensando que ya gastó el límite sin haberlo
gastado, o al revés, deja de frenar un gasto real de OpenAI. Estas pruebas
existen para que ese tipo de bug se note acá, no en la factura.
"""
import importlib

import pytest


@pytest.fixture()
def mem(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_DB", str(tmp_path / "conversations_test.db"))
    from core import memory as _mem

    importlib.reload(_mem)
    yield _mem


def test_add_message_y_get_history_orden_cronologico(mem):
    mem.add_message("u1", "user", "hola")
    mem.add_message("u1", "assistant", "hola, en qué ayudo")
    mem.add_message("u1", "user", "el AP de recepción está caído")

    hist = mem.get_history("u1")
    assert [h["content"] for h in hist] == [
        "hola", "hola, en qué ayudo", "el AP de recepción está caído",
    ]


def test_get_history_no_mezcla_usuarios(mem):
    mem.add_message("u1", "user", "mensaje de u1")
    mem.add_message("u2", "user", "mensaje de u2")

    assert [h["content"] for h in mem.get_history("u1")] == ["mensaje de u1"]
    assert [h["content"] for h in mem.get_history("u2")] == ["mensaje de u2"]


def test_add_message_mantiene_solo_los_ultimos_max_stored(mem):
    for i in range(mem.MAX_STORED + 10):
        mem.add_message("u1", "user", f"mensaje {i}")

    hist = mem.get_history("u1", limit=mem.MAX_STORED + 10)
    assert len(hist) == mem.MAX_STORED
    assert hist[-1]["content"] == f"mensaje {mem.MAX_STORED + 9}"
    assert hist[0]["content"] == "mensaje 10"


def test_clear_history_borra_solo_ese_usuario(mem):
    mem.add_message("u1", "user", "a")
    mem.add_message("u2", "user", "b")
    mem.clear_history("u1")

    assert mem.get_history("u1") == []
    assert len(mem.get_history("u2")) == 1


def test_get_tokens_today_suma_global_y_filtra_por_proveedor(mem):
    mem.record_tokens(1000, provider="groq")
    mem.record_tokens(500, provider="openai")

    assert mem.get_tokens_today() == 1500
    assert mem.get_tokens_today(provider="groq") == 1000
    assert mem.get_tokens_today(provider="openai") == 500


def test_get_user_tokens_today_aisla_por_usuario(mem):
    mem.record_tokens(300, provider="openai", user_id="u1")
    mem.record_tokens(700, provider="openai", user_id="u2")

    assert mem.get_user_tokens_today("u1", provider="openai") == 300
    assert mem.get_user_tokens_today("u2", provider="openai") == 700


class TestPresupuestoGlobal:
    """check_token_budget() -- si esto se rompe, el bot puede quedarse mudo
    sin haber gastado nada, o seguir respondiendo sin límite."""

    def test_ok_por_debajo_del_aviso(self, mem):
        mem.record_tokens(mem.TOKEN_WARN_DAILY - 1)
        assert mem.check_token_budget() == "ok"

    def test_warn_al_llegar_al_umbral_de_aviso(self, mem):
        mem.record_tokens(mem.TOKEN_WARN_DAILY)
        assert mem.check_token_budget() == "warn"

    def test_exceeded_al_llegar_al_limite_diario(self, mem):
        mem.record_tokens(mem.TOKEN_LIMIT_DAILY)
        assert mem.check_token_budget() == "exceeded"


class TestTopesOpenAI:
    """check_openai_caps() -- el cinturón de seguridad real contra un gasto
    inesperado en la cuenta paga de OpenAI."""

    def test_permitido_por_debajo_de_ambos_topes(self, mem):
        allowed, reason = mem.check_openai_caps("u1")
        assert allowed is True
        assert reason == "ok"

    def test_bloqueado_por_tope_diario_global(self, mem):
        mem.record_tokens(mem.OPENAI_LIMIT_DAILY, provider="openai", user_id="otro")
        allowed, reason = mem.check_openai_caps("u1")
        assert allowed is False
        assert "openai_daily" in reason

    def test_bloqueado_por_tope_diario_del_usuario_aunque_el_global_este_libre(self, mem):
        mem.record_tokens(mem.OPENAI_LIMIT_PER_USER_DAILY, provider="openai", user_id="u1")
        allowed, reason = mem.check_openai_caps("u1")
        assert allowed is False
        assert "openai_user_daily" in reason

    def test_un_usuario_al_tope_no_bloquea_a_otro(self, mem):
        mem.record_tokens(mem.OPENAI_LIMIT_PER_USER_DAILY, provider="openai", user_id="u1")
        allowed, _ = mem.check_openai_caps("u2")
        assert allowed is True


def test_estimate_cost_usd_modelo_desconocido_no_revienta(mem):
    assert mem.estimate_cost_usd(1000, "modelo-que-no-existe") == 0.0
