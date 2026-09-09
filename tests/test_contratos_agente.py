"""Contratos del agente que se desincronizan solos y no dan error al romperse.

Tres listas que viven en archivos distintos y se editan por separado:
  - los comandos registrados vs sus funciones vs el menú publicado,
  - los monitores definidos vs los lanzados vs los que se muestran en /monitores,
  - los endpoints que el agente invoca vs los que el backend expone.

Ninguna de estas roturas produce una excepción: el bot arranca igual y el fallo
aparece como un comando que no responde, un botón que no hace nada o una
vigilancia que el técnico cree tener. Por eso van cubiertas por herramientas
que fallan en CI y no por revisión a ojo.

Hallazgo real (9 sep 2026): watch_brain y watch_poller_heartbeat corrían desde
siempre pero faltaban en MONITOR_GROUPS, así que /monitores mostraba 37 de 39.
El ausente watch_poller_heartbeat es justo el que detecta "Guardian congelado".
"""
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TOOLS = RAIZ / "tools"


def _correr(script: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(TOOLS / script)],
        capture_output=True, text=True, timeout=120, env=env,
    )


class TestComandos(unittest.TestCase):
    def test_comandos_coherentes(self):
        r = _correr("auditar_comandos.py")
        self.assertEqual(
            r.returncode, 0,
            f"comandos desincronizados:\n{r.stdout}\n{r.stderr}",
        )


class TestMonitores(unittest.TestCase):
    def test_monitores_coherentes(self):
        r = _correr("auditar_monitores.py")
        self.assertEqual(
            r.returncode, 0,
            f"monitores desincronizados:\n{r.stdout}\n{r.stderr}",
        )

    def test_heartbeat_visible_para_el_tecnico(self):
        """El monitor que detecta 'Guardian congelado' debe verse en /monitores."""
        bot = (RAIZ / "core" / "bot.py").read_text(errors="replace")
        self.assertIn('"watch_poller_heartbeat"', bot)
        self.assertIn('"watch_brain"', bot)

    def test_tienen_etiqueta_legible(self):
        """Sin etiqueta se mostrarían con el nombre técnico crudo.

        Se lee el archivo en vez de importar core.bot: el módulo `telegram`
        solo está instalado dentro del contenedor, y esta suite debe correr
        también fuera de él.
        """
        import re

        bot = (RAIZ / "core" / "bot.py").read_text(errors="replace")
        bloque = re.search(r"MONITOR_LABELS\s*=\s*\{(.*?)\n\}", bot, re.S)
        self.assertIsNotNone(bloque, "no se encontró MONITOR_LABELS")
        etiquetas = set(re.findall(r'"([a-z_]+)"\s*:', bloque.group(1)))
        for n in ("watch_brain", "watch_poller_heartbeat"):
            self.assertIn(n, etiquetas, f"{n} se mostraría con su nombre crudo")


class TestBotones(unittest.TestCase):
    def test_callbacks_con_handler(self):
        r = _correr("auditar_callbacks.py")
        self.assertEqual(
            r.returncode, 0,
            f"hay botones inline sin handler:\n{r.stdout}\n{r.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
