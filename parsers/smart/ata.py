"""Parser for ATA SMART JSON produced by smartctl."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from models.disk import Disk
from models.disk_health import DiskHealth


class AtaSmartParser:
    """Convert smartctl ATA JSON into a normalized ``DiskHealth`` object."""

    _ATTRIBUTE_IDS = {
        5: "reallocated_sectors",
        197: "pending_sectors",
        198: "offline_uncorrectable",
        199: "crc_errors",
    }
    _INVALID_TEMPERATURES = frozenset({0, 255, 65535})
    _INTEGER_PATTERN = re.compile(r"[-+]?\d+")

    def parse(self, payload: Mapping[str, Any], disk: Disk, exit_code: int) -> DiskHealth:
        """Parse one smartctl payload without mutating the supplied ``Disk``."""
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        if not isinstance(disk, Disk):
            raise TypeError("disk must be an instance of Disk")

        attributes = self._attribute_table(payload)
        values: dict[str, int | None] = {
            "reallocated_sectors": None,
            "pending_sectors": None,
            "offline_uncorrectable": None,
            "crc_errors": None,
        }
        by_id: dict[int, Mapping[str, Any]] = {}

        for attribute in attributes:
            attribute_id = self._attribute_id(attribute)
            if attribute_id is None:
                continue
            by_id[attribute_id] = attribute
            target = self._ATTRIBUTE_IDS.get(attribute_id)
            if target:
                values[target] = self._raw_value(attribute)

        health_passed = self._health_passed(payload)
        temperature = self._temperature(payload, by_id)
        smart_available = self._smart_available(payload, attributes, health_passed, temperature)

        return DiskHealth(
            serial=disk.serial,
            device=disk.device,
            smart_available=smart_available,
            health_passed=health_passed,
            temperature_c=temperature,
            reallocated_sectors=values["reallocated_sectors"],
            pending_sectors=values["pending_sectors"],
            offline_uncorrectable=values["offline_uncorrectable"],
            crc_errors=values["crc_errors"],
            smartctl_exit_code=int(exit_code),
        )

    def _smart_available(
        self,
        payload: Mapping[str, Any],
        attributes: list[Mapping[str, Any]],
        health_passed: bool | None,
        temperature: int | None,
    ) -> bool:
        support = payload.get("smart_support")
        if isinstance(support, Mapping) and isinstance(support.get("available"), bool):
            return support["available"]
        return bool(attributes) or health_passed is not None or temperature is not None

    @staticmethod
    def _health_passed(payload: Mapping[str, Any]) -> bool | None:
        status = payload.get("smart_status")
        if not isinstance(status, Mapping):
            return None
        passed = status.get("passed")
        return passed if isinstance(passed, bool) else None

    def _temperature(
        self,
        payload: Mapping[str, Any],
        by_id: Mapping[int, Mapping[str, Any]],
    ) -> int | None:
        temperature = payload.get("temperature")
        if isinstance(temperature, Mapping):
            current = self._as_int(temperature.get("current"))
            if self._valid_temperature(current):
                return current

        for attribute_id in (194, 190):
            attribute = by_id.get(attribute_id)
            if attribute is None:
                continue
            value = self._raw_value(attribute)
            if self._valid_temperature(value):
                return value
        return None

    @classmethod
    def _valid_temperature(cls, value: int | None) -> bool:
        return value is not None and value not in cls._INVALID_TEMPERATURES and -40 <= value <= 125

    @staticmethod
    def _attribute_table(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        table = payload.get("ata_smart_attributes")
        if not isinstance(table, Mapping):
            return []
        raw_table = table.get("table")
        if not isinstance(raw_table, Sequence) or isinstance(raw_table, (str, bytes)):
            return []
        return [item for item in raw_table if isinstance(item, Mapping)]

    @classmethod
    def _attribute_id(cls, attribute: Mapping[str, Any]) -> int | None:
        return cls._as_int(attribute.get("id"))

    @classmethod
    def _raw_value(cls, attribute: Mapping[str, Any]) -> int | None:
        raw = attribute.get("raw")
        if not isinstance(raw, Mapping):
            return None

        value = raw.get("value")
        if isinstance(value, int) and not isinstance(value, bool):
            return value

        string_value = raw.get("string")
        if not isinstance(string_value, str):
            return None
        match = cls._INTEGER_PATTERN.search(string_value)
        if match is None:
            return None
        try:
            return int(match.group(0))
        except ValueError:
            return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None
