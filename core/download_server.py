"""
Servidor HTTP ligero para servir archivos de descarga temporales.
Corre en background thread (stdlib puro, sin dependencias extra).

Flujo:
  1. Bot descarga el archivo desde Shomer API y llama register_file()
  2. register_file() guarda el archivo en /app/data/downloads/{token}/
  3. Retorna la URL pública: http://HOST_IP:8082/{token}/{filename}
  4. El archivo se borra automáticamente después de TTL segundos (default 30 min)
"""
import os
import time
import secrets
import threading
import logging
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

log = logging.getLogger("shomer-downloads")

DOWNLOADS_DIR = Path("/app/data/downloads")
DOWNLOAD_PORT = int(os.environ.get("DOWNLOAD_PORT", "8082"))
DEFAULT_TTL   = 1800  # 30 minutos

# token -> (dirpath, expires_at)
_registry: dict[str, tuple[Path, float]] = {}
_lock = threading.Lock()


# ── HTTP handler ──────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(self.path).lstrip("/")
        parts = path.split("/", 1)
        if len(parts) != 2:
            self._404()
            return
        token, filename = parts[0], parts[1]

        with _lock:
            entry = _registry.get(token)

        if not entry:
            self._404()
            return

        dirpath, expires_at = entry
        if time.time() > expires_at:
            self._410()
            return

        filepath = dirpath / filename
        if not filepath.exists():
            self._404()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(filepath.stat().st_size))
        self.end_headers()
        with open(filepath, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def _404(self):
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not found")

    def _410(self):
        self.send_response(410)
        self.end_headers()
        self.wfile.write(b"Link expired")

    def log_message(self, fmt, *args):  # silenciar logs HTTP
        pass


# ── Limpieza periódica ────────────────────────────────────────────────────────

def _cleanup_loop():
    while True:
        time.sleep(300)
        now = time.time()
        with _lock:
            expired = [t for t, (_, exp) in _registry.items() if now > exp]
        for token in expired:
            with _lock:
                entry = _registry.pop(token, None)
            if entry:
                dirpath, _ = entry
                shutil.rmtree(dirpath, ignore_errors=True)
                log.debug("Download expirado eliminado: %s", token)


# ── API pública ───────────────────────────────────────────────────────────────

_started = False

def start():
    """Inicia el servidor en background (llamar una vez al arrancar el bot)."""
    global _started
    if _started:
        return
    _started = True
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("", DOWNLOAD_PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="dl-server").start()
    threading.Thread(target=_cleanup_loop, daemon=True, name="dl-cleanup").start()
    log.info("Download server en puerto %d", DOWNLOAD_PORT)


def register_file(data: bytes, filename: str, ttl: int = DEFAULT_TTL) -> str:
    """
    Guarda data en disco con un token único y retorna la URL de descarga.
    ttl: segundos hasta que el link expira (default 30 min).
    """
    token   = secrets.token_urlsafe(16)
    dirpath = DOWNLOADS_DIR / token
    dirpath.mkdir(parents=True, exist_ok=True)

    filepath = dirpath / filename
    filepath.write_bytes(data)

    with _lock:
        _registry[token] = (dirpath, time.time() + ttl)

    host_ip = os.environ.get("SHOMER_HOST", "localhost")
    url = f"http://{host_ip}:{DOWNLOAD_PORT}/{token}/{filename}"
    log.info("Archivo registrado para descarga: %s (%d bytes, ttl=%ds)",
             filename, len(data), ttl)
    return url


def get_download_url(token: str, filename: str) -> str | None:
    """Retorna la URL si el token sigue vigente, None si expiró."""
    with _lock:
        entry = _registry.get(token)
    if not entry:
        return None
    _, expires_at = entry
    if time.time() > expires_at:
        return None
    host_ip = os.environ.get("SHOMER_HOST", "localhost")
    return f"http://{host_ip}:{DOWNLOAD_PORT}/{token}/{filename}"
