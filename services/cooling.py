"""Cooling integration for x8fan and existing HSM temperature metrics."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

import config
from models.cooling import CoolingStatus
from services.command_runner import CommandRunner, CommandRunnerError

LOGGER = logging.getLogger("home_server_monitor.cooling")


class CoolingCollectionError(RuntimeError):
    pass


class InfluxTemperatureSource:
    """Read recent disk temperatures from HSM's existing InfluxDB metrics."""

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
                f'FROM "storage_status" WHERE time > now() - {age}s '
                'GROUP BY "serial"'
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
    """Run only the narrow privileged HSM x8fan helper."""

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
                if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    fans[str(fan_id)] = int(raw)
                else:
                    fans[str(fan_id)] = None

        def number(name: str) -> float | None:
            value = payload.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            return None

        def temperature(name: str) -> float | None:
            value = number(name)
            if value is None:
                return None
            # Super I/O/BMC sensor glitches may briefly expose sentinel-like
            # values such as -124 C. Do not persist these as real temperatures.
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


class CoolingCollector:
    """Feed current HSM disk temperature into x8fan and read resulting state."""

    def __init__(
        self,
        temperature_source: InfluxTemperatureSource | None = None,
        x8fan: X8FanClient | None = None,
    ) -> None:
        self.temperature_source = temperature_source or InfluxTemperatureSource()
        self.x8fan = x8fan or X8FanClient()

    def collect(self) -> CoolingStatus:
        disk_temperature: float | None = None
        auto_applied = False

        try:
            disk_temperature = self.temperature_source.maximum_temperature()
        except CoolingCollectionError as exc:
            LOGGER.warning("%s", exc)

        if disk_temperature is not None:
            self.x8fan.auto(disk_temperature)
            auto_applied = True

        status = self.x8fan.status()
        return CoolingStatus(
            board=status.board,
            controller=status.controller,
            bios_fan_profile=status.bios_fan_profile,
            mode=status.mode,
            pwm2_raw=status.pwm2_raw,
            pwm2_percent=status.pwm2_percent,
            cpu_max_c=status.cpu_max_c,
            system_temp_c=status.system_temp_c,
            hdd_max_c=status.hdd_max_c,
            source=status.source,
            last_change=status.last_change,
            last_update=status.last_update,
            hdd_input_available=disk_temperature is not None,
            hdd_input_c=disk_temperature,
            auto_applied=auto_applied,
            fans=status.fans,
        )
