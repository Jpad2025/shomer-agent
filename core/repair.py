"""
Diagnóstico y reparación de servicios Shomer.
- check_services / full_diagnosis: TCP desde el container
- restart_service / kill_zombie / restart_suricata: SSH → sudo en el host
- disk_cleanup: limpieza automática por niveles (sin autorización si es seguro)
"""
import socket
import logging
import paramiko

log = logging.getLogger("shomer-repair")

SSH_HOST = "127.0.0.1"
SSH_USER = "usb_admin"
SSH_KEY  = "/app/data/agent_restart_key"

SERVICES = {
    "guardian": {
        "label": "Guardian (API :8000)",
        "host":  "127.0.0.1",
        "port":  8000,
        "unit":  "shomer-guardian.service",
    },
    "tools": {
        "label": "Tools (API :8001)",
        "host":  "127.0.0.1",
        "port":  8001,
        "unit":  "shomer-tools.service",
    },
    "nginx": {
        "label": "Nginx (proxy HTTPS)",
        "host":  "127.0.0.1",
        "port":  80,
        "unit":  "nginx.service",
    },
}

# Niveles de limpieza automática de disco
# safe: sin autorización, siempre seguro
# warn: autorización del developer antes de ejecutar
DISK_CLEANUP_RULES = [
    {
        "id":    "journal_vacuum",
        "label": "Journal del sistema (>7 días)",
        "cmd":   "sudo journalctl --vacuum-time=7d",
        "level": "safe",
    },
    {
        "id":    "shomer_logs_old",
        "label": "Logs Shomer (>7 días)",
        "cmd":   "sudo find /var/log/shomer -name '*.log.*' -mtime +7 -delete 2>/dev/null; sudo find /var/log/shomer -name '*.log' -size +50M -exec truncate -s 10M {} \\;",
        "level": "safe",
    },
    {
        "id":    "tmp_cleanup",
        "label": "Archivos temporales /tmp (>1 día)",
        "cmd":   "sudo find /tmp -maxdepth 1 -mtime +1 -delete 2>/dev/null || true",
        "level": "safe",
    },
    {
        "id":    "docker_prune",
        "label": "Imágenes Docker sin uso",
        "cmd":   "sudo docker image prune -f",
        "level": "warn",   # requiere autorización — podría afectar otras imágenes
    },
    {
        "id":    "apt_cache",
        "label": "Cache APT",
        "cmd":   "sudo apt-get clean",
        "level": "safe",
    },
    {
        "id":    "restic_prune",
        "label": "Prune Restic local (snapshots > 7 días en /srv/shomer_backups)",
        "cmd":   "RESTIC_PASSWORD_FILE=/home/usb_admin/.restic-local-pass "
                 "/usr/bin/restic -r /srv/shomer_backups/staging forget --keep-daily=7 --prune",
        "level": "warn",   # borra snapshots — requiere autorización del admin
    },
]


# ── Verificación por TCP ──────────────────────────────────────────────────────

def _tcp_ok(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_services() -> dict[str, str]:
    return {k: ("active" if _tcp_ok(s["host"], s["port"]) else "inactive")
            for k, s in SERVICES.items()}


def full_diagnosis() -> str:
    lines = ["*Estado servicios Shomer:*\n"]
    for key, state in check_services().items():
        icon = "✅" if state == "active" else "❌"
        lines.append(f"{icon} `{SERVICES[key]['label']}`: {state}")
    return "\n".join(lines)


def failing_services() -> list[str]:
    return [k for k, s in check_services().items() if s != "active"]


# ── SSH al host ───────────────────────────────────────────────────────────────

def _ssh_run(cmd: str, timeout: int = 30) -> tuple[bool, str]:
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            SSH_HOST, username=SSH_USER,
            key_filename=SSH_KEY, timeout=5,
            look_for_keys=False, allow_agent=False,
        )
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        code = stdout.channel.recv_exit_status()
        client.close()
        return code == 0, out or err or "OK"
    except Exception as e:
        log.warning("SSH error: %s", e)
        return False, str(e)


def get_journal(unit_key: str, lines: int = 20) -> str:
    svc = SERVICES.get(unit_key)
    if not svc:
        return ""
    ok, out = _ssh_run(f"journalctl -u {svc['unit']} -n {lines} --no-pager")
    return out if ok else f"[No se pudo obtener journal: {out}]"


def restart_service(unit_key: str) -> tuple[bool, str]:
    svc = SERVICES.get(unit_key)
    if not svc:
        return False, "Servicio no reconocido"
    return _ssh_run(f"sudo systemctl restart {svc['unit']}", timeout=30)


def kill_zombie(port: int) -> tuple[bool, str]:
    return _ssh_run(f"sudo lsof -ti:{port} | xargs -r sudo kill -9")


def restart_suricata() -> tuple[bool, str]:
    return _ssh_run("sudo systemctl restart suricata", timeout=30)


# ── Limpieza de disco ─────────────────────────────────────────────────────────

def run_safe_cleanup() -> list[dict]:
    """
    Ejecuta automáticamente todas las reglas 'safe'.
    Retorna lista de {label, ok, output}.
    """
    results = []
    for rule in DISK_CLEANUP_RULES:
        if rule["level"] != "safe":
            continue
        ok, out = _ssh_run(rule["cmd"], timeout=60)
        results.append({"label": rule["label"], "ok": ok, "output": out[:100]})
        log.info("Disk cleanup [%s]: ok=%s", rule["id"], ok)
    return results


def run_cleanup_rule(rule_id: str) -> tuple[bool, str]:
    """Ejecuta una regla específica por ID (para reglas 'warn' con autorización)."""
    rule = next((r for r in DISK_CLEANUP_RULES if r["id"] == rule_id), None)
    if not rule:
        return False, "Regla no encontrada"
    return _ssh_run(rule["cmd"], timeout=60)


def disk_free_gb() -> float:
    """Lee espacio libre del host via SSH."""
    ok, out = _ssh_run("df / --output=avail -BG | tail -1")
    if ok:
        try:
            return float(out.replace("G", "").strip())
        except ValueError:
            pass
    return -1


def truncate_large_shomer_logs(min_mb: int = 50, target_mb: int = 10) -> list[dict]:
    """
    Trunca archivos /var/log/shomer/*.log mayores a min_mb hasta target_mb.
    TASK-005 — reversible (truncate, no borra).
    """
    cmd = (
        f"find /var/log/shomer -name '*.log' -size +{min_mb}M -type f 2>/dev/null "
        f"| while read -r f; do truncate -s {target_mb}M \"$f\" && echo \"$f\"; done"
    )
    ok, out = _ssh_run(cmd, timeout=120)
    files = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    return [{"file": f, "ok": ok} for f in files] or [{"file": "(ninguno)", "ok": ok}]


def is_suricata_active() -> bool:
    ok, out = _ssh_run("systemctl is-active suricata 2>/dev/null")
    return ok and out.strip() == "active"
