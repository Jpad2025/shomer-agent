"""
Driver Linux genérico — Ubiquiti UAP/EdgeRouter, DD-WRT, OpenWrt,
Raspberry Pi, cualquier equipo con SSH y shell Linux estándar.
"""
from .base import DeviceDriver, DeviceResult, DriverLevel
from .ssh_helper import ssh_run


class LinuxGenericDriver(DeviceDriver):
    NAME  = "linux"
    LEVEL = DriverLevel.FULL

    def reboot(self) -> DeviceResult:
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "reboot", self.port, self.timeout)
        # reboot corta la conexión — exit != 0 es normal
        if ok or "closed" in out.lower() or out == "":
            return DeviceResult(ok=True, message="reboot enviado")
        return DeviceResult(ok=False, message=f"reboot falló: {out}")

    def get_clients(self) -> DeviceResult:
        # iw dev — funciona en APs con hostapd (Ubiquiti, OpenWrt)
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "iw dev 2>/dev/null | grep -c 'Station' || "
                          "cat /tmp/dhcp.leases 2>/dev/null || "
                          "cat /var/lib/misc/dnsmasq.leases 2>/dev/null | wc -l",
                          self.port, self.timeout)
        clients = []
        if ok and out.strip().isdigit():
            return DeviceResult(ok=True, message=f"{out.strip()} clientes",
                                data={"count": int(out.strip()), "clients": clients})
        # Intentar tabla ARP como fallback
        ok2, out2 = ssh_run(self.ip, self.user, self.password,
                            "arp -n 2>/dev/null | grep -v incomplete | tail -n +2",
                            self.port, self.timeout)
        if ok2:
            for line in out2.splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    clients.append({"ip": parts[0], "mac": parts[2]})
            return DeviceResult(ok=True, message=f"{len(clients)} entradas ARP",
                                data={"count": len(clients), "clients": clients})
        return DeviceResult(ok=False, message="no se pudo obtener clientes", data={"clients": []})

    def get_info(self) -> DeviceResult:
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "uname -a; uptime; cat /etc/openwrt_release 2>/dev/null || "
                          "cat /etc/os-release 2>/dev/null | head -4",
                          self.port, self.timeout)
        if ok:
            return DeviceResult(ok=True, message="info obtenida",
                                data={"raw": out, "vendor": "linux"})
        return DeviceResult(ok=False, message=f"SSH falló: {out}")

    def test_connection(self) -> DeviceResult:
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "echo ok", self.port, self.timeout)
        return DeviceResult(ok=ok, message=out)

    def get_security_log(self) -> DeviceResult:
        """Log de drops del firewall Linux/OpenWrt + conteo de conexiones."""
        import re
        cmd = (
            "logread -l 200 2>/dev/null | grep -iE 'DROP|REJECT|blocked' | tail -100 ;"
            " echo '---CONN---' ;"
            " cat /proc/net/nf_conntrack 2>/dev/null | wc -l || echo 0"
        )
        ok, out = ssh_run(self.ip, self.user, self.password, cmd, self.port, self.timeout)
        if not ok and not out:
            return DeviceResult(ok=False, message="SSH falló o sin datos")

        parts = out.split("---CONN---")
        log_lines = [l for l in parts[0].strip().splitlines() if l.strip()]
        try:
            conn_count = int(parts[1].strip().splitlines()[0]) if len(parts) > 1 else 0
        except Exception:
            conn_count = 0

        drop_ips: dict = {}
        for line in log_lines:
            m = re.search(r'SRC=(\d{1,3}(?:\.\d{1,3}){3})', line, re.IGNORECASE)
            if m:
                ip = m.group(1)
                drop_ips[ip] = drop_ips.get(ip, 0) + 1

        top = sorted(drop_ips.items(), key=lambda x: x[1], reverse=True)[:5]
        return DeviceResult(
            ok=True,
            message=f"{len(log_lines)} drops, {conn_count} conexiones",
            data={
                "drop_count": len(log_lines),
                "conn_count": conn_count,
                "top_attackers": [{"ip": ip, "drops": n} for ip, n in top],
            },
        )
