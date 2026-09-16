"""16 sep 2026: _local_context_struct() (el snapshot que usa el modo local
cuando OpenAI Y Groq fallan a la vez) leía claves de Redis que NUNCA
existieron: "node_status:*" y "wan_status". Las reales, verificadas en vivo
en Ópera: "status:<ip>" (Guardian), "infra:<ip>:status" (Inframonitor) y
"shomer:wan_status". Resultado real en producción: el mensaje de emergencia
decía "Nodos online: 0" y "WAN: ok" SIEMPRE, sin importar la realidad --
justo en el único momento en que se usa, cuando ambos proveedores de IA
están caídos y una falla real de internet del hotel es la explicación más
probable.
"""
import pytest


class _FakeRedis:
    def __init__(self, data: dict):
        self._data = data

    def keys(self, pattern: str):
        import fnmatch
        return [k for k in self._data if fnmatch.fnmatch(k, pattern)]

    def get(self, key: str):
        return self._data.get(key)


@pytest.fixture()
def redis_real(monkeypatch):
    """Simula exactamente las claves reales verificadas en Ópera."""
    data = {
        "status:192.168.0.138": "online",
        "status:192.168.0.210": "offline",
        "status:192.168.0.217": "online",
        "infra:192.168.0.243:status": "offline",
        "infra:192.168.0.111:status": "online",
        "shomer:wan_status": "ok",
        "shomer_maintenance": "0",
    }

    import redis as _redis_mod
    monkeypatch.setattr(_redis_mod, "Redis", lambda **kw: _FakeRedis(data))
    return data


def test_encuentra_nodos_guardian_reales(redis_real):
    from core import llm_router

    d = llm_router._local_context_struct()
    assert "192.168.0.138" in d["online"]
    assert "192.168.0.210" in d["offline"]


def test_encuentra_nodos_infra_reales(redis_real):
    from core import llm_router

    d = llm_router._local_context_struct()
    assert "192.168.0.111" in d["online"]
    assert "192.168.0.243" in d["offline"]


def test_lee_el_wan_de_la_clave_real(redis_real):
    from core import llm_router

    d = llm_router._local_context_struct()
    assert d["wan"] == "ok"


def test_sin_ninguna_clave_no_dice_online_falso(monkeypatch):
    """Si Redis está vacío (o la app recién arrancó), el snapshot debe
    quedar vacío, no reportar '0 online' como si fuera un hecho verificado."""
    import redis as _redis_mod
    from core import llm_router

    monkeypatch.setattr(_redis_mod, "Redis", lambda **kw: _FakeRedis({}))
    d = llm_router._local_context_struct()
    assert d["online"] == []
    assert d["offline"] == []
    assert d["wan"] is None


def test_build_local_digest_no_dice_wan_ok_cuando_no_hay_dato():
    """Caso real: wan=None NO debe traducirse a 'ok' -- eso es justo lo que
    pasó en producción cuando ambos proveedores de IA cayeron a la vez por
    una falla real de internet, y el mensaje decía 'WAN: ok' de todas formas."""
    from core.local_fallback import build_local_digest

    snapshot = {"online": [], "offline": [], "wan": None, "blocked_ips": 0, "failed_backups": []}
    texto = build_local_digest(snapshot, "por que no hay internet")

    assert "desconocido" in texto.lower()
    assert "WAN: `ok`" not in texto


def test_build_local_digest_wan_caida_de_verdad():
    from core.local_fallback import build_local_digest

    snapshot = {"online": [], "offline": ["192.168.0.5"], "wan": "down", "blocked_ips": 0, "failed_backups": []}
    texto = build_local_digest(snapshot, "internet")
    assert "caída" in texto.lower()
