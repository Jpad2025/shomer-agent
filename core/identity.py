"""Identidad del cliente — SITE_NAME leído desde base.client_name de la API Shomer."""
import os
import urllib.request
import json

SITE_NAME = os.environ.get("SITE_NAME", "Shomer")


def _load_from_api() -> None:
    global SITE_NAME
    try:
        req = urllib.request.urlopen("http://127.0.0.1:8000/setup/status", timeout=5)
        data = json.loads(req.read())
        name = (data.get("current") or {}).get("client_name") or ""
        if name.strip():
            SITE_NAME = name.strip()
    except Exception:
        pass


_load_from_api()


def header() -> str:
    return f"🏢 *{SITE_NAME}*\n"


def alert_prefix() -> str:
    return f"[{SITE_NAME}] "
