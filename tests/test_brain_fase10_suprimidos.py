"""Fase 10 — el cerebro ve también lo que Shomer decidió NO avisar.

Las reglas de ruido (blip de gateway, caída masiva) suprimen a propósito
transiciones que casi siempre son del sitio y no del equipo. Está bien para no
inundar Telegram, pero dejaba al cerebro razonando sobre una fracción de lo
ocurrido: en Ópera, 30 días = **854 eventos avisados contra 7.592 suprimidos**.

Sin este contexto, un equipo al que se le callaron 202 caídas en el mes se ve
idéntico a uno sano, y la conclusión sale mal por falta de datos, no por mal
criterio.

Va AGREGADO por equipo y no evento por evento a propósito: inyectar 7.592
eventos en la bitácora haría escalar al modelo por puro volumen — justo el
problema de costo/ruido que evita _should_escalate_to_llm().
"""
import sqlite3
import unittest
from unittest.mock import patch

from core import brain, shomer_api


class TestFase10EnElCerebro(unittest.TestCase):
    def test_clave_en_el_payload(self):
        import inspect

        src = inspect.getsource(brain._procesar_clusters)
        self.assertIn("eventos_que_shomer_no_aviso", src)
        self.assertIn("eventos_suprimidos", src)

    def test_prompt_evita_la_mala_lectura(self):
        """El modelo no debe contar las supresiones como caídas reportadas."""
        p = brain._SYSTEM_PROMPT
        self.assertIn("eventos_que_shomer_no_aviso", p)
        self.assertIn("No cuentes estos numeros como caidas", p)

    def test_prompt_explica_ambos_sentidos(self):
        """Muchas supresiones = patrón compartido; ninguna = sospecha propia."""
        p = brain._SYSTEM_PROMPT
        self.assertIn("SIN supresiones", p)
        self.assertIn("causa a investigar es comun", p)


class TestConsultaDeSuprimidos(unittest.TestCase):
    def _db(self):
        con = sqlite3.connect(":memory:")
        con.execute(
            "CREATE TABLE eventos_filtrados (id INTEGER PRIMARY KEY, ts TEXT, ip TEXT, "
            "fuente TEXT, motivo TEXT)"
        )
        return con

    def test_lista_vacia_no_consulta(self):
        self.assertEqual(shomer_api.get_suppressed_events([]), {})
        self.assertEqual(shomer_api.get_suppressed_events(None), {})

    def test_agrupa_por_equipo_y_motivo(self):
        con = self._db()
        for _ in range(3):
            con.execute(
                "INSERT INTO eventos_filtrados (ts, ip, fuente, motivo) "
                "VALUES (datetime('now','-1 day'), '10.0.0.1', 'guardian poll', 'blip_gateway')"
            )
        con.execute(
            "INSERT INTO eventos_filtrados (ts, ip, fuente, motivo) "
            "VALUES (datetime('now','-2 hours'), '10.0.0.1', 'infra poll', 'blip_masivo')"
        )
        con.commit()

        with patch("sqlite3.connect", return_value=con):
            r = shomer_api.get_suppressed_events(["10.0.0.1"], days=30)

        self.assertEqual(r["10.0.0.1"]["total"], 4)
        self.assertEqual(r["10.0.0.1"]["por_motivo"]["blip_gateway"], 3)
        self.assertEqual(r["10.0.0.1"]["por_motivo"]["blip_masivo"], 1)

    def test_equipo_sin_supresiones_no_aparece(self):
        """Un equipo sano no debe ocupar espacio en el prompt."""
        con = self._db()
        con.execute(
            "INSERT INTO eventos_filtrados (ts, ip, fuente, motivo) "
            "VALUES (datetime('now','-1 day'), '10.0.0.1', 'x', 'blip_gateway')"
        )
        con.commit()
        with patch("sqlite3.connect", return_value=con):
            r = shomer_api.get_suppressed_events(["10.0.0.1", "10.0.0.99"], days=30)
        self.assertIn("10.0.0.1", r)
        self.assertNotIn("10.0.0.99", r)

    def test_respeta_la_ventana_de_dias(self):
        con = self._db()
        con.execute(
            "INSERT INTO eventos_filtrados (ts, ip, fuente, motivo) "
            "VALUES (datetime('now','-90 days'), '10.0.0.1', 'x', 'blip_gateway')"
        )
        con.commit()
        with patch("sqlite3.connect", return_value=con):
            r = shomer_api.get_suppressed_events(["10.0.0.1"], days=30)
        self.assertEqual(r, {}, "un evento de hace 90 días no entra en la ventana de 30")

    def test_error_de_bd_no_rompe_el_ciclo(self):
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("db locked")):
            self.assertEqual(shomer_api.get_suppressed_events(["10.0.0.1"]), {})


if __name__ == "__main__":
    unittest.main()
