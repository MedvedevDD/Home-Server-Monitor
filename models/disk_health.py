"""Dynamic SMART health data for one physical disk."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiskHealth:
    """Represent one SMART collection result without modifying disk inventory."""

    serial: str
    device: str
    smart_available: bool
    health_passed: bool | None
    temperature_c: int | None
    reallocated_sectors: int | None
    pending_sectors: int | None
    offline_uncorrectable: int | None
    crc_errors: int | None
    smartctl_exit_code: int
    error: str | None = None
