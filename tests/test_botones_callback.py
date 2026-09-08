"""Todo botón inline debe tener un handler que lo atienda.

Bug real (8 sep 2026): el botón "🔓 Desbloquear" de las alertas de Hunter
mandaba callback_data="block_unblock_<ip>", pero el handler registrado espera
"^unblock_(confirm:.+|cancel)$". No casaba con ningún patrón, así que pulsarlo
no hacía absolutamente nada — y no había forma de notarlo salvo probándolo a
mano. Se descubrió el mismo día en que Hunter bloqueó los DNS de Google y el
técnico no pudo liberarlos desde Telegram.
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
HERRAMIENTA = RAIZ / "tools" / "auditar_callbacks.py"

PATRONES_BLOQUEO = [
    r"^unblock_(confirm:.+|cancel)$",
    r"^block_(confirm:.+|cancel)$",
]


class TestBotonDesbloquearDeHunter(unittest.TestCase):
    def test_formato_actual_tiene_handler(self):
        valor = "unblock_confirm:8.8.8.8"
        self.assertTrue(
            any(re.match(p, valor) for p in PATRONES_BLOQUEO),
            "el botón Desbloquear debe enrutar a cb_unblock",
        )

    def test_formato_viejo_no_enrutaba(self):
        """Deja constancia de por qué el formato viejo estaba roto."""
        valor = "block_unblock_8.8.8.8"
        self.assertFalse(
            any(re.match(p, valor) for p in PATRONES_BLOQUEO),
            "este era el formato roto; si vuelve a aparecer, el botón muere",
        )

    def test_monitor_usa_el_formato_correcto(self):
        texto = (RAIZ / "core" / "monitor.py").read_text(errors="replace")
        self.assertIn("unblock_confirm:{ip}", texto)
        self.assertNotIn(
            'callback_data=f"block_unblock_', texto,
            "formato sin handler: el botón quedaría muerto otra vez",
        )


class TestNingunBotonHuerfano(unittest.TestCase):
    def test_auditoria_completa_de_callbacks(self):
        """Corre la herramienta que cruza los 39 botones contra los handlers."""
        r = subprocess.run(
            [sys.executable, str(HERRAMIENTA)],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(
            r.returncode, 0,
            f"hay botones inline sin handler:\n{r.stdout}\n{r.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
