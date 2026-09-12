"""Quién es "gente conocida" en la VPN de este sitio.

Vive aparte de monitor.py a propósito: es lógica de decisión pura, sin nada de
Telegram, así que se puede probar sin el contenedor y razonar sobre ella sola.

El problema que resuelve: las conexiones VPN rutinarias eran el 21,5% de todos
los mensajes del sitio (217 al mes) para avisar que un empleado entró a
trabajar. Pero mandarlas todas al resumen diario, sin más, significaría
enterarse al día siguiente de que alguien desconocido entró de madrugada — que
es justo lo único que ahí importa.

De ahí la distinción: los habituales van al resumen, un usuario nunca visto
avisa al instante.

**Ventana de aprendizaje.** Una instalación nueva no conoce a nadie, así que
durante los primeros VPN_APRENDIZAJE_DIAS registra a todo el que entra SIN
alertar. Recién pasada esa ventana un usuario nuevo se considera digno de aviso.
Sin esto, un Shomer recién instalado dispararía un aviso por cada empleado del
hotel la primera semana y el técnico aprendería a ignorarlos — lo contrario de
lo que se busca.

Nada se precarga a mano: cada sitio aprende su propia gente (norma B.1).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime

log = logging.getLogger("shomer-vpn-usuarios")

KNOWLEDGE_DB = os.environ.get("KNOWLEDGE_DB_PATH", "/app/data/knowledge.db")
APRENDIZAJE_DIAS = float(os.environ.get("VPN_APRENDIZAJE_DIAS", "14"))

_DDL = (
    "CREATE TABLE IF NOT EXISTS vpn_usuarios_conocidos ("
    "usuario TEXT PRIMARY KEY, primera_vez TEXT DEFAULT (datetime('now')), "
    "veces INTEGER DEFAULT 1)"
)


def es_conocido(user: str) -> bool:
    """True si NO hay que alertar por este usuario.

    Devuelve True cuando el usuario ya entró antes, cuando el sitio sigue en su
    ventana de aprendizaje, o ante cualquier duda (sin nombre, error de base de
    datos). El criterio por defecto es no interrumpir: una falsa alarma de
    seguridad enseña al técnico a ignorar los avisos.
    """
    user = (user or "").strip().lower()
    if not user or user == "desconocido":
        return True  # sin nombre no se puede afirmar que sea nuevo

    try:
        con = sqlite3.connect(KNOWLEDGE_DB, timeout=3)
    except Exception as e:
        log.debug("vpn usuarios: sin acceso a la base (%s)", e)
        return True

    try:
        con.execute(_DDL)
        row = con.execute(
            "SELECT veces FROM vpn_usuarios_conocidos WHERE usuario=?", (user,)
        ).fetchone()
        if row:
            con.execute(
                "UPDATE vpn_usuarios_conocidos SET veces=veces+1 WHERE usuario=?",
                (user,),
            )
            con.commit()
            return True

        # Usuario nuevo: ¿este sitio ya terminó de conocer a su gente?
        primera = con.execute(
            "SELECT MIN(primera_vez) FROM vpn_usuarios_conocidos"
        ).fetchone()
        con.execute("INSERT INTO vpn_usuarios_conocidos (usuario) VALUES (?)", (user,))
        con.commit()

        if not primera or not primera[0]:
            return True  # es el primero que se ve: nada con qué comparar
        try:
            inicio = datetime.fromisoformat(str(primera[0]))
        except Exception:
            return True
        dias = (datetime.now() - inicio).total_seconds() / 86400
        return dias < APRENDIZAJE_DIAS
    except Exception as e:
        log.debug("vpn usuarios: %s", e)
        return True
    finally:
        try:
            con.close()
        except Exception:
            pass
