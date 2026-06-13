"""
Detección automática de tipo de equipo por banner SSH y respuesta.
Si no hay credenciales, queda en PING level.
"""
import subprocess
from typing import Optional
from .base import DeviceDriver, DriverLevel, DeviceResult
from .linux_generic import LinuxGenericDriver
from .mikrotik import MikroTikDriver
from .tplink_eap import TpLinkEapDriver
from .cisco import CiscoDriver
from .ubiquiti import UbiquitiDriver
from .aruba import ArubaDriver


def _get_ssh_banner(ip: str, port: int = 22, timeout: int = 5) -> str:
    """Obtiene el banner SSH sin autenticar."""
    try:
        r = subprocess.run(
            ["ssh", "-o", f"ConnectTimeout={timeout}",
             "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null",
             "-o", "BatchMode=yes",
             "-p", str(port), f"root@{ip}", "exit"],
            capture_output=True, text=True, timeout=timeout + 2
        )
        return (r.stderr or r.stdout or "").lower()
    except Exception:
        return ""


def detect_driver(ip: str, user: str = "", password: str = "",
                  port: int = 22, vendor_hint: str = "") -> DeviceDriver:
    """
    Detecta el driver correcto para un equipo.
    vendor_hint: 'mikrotik' | 'linux' | 'cisco' | 'tplink_eap' | ''
    Si no hay credenciales → DeviceDriver base (ping only).
    """
    hint = vendor_hint.lower().strip()

    # Si viene hint explícito del usuario, confiar en él
    if hint == "mikrotik":
        return MikroTikDriver(ip, user, password, port)
    if hint in ("ubiquiti", "unifi", "uap", "edgerouter", "nanostation"):
        return UbiquitiDriver(ip, user, password, port)
    if hint in ("aruba", "arubaos", "instant", "iap", "hpe"):
        return ArubaDriver(ip, user, password, port)
    if hint in ("linux", "openwrt", "ddwrt", "glinet", "raspberry"):
        return LinuxGenericDriver(ip, user, password, port)
    if hint in ("tplink_eap", "omada"):
        return TpLinkEapDriver(ip, user, password, port)
    if hint == "cisco":
        return CiscoDriver(ip, user, password, port)

    # Sin credenciales → solo ping
    if not user or not password:
        return DeviceDriver(ip)

    # Detección automática por banner SSH
    banner = _get_ssh_banner(ip, port)

    if "mikrotik" in banner or "routeros" in banner:
        return MikroTikDriver(ip, user, password, port)

    if "cisco" in banner or "ios" in banner:
        return CiscoDriver(ip, user, password, port)

    if "ubnt" in banner or "ubiquiti" in banner or "unifi" in banner:
        return UbiquitiDriver(ip, user, password, port)

    if "aruba" in banner or "arubaos" in banner:
        return ArubaDriver(ip, user, password, port)

    if "tpos" in banner:
        # TP-Link consumer — solo ping
        return DeviceDriver(ip)

    # Banner OpenSSH genérico — probar Linux primero
    if "openssh" in banner or banner == "":
        drv = LinuxGenericDriver(ip, user, password, port)
        if drv.test_connection().ok:
            return drv
        # Probar Ubiquiti (responde "echo ok" pero tiene info específica)
        uq = UbiquitiDriver(ip, user, password, port)
        ok_uq, uq_out = ssh_run(ip, user, password, "info 2>/dev/null | grep -c Model", port, 5)
        if ok_uq and uq_out.strip().isdigit() and int(uq_out.strip()) > 0:
            return uq
        # Probar MikroTik
        mt = MikroTikDriver(ip, user, password, port)
        if mt.test_connection().ok:
            return mt

    # Fallback: solo ping
    return DeviceDriver(ip)
