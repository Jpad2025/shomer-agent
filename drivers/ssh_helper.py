"""Helper SSH compartido por todos los drivers que usan SSH."""
import subprocess
import shutil
from typing import Optional, Tuple


# Algoritmos legacy para equipos con firmware viejo (Ubiquiti, MikroTik viejos)
LEGACY_KEX = (
    "diffie-hellman-group14-sha256,"
    "diffie-hellman-group14-sha1,"
    "diffie-hellman-group1-sha1,"
    "curve25519-sha256,"
    "ecdh-sha2-nistp256"
)
LEGACY_HOSTKEY = "ssh-rsa,ssh-dss,ecdsa-sha2-nistp256,ssh-ed25519"


def ssh_run(ip: str, user: str, password: str, command: str,
            port: int = 22, timeout: int = 10,
            legacy: bool = False) -> Tuple[bool, str]:
    """
    Ejecuta un comando SSH y devuelve (éxito, output).
    Usa sshpass si hay contraseña, llave SSH si no.
    """
    sshpass = shutil.which("sshpass")

    base_opts = [
        "-o", f"ConnectTimeout={timeout}",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "BatchMode=no" if password else "BatchMode=yes",
        "-p", str(port),
    ]

    if legacy:
        base_opts += [
            "-o", f"KexAlgorithms={LEGACY_KEX}",
            "-o", f"HostKeyAlgorithms={LEGACY_HOSTKEY}",
            "-o", f"PubkeyAcceptedAlgorithms=+ssh-rsa,ssh-dss",
        ]

    if password and sshpass:
        cmd = [sshpass, "-p", password, "ssh"] + base_opts + [f"{user}@{ip}", command]
    else:
        cmd = ["ssh"] + base_opts + [f"{user}@{ip}", command]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout + 5)
        output = (r.stdout or r.stderr or "").strip()
        return r.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "timeout SSH"
    except Exception as e:
        return False, str(e)
