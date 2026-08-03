"""Combined current storage status model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StorageStatus:
    """Represent the latest combined inventory and SMART state for one disk."""

    status: str
    health_score: int
    smart_available: bool
    smartctl_exit_code: int | None
    health_passed: bool | None
    temperature_c: int | None
    reallocated_sectors: int | None
    pending_sectors: int | None
    offline_uncorrectable: int | None
    crc_errors: int | None
