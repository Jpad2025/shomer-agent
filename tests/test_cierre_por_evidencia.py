"""Un pendiente cuyo motivo ya no existe debe cerrarse solo.

Caso real (8-11 sep 2026): el cerebro abrió tickets por IPs que Hunter había
bloqueado mal (Akamai, tráfico de videollamadas). Esas IPs se liberaron el mismo
día al corregir la política, pero los tickets siguieron recordándose **3 veces
al día durante 3 días** por un problema que ya no existía.

Depender de que el técnico los cierre no alcanza: de 9 tickets, 7 seguían
abiertos, algunos de hace una semana. Y si el sistema no limpia lo suyo, se
auto-contamina: cada falso positivo deja ruido permanente.
"""
import sqlite3
import unittest
from unittest.mock import patch

from core import chronic_tickets as ct


class TestExtraccionDeIPs(unittest.TestCase):
    def test_toma_la_ip_del_ticket(self):
        ips = ct._ips_del_ticket({"ip": "10.0.0.1", "entity_name": "AP Lobby"})
        self.assertEqual(ips, ["10.0.0.1"])

    def test_toma_las_ips_que_el_cerebro_pone_en_el_nombre(self):
        """Los tickets del cerebro llevan el cluster entero en entity_name."""
        t = {"ip": "23.218.213.23",
             "entity_name": "🧠 23.218.213.23, 192.73.243.141"}
        ips = set(ct._ips_del_ticket(t))
        self.assertEqual(ips, {"23.218.213.23", "192.73.243.141"})

    def test_nombre_sin_ips_no_rompe(self):
        ips = ct._ips_del_ticket({"ip": "10.0.0.1", "entity_name": "AP Piso 3 (SW3)"})
        self.assertEqual(ips, ["10.0.0.1"])


class TestDecisionDeCierre(unittest.TestCase):
    def _db_con(self, filas):
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE blocked_ips (ip TEXT, unblocked_at TEXT)")
        con.executemany("INSERT INTO blocked_ips VALUES (?,?)", filas)
        con.commit()
        return con

    def test_todas_liberadas_se_puede_cerrar(self):
        con = self._db_con([("1.1.1.1", "2026-09-08"), ("2.2.2.2", "2026-09-08")])
        with patch("sqlite3.connect", return_value=con):
            self.assertIs(ct._sigue_bloqueada(["1.1.1.1", "2.2.2.2"]), False)

    def test_si_una_sigue_bloqueada_no_se_cierra(self):
        """Basta con que una del cluster siga activa para que el problema siga vivo."""
        con = self._db_con([("1.1.1.1", "2026-09-08"), ("2.2.2.2", None)])
        with patch("sqlite3.connect", return_value=con):
            self.assertIs(ct._sigue_bloqueada(["1.1.1.1", "2.2.2.2"]), True)

    def test_sin_registro_no_se_toca(self):
        """Un AP interno nunca pasó por Hunter: la falta de registro NO es
        evidencia de que se resolvió. Debe quedar abierto."""
        con = self._db_con([])
        with patch("sqlite3.connect", return_value=con):
            self.assertIsNone(ct._sigue_bloqueada(["192.168.0.148"]))

    def test_lista_vacia_no_consulta(self):
        self.assertIsNone(ct._sigue_bloqueada([]))

    def test_error_de_bd_no_cierra_nada(self):
        """Ante la duda, el pendiente se queda abierto."""
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("locked")):
            self.assertIsNone(ct._sigue_bloqueada(["1.1.1.1"]))


class TestSoloCierraLoResuelto(unittest.TestCase):
    def test_no_cierra_equipos_internos_del_hotel(self):
        """El caso que importa: los APs y switches con problemas reales deben
        seguir abiertos aunque se limpien los falsos positivos."""
        abiertos = [
            {"id": 2, "ip": "192.168.0.148", "entity_name": "AP HAB 103"},
            {"id": 9, "ip": "23.218.213.23",
             "entity_name": "🧠 23.218.213.23, 192.73.243.141"},
        ]
        cerrados_ids = []

        def fake_sigue(ips):
            # el AP interno no tiene registro; las externas están liberadas
            return None if any(i.startswith("192.168.") for i in ips) else False

        with patch.object(ct, "list_open", return_value=abiertos), \
             patch.object(ct, "_sigue_bloqueada", side_effect=fake_sigue), \
             patch.object(ct, "close_ticket", side_effect=lambda i: cerrados_ids.append(i) or True):
            cerrados = ct.cerrar_resueltos_por_evidencia()

        self.assertEqual(cerrados_ids, [9], "solo debe cerrarse el falso positivo")
        self.assertEqual(len(cerrados), 1)
        self.assertIn("falso positivo", cerrados[0]["motivo_cierre"])


if __name__ == "__main__":
    unittest.main()
