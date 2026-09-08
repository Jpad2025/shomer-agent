#!/usr/bin/env python3
"""Cruza los botones inline que el bot GENERA contra los handlers que los atienden.

Un botón de Telegram cuyo callback_data no case con ningún CallbackQueryHandler
no hace nada al pulsarlo, y no hay forma de notarlo salvo probándolo a mano.
Pasó de verdad: el botón "🔓 Desbloquear" de las alertas de Hunter mandaba
"block_unblock_<ip>" cuando el handler espera "unblock_confirm:<ip>" — estuvo
muerto hasta el 8 sep 2026, justo el día en que Hunter bloqueó los DNS de
Google y el técnico no pudo liberarlos desde Telegram.

Uso:  python3 tools/auditar_callbacks.py
Sale con código 1 si encuentra botones sin handler.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "core"

# callback_data="literal" | callback_data=f"prefijo{var}" | fmt.btn(txt, "data")
PAT_CB = re.compile(r"""callback_data\s*=\s*f?["']([^"']*)["']""")
PAT_BTN = re.compile(r"""fmt\.btn\(\s*[^,]+,\s*f?["']([^"']*)["']""")
PAT_HANDLER = re.compile(
    r"""CallbackQueryHandler\(\s*(\w+)\s*,\s*pattern\s*=\s*r?["']([^"']+)["']"""
)


def literal_de(plantilla: str) -> str:
    """Convierte 'unblock_confirm:{ip}' en una muestra concreta comprobable."""
    return re.sub(r"\{[^}]*\}", "X", plantilla)


def main() -> int:
    generados: dict[str, list[str]] = {}
    handlers: list[tuple[str, str]] = []

    for f in sorted(BASE.glob("*.py")):
        texto = f.read_text(errors="replace")
        for i, linea in enumerate(texto.splitlines(), 1):
            for pat in (PAT_CB, PAT_BTN):
                for m in pat.finditer(linea):
                    crudo = m.group(1).strip()
                    if not crudo:
                        continue
                    generados.setdefault(crudo, []).append(f"{f.name}:{i}")
            for m in PAT_HANDLER.finditer(linea):
                handlers.append((m.group(1), m.group(2)))

    print(f"callback_data distintos : {len(generados)}")
    print(f"handlers con patrón     : {len(handlers)}\n")

    def atiende(valor: str) -> str:
        for fn, pat in handlers:
            try:
                if re.match(pat, valor):
                    return fn
            except re.error:
                continue
        return ""

    muertos = []
    for crudo, donde in sorted(generados.items()):
        muestra = literal_de(crudo)
        if not atiende(muestra):
            muertos.append((crudo, muestra, donde))

    if muertos:
        print("*** BOTONES SIN HANDLER — no hacen nada al pulsarlos ***")
        for crudo, muestra, donde in muertos:
            print(f"  {crudo!r} (ej. {muestra!r})")
            print(f"      generado en: {', '.join(donde[:3])}")
        return 1

    print("OK — todos los botones inline tienen un handler que los atiende.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
