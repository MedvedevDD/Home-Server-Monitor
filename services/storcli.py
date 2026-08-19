"""StorCLI JSON integration for MegaRAID physical-drive discovery."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from config import STORCLI_BINARY, STORCLI_TIMEOUT_SECONDS, STORCLI_USE_SUDO
from services.command_runner import CommandResult, CommandRunner


@dataclass(frozen=True)
class MegaRaidDrive:
    """One physical drive exposed by a MegaRAID controller."""

    controller: int
    enclosure: int | None
    slot: int | None
    device_id: int
    serial: str = ""
    model: str = ""
    os_device: str = ""


@dataclass(frozen=True)
class MegaRaidController:
    """One MegaRAID controller and its safe smartctl control device."""

    controller_id: int
    control_device: str
    drives: tuple[MegaRaidDrive, ...]


class StorCliError(RuntimeError):
    """Raised when StorCLI cannot provide valid JSON discovery data."""


class StorCliService:
    """Execute StorCLI and parse only its JSON output."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        binary: str = STORCLI_BINARY,
        use_sudo: bool = STORCLI_USE_SUDO,
    ) -> None:
        self.runner = runner or CommandRunner(STORCLI_TIMEOUT_SECONDS)
        self.binary = binary
        self.use_sudo = use_sudo

    def list_physical_drives(self) -> list[MegaRaidDrive]:
        """Return all MegaRAID physical drives from StorCLI JSON."""
        drives = self._list_with_args(["/call", "/eall", "/sall", "show", "all", "J"])
        if drives:
            return drives
        return self._list_with_args(["/call", "/sall", "show", "all", "J"])

    def _list_with_args(self, args: list[str]) -> list[MegaRaidDrive]:
        command = [self.binary, *args]
        if self.use_sudo:
            command = ["sudo", *command]
        result = self.runner.run(command)
        payload = self._decode(result)
        return self._parse(payload)

    @staticmethod
    def _decode(result: CommandResult) -> Mapping[str, Any]:
        if not result.stdout.strip():
            raise StorCliError("StorCLI returned no JSON")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise StorCliError("StorCLI returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise StorCliError("StorCLI JSON root must be an object")
        return payload

    @classmethod
    def _parse(cls, payload: Mapping[str, Any]) -> list[MegaRaidDrive]:
        controllers = payload.get("Controllers")
        if not isinstance(controllers, Sequence) or isinstance(controllers, (str, bytes)):
            return []

        drives: list[MegaRaidDrive] = []
        for controller_index, controller in enumerate(controllers):
            if not isinstance(controller, Mapping):
                continue
            response = controller.get("Response Data")
            if not isinstance(response, Mapping):
                continue
            controller_id = cls._as_int(response.get("Controller"), controller_index)
            details = cls._detail_index(response, controller_id)
            for row in cls._drive_rows(response):
                did = cls._as_int(cls._value(row, "DID", "Device ID", "Device Id"))
                if did is None:
                    continue
                enclosure, slot = cls._enclosure_slot(row)
                detail = details.get((controller_id, slot), {}) if slot is not None else {}
                drives.append(
                    MegaRaidDrive(
                        controller=controller_id,
                        enclosure=enclosure,
                        slot=slot,
                        device_id=did,
                        serial=(
                            cls._text(cls._value(row, "SN", "Serial Number"))
                            or cls._text(
                                cls._value(
                                    detail,
                                    "SN",
                                    "Serial Number",
                                    "Drive Serial Number",
                                )
                            )
                        ),
                        model=(
                            cls._text(cls._value(row, "Model", "Inquiry Data"))
                            or cls._text(
                                cls._value(
                                    detail,
                                    "Model Number",
                                    "Model",
                                    "Inquiry Data",
                                )
                            )
                        ),
                        os_device=cls._text(
                            cls._value(row, "OS Drive Name", "OS Device", "Device")
                        ),
                    )
                )
        return drives

    @classmethod
    def _detail_index(
        cls,
        response: Mapping[str, Any],
        controller_id: int,
    ) -> dict[tuple[int, int], Mapping[str, Any]]:
        """Flatten detailed /cX[/eY]/sZ sections by controller and slot."""
        details: dict[tuple[int, int], Mapping[str, Any]] = {}

        for key, value in response.items():
            if not isinstance(value, Mapping):
                continue

            match = re.search(r"/c(\d+)(?:/e\d+)?/s(\d+)", str(key), re.I)
            if match is None:
                for nested_key in value:
                    match = re.search(
                        r"/c(\d+)(?:/e\d+)?/s(\d+)",
                        str(nested_key),
                        re.I,
                    )
                    if match is not None:
                        break
            if match is None:
                continue

            cid = int(match.group(1))
            slot = int(match.group(2))
            flat: dict[str, Any] = {}

            stack = [value]
            while stack:
                current = stack.pop()
                for nested_key, nested_value in current.items():
                    if isinstance(nested_value, Mapping):
                        stack.append(nested_value)
                    else:
                        flat[str(nested_key)] = nested_value

            details[(cid, slot)] = flat

        return details

    @staticmethod
    def _drive_rows(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        rows: list[Mapping[str, Any]] = []
        for key, value in response.items():
            normalized = str(key).lower()
            if "drive" not in normalized and "pd list" not in normalized:
                continue
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                rows.extend(item for item in value if isinstance(item, Mapping))
        return rows

    @classmethod
    def _enclosure_slot(cls, row: Mapping[str, Any]) -> tuple[int | None, int | None]:
        eid_slot = cls._text(cls._value(row, "EID:Slt", "EID:SLOT"))
        if ":" in eid_slot:
            left, right = eid_slot.split(":", 1)
            return cls._as_int(left), cls._as_int(right)
        return (
            cls._as_int(cls._value(row, "EID", "Enclosure ID")),
            cls._as_int(cls._value(row, "Slt", "Slot")),
        )

    @staticmethod
    def _value(row: Mapping[str, Any], *names: str) -> Any:
        lower = {str(key).lower(): value for key, value in row.items()}
        for name in names:
            if name.lower() in lower:
                return lower[name.lower()]
        return None

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _as_int(value: Any, default: int | None = None) -> int | None:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return default
        return default
