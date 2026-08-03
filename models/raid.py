"""Normalized RAID state models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RaidControllerStatus:
    provider: str
    controller: str
    model: str = ""
    serial: str = ""
    firmware: str = ""
    status: str = "Unknown"
    status_code: int = 0
    health_score: int = 50
    temperature_c: float | None = None
    cache_status: str = ""
    battery_status: str = ""
    patrol_read_status: str = ""
    virtual_drive_count: int = 0
    physical_drive_count: int = 0
    jbod_mode: bool = False


@dataclass(frozen=True)
class RaidArrayStatus:
    provider: str
    controller: str
    array_id: str
    name: str = ""
    raid_level: str = ""
    status: str = "Unknown"
    status_code: int = 0
    health_score: int = 50
    size_bytes: int | None = None
    progress_percent: float | None = None
    operation: str = ""


@dataclass(frozen=True)
class RaidDriveStatus:
    provider: str
    controller: str
    drive_id: str
    enclosure: str = ""
    slot: str = ""
    model: str = ""
    serial: str = ""
    state: str = "Unknown"
    status: str = "Unknown"
    status_code: int = 0
    health_score: int = 50
    size_bytes: int | None = None
    media_errors: int | None = None
    other_errors: int | None = None
    predictive_failures: int | None = None
    temperature_c: float | None = None
