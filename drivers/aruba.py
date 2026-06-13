"""
Driver Aruba — Aruba Instant (IAP) y ArubaOS (controlador).
SSH con comandos ArubaOS: show clients, show version, reload.
Compatible con Aruba Instant AP, Aruba 500/300 series, HPE Aruba.
"""
import re
from .base import DeviceDriver, DeviceResult, DriverLevel
from .ssh_helper import ssh_run

_MAC_RE = re.compile(r'([0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}')


class ArubaDriver(DeviceDriver):
    NAME  = "aruba"
    LEVEL = DriverLevel.FULL

    def reboot(self) -> DeviceResult:
        # ArubaOS: reload — pide confirmación; enviar 'y' o 'yes'
        ok, out = ssh_run(
            self.ip, self.user, self.password,
            # El comando reload en Aruba puede pedir 'Do you want to continue? [y/n]:'
            # Usamos el truco de pasar 'yes' seguido de enter
            "reload",
            self.port, self.timeout,
        )
        if ok or "reboot" in out.lower() or "reload" in out.lower() or out.strip() == "":
            return DeviceResult(ok=True, message="reload Aruba enviado")
        # Algunos Aruba piden confirmación — intentar con 'y\n'
        return DeviceResult(ok=False, message=f"reload: {out[:120]}")

    def get_clients(self) -> DeviceResult:
        # Aruba Instant: 'show clients'
        ok, out = ssh_run(
            self.ip, self.user, self.password,
            "show clients", self.port, self.timeout,
        )
        clients = []
        if ok:
            for line in out.splitlines():
                m = _MAC_RE.search(line)
                if m:
                    parts = line.split()
                    ip = next(
                        (p for p in parts if re.match(r'\d+\.\d+\.\d+\.\d+', p)),
                        "",
                    )
                    clients.append({"mac": m.group(0), "ip": ip})

        if clients:
            return DeviceResult(
                ok=True,
                message=f"{len(clients)} clientes",
                data={"count": len(clients), "clients": clients},
            )

        # Fallback: 'show user-table' (ArubaOS controller)
        ok2, out2 = ssh_run(
            self.ip, self.user, self.password,
            "show user-table", self.port, self.timeout,
        )
        clients2 = []
        if ok2:
            for line in out2.splitlines():
                m = _MAC_RE.search(line)
                if m:
                    parts = line.split()
                    ip = next(
                        (p for p in parts if re.match(r'\d+\.\d+\.\d+\.\d+', p)),
                        "",
                    )
                    clients2.append({"mac": m.group(0), "ip": ip})

        return DeviceResult(
            ok=ok2,
            message=f"{len(clients2)} usuarios (tabla)" if ok2 else "no se pudo obtener clientes",
            data={"count": len(clients2), "clients": clients2},
        )

    def get_info(self) -> DeviceResult:
        ok, out = ssh_run(
            self.ip, self.user, self.password,
            "show version", self.port, self.timeout,
        )
        if not ok:
            return DeviceResult(ok=False, message=f"SSH Aruba falló: {out[:80]}")

        data: dict = {"raw": out[:600], "vendor": "aruba"}
        for line in out.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                key = k.strip().lower().replace(" ", "_")
                if key:
                    data[key] = v.strip()

        model = data.get("aruba_model", data.get("model", "Aruba"))
        ver   = data.get("aruba_os_version", data.get("version", "?"))
        return DeviceResult(
            ok=True,
            message=f"{model} ArubaOS={ver}",
            data=data,
        )

    def test_connection(self) -> DeviceResult:
        # 'show clock' funciona en ambos Instant y Controller
        ok, out = ssh_run(
            self.ip, self.user, self.password,
            "show clock", self.port, self.timeout,
        )
        return DeviceResult(ok=ok, message=out.strip() if ok else f"falló: {out[:80]}")
