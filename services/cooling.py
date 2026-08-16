"""Cooling integration for x8fan with event-driven hardware access."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import config
from models.cooling import CoolingStatus
from services.command_runner import CommandRunner, CommandRunnerError

LOGGER = logging.getLogger("home_server_monitor.cooling")

HDD_RISING_THRESHOLDS = (35.0, 40.0, 45.0, 50.0, 55.0)
HDD_FALLING_THRESHOLDS = (32.0, 37.0, 42.0, 47.0, 52.0)
CPU_EMERGENCY = 85.0
CPU_EMERGENCY_RELEASE = 80.0
BACKOFF_SECONDS = (60, 300, 900)


class CoolingCollectionError(RuntimeError):
    pass


class InfluxTemperatureSource:
    def __init__(
        self,
        url: str = config.COOLING_INFLUX_URL,
        database: str = config.COOLING_INFLUX_DATABASE,
        max_age_seconds: int = config.COOLING_DISK_MAX_AGE_SECONDS,
        timeout_seconds: int = config.COOLING_INFLUX_TIMEOUT_SECONDS,
    ) -> None:
        self.url = url
        self.database = database
        self.max_age_seconds = max_age_seconds
        self.timeout_seconds = timeout_seconds

    def _query(self, query: str) -> Mapping[str, Any]:
        params = urllib.parse.urlencode({"db": self.database, "q": query})
        request = urllib.request.Request(f"{self.url}?{params}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CoolingCollectionError(f"InfluxDB temperature query failed: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise CoolingCollectionError("InfluxDB returned an invalid JSON root")
        return payload

    @staticmethod
    def _values(payload: Mapping[str, Any]) -> list[float]:
        temperatures: list[float] = []
        results = payload.get("results")
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            return temperatures
        for result in results:
            if not isinstance(result, Mapping):
                continue
            series = result.get("series")
            if not isinstance(series, Sequence) or isinstance(series, (str, bytes)):
                continue
            for item in series:
                if not isinstance(item, Mapping):
                    continue
                columns = item.get("columns")
                values = item.get("values")
                if not isinstance(columns, Sequence) or not isinstance(values, Sequence):
                    continue
                try:
                    index = list(columns).index("temperature_c")
                except ValueError:
                    continue
                for row in values:
                    if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
                        continue
                    if index >= len(row):
                        continue
                    value = row[index]
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        temperatures.append(float(value))
        return temperatures

    def maximum_temperature(self) -> float | None:
        age = max(1, int(self.max_age_seconds))
        queries = (
            (
                'SELECT last("temperature_c") AS "temperature_c" '
                f'FROM "storage_status" WHERE time > now() - {age}s GROUP BY "serial"'
            ),
            (
                'SELECT last("temperature_c") AS "temperature_c" '
                f'FROM "raid_drive_status" WHERE time > now() - {age}s '
                'GROUP BY "provider","controller","drive_id"'
            ),
        )
        values: list[float] = []
        for query in queries:
            values.extend(self._values(self._query(query)))
        return max(values) if values else None


class X8FanClient:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or CommandRunner(config.COOLING_X8FAN_TIMEOUT_SECONDS)

    def _run(self, args: list[str]) -> str:
        command = [config.COOLING_X8FAN_HELPER, *args]
        if config.COOLING_X8FAN_USE_SUDO:
            command = ["sudo", "-n", *command]
        try:
            result = self.runner.run(command)
        except CommandRunnerError as exc:
            raise CoolingCollectionError(str(exc)) from exc
        if result.return_code != 0:
            detail = (result.stderr or result.stdout).strip()
            raise CoolingCollectionError(
                f"x8fan helper failed with exit code {result.return_code}: {detail}"
            )
        return result.stdout

    def auto(self, temperature_c: float) -> None:
        temperature = int(round(temperature_c))
        if temperature <= 0:
            raise CoolingCollectionError("Refusing to pass a non-positive disk temperature")
        self._run(["auto", str(temperature)])

    def status(self) -> CoolingStatus:
        output = self._run(["status"])
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise CoolingCollectionError("x8fan status returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise CoolingCollectionError("x8fan status JSON root is not an object")

        fans_payload = payload.get("fans")
        fans: dict[str, int | None] = {}
        if isinstance(fans_payload, Mapping):
            for fan_id in range(1, 9):
                raw = fans_payload.get(str(fan_id))
                fans[str(fan_id)] = (
                    int(raw)
                    if isinstance(raw, (int, float)) and not isinstance(raw, bool)
                    else None
                )

        def number(name: str) -> float | None:
            value = payload.get(name)
            return (
                float(value)
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else None
            )

        def temperature(name: str) -> float | None:
            value = number(name)
            if value is None:
                return None
            if value <= -100.0 or value > 150.0:
                LOGGER.warning("Ignoring invalid x8fan %s value: %s C", name, value)
                return None
            return value

        pwm_raw = payload.get("pwm2_raw")
        return CoolingStatus(
            board=str(payload.get("board") or ""),
            controller=str(payload.get("controller") or ""),
            bios_fan_profile=str(payload.get("bios_fan_profile") or ""),
            mode=str(payload.get("mode") or "unknown"),
            pwm2_raw=int(pwm_raw) if isinstance(pwm_raw, (int, float)) and not isinstance(pwm_raw, bool) else None,
            pwm2_percent=number("pwm2_percent"),
            cpu_max_c=temperature("cpu_max"),
            system_temp_c=temperature("system_temp"),
            hdd_max_c=temperature("hdd_max"),
            source=str(payload.get("source") or "unknown"),
            last_change=number("last_change"),
            last_update=number("last_update"),
            fans=fans,
        )


def cpu_max_temperature() -> float | None:
    values: list[float] = []
    base = Path("/sys/class/hwmon")
    if not base.is_dir():
        return None
    for entry in base.iterdir():
        try:
            if (entry / "name").read_text(encoding="utf-8").strip() != "coretemp":
                continue
        except OSError:
            continue
        for path in entry.glob("temp*_input"):
            try:
                value = float(path.read_text(encoding="utf-8").strip()) / 1000.0
            except (OSError, ValueError):
                continue
            if 0.0 < value < 120.0:
                values.append(value)
    return max(values) if values else None


def bmc_all_sensors_na() -> bool | None:
    try:
        completed = subprocess.run(
            ["ipmitool", "sensor", "list"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None

    total = 0
    available = 0
    for raw in completed.stdout.splitlines():
        if "|" not in raw:
            continue
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 2:
            continue
        total += 1
        reading = parts[1].strip().lower()
        if reading not in {"na", "n/a", "no reading", ""}:
            available += 1
    if total == 0:
        return None
    return available == 0


class CoolingCollector:
    def __init__(
        self,
        temperature_source: InfluxTemperatureSource | None = None,
        x8fan: X8FanClient | None = None,
        state_file: str | Path = config.COOLING_CONTROL_STATE_FILE,
        status_interval_seconds: int = config.COOLING_STATUS_INTERVAL_SECONDS,
    ) -> None:
        self.temperature_source = temperature_source or InfluxTemperatureSource()
        self.x8fan = x8fan or X8FanClient()
        self.state_file = Path(state_file)
        self.status_interval_seconds = max(60, int(status_interval_seconds))

    def _load_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
            temporary.write_text(
                json.dumps(state, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.state_file)
        except OSError as exc:
            LOGGER.warning("Unable to persist Cooling state: %s", exc)

    @staticmethod
    def _crossed_hdd_boundary(previous: float | None, current: float | None) -> bool:
        if previous is None:
            return current is not None
        if current is None or previous == current:
            return False
        if current > previous:
            return any(previous < threshold <= current for threshold in HDD_RISING_THRESHOLDS)
        return any(current < threshold <= previous for threshold in HDD_FALLING_THRESHOLDS)

    @staticmethod
    def _cpu_transition(previous_emergency: bool, current: float | None) -> tuple[bool, bool]:
        if current is None:
            return False, previous_emergency
        if not previous_emergency and current >= CPU_EMERGENCY:
            return True, True
        if previous_emergency and current < CPU_EMERGENCY_RELEASE:
            return True, False
        return False, previous_emergency

    @staticmethod
    def _backoff_seconds(error_count: int) -> int:
        index = min(max(error_count, 1), len(BACKOFF_SECONDS)) - 1
        return BACKOFF_SECONDS[index]

    @staticmethod
    def _status_to_cache(status: CoolingStatus) -> dict[str, Any]:
        return {
            "board": status.board,
            "controller": status.controller,
            "bios_fan_profile": status.bios_fan_profile,
            "mode": status.mode,
            "pwm2_raw": status.pwm2_raw,
            "pwm2_percent": status.pwm2_percent,
            "cpu_max_c": status.cpu_max_c,
            "system_temp_c": status.system_temp_c,
            "hdd_max_c": status.hdd_max_c,
            "source": status.source,
            "last_change": status.last_change,
            "last_update": status.last_update,
            "fans": status.fans,
        }

    @staticmethod
    def _cached_status(payload: Mapping[str, Any]) -> CoolingStatus:
        fans = payload.get("fans")
        return CoolingStatus(
            board=str(payload.get("board") or ""),
            controller=str(payload.get("controller") or ""),
            bios_fan_profile=str(payload.get("bios_fan_profile") or ""),
            mode=str(payload.get("mode") or "unknown"),
            pwm2_raw=payload.get("pwm2_raw") if isinstance(payload.get("pwm2_raw"), int) else None,
            pwm2_percent=float(payload["pwm2_percent"]) if isinstance(payload.get("pwm2_percent"), (int, float)) else None,
            cpu_max_c=float(payload["cpu_max_c"]) if isinstance(payload.get("cpu_max_c"), (int, float)) else None,
            system_temp_c=float(payload["system_temp_c"]) if isinstance(payload.get("system_temp_c"), (int, float)) else None,
            hdd_max_c=float(payload["hdd_max_c"]) if isinstance(payload.get("hdd_max_c"), (int, float)) else None,
            source=str(payload.get("source") or "unknown"),
            last_change=float(payload["last_change"]) if isinstance(payload.get("last_change"), (int, float)) else None,
            last_update=float(payload["last_update"]) if isinstance(payload.get("last_update"), (int, float)) else None,
            fans=dict(fans) if isinstance(fans, Mapping) else {},
        )

    def collect(self) -> CoolingStatus:
        now = time.time()
        state = self._load_state()

        try:
            hdd_temp = self.temperature_source.maximum_temperature()
        except CoolingCollectionError as exc:
            LOGGER.warning("%s", exc)
            hdd_temp = None
        cpu_temp = cpu_max_temperature()

        previous_hdd = state.get("last_hdd_temp")
        if not isinstance(previous_hdd, (int, float)):
            previous_hdd = None
        previous_emergency = bool(state.get("cpu_emergency", False))

        hdd_event = self._crossed_hdd_boundary(
            float(previous_hdd) if previous_hdd is not None else None,
            hdd_temp,
        )
        cpu_event, next_emergency = self._cpu_transition(previous_emergency, cpu_temp)
        control_event = hdd_event or cpu_event

        last_status_unix = float(state.get("last_status_unix", 0.0) or 0.0)
        status_due = (now - last_status_unix) >= self.status_interval_seconds

        next_retry_unix = float(state.get("next_retry_unix", 0.0) or 0.0)
        in_backoff = now < next_retry_unix
        can_attempt = not in_backoff or cpu_event

        auto_applied = False
        status_polled = False
        hardware_access_ok = bool(state.get("hardware_access_ok", True))
        all_na = bool(state.get("bmc_all_sensors_na", False))
        last_error = str(state.get("last_error") or "")
        errors = int(state.get("consecutive_errors", 0) or 0)
        cached = state.get("last_status") if isinstance(state.get("last_status"), Mapping) else {}
        status = self._cached_status(cached)

        attempted = False
        try:
            if control_event and hdd_temp is not None and can_attempt:
                attempted = True
                self.x8fan.auto(hdd_temp)
                auto_applied = True

            if (control_event or status_due) and can_attempt:
                attempted = True
                status = self.x8fan.status()
                status_polled = True
                hardware_access_ok = True
                all_na = False
                last_error = ""
                errors = 0
                next_retry_unix = 0.0
                last_status_unix = now
                cached = self._status_to_cache(status)

        except CoolingCollectionError as exc:
            last_error = str(exc)
            errors += 1
            hardware_access_ok = False
            all_na = bmc_all_sensors_na() is True
            next_retry_unix = now + self._backoff_seconds(errors)
            LOGGER.warning(
                "Cooling hardware access failed; next retry in %ss: %s",
                self._backoff_seconds(errors),
                exc,
            )

        if not attempted and in_backoff:
            hardware_access_ok = False

        if auto_applied:
            if hdd_temp is not None:
                state["last_hdd_temp"] = float(hdd_temp)
            state["cpu_emergency"] = bool(next_emergency)

        state.update({
            "last_status_unix": last_status_unix,
            "last_status": cached,
            "hardware_access_ok": hardware_access_ok,
            "bmc_all_sensors_na": all_na,
            "last_error": last_error,
            "consecutive_errors": errors,
            "next_retry_unix": next_retry_unix,
        })
        self._save_state(state)

        age = max(0.0, now - last_status_unix) if last_status_unix > 0 else None
        if not hardware_access_ok and all_na:
            health_code, health_status = 3, "CRITICAL"
        elif not hardware_access_ok:
            health_code, health_status = 2, "WARNING"
        else:
            health_code, health_status = 1, "OK"

        return CoolingStatus(
            board=status.board or "Supermicro X8DTN+-F",
            controller=status.controller or "W83795ADG",
            bios_fan_profile=status.bios_fan_profile or "Quiet",
            mode=status.mode,
            pwm2_raw=status.pwm2_raw,
            pwm2_percent=status.pwm2_percent,
            cpu_max_c=cpu_temp if cpu_temp is not None else status.cpu_max_c,
            system_temp_c=status.system_temp_c,
            hdd_max_c=status.hdd_max_c,
            source=status.source,
            last_change=status.last_change,
            last_update=status.last_update,
            hdd_input_available=hdd_temp is not None,
            hdd_input_c=hdd_temp,
            auto_applied=auto_applied,
            fans=status.fans,
            status_polled=status_polled,
            hardware_access_ok=hardware_access_ok,
            bmc_all_sensors_na=all_na,
            health_code=health_code,
            health_status=health_status,
            last_error=last_error,
            consecutive_errors=errors,
            next_retry_unix=next_retry_unix if next_retry_unix > 0 else None,
            status_sample_age_seconds=age,
        )
