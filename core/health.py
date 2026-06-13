"""Comprobaciones Green State post-acción (Capa D — catálogo autónomo)."""
from __future__ import annotations

import socket
from typing import Any, Dict, Optional

from core import repair
from core import shomer_api


def check_tcp(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_service(unit_key: str) -> Dict[str, Any]:
    svc = repair.SERVICES.get(unit_key)
    if not svc:
        return {"ok": False, "detail": "servicio desconocido"}
    ok = check_tcp(svc["host"], svc["port"])
    return {"ok": ok, "detail": f"{unit_key}={'active' if ok else 'inactive'}"}


def check_disk_root_below(threshold_pct: float = 80.0) -> Dict[str, Any]:
    disk = shomer_api.get_disk_usage()
    if not disk.get("ok"):
        return {"ok": False, "detail": "sin datos disco"}
    root = next((p for p in disk.get("partitions", []) if p.get("mount") == "/"), None)
    if not root:
        return {"ok": False, "detail": "sin partición /"}
    pct = float(root.get("pct", 100))
    return {
        "ok": pct < threshold_pct,
        "detail": f"/ al {pct}%",
        "pct": pct,
        "free_gb": root.get("free_gb"),
    }


def check_disk_improved(before_pct: float, min_drop: float = 2.0) -> Dict[str, Any]:
    cur = check_disk_root_below(100)
    if not cur.get("pct"):
        return {"ok": False, "detail": cur.get("detail", "?")}
    after = float(cur["pct"])
    ok = after < 80 or after <= before_pct - min_drop
    return {
        "ok": ok,
        "detail": f"{before_pct}%→{after}%",
        "pct_before": before_pct,
        "pct_after": after,
    }


def check_suricata_active() -> Dict[str, Any]:
    from core import repair

    active = repair.is_suricata_active()
    return {"ok": active, "detail": "suricata active" if active else "suricata inactive"}


def check_port_free(port: int) -> Dict[str, Any]:
    ok = not check_tcp("127.0.0.1", port)
    return {"ok": ok, "detail": f"puerto {port} libre" if ok else f"puerto {port} ocupado"}


def check_guardian_node_online(ip: str) -> Dict[str, Any]:
    nodes = shomer_api.get_guardian_nodes()
    if not isinstance(nodes, list):
        return {"ok": False, "detail": "sin nodos"}
    node = next(
        (n for n in nodes if (n.get("ip") or n.get("ip_address")) == ip),
        None,
    )
    if not node:
        return {"ok": False, "detail": "nodo no encontrado"}
    status = (node.get("status") or "").lower()
    ok = status == "online"
    return {"ok": ok, "detail": f"status={status}", "status": status}
