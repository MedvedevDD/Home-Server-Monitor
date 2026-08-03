"""SMART provider for directly attached ATA and SATA disks."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from config import SMARTCTL_BINARY, SMARTCTL_TIMEOUT_SECONDS, SMART_USE_SUDO
from models.disk import Disk
from models.disk_health import DiskHealth
from parsers.smart.ata import AtaSmartParser
from services.command_runner import CommandNotFoundError, CommandPermissionError, CommandResult, CommandRunner, CommandRunnerError, CommandTimeoutError
from services.logger import get_logger
from services.providers.base import SmartProvider
from services.smart_exit_decoder import SmartExitDecoder


LOGGER = get_logger("smart.ata_provider")
_SD_DEVICE_PATTERN = re.compile(r"^/dev/sd[a-z]+$")


class SmartctlUnavailableError(RuntimeError):
    """Raised when the smartctl executable cannot be started."""


class AtaProvider(SmartProvider):
    """Read SMART JSON from directly attached ATA/SATA disks."""

    def __init__(self, runner: CommandRunner | None = None, parser: AtaSmartParser | None = None, binary: str = SMARTCTL_BINARY, use_sudo: bool = SMART_USE_SUDO) -> None:
        self.runner = runner or CommandRunner(SMARTCTL_TIMEOUT_SECONDS)
        self.parser = parser or AtaSmartParser()
        self.binary = binary
        self.use_sudo = use_sudo

    def collect(self, disks: Iterable[Disk]) -> list[DiskHealth]:
        results: list[DiskHealth] = []
        for disk in disks:
            if self.supports(disk):
                results.append(self._collect_disk(disk))
        return results

    def supports(self, disk: Disk) -> bool:
        if disk.disk_type.upper() == "USB" or disk.transport.upper() == "USB":
            return False
        transport = disk.transport.upper()
        return transport in {"ATA", "SATA"} or (transport == "UNKNOWN" and bool(_SD_DEVICE_PATTERN.fullmatch(disk.device)))

    def _command(self, disk: Disk) -> list[str]:
        command = [self.binary, "--json", "--all", disk.device]
        return ["sudo", *command] if self.use_sudo else command

    def _collect_disk(self, disk: Disk) -> DiskHealth:
        try:
            result = self.runner.run(self._command(disk))
        except CommandNotFoundError as exc:
            raise SmartctlUnavailableError(str(exc)) from exc
        except (CommandTimeoutError, CommandPermissionError, CommandRunnerError) as exc:
            return self._unavailable(disk, -1, str(exc))
        self._log_exit(result.return_code, disk.device)
        payload = self._decode(result, disk.device)
        if payload is None:
            return self._unavailable(disk, result.return_code, result.stderr.strip() or "Invalid or missing smartctl JSON")
        self._warn_serial(payload, disk)
        health = self.parser.parse(payload, disk, result.return_code)
        if health.smart_available:
            return health
        return DiskHealth(**{**health.__dict__, "error": result.stderr.strip() or "SMART data is unavailable"})

    @staticmethod
    def _decode(result: CommandResult, device: str) -> Mapping[str, Any] | None:
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            LOGGER.warning("Invalid smartctl JSON for %s", device)
            return None
        return payload if isinstance(payload, Mapping) else None

    @staticmethod
    def _warn_serial(payload: Mapping[str, Any], disk: Disk) -> None:
        serial = payload.get("serial_number")
        if isinstance(serial, str) and serial.strip() and disk.serial.strip() and serial.strip() != disk.serial.strip():
            LOGGER.warning("SMART serial does not match inventory serial for %s", disk.device)

    @staticmethod
    def _log_exit(exit_code: int, device: str) -> None:
        reasons = SmartExitDecoder.decode(exit_code)
        if reasons:
            LOGGER.warning("smartctl exit code %d for %s: %s", exit_code, device, "; ".join(reasons))

    @staticmethod
    def _unavailable(disk: Disk, exit_code: int, error: str) -> DiskHealth:
        return DiskHealth(disk.serial, disk.device, False, None, None, None, None, None, None, exit_code, error)
