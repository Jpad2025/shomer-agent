"""
Driver MikroTik RouterOS — hAP, RB, CCR, CRS, cualquier RouterOS.
Usa SSH con comandos /system reboot, /ip arp print, etc.
"""
import re
from .base import DeviceDriver, DeviceResult, DriverLevel
from .ssh_helper import ssh_run


class MikroTikDriver(DeviceDriver):
    NAME  = "mikrotik"
    LEVEL = DriverLevel.FULL

    def reboot(self) -> DeviceResult:
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "/system reboot", self.port, self.timeout)
        if ok or out == "" or "closed" in out.lower():
            return DeviceResult(ok=True, message="reboot RouterOS enviado")
        return DeviceResult(ok=False, message=f"reboot falló: {out}")

    def get_clients(self) -> DeviceResult:
        # Tabla ARP + DHCP leases de MikroTik
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "/ip arp print terse", self.port, self.timeout)
        clients = []
        if ok:
            for line in out.splitlines():
                if "ADDRESS=" in line.upper() or "address=" in line:
                    parts = {}
                    for tok in line.split():
                        if "=" in tok:
                            k, v = tok.split("=", 1)
                            parts[k.lower()] = v
                    if "address" in parts:
                        clients.append({
                            "ip": parts.get("address", ""),
                            "mac": parts.get("mac-address", ""),
                            "interface": parts.get("interface", ""),
                        })
                elif line.strip() and not line.startswith("Flags"):
                    # formato sin = — por columnas
                    cols = line.split()
                    if len(cols) >= 3:
                        for col in cols:
                            if "." in col and col[0].isdigit():
                                clients.append({"ip": col, "mac": "", "interface": ""})
                                break

        if clients:
            return DeviceResult(ok=True, message=f"{len(clients)} entradas ARP",
                                data={"count": len(clients), "clients": clients})

        # Fallback: DHCP leases
        ok2, out2 = ssh_run(self.ip, self.user, self.password,
                            "/ip dhcp-server lease print terse", self.port, self.timeout)
        if ok2:
            for line in out2.splitlines():
                parts = {}
                for tok in line.split():
                    if "=" in tok:
                        k, v = tok.split("=", 1)
                        parts[k.lower()] = v
                if "address" in parts:
                    clients.append({
                        "ip": parts.get("address", ""),
                        "mac": parts.get("mac-address", ""),
                        "hostname": parts.get("host-name", ""),
                    })
            return DeviceResult(ok=True, message=f"{len(clients)} leases DHCP",
                                data={"count": len(clients), "clients": clients})

        return DeviceResult(ok=False, message="no se pudo obtener clientes", data={"clients": []})

    def get_info(self) -> DeviceResult:
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "/system resource print; /system identity print",
                          self.port, self.timeout)
        if ok:
            info = {"vendor": "mikrotik", "raw": out}
            for line in out.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    k = k.strip().lower().replace(" ", "_")
                    info[k] = v.strip()
            return DeviceResult(ok=True, message="info RouterOS obtenida", data=info)
        return DeviceResult(ok=False, message=f"SSH RouterOS falló: {out}")

    def test_connection(self) -> DeviceResult:
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "/system identity print", self.port, self.timeout)
        return DeviceResult(ok=ok, message=out if ok else f"falló: {out}")

    def get_security_log(self) -> DeviceResult:
        """Últimas entradas de firewall RouterOS — detecta drops por IP de origen."""
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "/log print where topics~\"firewall\"",
                          self.port, self.timeout)
        if not ok:
            return DeviceResult(ok=False, message=f"SSH falló: {out}")

        lines = [l for l in out.splitlines() if l.strip()]
        drop_ips: dict = {}
        for line in lines:
            # Formato: "... proto TCP ..., 1.2.3.4:port->dst:port ..."
            m = re.search(r'(\d{1,3}(?:\.\d{1,3}){3}):\d+->[\d.]+:\d+', line)
            if m:
                ip = m.group(1)
                drop_ips[ip] = drop_ips.get(ip, 0) + 1

        top = sorted(drop_ips.items(), key=lambda x: x[1], reverse=True)[:5]
        return DeviceResult(
            ok=True,
            message=f"{len(lines)} entradas firewall",
            data={
                "total_entries": len(lines),
                "top_attackers": [{"ip": ip, "drops": n} for ip, n in top],
            },
        )

    def get_connection_count(self) -> DeviceResult:
        """Total de conexiones activas en RouterOS."""
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "/ip firewall connection print count-only",
                          self.port, self.timeout)
        try:
            count = int(out.strip())
            return DeviceResult(ok=True, message=f"{count} conexiones",
                                data={"count": count})
        except Exception:
            return DeviceResult(ok=ok, message=out or "sin datos")
