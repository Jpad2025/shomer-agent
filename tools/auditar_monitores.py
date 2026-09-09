#!/usr/bin/env python3
"""Cruza los monitores del agente: definidos vs realmente lanzados.

Un `async def watch_*` que nadie arranca no vigila nada, y no hay ninguna señal
de que falte: el bot arranca igual, sin error, y ese monitor simplemente no
existe en la práctica. Al revés también importa: si /salud dice que hay N
monitores activos y el número real es otro, el técnico confía en una vigilancia
que no está ocurriendo.

Uso:  python3 tools/auditar_monitores.py
Sale con código 1 si hay monitores definidos que nadie lanza.
"""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "core"

# Monitores que existen a propósito sin lanzarse desde start_monitors():
# los arranca otro módulo o se invocan puntualmente.
EXCEPCIONES_CONOCIDAS: set[str] = set()


def main() -> int:
    definidos: dict[str, str] = {}
    lanzados: set[str] = set()

    for f in sorted(BASE.glob("*.py")):
        texto = f.read_text(errors="replace")
        # Solo funciones públicas: las que empiezan con "_" son auxiliares que
        # se llaman con await desde otro sitio, no tareas de vigilancia
        # (ej. _send_reminder en incident_escalation.py).
        for m in re.finditer(
            r"^async def ((?:watch|daily|evening)_\w+|[a-z]\w*_reminder)\s*\(", texto, re.M
        ):
            definidos[m.group(1)] = f.name
        # create_task(x(...)) y create_task(modulo.x(...))
        for m in re.finditer(r"create_task\(\s*(?:\w+\.)?(\w+)\s*\(", texto):
            lanzados.add(m.group(1))

    print(f"monitores definidos : {len(definidos)}")
    print(f"funciones lanzadas  : {len(lanzados)}\n")

    huerfanos = {
        n: f for n, f in sorted(definidos.items())
        if n not in lanzados and n not in EXCEPCIONES_CONOCIDAS
    }

    problemas = 0
    if huerfanos:
        problemas += 1
        print("*** MONITORES DEFINIDOS QUE NADIE LANZA (no vigilan nada) ***")
        for n, f in huerfanos.items():
            print(f"  {n:34} definido en {f}")
        print()

    # Segundo cruce: lo que /monitores le MUESTRA al técnico contra lo que de
    # verdad registra actividad. MONITOR_GROUPS se edita a mano y se
    # desincroniza sola: si un monitor real falta ahí, el técnico cree que ese
    # frente no está vigilado (pasó con watch_poller_heartbeat, el que detecta
    # "Guardian congelado"). Si sobra, cree que hay vigilancia que no existe.
    bot = (BASE / "bot.py").read_text(errors="replace")
    grupos = re.search(r"MONITOR_GROUPS\s*=\s*\[(.*?)\n\]", bot, re.S)
    mostrados = set(re.findall(r'"([a-z_]+)"', grupos.group(1))) if grupos else set()

    con_tick: set[str] = set()
    for f in BASE.glob("*.py"):
        con_tick |= set(re.findall(r'_tick\(\s*"([a-z_]+)"', f.read_text(errors="replace")))

    print(f"mostrados en /monitores : {len(mostrados)}")
    print(f"registran actividad     : {len(con_tick)}\n")

    faltan = sorted(con_tick - mostrados)
    sobran = sorted(mostrados - con_tick)
    if faltan:
        problemas += 1
        print("*** CORREN DE VERDAD PERO NO APARECEN EN /monitores ***")
        for n in faltan:
            print(f"  {n}")
        print()
    if sobran:
        problemas += 1
        print("*** APARECEN EN /monitores PERO NO REGISTRAN ACTIVIDAD ***")
        for n in sobran:
            print(f"  {n}")
        print()

    if problemas:
        return 1

    print("OK — todos los monitores se lanzan y la lista mostrada coincide con la real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
