#!/usr/bin/env python3
"""Cruza los comandos del bot: registrados vs implementados vs publicados.

Tres listas que tienen que coincidir y se editan por separado, así que se
desincronizan sin que nadie lo note:
  1. los que se registran con CommandHandler (los que Telegram enruta),
  2. la función cmd_* que los atiende (que exista de verdad),
  3. el menú que se publica al usuario (setMyCommands) y la ayuda.

Un comando publicado sin registrar responde silencio. Uno registrado sin
publicar existe pero nadie sabe que existe.

Uso:  python3 tools/auditar_comandos.py
Sale con código 1 si encuentra inconsistencias.
"""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "core"
BOT = BASE / "bot.py"


def main() -> int:
    texto = BOT.read_text(errors="replace")

    # 1) registrados: pares ("cmd", funcion) dentro del bucle de CommandHandler
    bloque = re.search(r"for cmd, fn in \[(.*?)\]:", texto, re.S)
    registrados: dict[str, str] = {}
    if bloque:
        for m in re.finditer(r'\(\s*"([a-z_]+)"\s*,\s*(\w+)\s*\)', bloque.group(1)):
            registrados[m.group(1)] = m.group(2)

    # 2) funciones cmd_* definidas en todo el paquete
    definidas = set()
    for f in BASE.glob("*.py"):
        for m in re.finditer(r"^\s*async def (cmd_\w+)", f.read_text(errors="replace"), re.M):
            definidas.add(m.group(1))

    # 3) publicados en el menú de Telegram (BotCommand)
    publicados = set(re.findall(r'BotCommand\(\s*"([a-z_]+)"', texto))

    print(f"registrados con CommandHandler : {len(registrados)}")
    print(f"funciones cmd_* definidas      : {len(definidas)}")
    print(f"publicados en el menú Telegram : {len(publicados)}\n")

    problemas = 0

    sin_funcion = {c: fn for c, fn in registrados.items() if fn not in definidas}
    if sin_funcion:
        problemas += 1
        print("*** REGISTRADOS PERO SIN FUNCIÓN (romperían al invocarse) ***")
        for c, fn in sorted(sin_funcion.items()):
            print(f"  /{c:18} -> {fn}() no existe")
        print()

    publicados_sin_registrar = publicados - set(registrados)
    if publicados_sin_registrar:
        problemas += 1
        print("*** PUBLICADOS EN EL MENÚ PERO NO REGISTRADOS (responden silencio) ***")
        for c in sorted(publicados_sin_registrar):
            print(f"  /{c}")
        print()

    # Informativo: registrados que no se publican. No es error (hay comandos
    # de developer a propósito), pero conviene verlos.
    no_publicados = set(registrados) - publicados
    if no_publicados:
        print(f"--- registrados pero fuera del menú ({len(no_publicados)}), informativo ---")
        print("   " + " ".join("/" + c for c in sorted(no_publicados)))
        print()

    if problemas:
        return 1
    print("OK — todo comando registrado tiene función, y todo lo publicado está registrado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
