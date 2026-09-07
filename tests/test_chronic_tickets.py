"""Pruebas del ciclo de vida de tickets crónicos (chronic_tickets.py).

Estos tickets son la memoria de "esto ya se le avisó a alguien" -- un bug acá
(duplicar tickets para la misma falla, o no poder cerrar uno) genera spam
real en el grupo de Telegram del hotel o deja un problema marcado como
abierto para siempre.
"""


class TestGetOrCreate:
    def test_crea_ticket_nuevo(self, ct):
        ticket_id, es_nuevo = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        assert es_nuevo is True
        assert ticket_id > 0

    def test_reutiliza_ticket_abierto_misma_ip_y_fuente(self, ct):
        """Esto es lo que evita duplicar tickets para la misma falla que se
        reporta varias veces mientras sigue sin resolverse."""
        id1, nuevo1 = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        id2, nuevo2 = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        assert id1 == id2
        assert nuevo1 is True
        assert nuevo2 is False

    def test_misma_ip_distinta_fuente_crea_tickets_separados(self, ct):
        """Un mismo equipo puede tener un ticket de red Y uno del cerebro a
        la vez -- son problemas distintos, no deben fusionarse."""
        id1, _ = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        id2, _ = ct.get_or_create("192.168.0.10", "AP Test", "cerebro")
        assert id1 != id2

    def test_reabre_ticket_tras_cerrar_uno_previo(self, ct):
        """Si el ticket anterior para esa IP+fuente ya se cerró, una nueva
        falla debe abrir un ticket NUEVO, no reutilizar el cerrado."""
        id1, _ = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        ct.close_ticket(id1)
        id2, es_nuevo = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        assert es_nuevo is True
        assert id2 != id1


class TestCloseTicket:
    def test_cerrar_ticket_abierto_devuelve_true(self, ct):
        ticket_id, _ = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        assert ct.close_ticket(ticket_id) is True

    def test_cerrar_ticket_ya_cerrado_devuelve_false(self, ct):
        ticket_id, _ = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        ct.close_ticket(ticket_id)
        assert ct.close_ticket(ticket_id) is False

    def test_cerrar_ticket_inexistente_devuelve_false(self, ct):
        assert ct.close_ticket(999999) is False

    def test_ticket_cerrado_no_aparece_en_list_open(self, ct):
        ticket_id, _ = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        ct.close_ticket(ticket_id)
        abiertos = [t["id"] for t in ct.list_open()]
        assert ticket_id not in abiertos


class TestListOpen:
    def test_lista_vacia_sin_tickets(self, ct):
        assert ct.list_open() == []

    def test_incluye_solo_los_abiertos(self, ct):
        id1, _ = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        id2, _ = ct.get_or_create("192.168.0.20", "SW Test", "watch_devices")
        ct.close_ticket(id1)
        abiertos = [t["id"] for t in ct.list_open()]
        assert id1 not in abiertos
        assert id2 in abiertos

    def test_orden_por_fecha_de_apertura_ascendente(self, ct):
        id1, _ = ct.get_or_create("192.168.0.10", "Primero", "watch_devices")
        id2, _ = ct.get_or_create("192.168.0.20", "Segundo", "watch_devices")
        abiertos = ct.list_open()
        posiciones = [t["id"] for t in abiertos]
        assert posiciones.index(id1) < posiciones.index(id2)


class TestGetTicket:
    def test_devuelve_none_si_no_existe(self, ct):
        assert ct.get_ticket(999999) is None

    def test_devuelve_los_datos_correctos(self, ct):
        ticket_id, _ = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        t = ct.get_ticket(ticket_id)
        assert t is not None
        assert t["ip"] == "192.168.0.10"
        assert t["entity_name"] == "AP Test"
        assert t["fuente"] == "watch_devices"
        assert t["status"] == "open"


class TestMarkReminded:
    def test_no_lanza_error_con_ticket_valido(self, ct):
        ticket_id, _ = ct.get_or_create("192.168.0.10", "AP Test", "watch_devices")
        ct.mark_reminded(ticket_id)  # no debe lanzar excepción
        t = ct.get_ticket(ticket_id)
        assert t["last_reminder_at"] is not None
