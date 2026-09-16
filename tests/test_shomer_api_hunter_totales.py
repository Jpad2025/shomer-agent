"""16 sep 2026: get_hunter_alerts() no pasaba total_blocks_historico al chat
-- solo tenía alerts_today (solo hoy) y active_blocks (solo lo activo ahora,
excluye lo ya liberado solo). Verificado en Ópera real: 156 bloqueos
históricos contra 118 activos -- "cuántos ataques ha detenido Shomer" no
tenía ningún campo que respondiera eso."""
import pytest

from core import shomer_api


@pytest.fixture()
def stats_reales(monkeypatch):
    def _fake_get(path):
        if path == "/remedies/stats":
            return {
                "success": True, "alerts_today": 3986, "active_blocks": 118,
                "total_blocks_historico": 156, "blocks_by_origin": {"wazuh": 116, "auto": 2, "manual": 0},
            }
        if path.startswith("/remedies/history"):
            return {"history": []}
        return {}

    monkeypatch.setattr(shomer_api, "_get", _fake_get)


def test_get_hunter_alerts_incluye_el_total_historico(stats_reales):
    r = shomer_api.get_hunter_alerts()
    assert r["total_blocks_historico"] == 156
    assert r["active_blocks"] == 118
    assert r["alerts_today"] == 3986
