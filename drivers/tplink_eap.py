"""
Driver TP-Link EAP / Omada — línea business (EAP225, EAP245, EAP610, EAP670).
Usa SNMP en lugar de SSH porque el usuario admin del firmware no tiene permisos
de ping, reboot ni herramientas de red.

Verificado en lab (8 mayo 2026):
  EAP225  192.168.1.254  kernel 3.3.8 mips
  EAP610  192.168.1.253  kernel 4.4.198 mips

Convención de campos en devices.json:
  user     = comunidad SNMP lectura  (GET)
  password = comunidad SNMP escritura (SET / reboot)
  port     = ignorado (SNMP siempre UDP 161)

OIDs utilizados:
  1.3.6.1.2.1.1.1.0            sysDescr   (firmware/kernel)
  1.3.6.1.2.1.1.3.0            sysUpTime
  1.3.6.1.2.1.1.5.0            sysName    (hostname)
  1.3.6.1.2.1.4.22             ipNetToMediaTable (clientes ARP: IP + MAC)
  1.3.6.1.4.1.11863.10.1.2.1.0 reboot TP-Link (SET = 1 → reinicia)
"""
import subprocess
import shutil
from .base import DeviceDriver, DeviceResult, DriverLevel

SNMP_REBOOT_OID = "1.3.6.1.4.1.11863.10.1.2.1.0"
SNMP_ARP_OID   = "1.3.6.1.2.1.4.22"
SNMP_INFO_OIDS = [
    "1.3.6.1.2.1.1.1.0",  # sysDescr
    "1.3.6.1.2.1.1.3.0",  # sysUpTime
    "1.3.6.1.2.1.1.5.0",  # sysName
]


def _snmpget(ip: str, community: str, oid: str, timeout: int = 8) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["snmpget", "-v2c", "-c", community, "-t", str(timeout), "-r", "1",
             ip, oid],
            capture_output=True, text=True, timeout=timeout + 3
        )
        out = (r.stdout or r.stderr or "").strip()
        return r.returncode == 0, out
    except Exception as e:
        return False, str(e)


def _snmpwalk(ip: str, community: str, oid: str, timeout: int = 8) -> tuple[bool, list[str]]:
    try:
        r = subprocess.run(
            ["snmpwalk", "-v2c", "-c", community, "-t", str(timeout), "-r", "1",
             ip, oid],
            capture_output=True, text=True, timeout=timeout + 5
        )
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        return r.returncode == 0 or len(lines) > 0, lines
    except Exception as e:
        return False, []


def _snmpset(ip: str, community: str, oid: str, vtype: str, value: str,
             timeout: int = 8) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["snmpset", "-v2c", "-c", community, "-t", str(timeout), "-r", "1",
             ip, oid, vtype, value],
            capture_output=True, text=True, timeout=timeout + 3
        )
        out = (r.stdout or r.stderr or "").strip()
        return r.returncode == 0, out
    except Exception as e:
        return False, str(e)


class TpLinkEapDriver(DeviceDriver):
    """
    Driver SNMP para EAP225/EAP610 y familia Omada business.
    user     → comunidad SNMP GET
    password → comunidad SNMP SET (reboot)
    """
    NAME  = "tplink_eap"
    LEVEL = DriverLevel.FULL

    def reboot(self) -> DeviceResult:
        if not self.password:
            return DeviceResult(ok=False, message="sin comunidad SNMP SET configurada")
        ok, out = _snmpset(self.ip, self.password, SNMP_REBOOT_OID, "i", "1", self.timeout)
        if ok:
            return DeviceResult(ok=True, message="reboot SNMP enviado")
        return DeviceResult(ok=False, message=f"reboot SNMP falló: {out}")

    def get_clients(self) -> DeviceResult:
        community = self.user or "public"
        ok, lines = _snmpwalk(self.ip, community, SNMP_ARP_OID, self.timeout)
        if not ok and not lines:
            return DeviceResult(ok=False, message="SNMP ARP sin respuesta",
                                data={"count": 0, "clients": []})

        # Construir mapa IP→MAC desde la tabla ipNetToMediaTable
        ip_map: dict[str, str] = {}
        mac_map: dict[str, str] = {}

        for line in lines:
            # iso.3.6.1.2.1.4.22.1.3.4.192.168.1.50 = IpAddress: 192.168.1.50
            if "IpAddress:" in line:
                parts = line.split()
                if len(parts) >= 3:
                    oid_part = parts[0]
                    ip_val   = parts[-1]
                    idx = oid_part.rsplit(".", 4)[0].split(".")[-1]  # índice de fila
                    ip_map[oid_part.rsplit(".", 4)[0]] = ip_val
            # iso.3.6.1.2.1.4.22.1.2.4.192.168.1.50 = Hex-STRING: 7C 57 58 1B F4 38
            if "Hex-STRING:" in line:
                parts = line.split("Hex-STRING:")
                if len(parts) == 2:
                    mac_bytes = parts[1].strip().split()
                    mac = ":".join(b.lower() for b in mac_bytes)
                    oid_key = parts[0].strip().split()[0]
                    # obtener IP del mismo índice
                    ip_key = oid_key.replace(".1.2.4.", ".1.3.4.")
                    mac_map[ip_key] = mac

        # Cruzar IP y MAC
        clients = []
        seen_ips = set()
        for line in lines:
            if "IpAddress:" in line:
                parts_l = line.split()
                if len(parts_l) < 3:
                    continue
                oid_key = parts_l[0]
                ip_val  = parts_l[-1]
                if ip_val in seen_ips:
                    continue
                seen_ips.add(ip_val)
                mac_oid = oid_key.replace(".1.3.4.", ".1.2.4.")
                mac_val = mac_map.get(mac_oid, "?")
                clients.append({"ip": ip_val, "mac": mac_val})

        return DeviceResult(
            ok=True,
            message=f"{len(clients)} clientes",
            data={"count": len(clients), "clients": clients}
        )

    def get_info(self) -> DeviceResult:
        community = self.user or "public"
        lines = []
        for oid in SNMP_INFO_OIDS:
            ok, out = _snmpget(self.ip, community, oid, self.timeout)
            if ok:
                lines.append(out)
        if lines:
            raw = "\n".join(lines)
            return DeviceResult(ok=True, message="info EAP via SNMP",
                                data={"raw": raw, "vendor": "tplink_eap"})
        return DeviceResult(ok=False, message="SNMP sin respuesta")

    def test_connection(self) -> DeviceResult:
        community = self.user or "public"
        ok, out = _snmpget(self.ip, community, "1.3.6.1.2.1.1.3.0", self.timeout)
        return DeviceResult(ok=ok, message=out if ok else "SNMP sin respuesta")
