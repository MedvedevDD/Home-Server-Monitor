"""Normalized cooling state models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CoolingStatus:
    board: str = ""
    controller: str = ""
    bios_fan_profile: str = ""
    mode: str = "unknown"
    pwm2_raw: int | None = None
    pwm2_percent: float | None = None
    cpu_max_c: float | None = None
    system_temp_c: float | None = None
    hdd_max_c: float | None = None
    source: str = "unknown"
    last_change: float | None = None
    last_update: float | None = None
    hdd_input_available: bool = False
    hdd_input_c: float | None = None
    auto_applied: bool = False
    fans: dict[str, int | None] = field(default_factory=dict)
    status_polled: bool = False
    hardware_access_ok: bool = True
    bmc_all_sensors_na: bool = False
    health_code: int = 1
    health_status: str = "OK"
    last_error: str = ""
    consecutive_errors: int = 0
    next_retry_unix: float | None = None
    status_sample_age_seconds: float | None = None
