"""17 sep 2026: verificado en producción -- preguntar "el hunter bloqueó la
8.8.8.8, es una amenaza real?" contestó "sí, amenaza real" con la misma
confianza que un bloqueo activo confirmado, aunque esa IP NO está bloqueada
ahora (se liberó sola hace días) y el propio registro la clasifica como
riesgo 'medio, confirmar en panel' -- no como amenaza confirmada. No existía
ninguna tool para consultar el historial real de UNA ip puntual.
"""
from unittest.mock import patch

from core import tools


def test_ip_bloqueada_ahora_y_con_historial():
    with patch("core.shomer_api._get") as mock_get:
        def side_effect(path):
            if "check_blocked" in path:
                return {"success": True, "ip": "158.51.78.4", "blocked": True, "external": True}
            if "history" in path:
                return {"history": [
                    {"ip": "158.51.78.4", "alert_signature": "GPL VOIP SIP INVITE message flooding",
                     "alert_human_risk_label": "MEDIO", "blocked_at": "2026-09-17T03:47:15+00:00"},
                ]}
            return None
        mock_get.side_effect = side_effect

        r = tools.execute("check_ip_hunter", {"ip": "158.51.78.4"})

    assert r["bloqueada_ahora"] is True
    assert r["veces_bloqueada_historico"] == 1


def test_ip_no_bloqueada_ahora_pero_con_historial_pasado():
    """El caso real: 8.8.8.8 se liberó sola hace días -- bloqueada_ahora debe
    ser False aunque haya historial, para no decir 'amenaza real' de algo
    que ya no está activo."""
    with patch("core.shomer_api._get") as mock_get:
        def side_effect(path):
            if "check_blocked" in path:
                return {"success": True, "ip": "8.8.8.8", "blocked": False, "external": True}
            if "history" in path:
                return {"history": [
                    {"ip": "8.8.8.8", "alert_signature": "SURICATA STREAM ESTABLISHED SYNACK resend",
                     "alert_human_risk_label": "MEDIO",
                     "blocked_at": "2026-09-07T22:11:33+00:00",
                     "unblocked_at": "2026-09-08T11:46:04+00:00"},
                ]}
            return None
        mock_get.side_effect = side_effect

        r = tools.execute("check_ip_hunter", {"ip": "8.8.8.8"})

    assert r["bloqueada_ahora"] is False
    assert r["veces_bloqueada_historico"] == 1
    assert r["ultimos_bloqueos"][0]["alert_human_risk_label"] == "MEDIO"


def test_ip_sin_ningun_historial():
    with patch("core.shomer_api._get") as mock_get:
        def side_effect(path):
            if "check_blocked" in path:
                return {"success": True, "ip": "1.2.3.4", "blocked": False, "external": True}
            if "history" in path:
                return {"history": []}
            return None
        mock_get.side_effect = side_effect

        r = tools.execute("check_ip_hunter", {"ip": "1.2.3.4"})

    assert r["veces_bloqueada_historico"] == 0
    assert r["ultimos_bloqueos"] == []


def test_ip_invalida_da_error_claro():
    r = tools.execute("check_ip_hunter", {"ip": "no-es-una-ip"})
    assert "error" in r
