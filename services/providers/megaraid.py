"""SMART provider for physical drives behind MegaRAID controllers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from config import SMARTCTL_BINARY, SMARTCTL_TIMEOUT_SECONDS, SMART_USE_SUDO
from models.disk import Disk
from models.disk_health import DiskHealth
from parsers.smart.ata import AtaSmartParser
from services.command_runner import CommandNotFoundError, CommandResult, CommandRunner, CommandRunnerError
from services.logger import get_logger
from services.providers.ata import SmartctlUnavailableError
from services.providers.base import SmartProvider
from services.smart_exit_decoder import SmartExitDecoder
from services.storcli import MegaRaidDrive


LOGGER = get_logger("smart.megaraid_provider")


class MegaRaidProvider(SmartProvider):
    """Read physical-drive SMART through smartctl -d megaraid,N."""

    def __init__(self, drives: Iterable[MegaRaidDrive], control_device: str, runner: CommandRunner | None = None, parser: AtaSmartParser | None = None, binary: str = SMARTCTL_BINARY, use_sudo: bool = SMART_USE_SUDO) -> None:
        self.drives = list(drives)
        self.control_device = control_device
        self.runner = runner or CommandRunner(SMARTCTL_TIMEOUT_SECONDS)
        self.parser = parser or AtaSmartParser()
        self.binary = binary
        self.use_sudo = use_sudo

    def collect(self, disks: Iterable[Disk]) -> list[DiskHealth]:
        disk_list = list(disks)
        template = self._template_disk(disk_list)
        if template is None:
            return []
        return [self._collect_drive(drive, template) for drive in self.drives]

    def _command(self, drive: MegaRaidDrive) -> list[str]:
        command = [self.binary, "-j", "-a", "-d", f"megaraid,{drive.device_id}", self.control_device]
        return ["sudo", *command] if self.use_sudo else command

    def _collect_drive(self, drive: MegaRaidDrive, template: Disk) -> DiskHealth:
        disk = Disk(**template.__dict__)
        disk.device = self.control_device
        if drive.serial:
            disk.serial = drive.serial
        if drive.model:
            disk.model = drive.model
        try:
            result = self.runner.run(self._command(drive))
        except CommandNotFoundError as exc:
            raise SmartctlUnavailableError(str(exc)) from exc
        except CommandRunnerError as exc:
            return self._unavailable(disk, -1, str(exc))
        reasons = SmartExitDecoder.decode(result.return_code)
        if reasons:
            LOGGER.warning("smartctl exit code %d for MegaRAID DID %d: %s", result.return_code, drive.device_id, "; ".join(reasons))
        payload = self._decode(result)
        if payload is None:
            return self._unavailable(disk, result.return_code, result.stderr.strip() or "Invalid or missing smartctl JSON")

        self._apply_smartctl_identity(disk, drive, payload)
        return self.parser.parse(payload, disk, result.return_code)


    @staticmethod
    def _apply_smartctl_identity(
        disk: Disk,
        drive: MegaRaidDrive,
        payload: Mapping[str, Any],
    ) -> None:
        """Use smartctl identity when StorCLI omitted physical-drive details."""
        if not drive.serial:
            serial = payload.get("serial_number")
            if isinstance(serial, str) and serial.strip():
                disk.serial = serial.strip()

        if not drive.model:
            model = payload.get("model_name")
            if isinstance(model, str) and model.strip():
                disk.model = model.strip()

    @staticmethod
    def _decode(result: CommandResult) -> Mapping[str, Any] | None:
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return None
        return payload if isinstance(payload, Mapping) else None

    def _template_disk(self, disks: list[Disk]) -> Disk | None:
        for disk in disks:
            if disk.device == self.control_device:
                return disk
        return disks[0] if disks else None

    @staticmethod
    def _unavailable(disk: Disk, exit_code: int, error: str) -> DiskHealth:
        return DiskHealth(disk.serial, disk.device, False, None, None, None, None, None, None, exit_code, error)
