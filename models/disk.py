"""Data model for a physical storage device."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Disk:
    """Represent inventory and future health data for one physical disk."""

    serial: str = ""
    vendor: str = ""
    model: str = ""
    display_name: str = ""
    capacity: str = ""
    capacity_bytes: int = 0
    disk_type: str = ""
    transport: str = ""
    device: str = ""
    device_class: str = "UNKNOWN"
    removable: bool = False
    hotplug: bool = False
    temperature: float | None = None
    smart_health: str | None = None
    reallocated: int = 0
    pending: int = 0
    offline: int = 0
    crc: int = 0
