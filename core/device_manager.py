"""
Gestor de dispositivos — carga, guarda y opera sobre el inventario de equipos.
Persiste en /data/devices.json dentro del contenedor (volumen montado).
"""
import json
import os
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime

import sys
sys.path.insert(0, "/app")
from drivers.detector import detect_driver
from drivers.base import DeviceDriver, DriverLevel

DATA_FILE = os.environ.get("DEVICES_FILE", "/app/data/devices.json")
_lock = threading.Lock()


def _load() -> Dict[str, Any]:
    if os.path.isfile(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def list_devices() -> List[Dict[str, Any]]:
    with _lock:
        db = _load()
        return list(db.values())


def get_device(ip: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return _load().get(ip)


def add_device(ip: str, name: str, user: str, password: str,
               vendor_hint: str = "", port: int = 22) -> Dict[str, Any]:
    with _lock:
        db = _load()
        db[ip] = {
            "ip": ip,
            "name": name,
            "user": user,
            "password": password,
            "vendor_hint": vendor_hint,
            "port": port,
            "level": "unknown",
            "last_seen": None,
            "last_reboot": None,
            "status": "unknown",
            "added_at": datetime.utcnow().isoformat(),
        }
        _save(db)
        return db[ip]


def remove_device(ip: str) -> bool:
    with _lock:
        db = _load()
        if ip in db:
            del db[ip]
            _save(db)
            return True
        return False


def update_status(ip: str, status: str, extra: Dict = None) -> None:
    with _lock:
        db = _load()
        if ip in db:
            db[ip]["status"] = status
            db[ip]["last_seen"] = datetime.utcnow().isoformat()
            if extra:
                db[ip].update(extra)
            _save(db)


def get_driver(ip: str) -> DeviceDriver:
    dev = get_device(ip)
    if not dev:
        return DeviceDriver(ip)
    return detect_driver(
        ip=ip,
        user=dev.get("user", ""),
        password=dev.get("password", ""),
        port=int(dev.get("port", 22)),
        vendor_hint=dev.get("vendor_hint", ""),
    )


def ping_device(ip: str) -> Dict[str, Any]:
    drv = get_driver(ip)
    result = drv.ping()
    status = "online" if result.ok else "offline"
    update_status(ip, status)
    return {"ip": ip, "ok": result.ok, "message": result.message}


def reboot_device(ip: str) -> Dict[str, Any]:
    dev = get_device(ip)
    if dev and dev.get("no_reboot"):
        return {"ip": ip, "ok": False,
                "message": f"⛔ {dev.get('name', ip)} tiene reboot bloqueado — {dev.get('note', 'equipo crítico')}"}
    drv = get_driver(ip)
    if drv.LEVEL == DriverLevel.NONE or drv.LEVEL == DriverLevel.PING:
        return {"ip": ip, "ok": False,
                "message": "equipo en modo solo-ping — reboot no disponible remotamente"}
    result = drv.reboot()
    if result.ok:
        with _lock:
            db = _load()
            if ip in db:
                db[ip]["last_reboot"] = datetime.utcnow().isoformat()
                _save(db)
    return {"ip": ip, "ok": result.ok, "message": result.message}


def get_clients(ip: str) -> Dict[str, Any]:
    drv = get_driver(ip)
    result = drv.get_clients()
    return {"ip": ip, "ok": result.ok, "message": result.message,
            "data": result.data}


def get_info(ip: str) -> Dict[str, Any]:
    drv = get_driver(ip)
    result = drv.get_info()
    return {"ip": ip, "ok": result.ok, "message": result.message,
            "data": result.data}
