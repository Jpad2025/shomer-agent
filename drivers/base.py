"""Contrato base que todos los drivers deben cumplir."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DriverLevel(str, Enum):
    FULL   = "full"    # ping + SSH/API + reboot + clientes
    API    = "api"     # ping + reboot + clientes via HTTP
    PING   = "ping"    # solo ICMP — monitoreo pasivo
    NONE   = "none"    # sin acceso


@dataclass
class DeviceResult:
    ok: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)


class DeviceDriver:
    """Clase base. Todos los drivers heredan de aquí."""

    NAME = "base"
    LEVEL = DriverLevel.NONE

    def __init__(self, ip: str, user: str = "", password: str = "",
                 port: int = 22, timeout: int = 8):
        self.ip = ip
        self.user = user
        self.password = password
        self.port = port
        self.timeout = timeout

    def ping(self) -> DeviceResult:
        """ICMP ping — implementado en base, igual para todos."""
        import subprocess
        try:
            r = subprocess.run(
                ["ping", "-c", "2", "-W", "2", self.ip],
                capture_output=True, text=True, timeout=6
            )
            ok = r.returncode == 0
            loss = "100%" if not ok else "0%"
            for line in r.stdout.splitlines():
                if "packet loss" in line:
                    loss = line.split("%")[0].split()[-1] + "%"
            return DeviceResult(ok=ok, message=f"ping {'OK' if ok else 'FAIL'} — pérdida {loss}",
                                data={"loss_pct": loss})
        except Exception as e:
            return DeviceResult(ok=False, message=f"ping error: {e}")

    def reboot(self) -> DeviceResult:
        return DeviceResult(ok=False, message="reboot no implementado para este driver")

    def get_clients(self) -> DeviceResult:
        return DeviceResult(ok=False, message="get_clients no implementado", data={"clients": []})

    def get_info(self) -> DeviceResult:
        return DeviceResult(ok=False, message="get_info no implementado", data={})

    def test_connection(self) -> DeviceResult:
        """Verifica si podemos conectar (para detección automática)."""
        return DeviceResult(ok=False, message="no implementado")
