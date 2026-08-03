"""NUT UPS collector."""

from __future__ import annotations

import logging
import socket
import subprocess
from collections.abc import Mapping

import config
from models.ups_status import UPSStatus


LOGGER = logging.getLogger("home_server_monitor.collectors.ups")


class UPSCollectionError(RuntimeError):
    """Raised when UPS data cannot be collected or parsed."""


def _optional_float(values: Mapping[str, str], key: str) -> float | None:
    raw = values.get(key, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        LOGGER.warning("Ignoring non-numeric UPS value %s=%r", key, raw)
        return None


def _optional_int(values: Mapping[str, str], key: str) -> int | None:
    value = _optional_float(values, key)
    return None if value is None else int(value)


def _estimate_charge_percent(voltage: float | None) -> float | None:
    """Estimate charge for a 48 V lead-acid bank and clamp to 0..100."""
    if voltage is None:
        return None
    empty = config.UPS_BATTERY_EMPTY_VOLTAGE
    full = config.UPS_BATTERY_FULL_VOLTAGE
    if full <= empty:
        raise ValueError("UPS full voltage must be greater than empty voltage")
    charge = (voltage - empty) * 100.0 / (full - empty)
    return round(max(0.0, min(100.0, charge)), 1)


def _normalize_status(raw_status: str) -> tuple[str, int, dict[str, bool]]:
    flags = {item.upper() for item in raw_status.split() if item.strip()}
    state = {
        "online": "OL" in flags,
        "on_battery": "OB" in flags,
        "low_battery": "LB" in flags,
        "overload": "OVER" in flags,
        "charging": "CHRG" in flags,
        "discharging": "DISCHRG" in flags,
        "replace_battery": "RB" in flags,
    }

    if state["low_battery"]:
        status = "Critical"
        status_code = 3
    elif state["on_battery"] or state["overload"] or state["replace_battery"]:
        status = "Warning"
        status_code = 2
    elif state["online"]:
        status = "Online"
        status_code = 1
    else:
        status = "Unknown"
        status_code = 0
    return status, status_code, state


class UPSCollector:
    """Collect one UPS through the NUT upsc command."""

    def __init__(self, ups_name: str | None = None) -> None:
        self.ups_name = (ups_name or config.UPS_NAME).strip()

    def _run_upsc(self) -> str:
        if not self.ups_name:
            raise UPSCollectionError("UPS name is empty")
        command = [config.UPSC_BINARY, self.ups_name]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=config.UPSC_TIMEOUT_SECONDS,
                check=False,
            )
        except FileNotFoundError as exc:
            raise UPSCollectionError(f"{config.UPSC_BINARY} was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise UPSCollectionError("upsc command timed out") from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise UPSCollectionError(f"upsc failed: {detail}")
        return completed.stdout

    @staticmethod
    def parse(output: str, ups_name: str, host: str | None = None) -> UPSStatus:
        values: dict[str, str] = {}
        for line in output.splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            values[key.strip()] = value.strip()

        raw_status = values.get("ups.status", "")
        status, status_code, state = _normalize_status(raw_status)
        voltage = _optional_float(values, "battery.voltage")
        beeper_text = values.get("ups.beeper.status", "").strip().lower()
        beeper_enabled = None
        if beeper_text:
            beeper_enabled = beeper_text not in {"disabled", "off", "muted", "0"}

        return UPSStatus(
            ups_name=ups_name,
            host=host or socket.gethostname(),
            model=values.get("device.model", values.get("ups.model", "")),
            serial=values.get("device.serial", values.get("ups.serial", "")),
            status=status,
            raw_status=raw_status,
            status_code=status_code,
            battery_voltage=voltage,
            battery_charge_estimated=_estimate_charge_percent(voltage),
            input_voltage=_optional_float(values, "input.voltage"),
            output_voltage=_optional_float(values, "output.voltage"),
            input_frequency=_optional_float(values, "input.frequency"),
            load_percent=_optional_float(values, "ups.load"),
            internal_temp=_optional_float(values, "ups.temperature"),
            beeper_enabled=beeper_enabled,
            delay_start_seconds=_optional_int(values, "ups.delay.start"),
            delay_shutdown_seconds=_optional_int(values, "ups.delay.shutdown"),
            **state,
        )

    def collect(self) -> UPSStatus:
        return self.parse(self._run_upsc(), self.ups_name)
