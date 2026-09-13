"""El mensaje del cerebro tiene que leerlo un técnico bajo presión, no un programador.

13 sep 2026. Juan Pablo señaló que los mensajes de Telegram del cerebro y de
Shomer, aunque técnicos, no siempre usan el lenguaje más claro. Revisando
mensajes REALES ya enviados se encontró un caso concreto: la línea "Sistemas:"
mostraba el valor tal cual vive en la base de datos ("infra", "hunter",
"guardian, infra") -- un nombre de variable, no una palabra pensada para
leerse. El resto de Shomer (el resumen diario) ya nombra estos mismos módulos
en lenguaje natural ("Guardian — WiFi del hotel", "Infra — equipos del
hotel"); el cerebro debía usar el mismo vocabulario, no inventar uno propio.
"""
import unittest

from core import brain


def _conclusion(urgency="media", entities="AP X, AP Y", sources="infra",
               root_cause="causa", recommendation="revisar", evidence_count=2,
               ticket_id=None):
    return {"urgency": urgency, "entities": entities, "sources": sources,
            "root_cause": root_cause, "recommendation": recommendation,
            "evidence_count": evidence_count, "ticket_id": ticket_id}


class TestNombresDeSistemaEnLenguajeNatural(unittest.TestCase):
    """El fallo real: "infra"/"hunter" en crudo, en vez del nombre que el
    técnico ya conoce del resumen diario."""

    def test_infra_se_traduce(self):
        self.assertEqual(brain._sistemas_en_lenguaje_natural("infra"),
                         "Infra (equipos del hotel)")

    def test_hunter_se_traduce(self):
        self.assertEqual(brain._sistemas_en_lenguaje_natural("hunter"),
                         "Hunter (seguridad)")

    def test_guardian_se_traduce(self):
        self.assertEqual(brain._sistemas_en_lenguaje_natural("guardian"),
                         "Guardian (WiFi)")

    def test_combinacion_de_sistemas(self):
        self.assertEqual(brain._sistemas_en_lenguaje_natural("guardian, infra"),
                         "Guardian (WiFi), Infra (equipos del hotel)")

    def test_un_sistema_desconocido_no_rompe_solo_no_se_traduce(self):
        """Si algun dia aparece un sistema nuevo, mejor mostrarlo tal cual
        que reventar el mensaje entero."""
        self.assertIn("nuevo_sistema", brain._sistemas_en_lenguaje_natural("nuevo_sistema"))

    def test_vacio_no_rompe(self):
        self.assertEqual(brain._sistemas_en_lenguaje_natural(""), "—")


class TestElMensajeCompletoNoMuestraJerga(unittest.TestCase):
    def test_no_aparece_el_valor_crudo_infra(self):
        """Regresion directa del hallazgo: "infra" ya no debe aparecer solo,
        sin traducir, en el mensaje final."""
        msg = brain.format_telegram(_conclusion(sources="infra"))
        self.assertNotIn("Sistemas:", msg)
        self.assertIn("Infra (equipos del hotel)", msg)

    def test_hunter_tambien_traducido(self):
        msg = brain.format_telegram(_conclusion(sources="hunter"))
        self.assertIn("Hunter (seguridad)", msg)

    def test_titulo_ya_no_dice_hallazgo_correlacionado(self):
        """"Hallazgo correlacionado" es jerga -- el reemplazo dice que
        pasa, no como se llama tecnicamente."""
        msg = brain.format_telegram(_conclusion())
        self.assertNotIn("hallazgo correlacionado", msg)
        self.assertIn("mismo problema en varios equipos", msg)

    def test_pluralizacion_de_eventos_correcta(self):
        """El "evento(s)" -- un placeholder de codigo sin resolver -- ya no
        debe aparecer; debe decir "evento" o "eventos" segun corresponda."""
        uno = brain.format_telegram(_conclusion(evidence_count=1))
        varios = brain.format_telegram(_conclusion(evidence_count=4))
        self.assertNotIn("evento(s)", uno)
        self.assertNotIn("evento(s)", varios)
        self.assertIn("1 evento ", uno)
        self.assertIn("4 eventos ", varios)

    def test_sigue_incluyendo_lo_esencial(self):
        """No perder informacion al aclarar el lenguaje -- equipos, causa y
        recomendacion tienen que seguir estando."""
        c = _conclusion(entities="Switch A, Switch B", root_cause="cable dañado",
                        recommendation="revisar cableado")
        msg = brain.format_telegram(c)
        self.assertIn("Switch A, Switch B", msg)
        self.assertIn("cable dañado", msg)
        self.assertIn("revisar cableado", msg)

    def test_ticket_sigue_apareciendo(self):
        msg = brain.format_telegram(_conclusion(ticket_id=7))
        self.assertIn("#7", msg)


if __name__ == "__main__":
    unittest.main()
