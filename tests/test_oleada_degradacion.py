"""Diez equipos lentos a la vez son un hecho, no veinte noticias.

12 sep 2026, caso real medido en Ópera. A las 21:09 diez equipos —dos
servidores, cinco switches, una impresora y el propio router— avisaron
"Pulse — degradando" en 40 segundos, todos con 534-538 ms contra su normal de
~349 ms. Tres minutos después los mismos diez avisaron "estable". Veinte
mensajes para un solo evento de red.

El delator estaba en la propia lista: el gateway. Si sube la latencia del
router, sube la de todo lo que pasa por él. Mandar al técnico a revisar diez
equipos es mandarlo al lugar equivocado diez veces.

Lo que no puede pasar: que un equipo solo, con un problema propio, se pierda
dentro de una agrupación.
"""
import unittest

from core import pulse_correlate as pc


def _ev(ip, name, lat, base=349.0):
    return {"ip": ip, "name": name, "ewma_latency_ms": lat,
            "baseline_latency_ms": base, "transition": "enter_degrading"}


OLEADA = [
    _ev("192.168.0.5", "SRVZEUS", 534.0),
    _ev("192.168.0.212", "SW-REST-SCALA", 534.0),
    _ev("192.168.0.216", "SW-POE-OFC-SISTEMAS", 534.0),
    _ev("192.168.0.118", "SW Piso 7", 538.0),
    _ev("192.168.0.1", "MikroTik Router (Gateway)", 534.0),
]


class TestSeReconoceLaCausaCompartida(unittest.TestCase):
    def test_misma_latencia_en_equipos_distintos_es_una_sola_causa(self):
        self.assertTrue(pc._mismo_sintoma(OLEADA))

    def test_latencias_dispares_no_se_declaran_causa_comun(self):
        distintos = [_ev("10.0.0.1", "A", 120.0), _ev("10.0.0.2", "B", 900.0)]
        self.assertFalse(pc._mismo_sintoma(distintos))

    def test_un_solo_equipo_no_tiene_con_quien_compartir_causa(self):
        self.assertFalse(pc._mismo_sintoma([OLEADA[0]]))


class TestElMensajeAgrupado(unittest.TestCase):
    def test_dice_cuantos_son_y_no_los_lista_uno_por_uno(self):
        m = pc.format_ewma_wave_degrading(OLEADA, {"gateway_ip": "192.168.0.1"})
        self.assertIn("5 equipos", m)
        self.assertIn("SRVZEUS", m)

    def test_senala_al_router_cuando_esta_en_la_lista(self):
        """Es el dato que ahorra el viaje en falso."""
        m = pc.format_ewma_wave_degrading(OLEADA, {"gateway_ip": "192.168.0.1"})
        self.assertIn("router", m.lower())
        self.assertIn("hereda su latencia", m)

    def test_sin_router_igual_explica_que_la_causa_es_compartida(self):
        sin_gw = [e for e in OLEADA if e["ip"] != "192.168.0.1"]
        m = pc.format_ewma_wave_degrading(sin_gw, {"gateway_ip": "192.168.0.1"})
        self.assertIn("causa compartida", m)

    def test_da_la_medida_en_lenguaje_llano(self):
        m = pc.format_ewma_wave_degrading(OLEADA, {})
        self.assertIn("535 ms", m)
        self.assertIn("349 ms", m)

    def test_aclara_que_no_es_una_caida(self):
        """No confundir lentitud con que el hotel se quedó sin servicio."""
        m = pc.format_ewma_wave_degrading(OLEADA, {})
        self.assertIn("no caída", m)

    def test_la_recuperacion_tambien_es_un_solo_mensaje(self):
        m = pc.format_ewma_wave_recovered(OLEADA)
        self.assertIn("5 equipos", m)

    def test_sin_medidas_no_inventa_numeros(self):
        sin = [{"ip": "10.0.0.1", "name": "X"}, {"ip": "10.0.0.2", "name": "Y"}]
        m = pc.format_ewma_wave_degrading(sin, {})
        self.assertIn("2 equipos", m)
        self.assertNotIn("ms", m.split("Siguen")[0].replace("equipos", ""))


class TestNoSePierdeElCasoIndividual(unittest.TestCase):
    """Se lee monitor.py como TEXTO a propósito: importarlo arrastra `telegram`,
    que solo existe dentro del contenedor, y la prueba dejaría de correr fuera."""

    @staticmethod
    def _envio():
        from pathlib import Path
        texto = (Path(__file__).resolve().parents[1] / "core" / "monitor.py").read_text()
        i = texto.find("async def _process_pulse_ewma_events")
        assert i > 0, "no se encontró la función de envío de Pulse"
        return texto[i:i + 4000]

    def test_el_umbral_deja_pasar_al_equipo_solo(self):
        """Un equipo con un problema propio merece su mensaje detallado."""
        fuente = self._envio()
        self.assertIn("if len(entrando) >= umbral:", fuente)
        self.assertIn("format_ewma_degrading(ev)", fuente,
                      "por debajo del umbral se sigue avisando equipo por equipo")

    def test_se_confirma_el_aviso_de_cada_equipo_aunque_vaya_agrupado(self):
        """Sin el ack por IP, el cooldown se pierde y vuelve el mensaje repetido."""
        self.assertIn("_ack(entrando)", self._envio())


if __name__ == "__main__":
    unittest.main()
