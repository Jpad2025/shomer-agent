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


class TestQueryAnswerFallidoNoAbortaLaAccionReal(unittest.TestCase):
    """Bug real (15 sep 2026): un timeout de red hizo que Telegram considerara
    vencidos varios callbacks; query.answer() -- primera línea de
    cb_ticket_close/cb_ticket_pause, sin try/except -- lanzó 'Query is too
    old...', y como no había nada alrededor que lo atajara, el handler entero
    abortó ahí mismo. El técnico apretó Cerrar/Pausar en el reporte de
    pendientes y no pasó nada -- ni el toast, ni el cierre real del pendiente,
    ni ningún aviso de error. Verificado en el log de producción de Ópera:
    5 'Query is too old' seguidos de un 'Timed out', ese mismo minuto."""

    def test_no_queda_ningun_await_query_answer_directo(self):
        """Si alguien vuelve a escribir 'await query.answer(...)' a mano en
        vez de usar _safe_answer, ese botón queda otra vez a merced de
        cualquier hipo de red."""
        texto = (RAIZ / "core" / "bot.py").read_text(errors="replace")
        # Las únicas 2 apariciones legítimas son dentro de la propia
        # implementación de _safe_answer.
        directas = re.findall(r"await query\.answer\(", texto)
        self.assertEqual(
            len(directas), 2,
            "debe haber query.answer() sin envolver solo dentro de _safe_answer "
            "-- cualquier otro handler debe usar _safe_answer(query, ...)",
        )

    def test_safe_answer_no_propaga_si_telegram_rechaza(self):
        """No podemos importar core/bot.py sin el token real de Telegram en
        este entorno de test -- se ejecuta el cuerpo de _safe_answer aislado,
        con un objeto que falla igual que lo hizo Telegram en producción."""
        import asyncio

        class QueryQueFallaComoTelegram:
            async def answer(self, *a, **kw):
                raise RuntimeError("Query is too old and response timeout expired or query id is invalid")

        async def _safe_answer(query, text: str = "") -> None:
            try:
                if text:
                    await query.answer(text)
                else:
                    await query.answer()
            except Exception:
                pass

        # No debe lanzar -- ese es exactamente el comportamiento que faltaba.
        asyncio.run(_safe_answer(QueryQueFallaComoTelegram(), "Cerrando..."))


if __name__ == "__main__":
    unittest.main()
