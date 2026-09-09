#!/usr/bin/env python3
"""Cruza los endpoints que el agente INVOCA contra los que el backend EXPONE.

El agente y network_monitor son dos repos que se despliegan por separado: un
endpoint que se renombra o se borra de un lado deja al otro llamando a una ruta
que ya no existe, y el fallo aparece recién en producción como un comando que
"no responde" — nunca como un error de arranque.

Las rutas del backend se leen de la aplicación FastAPI REAL (app.routes), no
parseando decoradores: los routers se componen anidados y con prefijos
(casador.py agrega los sub-routers bajo /remedies), así que cualquier parser
por texto da falsos positivos. Preguntarle a la app es la única fuente fiel.

Uso:  python3 tools/auditar_endpoints.py
Sale con código 1 si alguna ruta invocada no existe en el backend.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

AGENTE = Path(__file__).resolve().parent.parent / "core"
NETWORK_MONITOR = "/opt/network_monitor"

PAT_LLAMADA = re.compile(r"""\b_(?:get|post|put|patch|delete)\(\s*f?["']([^"']+)["']""")


def rutas_del_backend() -> set[str]:
    """Rutas reales de las dos apps (8000 core y 8001 tools)."""
    sys.path.insert(0, NETWORK_MONITOR)
    rutas: set[str] = set()
    for modulo, nombre in (("app.api.main", "app"), ("app.api.main_tools", "app")):
        try:
            mod = __import__(modulo, fromlist=[nombre])
            for r in getattr(mod, nombre).routes:
                if getattr(r, "path", None):
                    rutas.add(normalizar(r.path))
        except Exception as e:  # pragma: no cover
            print(f"  aviso: no se pudo cargar {modulo}: {e}", file=sys.stderr)
    return rutas


def normalizar(ruta: str) -> str:
    """/infra/snmp/{ip} y /infra/snmp/1.2.3.4 deben comparar igual.

    La query string no es parte de la ruta: el agente construye llamadas como
    f"/audit/network/findings{qs}", donde qs puede ser "" o "?severity=alta".
    """
    ruta = ruta.split("?", 1)[0]
    ruta = re.sub(r"\{[^}]*\}", "{}", ruta)
    ruta = re.sub(r"\{\}$", "", ruta)  # placeholder final = query string vacía
    return "/" + ruta.strip("/")


def main() -> int:
    expuestas = rutas_del_backend()
    if not expuestas:
        print("No se pudieron leer las rutas del backend; nada que comparar.")
        return 0

    invocadas: dict[str, list[str]] = {}
    for f in sorted(AGENTE.glob("*.py")):
        for i, linea in enumerate(f.read_text(errors="replace").splitlines(), 1):
            for m in PAT_LLAMADA.finditer(linea):
                invocadas.setdefault(normalizar(m.group(1)), []).append(f"{f.name}:{i}")

    print(f"rutas expuestas por el backend : {len(expuestas)}")
    print(f"rutas invocadas por el agente  : {len(invocadas)}\n")

    def existe(ruta: str) -> bool:
        if ruta in expuestas:
            return True
        partes = ruta.strip("/").split("/")
        for exp in expuestas:
            pe = exp.strip("/").split("/")
            if len(pe) != len(partes):
                continue
            if all(a == b or a == "{}" or b == "{}" for a, b in zip(pe, partes)):
                return True
        return False

    faltantes = {r: d for r, d in sorted(invocadas.items()) if not existe(r)}
    if faltantes:
        print("*** EL AGENTE LLAMA RUTAS QUE EL BACKEND NO EXPONE ***")
        for ruta, donde in faltantes.items():
            print(f"  {ruta}")
            print(f"      desde: {', '.join(donde[:3])}")
        return 1

    print("OK — todas las rutas que invoca el agente existen en el backend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
