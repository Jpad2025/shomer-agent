"""
Backup completo del sistema Shomer.

Flujo:
1. Via SSH al host: crea tarball de DBs + configs en /storage/shomer-agent/data/backups/
2. Esa carpeta está montada como /app/data/backups/ en el container → accesible aquí
3. Rotación: mantiene máximo MAX_BACKUPS=2 (borra el más antiguo)
4. Subida opcional a B2 si BACKUP_B2_KEY_ID / APP_KEY / BUCKET_ID están en .env
"""
import os
import hashlib
import logging
import requests
from datetime import datetime
from pathlib import Path

from core.repair import _ssh_run

log = logging.getLogger("shomer-backup")

BACKUP_DIR_HOST      = "/storage/shomer-agent/data/backups"
BACKUP_DIR_CONTAINER = Path("/app/data/backups")
MAX_BACKUPS          = 2

B2_KEY_ID    = os.environ.get("BACKUP_B2_KEY_ID", "")
B2_APP_KEY   = os.environ.get("BACKUP_B2_APP_KEY", "")
B2_BUCKET_ID = os.environ.get("BACKUP_B2_BUCKET_ID", "")

# Archivos individuales críticos
_FILES = [
    "/opt/network_monitor/network_monitor.db",
    "/storage/db/inventory.db",
    "/etc/shomer/shomer-runtime.env",
    "/storage/shomer-agent/data/devices.json",
    "/storage/shomer-agent/.env",
    "/etc/systemd/system/shomer-guardian.service",
    "/etc/systemd/system/shomer-tools.service",
]

# Directorios a incluir recursivamente
_DIRS = [
    "/etc/nginx/sites-available",
    "/etc/suricata/rules",
]


def create_backup() -> tuple[bool, str, int]:
    """
    Crea backup completo via SSH.
    Retorna (ok, mensaje_formateado, tamaño_mb).
    """
    BACKUP_DIR_CONTAINER.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"shomer_backup_{ts}.tar.gz"
    dest     = f"{BACKUP_DIR_HOST}/{filename}"

    _ssh_run(f"sudo mkdir -p {BACKUP_DIR_HOST}")

    files_part = " ".join(f'"{f}"' for f in _FILES)
    dirs_part  = " ".join(f'"{d}"' for d in _DIRS)
    cmd = (
        f"sudo tar -czf {dest} --ignore-failed-read {files_part} {dirs_part} "
        f"2>/dev/null; echo EXIT:$?"
    )
    ok, out = _ssh_run(cmd, timeout=120)
    if "EXIT:0" not in out and not ok:
        return False, f"Error creando backup: {out[:200]}", 0

    _, size_out = _ssh_run(f"sudo du -m {dest} | cut -f1")
    try:
        size_mb = int(size_out.strip())
    except ValueError:
        size_mb = 0

    _rotate()

    b2_msg = ""
    if B2_KEY_ID and B2_APP_KEY and B2_BUCKET_ID:
        b2_ok, b2_detail = _upload_b2(filename)
        b2_msg = f"\n☁️ B2: {'✅ subido' if b2_ok else '⚠️ ' + b2_detail}"

    return True, f"✅ `{filename}` — {size_mb} MB{b2_msg}", size_mb


def _rotate():
    """Borra backups que excedan MAX_BACKUPS, empezando por el más antiguo."""
    backups = sorted(BACKUP_DIR_CONTAINER.glob("shomer_backup_*.tar.gz"), key=lambda p: p.stat().st_mtime)
    while len(backups) > MAX_BACKUPS:
        try:
            backups[0].unlink()
            log.info("Backup antiguo eliminado: %s", backups[0].name)
        except Exception as e:
            log.warning("No se pudo eliminar backup antiguo %s: %s", backups[0].name, e)
        backups = backups[1:]


def list_backups() -> list[dict]:
    """Lista backups disponibles ordenados del más reciente al más antiguo."""
    BACKUP_DIR_CONTAINER.mkdir(parents=True, exist_ok=True)
    result = []
    for p in sorted(BACKUP_DIR_CONTAINER.glob("shomer_backup_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = p.stat()
        result.append({
            "name":    p.name,
            "size_mb": round(stat.st_size / 1_048_576, 1),
            "ts":      datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return result


def restore_backup(backup_name: str) -> tuple[bool, str]:
    """
    Restaura un backup (solo developer).
    Para shomer-guardian y shomer-tools, extrae el tarball sobre /, reinicia.
    """
    backup_path = f"{BACKUP_DIR_HOST}/{backup_name}"

    ok, out = _ssh_run(f"sudo test -f {backup_path} && echo EXISTS")
    if "EXISTS" not in out:
        return False, f"Backup no encontrado: {backup_name}"

    _ssh_run("sudo systemctl stop shomer-guardian shomer-tools", timeout=30)

    ok, out = _ssh_run(
        f"sudo tar -xzf {backup_path} -C / --overwrite 2>&1 | tail -3",
        timeout=120
    )
    _ssh_run("sudo systemctl daemon-reload", timeout=15)
    ok2, out2 = _ssh_run(
        "sudo systemctl start shomer-guardian shomer-tools", timeout=30
    )

    if not ok:
        return False, f"Archivos restaurados con advertencias: {out}\nServicios: {'OK' if ok2 else out2}"

    return True, f"Restauración completa. Servicios: {'✅ activos' if ok2 else '⚠️ ' + out2}"


def _upload_b2(filename: str) -> tuple[bool, str]:
    """Sube el backup a Backblaze B2 usando la API nativa + requests."""
    local_path = BACKUP_DIR_CONTAINER / filename
    if not local_path.exists():
        return False, "Archivo no encontrado en container"

    try:
        auth_resp = requests.post(
            "https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
            auth=(B2_KEY_ID, B2_APP_KEY),
            timeout=15,
        )
        auth_resp.raise_for_status()
        auth      = auth_resp.json()
        api_url   = auth["apiUrl"]
        auth_token = auth["authorizationToken"]

        upload_resp = requests.post(
            f"{api_url}/b2api/v2/b2_get_upload_url",
            headers={"Authorization": auth_token},
            json={"bucketId": B2_BUCKET_ID},
            timeout=15,
        )
        upload_resp.raise_for_status()
        upload = upload_resp.json()

        with open(local_path, "rb") as f:
            data = f.read()
        sha1 = hashlib.sha1(data).hexdigest()

        result = requests.post(
            upload["uploadUrl"],
            headers={
                "Authorization":    upload["authorizationToken"],
                "X-Bz-File-Name":   filename,
                "Content-Type":     "application/gzip",
                "Content-Length":   str(len(data)),
                "X-Bz-Content-Sha1": sha1,
            },
            data=data,
            timeout=300,
        )
        result.raise_for_status()
        return True, "OK"

    except Exception as e:
        log.warning("B2 upload error: %s", e)
        return False, str(e)[:80]
