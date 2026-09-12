"""La detección de usuario VPN nuevo debe funcionar sin sembrar datos.

Principio del proyecto (norma B.1, reafirmado por Juan Pablo el 11 sep 2026):
nada ad-hoc ni local. Si una función solo se comporta bien porque alguien
precargó datos de un sitio concreto, está mal diseñada — en el cliente
siguiente no funcionaría.

El mecanismo correcto es una ventana de aprendizaje: una instalación nueva
registra a todo el que entra SIN alertar hasta conocer a su gente, y recién
después un usuario nuevo merece aviso. Sin eso, un Shomer recién instalado
dispararía un aviso por cada empleado la primera semana y el técnico aprendería
a ignorarlos.
"""
import sqlite3
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from core import vpn_usuarios


class _ConexionPersistente:
    """Conexión en memoria que sobrevive al close() de la función bajo prueba.

    es_conocido() cierra su conexión en un finally, que es lo correcto en
    producción; acá la compartimos entre llamadas para poder inspeccionar el
    resultado, así que se ignora el cierre.
    """

    def __init__(self):
        self._con = sqlite3.connect(":memory:")

    def __getattr__(self, nombre):
        return getattr(self._con, nombre)

    def close(self):
        pass

    def cerrar_de_verdad(self):
        self._con.close()


class TestSinSembrarNada(unittest.TestCase):
    def setUp(self):
        self.con = _ConexionPersistente()
        self.p = patch("sqlite3.connect", return_value=self.con)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.con.cerrar_de_verdad()

    def test_instalacion_nueva_no_alerta_por_nadie(self):
        """Cliente recién instalado: aprende en silencio, no molesta."""
        for u in ("empleado.uno", "empleado.dos", "empleado.tres"):
            self.assertTrue(
                vpn_usuarios.es_conocido(u),
                f"{u} no debería alertar durante la ventana de aprendizaje",
            )

    def test_los_registra_aunque_no_alerte(self):
        vpn_usuarios.es_conocido("empleado.uno")
        n = self.con.execute("SELECT COUNT(*) FROM vpn_usuarios_conocidos").fetchone()[0]
        self.assertEqual(n, 1, "aprender en silencio sigue siendo aprender")

    def test_usuario_repetido_es_conocido(self):
        vpn_usuarios.es_conocido("empleado.uno")
        self.assertTrue(vpn_usuarios.es_conocido("empleado.uno"))
        veces = self.con.execute(
            "SELECT veces FROM vpn_usuarios_conocidos WHERE usuario='empleado.uno'"
        ).fetchone()[0]
        self.assertEqual(veces, 2)


class TestPasadaLaVentana(unittest.TestCase):
    def test_usuario_nuevo_si_alerta(self):
        """Con el sitio ya conocido, alguien nunca visto sí merece aviso."""
        con = _ConexionPersistente()
        con.execute(
            "CREATE TABLE vpn_usuarios_conocidos (usuario TEXT PRIMARY KEY, "
            "primera_vez TEXT, veces INTEGER DEFAULT 1)"
        )
        viejo = (datetime.now() - timedelta(days=60)).isoformat(sep=" ", timespec="seconds")
        con.execute(
            "INSERT INTO vpn_usuarios_conocidos (usuario, primera_vez) VALUES (?,?)",
            ("empleado.habitual", viejo),
        )
        con.commit()
        with patch("sqlite3.connect", return_value=con):
            self.assertFalse(
                vpn_usuarios.es_conocido("intruso.desconocido"),
                "pasada la ventana, un usuario nunca visto debe alertar",
            )
            # y el habitual sigue sin alertar
            self.assertTrue(vpn_usuarios.es_conocido("empleado.habitual"))


class TestCasosBorde(unittest.TestCase):
    def test_sin_nombre_no_alarma(self):
        self.assertTrue(vpn_usuarios.es_conocido(""))
        self.assertTrue(vpn_usuarios.es_conocido("desconocido"))

    def test_error_de_bd_no_alarma(self):
        with patch("sqlite3.connect", side_effect=sqlite3.OperationalError("locked")):
            self.assertTrue(
                vpn_usuarios.es_conocido("quien.sea"),
                "ante la duda no se interrumpe al técnico",
            )


if __name__ == "__main__":
    unittest.main()
