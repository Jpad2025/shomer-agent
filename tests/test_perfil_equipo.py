"""El perfil de comportamiento: de recomendaciones de manual a recomendaciones de sitio.

El contexto de aprendizaje que había dependía de que el técnico guardara
soluciones a mano, y eso casi no ocurre — medido en Ópera: 6 acciones en 3 meses
y solo 2 de 4 equipos con algún dato. Por eso las recomendaciones del cerebro
salían genéricas ("inspeccionar el cableado y verificar la configuración VLAN"),
que es lo que cualquier técnico ya sabe.

El perfil sale de hechos que Shomer YA registró, sin que nadie enseñe nada:
cuántas veces cayó el equipo, en cuánto vuelve y si vuelve solo. Con eso la
recomendación pasa a ser "cae 41 veces al mes y vuelve solo en 30 segundos: es
intermitencia, el cable ya se descarta".
"""
import sqlite3
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from core import shomer_api


def _db_con(eventos):
    """eventos: [(minutos_atras, status)]"""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE status_events (ts TEXT, ip TEXT, status TEXT)")
    ahora = datetime.now()
    for minutos, estado in eventos:
        ts = (ahora - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
        con.execute(
            "INSERT INTO status_events (ts, ip, status) VALUES (?,?,?)",
            (ts, "10.0.0.1", estado),
        )
    con.commit()
    return con


class TestEquipoIntermitente(unittest.TestCase):
    """El caso real: cae seguido y vuelve solo en segundos."""

    def test_detecta_el_patron(self):
        eventos = []
        for i in range(12):
            base = i * 120
            eventos += [(base + 1, "offline"), (base, "online")]
        con = _db_con(eventos)
        with patch("sqlite3.connect", return_value=con):
            p = shomer_api.get_perfil_equipo("10.0.0.1")

        self.assertEqual(p["caidas"], 12)
        self.assertTrue(p["vuelve_solo"], "vuelve en ~1 min: vuelve solo")
        self.assertIn("es un patrón", p["lectura"])

    def test_recuperacion_tipica_es_la_mediana(self):
        """Una recuperación lentísima aislada no debe torcer el perfil."""
        eventos = [
            (500, "offline"), (499, "online"),   # 1 min
            (400, "offline"), (399, "online"),   # 1 min
            (300, "offline"), (240, "online"),   # 60 min, caso raro
        ]
        con = _db_con(eventos)
        with patch("sqlite3.connect", return_value=con):
            p = shomer_api.get_perfil_equipo("10.0.0.1")
        self.assertLessEqual(
            p["recuperacion_tipica_min"], 60,
            "la mediana no debe dispararse por un caso aislado",
        )


class TestEquipoSano(unittest.TestCase):
    def test_pocas_caidas_no_es_patron(self):
        con = _db_con([(100, "offline"), (98, "online")])
        with patch("sqlite3.connect", return_value=con):
            p = shomer_api.get_perfil_equipo("10.0.0.1")
        self.assertEqual(p["caidas"], 1)
        self.assertNotIn("lectura", p, "una caída aislada no es un patrón")


class TestEquipoQueNoVuelve(unittest.TestCase):
    def test_caida_larga_no_es_vuelve_solo(self):
        """El que NO vuelve solo es el que sí merece revisión física."""
        con = _db_con([(200, "offline"), (100, "online")])  # 100 min caído
        with patch("sqlite3.connect", return_value=con):
            p = shomer_api.get_perfil_equipo("10.0.0.1")
        self.assertFalse(p["vuelve_solo"])


class TestSinDatos(unittest.TestCase):
    def test_sin_historial_devuelve_vacio(self):
        """Sin hechos no se afirma nada: es la diferencia con adivinar."""
        con = _db_con([])
        with patch("sqlite3.connect", return_value=con):
            self.assertEqual(shomer_api.get_perfil_equipo("10.0.0.1"), {})

    def test_ip_vacia(self):
        self.assertEqual(shomer_api.get_perfil_equipo(""), {})

    def test_error_de_bd_no_rompe(self):
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("locked")):
            self.assertEqual(shomer_api.get_perfil_equipo("10.0.0.1"), {})


class TestElCerebroLoRecibe(unittest.TestCase):
    def test_el_prompt_explica_como_usarlo(self):
        from core import brain

        p = brain._SYSTEM_PROMPT
        self.assertIn("comportamiento_real", p)
        self.assertIn("intermitencia", p)
        self.assertIn("causa es", p.replace("\n", " "))


if __name__ == "__main__":
    unittest.main()
