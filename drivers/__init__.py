"""
Drivers multi-vendor para el agente Shomer.
Cada driver implementa: ping(), reboot(), get_clients(), get_info()
"""
from .base import DeviceDriver, DeviceResult, DriverLevel
from .linux_generic import LinuxGenericDriver
from .mikrotik import MikroTikDriver
from .tplink_eap import TpLinkEapDriver
from .cisco import CiscoDriver
from .detector import detect_driver

__all__ = [
    "DeviceDriver", "DeviceResult", "DriverLevel",
    "LinuxGenericDriver", "MikroTikDriver", "TpLinkEapDriver",
    "CiscoDriver", "detect_driver",
]
