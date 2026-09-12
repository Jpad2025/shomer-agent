"""El informe al coordinador: supervisar no es recibir las mismas alertas.

El técnico actúa —alertas de Telegram, ahora, para hacer algo— y el coordinador
supervisa: necesita saber qué lleva días sin resolverse y qué exige una visita.
Mandarle al coordinador las alertas del día no lo informa, lo entierra.

Dos cosas que este informe NO puede hacer:

1. Inventar. Si un dato no se pudo consultar se dice que no está. Se decide
   sobre este texto, y un informe que rellena huecos con supuestos es peor que
   no tener informe.
2. Confundir "no se midió" con "todo bien". Es el mismo error que ya costó caro
   en el internet del hotel.
"""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from core import informe_coordinador as ic


class TestConfiguracionPorSitio(unittest.TestCase):
    """Norma B.1: nada de esto se comparte entre hoteles."""

    def test_sin_smtp_no_se_considera_configurado(self):
        with patch.dict(os.environ, {"SMTP_HOST": "", "SUPPORT_EMAIL_TO": "a@b.c"}):
            self.assertFalse(ic.configurado())

    def test_sin_destinatario_tampoco(self):
        with patch.dict(os.environ, {"SMTP_HOST": "smtp.x", "SUPPORT_EMAIL_TO": ""}):
            self.assertFalse(ic.configurado())

    def test_con_ambos_si(self):
        with patch.dict(os.environ, {"SMTP_HOST": "smtp.x", "SUPPORT_EMAIL_TO": "a@b.c"}):
            self.assertTrue(ic.configurado())

    def test_sin_configurar_no_intenta_enviar(self):
        with patch.dict(os.environ, {"SMTP_HOST": "", "SUPPORT_EMAIL_TO": ""}):
            self.assertFalse(ic.enviar("Hotel X"))

    def test_periodicidad_y_hora_configurables(self):
        with patch.dict(os.environ, {"INFORME_COORDINADOR_CADA": "diario",
                                     "INFORME_COORDINADOR_HORA": "9"}):
            self.assertEqual(ic.cada(), "diario")
            self.assertEqual(ic.hora(), 9)

    def test_una_hora_absurda_no_rompe(self):
        with patch.dict(os.environ, {"INFORME_COORDINADOR_HORA": "99"}):
            self.assertEqual(ic.hora(), 23)
        with patch.dict(os.environ, {"INFORME_COORDINADOR_HORA": "no soy un numero"}):
            self.assertEqual(ic.hora(), 7)


class TestNoSeEnviaDosVeces(unittest.TestCase):
    """Un reinicio del agente no puede disparar un informe repetido."""

    def test_semanal_solo_su_dia_y_su_hora(self):
        with patch.dict(os.environ, {"INFORME_COORDINADOR_CADA": "semanal",
                                     "INFORME_COORDINADOR_HORA": "7",
                                     "INFORME_COORDINADOR_DIA": "0"}):
            lunes_7 = datetime(2026, 9, 14, 7, 30)
            self.assertTrue(ic.toca_ahora(lunes_7, ultimo_envio=""))
            self.assertFalse(ic.toca_ahora(datetime(2026, 9, 14, 8, 0), ""))
            self.assertFalse(ic.toca_ahora(datetime(2026, 9, 15, 7, 0), ""))

    def test_no_repite_en_el_mismo_periodo(self):
        with patch.dict(os.environ, {"INFORME_COORDINADOR_CADA": "semanal",
                                     "INFORME_COORDINADOR_HORA": "7",
                                     "INFORME_COORDINADOR_DIA": "0"}):
            lunes = datetime(2026, 9, 14, 7, 30)
            clave = ic.clave_periodo(lunes)
            self.assertFalse(ic.toca_ahora(lunes, ultimo_envio=clave))

    def test_la_semana_siguiente_si(self):
        with patch.dict(os.environ, {"INFORME_COORDINADOR_CADA": "semanal",
                                     "INFORME_COORDINADOR_HORA": "7",
                                     "INFORME_COORDINADOR_DIA": "0"}):
            anterior = ic.clave_periodo(datetime(2026, 9, 14, 7, 30))
            self.assertTrue(ic.toca_ahora(datetime(2026, 9, 21, 7, 30), anterior))


class TestElInformeNoInventa(unittest.TestCase):
    def _construir(self, cronicos=None, resp=None, net=None, seg=None):
        with patch.object(ic, "_pendientes_cronicos", return_value=cronicos or []), \
             patch.object(ic, "_respaldos", return_value=resp if resp is not None else {}), \
             patch.object(ic, "_internet_huespedes", return_value=net or {}), \
             patch.object(ic, "_seguridad", return_value=seg or {}):
            return ic.construir("Hotel X", 168)

    def test_sin_lecturas_dice_que_no_se_midio(self):
        """El error que ya costó caro: creerle al silencio."""
        texto = self._construir(net={"lecturas": 0})
        self.assertIn("no se midió", texto)
        self.assertNotIn("0 de 0 comprobaciones sin problema", texto)

    def test_un_dato_no_consultable_se_declara(self):
        texto = self._construir(resp={}, seg={})
        self.assertIn("sin dato", texto)

    def test_nada_pendiente_se_dice_claro(self):
        texto = self._construir()
        self.assertIn("Nada pendiente", texto)

    def test_los_pendientes_traen_su_antiguedad(self):
        """Cuánto lleva abierto es el dato que hace decidir al coordinador."""
        texto = self._construir(cronicos=[
            {"nombre": "AP HAB 103", "ip": "192.168.0.148", "fuente": "guardian", "dias": 8}])
        self.assertIn("AP HAB 103", texto)
        self.assertIn("abierto hace 8 días", texto)

    def test_sin_fecha_no_se_inventa_una_antiguedad(self):
        texto = self._construir(cronicos=[
            {"nombre": "X", "ip": "10.0.0.1", "fuente": "y", "dias": None}])
        self.assertIn("sin fecha de inicio registrada", texto)

    def test_un_respaldo_atrasado_se_marca(self):
        texto = self._construir(resp={"total": 2, "nube_dias": 0,
                                      "atrasados": [{"nombre": "SRV PMS", "dias": 5}]})
        self.assertIn("ATRASADO: SRV PMS", texto)
        self.assertIn("hace 5 días", texto)

    def test_no_repite_las_alertas_del_dia(self):
        texto = self._construir()
        self.assertIn("es lo que sigue pendiente", texto)


class TestHallazgosDelCerebroLegibles(unittest.TestCase):
    def test_una_lista_larga_se_resume_por_lo_que_es(self):
        """Recortada a la mitad engaña: parece que el problema es del primero."""
        falso = [{"entity_name": "🧠 SW A, SW B, NVR 1, Cámara .52, Terminal .136",
                  "ip": "10.0.0.1", "fuente": "cerebro", "opened_at": None}]
        with patch("core.chronic_tickets.list_open", return_value=falso):
            r = ic._pendientes_cronicos()
        self.assertEqual(len(r), 1)
        self.assertIn("Causa común entre 5 equipos", r[0]["nombre"])

    def test_la_antiguedad_sale_de_opened_at(self):
        """La columna se llama opened_at; leer created_at daba siempre vacío."""
        falso = [{"entity_name": "AP 1", "ip": "10.0.0.1", "fuente": "g",
                  "opened_at": "2026-09-01 10:00:00"}]
        with patch("core.chronic_tickets.list_open", return_value=falso):
            r = ic._pendientes_cronicos()
        self.assertIsNotNone(r[0]["dias"], "sin esto el informe pierde su dato clave")


if __name__ == "__main__":
    unittest.main()
