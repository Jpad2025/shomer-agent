"""
Driver Ubiquiti UniFi — UAP-AC, UAP-U6, NanoStation, EdgeRouter.
SSH al AP directamente (no requiere UniFi Controller).
Comandos específicos: info, mca-dump, syswrapper.sh.
"""
import re
from .base import DeviceDriver, DeviceResult, DriverLevel
from .ssh_helper import ssh_run


class UbiquitiDriver(DeviceDriver):
    NAME  = "ubiquiti"
    LEVEL = DriverLevel.FULL

    def reboot(self) -> DeviceResult:
        # syswrapper.sh restart es más limpio (UniFi)
        # Si no existe (EdgeRouter), fallback a reboot estándar
        ok, out = ssh_run(
            self.ip, self.user, self.password,
            "syswrapper.sh restart 2>/dev/null || reboot",
            self.port, self.timeout,
        )
        if ok or "closed" in out.lower() or out.strip() == "":
            return DeviceResult(ok=True, message="reboot UniFi enviado")
        return DeviceResult(ok=False, message=f"reboot falló: {out[:80]}")

    def get_clients(self) -> DeviceResult:
        # Contar estaciones WiFi asociadas por todas las interfaces
        ok, out = ssh_run(
            self.ip, self.user, self.password,
            "for iface in $(iw dev 2>/dev/null | awk '/Interface/{print $2}'); do "
            "  iw dev $iface station dump 2>/dev/null; "
            "done | grep -c '^Station' 2>/dev/null || echo 0",
            self.port, self.timeout,
        )
        if ok:
            try:
                count = int(out.strip().splitlines()[0])
                return DeviceResult(
                    ok=True,
                    message=f"{count} clientes WiFi",
                    data={"count": count, "clients": []},
                )
            except Exception:
                pass

        # Fallback: tabla ARP local
        ok2, out2 = ssh_run(
            self.ip, self.user, self.password,
            "arp -n 2>/dev/null | grep -v 'incomplete' | tail -n +2",
            self.port, self.timeout,
        )
        clients = []
        if ok2:
            for line in out2.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0][0].isdigit():
                    clients.append({"ip": parts[0], "mac": parts[2]})
        return DeviceResult(
            ok=True,
            message=f"{len(clients)} entradas ARP",
            data={"count": len(clients), "clients": clients},
        )

    def get_info(self) -> DeviceResult:
        ok, out = ssh_run(
            self.ip, self.user, self.password,
            "info 2>/dev/null; echo '==='; cat /etc/version 2>/dev/null; "
            "echo '==='; uptime 2>/dev/null",
            self.port, self.timeout,
        )
        if not ok and not out:
            return DeviceResult(ok=False, message=f"SSH UniFi falló: {out[:80]}")

        data: dict = {"raw": out[:600], "vendor": "ubiquiti"}
        # Parsear campos "Key: Value" del comando info
        for line in out.splitlines():
            if ":" in line and not line.startswith("="):
                k, _, v = line.partition(":")
                key = k.strip().lower().replace(" ", "_")
                data[key] = v.strip()

        model = data.get("model", "UniFi")
        ver   = data.get("version", data.get("firmware_version", "?"))
        return DeviceResult(
            ok=True,
            message=f"{model} fw={ver}",
            data=data,
        )

    def get_security_log(self) -> DeviceResult:
        """Drops del firewall local del AP (iptables/nftables)."""
        ok, out = ssh_run(
            self.ip, self.user, self.password,
            "iptables -L INPUT -n --line-numbers 2>/dev/null | grep -i 'DROP\\|REJECT' | head -20",
            self.port, self.timeout,
        )
        lines = [l for l in (out or "").splitlines() if l.strip()]
        return DeviceResult(
            ok=ok,
            message=f"{len(lines)} reglas drop en INPUT",
            data={"drop_rules": lines},
        )

    def test_connection(self) -> DeviceResult:
        ok, out = ssh_run(
            self.ip, self.user, self.password,
            "echo ok", self.port, self.timeout,
        )
        return DeviceResult(ok=ok, message=out.strip() if ok else f"falló: {out[:80]}")
