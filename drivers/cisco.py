"""
Driver Cisco — switches SG/SF y routers IOS básicos.
El comando de reboot en IOS es 'reload' con confirmación.
"""
from .base import DeviceDriver, DeviceResult, DriverLevel
from .ssh_helper import ssh_run
import subprocess, shutil


class CiscoDriver(DeviceDriver):
    NAME  = "cisco"
    LEVEL = DriverLevel.FULL

    def reboot(self) -> DeviceResult:
        # Cisco IOS requiere 'reload' + confirmar con Enter
        sshpass = shutil.which("sshpass")
        if not sshpass:
            return DeviceResult(ok=False, message="sshpass no disponible")
        try:
            cmd = [
                sshpass, "-p", self.password,
                "ssh",
                "-o", f"ConnectTimeout={self.timeout}",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
                "-o", "HostKeyAlgorithms=+ssh-rsa",
                "-p", str(self.port),
                f"{self.user}@{self.ip}",
            ]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Enviar 'reload' + Enter para confirmar
            out, err = proc.communicate(input=b"reload\n\n", timeout=self.timeout + 5)
            output = (out + err).decode("utf-8", errors="replace")
            if "reload" in output.lower() or proc.returncode in (0, 1):
                return DeviceResult(ok=True, message="reload IOS enviado")
            return DeviceResult(ok=False, message=f"reload falló: {output[:100]}")
        except Exception as e:
            return DeviceResult(ok=False, message=str(e))

    def get_clients(self) -> DeviceResult:
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "show arp", self.port, self.timeout)
        clients = []
        if ok:
            for line in out.splitlines():
                parts = line.split()
                # Formato: Protocol Address Age(min) Hardware Addr Type Interface
                if len(parts) >= 4 and parts[0] in ("Internet",):
                    clients.append({"ip": parts[1], "mac": parts[3]})
            return DeviceResult(ok=True, message=f"{len(clients)} entradas ARP",
                                data={"count": len(clients), "clients": clients})
        return DeviceResult(ok=False, message=f"SSH Cisco falló: {out}", data={"clients": []})

    def get_info(self) -> DeviceResult:
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "show version | head -5", self.port, self.timeout)
        if ok:
            return DeviceResult(ok=True, message="info IOS obtenida",
                                data={"raw": out, "vendor": "cisco"})
        return DeviceResult(ok=False, message=f"SSH Cisco falló: {out}")

    def test_connection(self) -> DeviceResult:
        ok, out = ssh_run(self.ip, self.user, self.password,
                          "show clock", self.port, self.timeout)
        return DeviceResult(ok=ok, message=out if ok else f"falló: {out}")
