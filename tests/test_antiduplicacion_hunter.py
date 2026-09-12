"""Un bloqueo de Hunter debe avisarse UNA vez, no dos.

El backend avisa cuando bloquea, y ~60 s después watch_hunter detecta la misma
IP por su cuenta y avisaba de nuevo. La Sesión 80 agregó una supresión para
esto, pero **nunca funcionó**: extraía la IP del mensaje con una regex que
exigía un dígito inmediatamente después de "IP:", cuando el formato real la
envuelve en <code>…</code>. El 8 sep 2026 el mismo bloqueo salió dos veces con
64 segundos de diferencia, y encima el cerebro sumó un tercer aviso.

La lección del caso: una supresión que depende del maquetado del texto se rompe
en silencio la primera vez que alguien cambia el formato del mensaje, y nadie se
entera porque el síntoma es "se manda de más", no un error.
"""
import re
import unittest

# Formato real que produce format_hunter_telegram_block() en network_monitor.
MENSAJE_REAL = (
    "🚨 <b>BLOQUEO AUTOMÁTICO — Hunter</b>\n"
    "🟡 <b>MEDIO</b> — Amenaza detectada por Hunter\n"
    "🌐 IP: <code>192.73.243.141</code>\n"
    "📋 <b>Qué significa:</b> Regla de seguridad Suricata activada\n"
    "✅ Firewall del hotel: IP bloqueada"
)

MENSAJE_WAZUH = (
    "🛡️ <b>BLOQUEO (Wazuh → Shomer)</b>\n"
    "🟠 <b>ALTO</b> — IP con mala reputación\n"
    "🌐 IP: <code>69.5.169.186</code>\n"
    "✅ Firewall del hotel: IP bloqueada"
)

REGEX_VIEJA = r"IP:\s*(\d{1,3}(?:\.\d{1,3}){3})"
REGEX_NUEVA = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"


class TestLaRegexViejaNoServia(unittest.TestCase):
    def test_no_matcheaba_el_formato_real(self):
        """Deja constancia de por qué la supresión nunca actuó."""
        self.assertIsNone(
            re.search(REGEX_VIEJA, MENSAJE_REAL),
            "si esto matchea, el bug era otro y hay que revisar la conclusión",
        )


class TestExtraccionActual(unittest.TestCase):
    def test_encuentra_la_ip_dentro_de_code(self):
        ips = re.findall(REGEX_NUEVA, MENSAJE_REAL)
        self.assertIn("192.73.243.141", ips)

    def test_funciona_tambien_con_el_formato_wazuh(self):
        ips = re.findall(REGEX_NUEVA, MENSAJE_WAZUH)
        self.assertIn("69.5.169.186", ips)

    def test_no_depende_del_maquetado(self):
        """El punto del arreglo: que sobreviva a cambios de formato."""
        for variante in (
            "IP: 10.0.0.1",
            "IP: <code>10.0.0.1</code>",
            "IP: <b><code>10.0.0.1</code></b>",
            "la IP 10.0.0.1 fue bloqueada",
        ):
            with self.subTest(variante=variante):
                self.assertIn("10.0.0.1", re.findall(REGEX_NUEVA, variante))


class TestCodigoEnProduccion(unittest.TestCase):
    def test_el_relay_usa_la_extraccion_robusta(self):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / "core" / "monitor.py").read_text()
        self.assertNotIn(
            'r"IP:\\s*(\\d{1,3}(?:\\.\\d{1,3}){3})"', src,
            "la regex frágil no debe volver: rompe la supresión en silencio",
        )
        self.assertIn("_direct_relayed_ips[encontrada]", src)


if __name__ == "__main__":
    unittest.main()
