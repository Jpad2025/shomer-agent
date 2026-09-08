"""El cerebro no puede atascarse ni gastar el modelo en bucle por un evento malo.

Bug encontrado en la auditoría del 8 sep 2026: run_cycle() avanzaba el cursor
(last_incident_id) DESPUÉS del bucle de clusters. Cualquier excepción no
capturada dejaba el cursor sin mover y la conexión sqlite abierta, así que el
ciclo siguiente volvía a leer los mismos eventos y a pagar las mismas llamadas
al modelo — en bucle, mientras el evento problemático siguiera ahí.
"""
import inspect
import unittest
from unittest.mock import patch

from core import brain


class TestCursorSiempreAvanza(unittest.TestCase):
    def test_cursor_en_finally(self):
        src = inspect.getsource(brain.run_cycle)
        self.assertIn("finally:", src)
        pos_finally = src.index("finally:")
        pos_cursor = src.index('_set_state("last_incident_id"')
        self.assertGreater(
            pos_cursor, pos_finally,
            "el cursor debe avanzarse dentro del finally, no antes",
        )

    def test_un_cluster_roto_no_tumba_el_ciclo(self):
        """Si un cluster falla, los demás se siguen evaluando."""
        vistos = []

        def entities_explosivo(cluster):
            vistos.append(cluster)
            if len(vistos) == 1:
                raise RuntimeError("cluster veneno")
            return []

        with patch.object(brain, "_cluster_entities", side_effect=entities_explosivo):
            conclusiones = []
            brain._procesar_clusters(
                [[{"id": 1}], [{"id": 2}]], con=None,
                site_context="", conclusiones=conclusiones,
            )
        self.assertEqual(
            len(vistos), 2,
            "el segundo cluster debe evaluarse aunque el primero reviente",
        )

    def test_run_cycle_avanza_cursor_aunque_falle(self):
        eventos = [{"id": 7, "ts": "2026-09-08 06:00:00", "source": "hunter",
                    "entity_ip": "1.2.3.4", "entity_name": "x",
                    "device_type": "", "event": "bloqueo", "detail": "",
                    "severity": "warn"}]
        guardado = {}

        def fake_set_state(k, v):
            guardado[k] = v

        with patch.object(brain, "_bootstrap_if_needed", return_value=False), \
             patch.object(brain, "_new_events", return_value=eventos), \
             patch.object(brain, "_procesar_clusters", side_effect=RuntimeError("boom")), \
             patch.object(brain, "_set_state", side_effect=fake_set_state), \
             patch("sqlite3.connect"):
            with self.assertRaises(RuntimeError):
                brain.run_cycle()

        self.assertEqual(
            guardado.get("last_incident_id"), "7",
            "aunque el procesamiento falle, el cursor debe quedar avanzado "
            "para no reprocesar (y repagar) los mismos eventos",
        )


if __name__ == "__main__":
    unittest.main()
