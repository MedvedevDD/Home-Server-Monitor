"""Normalized UPS status model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UPSStatus:
    """Current normalized UPS state."""

    ups_name: str
    host: str
    model: str = ""
    serial: str = ""
    status: str = "Unknown"
    raw_status: str = ""
    status_code: int = 0
    online: bool = False
    on_battery: bool = False
    low_battery: bool = False
    overload: bool = False
    charging: bool = False
    discharging: bool = False
    replace_battery: bool = False
    battery_voltage: float | None = None
    battery_charge_estimated: float | None = None
    input_voltage: float | None = None
    output_voltage: float | None = None
    input_frequency: float | None = None
    load_percent: float | None = None
    internal_temp: float | None = None
    beeper_enabled: bool | None = None
    delay_start_seconds: int | None = None
    delay_shutdown_seconds: int | None = None
