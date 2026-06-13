"""
Driver para impresoras en red — all-terrain.
Prueba en orden: ping → TCP 9100 → SNMP (laser) → ESC/POS (térmica/POS).
Usa snmpget/snmpwalk CLI (mismo patrón que tplink_eap.py).
"""
from __future__ import annotations
import socket
import subprocess
from typing import Optional

# SNMP OIDs — RFC 3805 Printer MIB
_OID_DESCR      = "1.3.6.1.2.1.1.1.0"
_OID_TONER_MAX  = "1.3.6.1.2.1.43.11.1.1.8.1.1"
_OID_TONER_CUR  = "1.3.6.1.2.1.43.11.1.1.9.1.1"
_OID_PAPER      = "1.3.6.1.2.1.43.8.2.1.10.1.1"

# ESC/POS DLE EOT n=1 — Epson TM series y compatibles
_ESCPOS_STATUS  = bytes([0x10, 0x04, 0x01])


def _snmpget(ip: str, community: str, oid: str, timeout: int = 3) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["snmpget", "-v2c", "-c", community, "-t", str(timeout), "-r", "0", ip, oid],
            capture_output=True, text=True, timeout=timeout + 2
        )
        out = (r.stdout or r.stderr or "").strip()
        return r.returncode == 0, out
    except Exception as e:
        return False, str(e)


def _snmpwalk(ip: str, community: str, oid: str, timeout: int = 3) -> tuple[bool, list[str]]:
    try:
        r = subprocess.run(
            ["snmpwalk", "-v2c", "-c", community, "-t", str(timeout), "-r", "0", ip, oid],
            capture_output=True, text=True, timeout=timeout + 3
        )
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        return len(lines) > 0, lines
    except Exception:
        return False, []


def _tcp_ok(ip: str, port: int = 9100, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def _escpos_status(ip: str, port: int = 9100, timeout: float = 3.0) -> Optional[dict]:
    """Consulta estado Epson ESC/POS via TCP 9100 — DLE EOT."""
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.settimeout(timeout)
        s.sendall(_ESCPOS_STATUS)
        data = s.recv(4)
        s.close()
        if not data:
            return None
        b = data[0]
        return {
            "online":   not bool(b & 0x08),
            "paper_ok": not bool(b & 0x60),
            "error":    bool(b & 0x28),
        }
    except Exception:
        return None


def _parse_int(val: str) -> Optional[int]:
    """'INTEGER: 42' / 'Gauge32: 42' → 42"""
    try:
        return int(val.split(":")[-1].strip())
    except Exception:
        return None


def get_printer_status(ip: str, snmp_community: str = "public") -> dict:
    """
    Diagnóstico all-terrain.
    Retorna dict con campos disponibles según lo que responde la impresora.
    """
    result: dict = {
        "ip": ip,
        "ping": False,
        "port_9100": False,
        "method": "none",
        "online": False,
        "status": "offline",
    }

    # 1. Ping
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", ip],
                           capture_output=True, timeout=5)
        result["ping"] = (r.returncode == 0)
    except Exception:
        pass

    result["online"] = result["ping"]

    if not result["ping"]:
        return result

    # 2. TCP 9100
    result["port_9100"] = _tcp_ok(ip)

    # 3. SNMP — laser/oficina (HP, Xerox, Canon, Brother...)
    ok, descr_raw = _snmpget(ip, snmp_community, _OID_DESCR)
    if ok and descr_raw and "No Such" not in descr_raw and "Timeout" not in descr_raw:
        result["method"] = "snmp"
        result["status"] = "online"
        result["model"] = descr_raw.split("STRING:")[-1].strip().strip('"')[:80]

        _, max_raw = _snmpget(ip, snmp_community, _OID_TONER_MAX)
        _, cur_raw = _snmpget(ip, snmp_community, _OID_TONER_CUR)
        t_max = _parse_int(max_raw)
        t_cur = _parse_int(cur_raw)
        if t_max and t_max > 0 and t_cur is not None and t_cur >= 0:
            result["toner_pct"] = round(t_cur / t_max * 100)
        elif t_cur == -3:
            result["toner_pct"] = 0
            result["toner_low"] = True
        elif t_cur == -2:
            result["toner_note"] = "nivel no reportado por esta impresora"

        _, paper_raw = _snmpget(ip, snmp_community, _OID_PAPER)
        p = _parse_int(paper_raw)
        if p is not None:
            result["paper_ok"] = (p not in (0, -3))

        return result

    # 4. ESC/POS — térmica/matricial POS (Epson TM, Star, etc.)
    if result["port_9100"]:
        escpos = _escpos_status(ip)
        if escpos:
            result["method"] = "escpos"
            result["paper_ok"] = escpos["paper_ok"]
            result["error"]    = escpos["error"]
            result["printer_online"] = escpos["online"]
            result["status"] = "online" if escpos["online"] else "error"
            return result
        # Puerto abierto pero sin respuesta ESC/POS (impresora raw-only)
        result["method"] = "raw_9100"

    result["status"] = "online"
    return result
