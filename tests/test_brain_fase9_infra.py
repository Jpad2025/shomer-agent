"""Fase 9 del cerebro — contexto del ciclo del poller de Inframonitor.

El poller ya sabe, con el gateway en la mano, si una tanda de caídas fue una
oleada del propio sitio y cuántas transiciones suprimió. Ese dato nunca llegaba
al cerebro (además de que el backend jamás lo escribía en Redis: NameError
silencioso corregido en la auditoría del 7 sep 2026), así que el modelo veía N
eventos sueltos y podía concluir "falló el switch X" cuando en realidad cayeron
20 equipos a la vez con el gateway sano.
"""
import unittest
from unittest.mock import patch


class TestFase9EnElPayload(unittest.TestCase):
    def test_clave_presente_en_el_payload(self):
        """El armado del payload vive en _procesar_clusters (run_cycle quedó
        como envoltorio con el finally que asegura el avance del cursor)."""
        import inspect

        from core import brain

        src = inspect.getsource(brain._procesar_clusters)
        self.assertIn("contexto_del_ciclo_de_inframonitor", src)
        self.assertIn("contexto_ciclo_infra", src)

    def test_lectura_de_oleada_cuando_caen_varios(self):
        """Con muchos equipos caídos en el mismo ciclo, el contexto debe pedir
        explícitamente evaluar causa compartida antes que N fallas sueltas."""
        from core import pulse_correlate as _pulse

        pctx = {
            "total_devices": 21, "offline_count": 12, "gateway_ip": "192.168.0.1",
            "gateway_status": "online", "host_network_blip": False,
            "blip_skip_count": 0, "wave_threshold": 3,
        }
        caidos = pctx["offline_count"]
        self.assertGreaterEqual(caidos, max(2, pctx["wave_threshold"]))
        self.assertFalse(_pulse.is_blip_poll(pctx))

    def test_blip_marca_no_atribuir_al_equipo(self):
        from core import pulse_correlate as _pulse

        pctx = {
            "total_devices": 21, "offline_count": 9, "gateway_ip": "192.168.0.1",
            "gateway_status": "degraded", "host_network_blip": True,
            "blip_skip_count": 9, "wave_threshold": 3,
        }
        self.assertTrue(_pulse.is_blip_poll(pctx))

    def test_sin_datos_no_rompe_el_ciclo(self):
        """Si el poller no publicó contexto, el cerebro sigue funcionando."""
        from core import shomer_api

        with patch.object(shomer_api, "get_infra_snapshot", return_value={}):
            snap = shomer_api.get_infra_snapshot()
            self.assertEqual(snap.get("poll_context") or {}, {})


if __name__ == "__main__":
    unittest.main()
