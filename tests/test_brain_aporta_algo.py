"""El cerebro habla cuando correlaciona, no cuando repite.

El cerebro existe para explicar que varios hechos sueltos son uno solo. Cuando
no hace eso, su mensaje llega después de que el monitor del equipo ya avisó,
diciendo lo mismo con otras palabras — y el técnico recibe el mismo hecho dos
veces (tres, contando el aviso del backend).

Medido sobre las 50 conclusiones reales de Ópera (11 sep 2026):
  - 32 eran de un solo equipo (64%): ninguna correlación que aportar.
  - 11 concluían que NO había relación entre los eventos (22%): avisar que no
    hay nada que avisar.
Con el criterio aplicado: se enviarían 11 y se guardarían 39 sin interrumpir.

Nada se pierde: la conclusión se guarda igual en brain_conclusions y sigue
consultable. Lo único que cambia es si interrumpe.

Los textos de abajo son conclusiones REALES del sistema, no inventadas.
"""
import unittest

from core.brain import aporta_algo


class TestCorrelacionesRealesSeEnvian(unittest.TestCase):
    """Varios equipos + causa común = eso es lo que el cerebro debe aportar."""

    def test_switches_con_causa_comun(self):
        vale, _ = aporta_algo({
            "entities": "SW Piso 3 (SW3), SW Amalfi (Piso 1), NVR Hikvision 1",
            "root_cause": "fallo de alimentación o hardware en los switches SW Piso 3 "
                          "y SW Amalfi, que interrumpe la conectividad de los equipos "
                          "que dependen de ellos",
        })
        self.assertTrue(vale, "una causa común entre varios equipos SÍ debe avisarse")

    def test_infraestructura_afectando_varios(self):
        vale, _ = aporta_algo({
            "entities": "SW Amalfi (Piso 1), Cámara/equipo .52, AP REST SCALA",
            "root_cause": "Posible fallo en la infraestructura de red que afecta "
                          "múltiples dispositivos en el mismo intervalo",
        })
        self.assertTrue(vale)


class TestRepeticionesNoSeEnvian(unittest.TestCase):
    """Un solo equipo: su monitor ya avisó. El cerebro repetiría."""

    def test_un_ap_solo(self):
        vale, motivo = aporta_algo({
            "entities": "AP CONTABILIDAD",
            "root_cause": "El AP CONTABILIDAD está offline debido a una falta de "
                          "respuesta LAN",
        })
        self.assertFalse(vale)
        self.assertIn("un solo equipo", motivo)

    def test_una_impresora_sola(self):
        vale, _ = aporta_algo({
            "entities": "Impresora POS Bixolon .243",
            "root_cause": "La impresora está offline debido a falta de respuesta de ping",
        })
        self.assertFalse(vale)


class TestNoHallazgosNoSeEnvian(unittest.TestCase):
    """Avisar que no hay nada que avisar es ruido puro."""

    def test_no_comparten_causa(self):
        vale, motivo = aporta_algo({
            "entities": "SRVZEUS, SRVAD — Servidor Dominio AD",
            "root_cause": "Los eventos de offline y online de SRVZEUS y SRVAD no "
                          "comparten causa común, ya que no hay coincidencia temporal",
        })
        self.assertFalse(vale)
        self.assertIn("no hay causa común", motivo)

    def test_sin_evidencia_de_problema_comun(self):
        vale, _ = aporta_algo({
            "entities": "Terminal pago Ingenico .136, Terminal pago Ingenico .143",
            "root_cause": "Ambas terminales experimentaron cortes transitorios, pero "
                          "no hay evidencia de un problema compartido",
        })
        self.assertFalse(vale, "aunque sean 2 equipos, la conclusión es que no hay relación")


class TestCasosBorde(unittest.TestCase):
    def test_sin_entidades_no_aporta(self):
        vale, _ = aporta_algo({"entities": "", "root_cause": "algo pasó"})
        self.assertFalse(vale)

    def test_sin_causa_pero_varias_entidades_se_envia(self):
        """Si el modelo no explicó la causa pero hay varios equipos, se manda:
        ante la duda, es mejor avisar de más que ocultar una correlación real."""
        vale, _ = aporta_algo({"entities": "SW1, SW2, SW3", "root_cause": ""})
        self.assertTrue(vale)

    def test_es_insensible_a_mayusculas(self):
        vale, _ = aporta_algo({
            "entities": "A, B",
            "root_cause": "NO HAY EVIDENCIA de un problema comun",
        })
        self.assertFalse(vale)


if __name__ == "__main__":
    unittest.main()
