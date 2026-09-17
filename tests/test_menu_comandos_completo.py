"""17 sep 2026: revisión general del bot en busca de inconsistencias --
/silenciar tiene su propio comando real, registrado y funcional
(cmd_silenciar), pero nunca se agregó a la lista de BotCommand que arma el
menú de Telegram (el autocompletado que aparece al escribir "/"). Un
técnico que no supiera de memoria que existe /silenciar nunca lo iba a
descubrir -- y justo ese mismo día se le pidió al chat libre que lo
recomendara activamente para pausar avisos.

Esta prueba escanea el código fuente de bot.py (no requiere levantar el
bot) para que cualquier comando nuevo con handler real y sin entrada en el
menú se detecte solo, en vez de encontrarse por accidente meses después.
"""
import re
from pathlib import Path

BOT_PY = Path(__file__).resolve().parent.parent / "core" / "bot.py"


def _comandos_en_menu() -> set[str]:
    src = BOT_PY.read_text(encoding="utf-8")
    return set(re.findall(r'BotCommand\(\s*"([a-z_]+)"', src))


def _comandos_registrados() -> set[str]:
    src = BOT_PY.read_text(encoding="utf-8")
    bloque = re.search(
        r"for cmd, fn in \[(.*?)\]:\s*\n\s*app\.add_handler\(CommandHandler\(cmd, fn\)\)",
        src, re.S,
    )
    assert bloque, "no se encontró el bloque de registro de comandos -- ¿cambió la estructura?"
    return set(re.findall(r'\(\s*"([a-z_]+)"\s*,', bloque.group(1)))


# Comandos con handler real que, a propósito, no van en el menú (internos,
# de arranque, o alias que no aportan al listar dos veces lo mismo).
_A_PROPOSITO_FUERA_DEL_MENU = {
    "start",         # Telegram lo maneja aparte, no necesita estar en el menú
    "aprobar_task",  # flujo interno vía botón, no se escribe a mano
    "autobloqueo",   # alias de /seguro, que sí está en el menú
}


def test_todo_comando_del_menu_tiene_handler_registrado():
    """La dirección grave: un comando que el técnico ve y toca, y no hace
    nada. Ya se verificó que hoy no pasa -- esta prueba lo mantiene así."""
    menu = _comandos_en_menu()
    registrados = _comandos_registrados()
    huerfanos = menu - registrados
    assert not huerfanos, f"en el menú pero SIN handler real: {huerfanos}"


def test_comandos_de_seguridad_estan_en_el_menu():
    """Regresión directa: /silenciar existía y funcionaba, pero no aparecía
    en el menú -- un técnico no tenía cómo descubrirlo sin que se lo dijera
    el chat o alguien más. bloquear/desbloquear son su comparación directa
    (misma sección del menú, mismo nivel de importancia)."""
    menu = _comandos_en_menu()
    for cmd in ("bloquear", "desbloquear", "silenciar"):
        assert cmd in menu, f"/{cmd} tiene handler pero no aparece en el menú de Telegram"


def test_comandos_registrados_sin_menu_son_los_esperados():
    """No es un bug que existan -- pero si aparece uno nuevo sin querer
    (o alguien quita uno de este set sin agregarlo al menú), esta prueba
    avisa en vez de dejarlo pasar en silencio."""
    menu = _comandos_en_menu()
    registrados = _comandos_registrados()
    fuera_del_menu = registrados - menu
    assert fuera_del_menu == _A_PROPOSITO_FUERA_DEL_MENU, (
        f"comandos registrados sin entrada en el menú, no reconocidos como "
        f"intencionales: {fuera_del_menu - _A_PROPOSITO_FUERA_DEL_MENU}"
    )
