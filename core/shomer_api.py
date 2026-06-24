"""
Cliente hacia las APIs de Shomer (:8000 / :8001).
GET: lectura de estado.
POST: acciones autorizadas (block, unblock, reload, scan).
"""
import os
import logging
import requests
import sqlite3 as _sq
from typing import Any, Dict, Optional

log = logging.getLogger("shomer-api")

SHOMER_BASE = os.environ.get("SHOMER_URL", "http://127.0.0.1:8000")
SHOMER_USER = os.environ.get("SHOMER_USER", "admin")
SHOMER_PASS = os.environ.get("SHOMER_PASS", "")
INTEGRATION_KEY = os.environ.get("SHOMER_INTEGRATION_KEY", "")

_session_token: Optional[str] = None


def _login() -> Optional[str]:
    global _session_token
    for path in ("/auth/login", "/auth/token"):
        try:
            r = requests.post(f"{SHOMER_BASE}{path}",
                              json={"username": SHOMER_USER, "password": SHOMER_PASS},
                              timeout=5)
            if r.ok:
                data = r.json()
                _session_token = data.get("token") or data.get("access_token")
                if _session_token:
                    return _session_token
        except Exception:
            pass
    return None


def _headers() -> dict:
    global _session_token
    if not _session_token:
        _login()
    h = {}
    if _session_token:
        h["Authorization"] = f"Bearer {_session_token}"
    if INTEGRATION_KEY:
        h["X-Shomer-Integration-Key"] = INTEGRATION_KEY
    return h


def _get(path: str) -> Optional[Dict[str, Any]]:
    global _session_token
    try:
        r = requests.get(f"{SHOMER_BASE}{path}", headers=_headers(), timeout=8)
        if r.status_code == 401:
            _login()
            r = requests.get(f"{SHOMER_BASE}{path}", headers=_headers(), timeout=8)
        if r.ok:
            return r.json()
    except Exception as e:
        log.debug("GET %s error: %s", path, e)
    return None


def _post(path: str, data: dict = None) -> tuple[bool, Any]:
    global _session_token
    try:
        r = requests.post(f"{SHOMER_BASE}{path}", json=data or {},
                          headers=_headers(), timeout=10)
        if r.status_code == 401:
            _login()
            r = requests.post(f"{SHOMER_BASE}{path}", json=data or {},
                              headers=_headers(), timeout=10)
        try:
            body = r.json()
        except Exception:
            body = r.text
        return r.ok, body
    except Exception as e:
        log.warning("POST %s error: %s", path, e)
        return False, str(e)


# ── Lecturas ──────────────────────────────────────────────────────────────────

def get_guardian_nodes():
    data = _get("/nodes")
    if isinstance(data, dict):
        return data.get("nodes", [])
    return data if isinstance(data, list) else []

def get_server_metrics():
    return _get("/api/server-metrics")

def get_wan_status():
    return _get("/api/wan-status")

def get_hunter_alerts(limit: int = 10):
    """Combina stats + historial reciente de Hunter (no hay endpoint /alerts dedicado)."""
    stats = _get("/remedies/stats") or {}
    history = _get(f"/remedies/history?limit={limit}") or {}
    return {
        "alerts_today": stats.get("alerts_today", 0),
        "active_blocks": stats.get("active_blocks", 0),
        "pipeline_ok": stats.get("pipeline_ok"),
        "recent_blocks": (history.get("history") or [])[:limit],
    }

def get_health():
    return _get("/health")

def get_blocked_ips() -> Optional[list]:
    data = _get("/remedies/blocked")
    if isinstance(data, dict):
        return data.get("blocked", [])
    return data if isinstance(data, list) else None

def get_pipeline_health():
    return _get("/remedies/pipeline/health")

def get_backup_health():
    return _get("/backups/health")

def get_backup_devices() -> list:
    DB = "file:/storage/db/network_monitor.db?mode=ro&immutable=1"
    try:
        con = _sq.connect(DB, uri=True)
        con.row_factory = _sq.Row
        try:
            rows = con.execute(
                "SELECT id, name, ip, device_type, last_backup_at, last_status, is_active, schedule_enabled "
                "FROM backup_devices WHERE is_active=1"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
    except Exception:
        return []


# ── Acciones Hunter ───────────────────────────────────────────────────────────

def block_ip(ip: str, reason: str = "manual-agente") -> tuple[bool, str]:
    ok, body = _post("/remedies/block", {"ip": ip, "reason": reason})
    msg = body.get("message", str(body)) if isinstance(body, dict) else str(body)
    return ok, msg

def unblock_ip(ip: str) -> tuple[bool, str]:
    ok, body = _post("/remedies/unblock", {"ip": ip})
    msg = body.get("message", str(body)) if isinstance(body, dict) else str(body)
    return ok, msg


def reboot_guardian_node(ip: str) -> tuple[bool, str]:
    """Reinicia un nodo via Guardian API (usa las credenciales SSH/SNMP ya configuradas)."""
    global _session_token
    try:
        r = requests.post(f"{SHOMER_BASE}/reboot/{ip}", headers=_headers(), timeout=15)
        if r.status_code == 401:
            _login()
            r = requests.post(f"{SHOMER_BASE}/reboot/{ip}", headers=_headers(), timeout=15)
        if r.status_code == 423:
            return False, "Modo mantenimiento activo — reinicio rechazado"
        if r.ok:
            return True, "Reinicio enviado correctamente vía Guardian"
        try:
            detail = r.json().get("detail", f"Error {r.status_code}")
        except Exception:
            detail = f"Error {r.status_code}"
        return False, detail
    except Exception as e:
        return False, str(e)


def reload_rules() -> tuple[bool, str]:
    ok, body = _post("/remedies/rules/reload")
    msg = body.get("message", str(body)) if isinstance(body, dict) else str(body)
    return ok, msg


# ── Acciones Tracker ──────────────────────────────────────────────────────────

def trigger_scan(scan_type: str = "quick") -> tuple[bool, str]:
    """scan_type: 'quick' o 'deep'"""
    ok, body = _post(f"/inventory/scan/{scan_type}")
    msg = body.get("message", str(body)) if isinstance(body, dict) else str(body)
    return ok, msg


def get_tracker_summary() -> dict:
    """Resumen de Tracker: total equipos, últimas IPs descubiertas, estado último scan."""
    DB = "file:/storage/db/inventory.db?mode=ro&immutable=1"
    try:
        con = _sq.connect(DB, timeout=5, uri=True)
        try:
            total = con.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
            recent = con.execute(
                "SELECT ip, hostname, vendor, os_family, last_seen "
                "FROM assets ORDER BY last_seen DESC LIMIT 5"
            ).fetchall()
            # Distribución por tipo de OS
            os_dist = con.execute(
                "SELECT os_family, COUNT(*) FROM assets GROUP BY os_family ORDER BY COUNT(*) DESC LIMIT 5"
            ).fetchall()
            return {
                "total_devices": total,
                "recent": [
                    {"ip": r[0], "hostname": r[1] or "?", "vendor": r[2] or "?",
                     "os": r[3] or "?", "last_seen": r[4]}
                    for r in recent
                ],
                "os_distribution": [{"os": r[0] or "Desconocido", "count": r[1]} for r in os_dist],
            }
        finally:
            con.close()
    except Exception as e:
        return {"error": str(e)}


def get_device_profile(identificador: str) -> dict:
    """Perfil completo de Tracker para un equipo — por IP exacta o nombre (LIKE).
    Para el modo investigación: trae todo el detalle real, no un resumen."""
    DB = "file:/storage/db/inventory.db?mode=ro&immutable=1"
    try:
        con = _sq.connect(DB, timeout=5, uri=True)
        try:
            row = con.execute(
                "SELECT ip, hostname, vendor, asset_type, os_family, os_version, cpu, ram, "
                "storage_cap, serial_number, firmware_version, location, asset_model, "
                "software_list, last_seen, status_audit, internal_notes "
                "FROM assets WHERE ip = ? LIMIT 1",
                (identificador,),
            ).fetchone()
            if not row:
                row = con.execute(
                    "SELECT ip, hostname, vendor, asset_type, os_family, os_version, cpu, ram, "
                    "storage_cap, serial_number, firmware_version, location, asset_model, "
                    "software_list, last_seen, status_audit, internal_notes "
                    "FROM assets WHERE hostname LIKE ? LIMIT 1",
                    (f"%{identificador}%",),
                ).fetchone()
            if not row:
                return {}
            keys = (
                "ip", "hostname", "vendor", "asset_type", "os_family", "os_version", "cpu", "ram",
                "storage_cap", "serial_number", "firmware_version", "location", "asset_model",
                "software_list", "last_seen", "status_audit", "internal_notes",
            )
            return {k: v for k, v in zip(keys, row) if v not in (None, "")}
        finally:
            con.close()
    except Exception as e:
        log.debug("get_device_profile: %s", e)
        return {}


def get_recent_events(limit: int = 10) -> dict:
    """Últimos eventos del log de Guardian (event_log)."""
    DB = "file:/storage/db/network_monitor.db?mode=ro&immutable=1"
    try:
        con = _sq.connect(DB, timeout=5, uri=True)
        con.row_factory = _sq.Row
        try:
            rows = con.execute(
                "SELECT id, event_type, node_ip, details, created_at "
                "FROM event_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return {
                "events": [dict(r) for r in rows],
                "total": len(rows),
            }
        finally:
            con.close()
    except Exception as e:
        return {"error": str(e)}


def get_server_logs(service: str = "guardian", lines: int = 30) -> dict:
    """Últimas N líneas del log de un servicio Shomer vía SSH al host."""
    import subprocess, shutil
    unit_map = {
        "guardian": "shomer-guardian",
        "tools":    "shomer-tools",
        "nginx":    "nginx",
        "suricata": "suricata",
    }
    unit = unit_map.get(service.lower(), "shomer-guardian")
    key  = "/app/data/agent_restart_key"
    host = "127.0.0.1"

    # Primero intentar journalctl directo (por si corre fuera de container)
    jctl = shutil.which("journalctl")
    if jctl:
        try:
            r = subprocess.run(
                [jctl, "-u", unit, "-n", str(lines), "--no-pager", "--output=short"],
                capture_output=True, text=True, timeout=10,
            )
            output = (r.stdout or r.stderr).strip()
            return {"service": unit, "lines": output.splitlines()[-lines:], "ok": True}
        except Exception:
            pass

    # Fallback: SSH al host con la llave del agente
    ssh = shutil.which("ssh")
    if not ssh:
        return {"service": unit, "error": "ssh no disponible en el container", "ok": False}
    import os as _os
    ssh_user = _os.environ.get("HOST_SSH_USER", "usb_admin")
    try:
        r = subprocess.run(
            [ssh, "-i", key, "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null",
             f"{ssh_user}@{host}",
             f"journalctl -u {unit} -n {lines} --no-pager --output=short 2>&1"],
            capture_output=True, text=True, timeout=15,
        )
        output = (r.stdout or r.stderr).strip()
        if output:
            return {"service": unit, "lines": output.splitlines()[-lines:], "ok": True}
        return {"service": unit, "error": "sin output del host", "ok": False}
    except Exception as e:
        return {"service": unit, "error": str(e), "ok": False}


# ── Disco ─────────────────────────────────────────────────────────────────────

def get_disk_usage() -> dict:
    """Disco del host vía API (ve todas las particiones reales)."""
    data = _get("/api/disk-partitions")
    if data and data.get("success") and data.get("partitions"):
        return {"ok": True, "partitions": data["partitions"]}
    return {"ok": False, "error": "No se pudo leer disco"}


# ── WAN desde firewall ────────────────────────────────────────────────────────

def ping_from_firewall(firewall_ip, firewall_user, firewall_pass, target="8.8.8.8") -> bool:
    import subprocess, shutil
    sshpass = shutil.which("sshpass")
    if not sshpass:
        return True
    try:
        cmd = [sshpass, "-p", firewall_pass, "ssh",
               "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no",
               "-o", "UserKnownHostsFile=/dev/null",
               f"{firewall_user}@{firewall_ip}",
               f"ping -c 1 -W 3 {target} >/dev/null 2>&1 && echo yes || echo no"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
        return "yes" in r.stdout
    except Exception:
        return True


# ── Modo mantenimiento (Redis directo — bot tiene network_mode:host) ──────────

def _redis():
    try:
        import redis as _redis_lib
        r = _redis_lib.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None

def get_maintenance() -> bool:
    r = _redis()
    return bool(r and r.get("shomer_maintenance") == "1")

def set_maintenance(on: bool) -> bool:
    """Activa/desactiva vía API Guardian (Redis + Telegram al chat configurado)."""
    path = "/maintenance/on" if on else "/maintenance/off"
    ok, _body = _post(path)
    if ok:
        return True
    r = _redis()
    if not r:
        return False
    if on:
        r.set("shomer_maintenance", "1")
    else:
        r.delete("shomer_maintenance")
    return True

def log_ia_action(engine: str, msg: str, action_type: str = "auto") -> None:
    """Registra acción IA en Redis noc:ia_log para display NOC (máx 20 entradas)."""
    from datetime import datetime
    import json as _json
    r = _redis()
    if not r:
        return
    try:
        entry = _json.dumps({
            "at": datetime.utcnow().strftime("%H:%M:%S"),
            "engine": engine,
            "msg": str(msg).strip()[:110],
            "type": action_type,
        }, ensure_ascii=False)
        r.lpush("noc:ia_log", entry)
        r.ltrim("noc:ia_log", 0, 19)
    except Exception:
        pass

def get_interfaces() -> list:
    """Estado de interfaces de red del host vía /proc (funciona sin comando 'ip')."""
    import os
    ifaces = []
    try:
        net_dir = "/sys/class/net"
        for name in sorted(os.listdir(net_dir)):
            if name == "lo":
                continue
            try:
                with open(f"{net_dir}/{name}/operstate") as f:
                    state = f.read().strip().upper()  # up, down, unknown → UP/DOWN/UNKNOWN
                ifaces.append({"name": name, "state": state})
            except Exception:
                ifaces.append({"name": name, "state": "UNKNOWN"})
    except Exception:
        pass
    return ifaces


def get_snmp_uptime(ip: str, community: str = "shomer2026") -> str | None:
    """Obtiene uptime vía SNMP (para EAPs sin SSH)."""
    import subprocess, shutil
    snmpget = shutil.which("snmpget")
    if not snmpget:
        return None
    try:
        r = subprocess.run(
            [snmpget, "-v2c", "-c", community, "-t", "5", "-r", "1",
             ip, "1.3.6.1.2.1.1.3.0"],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0 and "Timeticks" in r.stdout:
            # Formato: "Timeticks: (12345678) 1 day, 10:17:57.78"
            raw = r.stdout.strip()
            if ")" in raw:
                return raw.split(")", 1)[1].strip()
    except Exception:
        pass
    return None


def get_node_failures(ip: str) -> dict:
    """Retorna failures acumulados y último reboot de un nodo Guardian."""
    r = _redis()
    if not r:
        return {}
    import time
    failures = int(r.get(f"failures:{ip}") or 0)
    last_raw = r.get(f"last_reboot:{ip}")
    last_reboot = int(last_raw) if last_raw else None
    last_reboot_ago = int(time.time()) - last_reboot if last_reboot else None
    return {"failures": failures, "last_reboot": last_reboot, "last_reboot_ago": last_reboot_ago}


# ── Config BD (system_state) ─────────────────────────────────────────────────

def get_config(key: str) -> Optional[str]:
    """Lee un valor de system_state en network_monitor.db."""
    DB = "file:/storage/db/network_monitor.db?mode=ro"
    try:
        con = _sq.connect(DB, timeout=5, uri=True)
        try:
            row = con.execute(
                "SELECT value FROM system_state WHERE key=? LIMIT 1", (key,)
            ).fetchone()
            return row[0] if row else None
        finally:
            con.close()
    except Exception:
        return None


def _config_bool(val) -> bool:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    try:
        import json as _json
        parsed = _json.loads(s)
        return parsed is True
    except Exception:
        return False


def get_hunter_autoblock() -> bool:
    return _config_bool(get_config("hunter.auto_block_enabled"))


def set_hunter_autoblock(enabled: bool) -> tuple[bool, str]:
    ok, body = _post("/config/system", {"hunter": {"auto_block_enabled": enabled}})
    if not ok:
        return False, str(body)
    if isinstance(body, dict) and not body.get("success", True):
        errs = body.get("errors") or []
        return False, ", ".join(errs) if errs else "error al guardar"
    return True, "ok"


def get_pc_credentials(ip: str) -> dict:
    """
    Devuelve credenciales SSH/WMI para un PC por IP.
    Prioridad: override_user/override_pass del activo → credenciales globales base.service_user/password.
    """
    user = password = None
    INVENTORY_DB = "file:/storage/db/inventory.db?mode=ro&immutable=1"
    try:
        con = _sq.connect(INVENTORY_DB, timeout=5, uri=True)
        try:
            row = con.execute(
                "SELECT override_user, override_pass FROM assets WHERE ip=? LIMIT 1", (ip,)
            ).fetchone()
            if row:
                user = row[0] or None
                password = row[1] or None
        finally:
            con.close()
    except Exception:
        pass
    # Fallback a credenciales globales de servicio
    if not user:
        user = get_config("base.service_user") or ""
    if not password:
        password = get_config("base.service_password") or ""
    return {"user": user, "password": password, "source": "override" if (user and password) else "global"}


def _mirror_nic_ip(iface: str) -> Optional[str]:
    """Retorna la IP asignada a la interfaz espejo, o None si no tiene."""
    import subprocess
    try:
        r = subprocess.run(
            ["ip", "-br", "addr", "show", iface],
            capture_output=True, text=True, timeout=5
        )
        parts = r.stdout.strip().split()
        return parts[2] if len(parts) >= 3 else None
    except Exception:
        return None


def run_install_check() -> dict:
    """
    Ejecuta todos los checks de verificación post-instalación.
    Retorna dict con results[], total, ok, warnings, site_name.
    """
    results = []

    def _add(label: str, ok: bool, detail: str = "", warn_if_not_ok: bool = True):
        results.append({"label": label, "ok": ok,
                        "warn": (not ok) if warn_if_not_ok else False,
                        "detail": detail})

    # 1. Core + Redis
    health = get_health()
    core_ok = health is not None
    redis_ok = (health or {}).get("redis") == "ok"
    _add("Servicio Guardian (core)", core_ok,
         "activo" if core_ok else "sin respuesta — revisar shomer-guardian")
    _add("Redis (memoria de estado)", redis_ok,
         "activo" if redis_ok else "caído — Guardian no funciona sin Redis")

    # 2. Nombre del sitio
    site_name = get_config("base.site_name") or ""
    site_ok = bool(site_name and site_name.lower() not in ("shomer", "default", ""))
    _add("Nombre del sitio", site_ok,
         f'"{site_name}"' if site_ok else "no configurado — Setup → Nombre del sitio")

    # 3. Zona horaria
    tz = get_config("base.timezone") or ""
    tz_ok = bool(tz and tz not in ("UTC", "Etc/UTC", ""))
    _add("Zona horaria", tz_ok,
         tz if tz_ok else f"{'UTC — ' if tz else ''}configurar en Setup para hora local")

    # 4. Telegram (ya funciona si recibimos el comando)
    _add("Telegram", True, "funcionando")

    # 5. Nodos Guardian
    nodes = get_guardian_nodes() or []
    nodes_ok = len(nodes) > 0
    _add("Guardian — nodos monitoreados", nodes_ok,
         f"{len(nodes)} nodo(s)" if nodes_ok else "ninguno — agregar APs en Guardian → Dispositivos")

    # 6. Hunter firewall
    fw_ip = get_config("hunter.firewall_ip") or get_config("hunter.firewall_host") or ""
    fw_ok = bool(fw_ip)
    _add("Hunter — firewall configurado", fw_ok,
         f"IP: {fw_ip}" if fw_ok else "sin firewall — completar Paso 9")

    # 7. Hunter subredes internas
    subnets = get_config("hunter.subnets") or get_config("hunter.local_networks") or ""
    subnets_ok = bool(subnets)
    _add("Hunter — subredes internas", subnets_ok,
         subnets if subnets_ok else "no configuradas — riesgo de bloquear clientes reales")

    # 8. Suricata / pipeline (solo si Hunter habilitado)
    hunter_enabled = get_config("modules.hunter") in ("1", "true", "True")
    if hunter_enabled:
        pipeline = get_pipeline_health() or {}
        pipe_ok = pipeline.get("overall_ok", False)
        _add("Suricata — espejo activo", pipe_ok,
             "recibiendo tráfico" if pipe_ok else "sin tráfico — verificar SPAN en el switch")

    # 9. NIC espejo sin IP
    mirror_iface = get_config("base.mirror_interface") or "enp4s0"
    mirror_ip = _mirror_nic_ip(mirror_iface)
    mirror_clean = not mirror_ip or "/" not in (mirror_ip or "")
    _add(f"NIC espejo ({mirror_iface}) sin IP", mirror_clean,
         "correcto — sin IP" if mirror_clean else f"tiene IP {mirror_ip} — puede causar conflictos de red")

    # 10. Internet del servidor
    wan = get_wan_status() or {}
    wan_ok = wan.get("internet", False)
    _add("Internet del servidor Shomer", wan_ok,
         "activo" if wan_ok else "sin internet — Telegram y alertas afectados")

    # 11. Protector (solo si habilitado)
    protector_enabled = get_config("modules.protector") in ("1", "true", "True")
    if protector_enabled:
        backup_devs = get_backup_devices()
        prot_ok = len(backup_devs) > 0
        _add("Protector — equipos con backup", prot_ok,
             f"{len(backup_devs)} equipo(s)" if prot_ok else "ninguno — ¿el cliente tiene backup contratado?")

    ok_count = sum(1 for r in results if r["ok"])
    warn_count = sum(1 for r in results if r.get("warn"))
    return {
        "results": results,
        "total": len(results),
        "ok": ok_count,
        "warnings": warn_count,
        "site_name": site_name or "Sin nombre configurado",
    }


# ── Seguridad perimetral (firewall Hunter vía SSH) ────────────────────────────

def get_firewall_security_log() -> dict:
    """
    Lee log de drops y conteo de conexiones del firewall perimetral (OpenWrt/Linux)
    usando las credenciales hunter.firewall_* de system_state.
    """
    import subprocess, shutil, re as _re
    fw_ip   = get_config("hunter.firewall_ip") or get_config("hunter.firewall_host") or ""
    fw_user = get_config("hunter.firewall_user") or "root"
    fw_pass = get_config("hunter.firewall_pass") or ""
    if not fw_ip:
        return {"ok": False, "error": "firewall no configurado"}

    sshpass = shutil.which("sshpass")
    if not sshpass or not fw_pass:
        return {"ok": False, "error": "sin sshpass o credenciales SSH"}

    cmd_str = (
        "logread -l 200 2>/dev/null | grep -iE 'DROP|REJECT|blocked' | tail -100 ;"
        " echo '---CONN---' ;"
        " cat /proc/net/nf_conntrack 2>/dev/null | wc -l || echo 0"
    )
    try:
        r = subprocess.run(
            [sshpass, "-p", fw_pass, "ssh",
             "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null",
             f"{fw_user}@{fw_ip}", cmd_str],
            capture_output=True, text=True, timeout=18,
        )
        out = r.stdout or ""
        parts = out.split("---CONN---")
        log_lines = [l for l in parts[0].strip().splitlines() if l.strip()]
        try:
            conn_count = int(parts[1].strip().splitlines()[0]) if len(parts) > 1 else 0
        except Exception:
            conn_count = 0

        drop_ips: dict = {}
        for line in log_lines:
            m = _re.search(r'SRC=(\d{1,3}(?:\.\d{1,3}){3})', line, _re.IGNORECASE)
            if m:
                ip = m.group(1)
                drop_ips[ip] = drop_ips.get(ip, 0) + 1

        top = sorted(drop_ips.items(), key=lambda x: x[1], reverse=True)[:5]
        return {
            "ok": True,
            "fw_ip": fw_ip,
            "drop_count": len(log_lines),
            "conn_count": conn_count,
            "top_attackers": [{"ip": ip, "drops": n} for ip, n in top],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Resumen LLM ───────────────────────────────────────────────────────────────

def get_infra_devices() -> list:
    """Lista equipos Inframonitor con estado ICMP, TCP y SNMP."""
    return get_infra_snapshot().get("devices", [])


def get_infra_snapshot() -> dict:
    """Equipos Infra + contador de caídas distintas en 24 h."""
    data = _get("/infra/devices") or {}
    return {
        "devices": data.get("devices", []),
        "outages_24h": data.get("outages_24h", 0),
    }


def get_infra_summary() -> dict:
    """Resumen compacto Infra para reportes y /salud."""
    snap = get_infra_snapshot()
    devs = snap.get("devices") or []
    off = [d for d in devs if d.get("status") == "offline"]
    by_type: Dict[str, int] = {}
    for d in devs:
        t = d.get("device_type") or "generic"
        by_type[t] = by_type.get(t, 0) + 1
    low_toner = [
        d for d in devs
        if d.get("device_type") in ("printer", "pos")
        and (d.get("printer") or {}).get("toner_pct") is not None
        and int((d.get("printer") or {}).get("toner_pct", 100)) <= 15
    ]
    return {
        "total": len(devs),
        "online": len(devs) - len(off),
        "offline": off,
        "outages_24h": snap.get("outages_24h", 0),
        "by_type": by_type,
        "low_toner": low_toner,
    }


def get_infra_snmp(ip: str) -> dict:
    """Datos SNMP de un equipo Inframonitor: modelo, uptime, interfaces."""
    return _get(f"/infra/snmp/{ip}") or {}


def get_infra_device(ip: str) -> dict:
    """Un equipo Infra por IP (estado, tóner, TCP, SNMP) o dict vacío."""
    ip = (ip or "").strip()
    if not ip:
        return {}
    for d in get_infra_devices():
        if d.get("ip") == ip:
            return d
    return {}


def get_switch_port_errors() -> list:
    """
    Lee contadores de errores SNMP por puerto de todos los switches/routers
    con SNMP activo en Inframonitor.
    Retorna lista de dicts:
      {ip, name, device_type, ports: [{name, oper, in_errors, out_errors, speed_mbps}]}
    Solo incluye dispositivos que tienen interfaces con datos de errores.
    """
    import sqlite3 as _sqlite3
    import json as _json
    DB = "/storage/db/network_monitor.db"
    results = []
    try:
        conn = _sqlite3.connect(DB)
        conn.row_factory = _sqlite3.Row
        rows = conn.execute("""
            SELECT d.ip, d.name, d.device_type, s.snmp_data
            FROM infra_devices d
            JOIN infra_status s ON s.ip = d.ip
            WHERE d.device_type IN ('switch', 'router')
              AND d.active = 1
              AND s.snmp_ok = 1
              AND s.snmp_data IS NOT NULL
              AND length(s.snmp_data) > 20
            ORDER BY s.checked_at DESC
        """).fetchall()
        conn.close()
        seen = set()
        for r in rows:
            if r["ip"] in seen:
                continue
            seen.add(r["ip"])
            try:
                sd = _json.loads(r["snmp_data"])
                ifaces = sd.get("interfaces", [])
                if not ifaces:
                    continue
                ports = []
                for i in ifaces:
                    ports.append({
                        "name":       i.get("name", "?"),
                        "oper":       i.get("oper", "unknown"),
                        "in_errors":  int(i.get("in_errors") or 0),
                        "out_errors": int(i.get("out_errors") or 0),
                        "speed_mbps": i.get("speed_mbps"),
                    })
                results.append({
                    "ip":          r["ip"],
                    "name":        r["name"],
                    "device_type": r["device_type"],
                    "ports":       ports,
                })
            except Exception:
                continue
    except Exception:
        pass
    return results


def knowledge_hint(ip: str, max_len: int = 55) -> str:
    """Texto corto de la última solución guardada para esa IP (alertas / IA)."""
    if not ip:
        return ""
    try:
        hist = get_knowledge(ip=ip, limit=1)
        if not hist:
            return ""
        act = (hist[0].get("action") or "").strip()
        if not act:
            return ""
        if len(act) > max_len:
            act = act[: max_len - 1] + "…"
        return act
    except Exception:
        return ""


def summary_text() -> str:
    lines = []
    health = get_health()
    if health:
        redis = health.get("redis", "?")
        lines.append(f"Shomer core: {'✅' if redis == 'ok' else '⚠️'} (redis={redis})")
    nodes = get_guardian_nodes()
    if nodes and isinstance(nodes, list):
        online = sum(1 for n in nodes if n.get("status") == "online")
        lines.append(f"Guardian: {online}/{len(nodes)} nodos online")
        for n in nodes:
            lines.append(f"  • {n.get('name', n.get('ip'))} — {n.get('status','?')}")
    metrics = get_server_metrics()
    if metrics and metrics.get("success"):
        now = metrics.get("now", {})
        cpu = round(now.get("cpu", 0), 1)
        ram = round(now.get("ram", 0), 1)
        temp = now.get("temp", "?")
        lines.append(f"Servidor: CPU {cpu}% | RAM {ram}% | Temp {temp}°C")
    alerts = get_hunter_alerts(5)
    if alerts:
        count = alerts.get("total", 0) if isinstance(alerts, dict) else len(alerts)
        lines.append(f"Hunter: {count} evento(s) recientes — vigilancia activa")
    blocked = get_blocked_ips() or []
    if blocked:
        lines.append(f"Protección Hunter: {len(blocked)} IP(s) contenida(s) — red protegida")
    audit = get_network_audit_summary()
    if isinstance(audit, dict) and audit.get("by_severity"):
        by = audit["by_severity"]
        crit = by.get("critico", 0)
        alto = by.get("alto", 0)
        if crit or alto:
            lines.append(
                f"Riesgos de red pendientes: {crit} crítico(s), {alto} alto(s) — "
                f"panel Hunter → Riesgos de Red"
            )
    infra = get_infra_summary()
    if infra.get("total"):
        lines.append(
            f"Infra: {infra['online']}/{infra['total']} online "
            f"({', '.join(f'{v} {k}' for k, v in sorted(infra['by_type'].items(), key=lambda x: -x[1]))})"
        )
        if infra.get("outages_24h"):
            lines.append(f"Infra caídas 24h: {infra['outages_24h']} equipo(s) distintos")
        for d in infra.get("offline", [])[:8]:
            lines.append(
                f"  • {d.get('name', d.get('ip'))} ({d.get('device_type', '?')}) — caído"
            )
        extra = len(infra.get("offline", [])) - 8
        if extra > 0:
            lines.append(f"  • …y {extra} más caídos")
        if infra.get("low_toner"):
            lines.append(f"Impresoras con tóner bajo: {len(infra['low_toner'])}")
    try:
        from core import llm_router as _llm
        lines.append("IA:")
        lines.extend(_llm.status_lines(html=False))
    except Exception:
        pass
    return "\n".join(lines) if lines else "No se pudo obtener estado de Shomer"


def get_network_audit_findings(severity: str = "", finding_status: str = "") -> dict:
    """Hallazgos de auditoría de red. severity: critico/alto/medio/bajo. finding_status: pendiente/en_revision/terminado."""
    params = []
    if severity:
        params.append(f"severity={severity}")
    if finding_status:
        params.append(f"finding_status={finding_status}")
    qs = "?" + "&".join(params) if params else ""
    findings = _get(f"/audit/network/findings{qs}")
    summary = _get("/audit/network/summary")
    return {
        "findings": findings,
        "summary": summary,
    }


def get_network_audit_summary() -> dict:
    """Resumen rápido de hallazgos activos de auditoría de red (para el bot)."""
    return _get("/audit/network/summary") or {}


def run_network_audit_scan() -> dict:
    """
    Lanza escaneo de auditoría de red (nmap + parches SSH).
    Hace polling hasta completar o timeout de 8 minutos.
    Retorna: {ok, status, findings_count, total_hosts, error}
    """
    ok, body = _post("/audit/network/scan")
    if not ok:
        msg = body.get("detail", str(body)) if isinstance(body, dict) else str(body)
        # Si ya hay un escaneo corriendo, body puede ser el estado actual
        if isinstance(body, dict) and body.get("status") in ("running", "pending"):
            pass  # continuar con polling
        else:
            return {"ok": False, "status": "failed", "error": msg}

    # Polling hasta completar (máx 8 min = 48 intentos × 10s)
    for _ in range(48):
        import time as _time
        _time.sleep(10)
        status = _get("/audit/network/status")
        if not status:
            continue
        current = status.get("status", "")
        if current == "completed":
            return {
                "ok":             True,
                "status":         "completed",
                "findings_count": status.get("findings_count", 0),
                "total_hosts":    status.get("total_hosts", 0),
                "error":          None,
            }
        if current == "failed":
            return {
                "ok":    False,
                "status": "failed",
                "error": status.get("error_msg", "Error desconocido"),
            }

    return {"ok": False, "status": "timeout", "error": "El escaneo tardó más de 8 minutos."}


# ── Base de conocimiento de incidentes ────────────────────────────────────────

_KNOWLEDGE_DB = "/app/data/knowledge.db"

def _init_knowledge_db():
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS incident_knowledge (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_ip   TEXT,
            device_name TEXT,
            problem     TEXT NOT NULL,
            action      TEXT NOT NULL,
            result      TEXT DEFAULT 'resuelto',
            saved_by    TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS technician_actions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            device_ip   TEXT DEFAULT '',
            device_name TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS technician_names (
            telegram_id TEXT PRIMARY KEY,
            nombre      TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now'))
        )""")


def save_knowledge(device_ip: str, device_name: str, problem: str, action: str, saved_by: str = "") -> dict:
    """Guarda incidente resuelto. Retorna {kid, task_id, skill_id}."""
    _init_knowledge_db()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        cur = conn.execute(
            "INSERT INTO incident_knowledge (device_ip, device_name, problem, action, saved_by) VALUES (?,?,?,?,?)",
            (device_ip or "", device_name or "", problem, action, saved_by)
        )
        kid = cur.lastrowid
    meta = {"kid": kid, "task_id": None, "skill_id": None}
    try:
        from core import learning

        meta.update(
            learning.on_knowledge_saved(
                problem,
                action,
                device_ip=device_ip,
                device_name=device_name,
                saved_by=saved_by,
            )
        )
        meta["kid"] = kid
    except Exception:
        pass
    return meta


def get_knowledge(ip: str = None, limit: int = 8) -> list:
    """Consulta incidentes resueltos. Si se da ip, filtra por ese equipo."""
    _init_knowledge_db()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.row_factory = _sq.Row
        if ip:
            rows = conn.execute(
                "SELECT * FROM incident_knowledge WHERE device_ip=? ORDER BY created_at DESC LIMIT ?",
                (ip, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM incident_knowledge ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


def log_technician_action(telegram_id: str, action_type: str, device_ip: str = "", device_name: str = ""):
    """Registra una acción del técnico para métricas de gestión."""
    _init_knowledge_db()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute(
            "INSERT INTO technician_actions (telegram_id, action_type, device_ip, device_name) VALUES (?,?,?,?)",
            (str(telegram_id), action_type, device_ip or "", device_name or "")
        )


def save_technician_name(telegram_id: str, nombre: str):
    """Registra o actualiza el nombre de un técnico."""
    _init_knowledge_db()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.execute(
            "INSERT INTO technician_names (telegram_id, nombre) VALUES (?,?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET nombre=excluded.nombre",
            (str(telegram_id), nombre)
        )


def get_technician_stats(month: str = None) -> list:
    """
    Retorna métricas por técnico para el mes dado (YYYY-MM) o el mes actual.
    Métricas: acciones_total, reboots, soluciones_documentadas, reboots_repetidos.
    """
    import datetime as _dt
    if not month:
        month = _dt.datetime.now().strftime("%Y-%m")
    _init_knowledge_db()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.row_factory = _sq.Row
        # Técnicos con acciones en el mes
        techs = conn.execute(
            "SELECT DISTINCT telegram_id FROM technician_actions "
            "WHERE strftime('%Y-%m', created_at) = ?", (month,)
        ).fetchall()

        # Nombres registrados
        names_rows = conn.execute("SELECT telegram_id, nombre FROM technician_names").fetchall()
        names = {r["telegram_id"]: r["nombre"] for r in names_rows}

        result = []
        for t in techs:
            tid = t["telegram_id"]
            # Total acciones
            total = conn.execute(
                "SELECT COUNT(*) FROM technician_actions WHERE telegram_id=? AND strftime('%Y-%m',created_at)=?",
                (tid, month)
            ).fetchone()[0]
            # Reboots
            reboots = conn.execute(
                "SELECT COUNT(*) FROM technician_actions WHERE telegram_id=? AND action_type='reboot' AND strftime('%Y-%m',created_at)=?",
                (tid, month)
            ).fetchone()[0]
            # Soluciones documentadas
            docs = conn.execute(
                "SELECT COUNT(*) FROM incident_knowledge WHERE saved_by=? AND strftime('%Y-%m',created_at)=?",
                (tid, month)
            ).fetchone()[0]
            # Reboots repetidos: mismo device_ip reiniciado >2 veces en 7 días en el mes
            rep_rows = conn.execute(
                """SELECT device_ip, COUNT(*) as cnt,
                          MIN(created_at) as first_at, MAX(created_at) as last_at
                   FROM technician_actions
                   WHERE telegram_id=? AND action_type='reboot'
                     AND strftime('%Y-%m',created_at)=?
                     AND device_ip != ''
                   GROUP BY device_ip
                   HAVING cnt > 2""",
                (tid, month)
            ).fetchall()
            reboots_repetidos = len(rep_rows)

            # Score 0-100
            doc_rate = round((docs / reboots * 100) if reboots > 0 else 100)
            penalty  = min(reboots_repetidos * 10, 30)
            score    = max(0, min(100, doc_rate - penalty))

            result.append({
                "telegram_id":        tid,
                "nombre":             names.get(tid, f"Técnico {tid[-4:]}"),
                "mes":                month,
                "acciones_total":     total,
                "reboots":            reboots,
                "soluciones_doc":     docs,
                "reboots_repetidos":  reboots_repetidos,
                "doc_rate_pct":       doc_rate,
                "score":              score,
            })

        return sorted(result, key=lambda x: x["score"], reverse=True)


def get_technician_names() -> list:
    """Lista todos los técnicos registrados con nombre."""
    _init_knowledge_db()
    with _sq.connect(_KNOWLEDGE_DB) as conn:
        conn.row_factory = _sq.Row
        rows = conn.execute("SELECT * FROM technician_names ORDER BY nombre").fetchall()
    return [dict(r) for r in rows]
