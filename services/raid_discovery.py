"""Discover direct ATA disks and MegaRAID controllers safely."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum

from config import MEGARAID_CONTROL_DEVICE, MEGARAID_CONTROL_DEVICES
from models.disk import Disk
from services.command_runner import CommandRunnerError
from services.logger import get_logger
from services.storcli import MegaRaidController, MegaRaidDrive, StorCliError, StorCliService


LOGGER = get_logger("raid_discovery")
_SD_DEVICE_PATTERN = re.compile(r"^/dev/sd[a-z]+$")


class RaidMode(str, Enum):
    """Compatibility summary of detected storage access modes."""

    NONE = "none"
    SATA = "sata"
    MEGARAID = "megaraid"
    MIXED = "mixed"


@dataclass(frozen=True)
class RaidDiscoveryResult:
    """Discovery result consumed by SmartService.

    The first three fields preserve the v5.8 constructor and attribute API.
    New code should use megaraid_controllers and direct_disks.
    """

    mode: RaidMode
    megaraid_drives: tuple[MegaRaidDrive, ...] = ()
    control_device: str = ""
    megaraid_controllers: tuple[MegaRaidController, ...] = ()
    direct_disks: tuple[Disk, ...] = ()


class RaidDiscoveryService:
    """Discover all usable SMART paths without selecting one global mode."""

    def __init__(
        self,
        storcli: StorCliService | None = None,
        controller_devices: Mapping[int, str] | None = None,
        fallback_control_device: str = MEGARAID_CONTROL_DEVICE,
    ) -> None:
        self.storcli = storcli or StorCliService()
        self.controller_devices = dict(
            MEGARAID_CONTROL_DEVICES if controller_devices is None else controller_devices
        )
        self.fallback_control_device = fallback_control_device.strip()

    def discover(self, disks: Iterable[Disk]) -> RaidDiscoveryResult:
        disk_list = list(disks)
        try:
            drives = self.storcli.list_physical_drives()
        except (CommandRunnerError, StorCliError) as exc:
            LOGGER.warning("MegaRAID discovery unavailable: %s", exc)
            drives = []

        controllers = self._build_controllers(disk_list, drives)
        megaraid_devices = {
            controller.control_device for controller in controllers if controller.control_device
        }
        megaraid_devices.update(
            drive.os_device
            for drive in drives
            if drive.os_device and _SD_DEVICE_PATTERN.fullmatch(drive.os_device)
        )
        megaraid_serials = {
            drive.serial.strip()
            for drive in drives
            if drive.serial.strip()
        }
        direct_disks = tuple(
            disk
            for disk in disk_list
            if self._is_direct_ata(disk)
            and disk.device not in megaraid_devices
            and (
                not disk.serial.strip()
                or disk.serial.strip() not in megaraid_serials
            )
        )

        if controllers and direct_disks:
            mode = RaidMode.MIXED
        elif controllers:
            mode = RaidMode.MEGARAID
        elif direct_disks:
            mode = RaidMode.SATA
        else:
            mode = RaidMode.NONE

        all_drives = tuple(drive for controller in controllers for drive in controller.drives)
        legacy_control = controllers[0].control_device if len(controllers) == 1 else ""
        return RaidDiscoveryResult(
            mode=mode,
            megaraid_drives=all_drives,
            control_device=legacy_control,
            megaraid_controllers=tuple(controllers),
            direct_disks=direct_disks,
        )

    def _build_controllers(
        self,
        disks: list[Disk],
        drives: list[MegaRaidDrive],
    ) -> list[MegaRaidController]:
        grouped: dict[int, list[MegaRaidDrive]] = defaultdict(list)
        for drive in drives:
            grouped[drive.controller].append(drive)

        known_devices = {disk.device for disk in disks if _SD_DEVICE_PATTERN.fullmatch(disk.device)}
        controllers: list[MegaRaidController] = []
        for controller_id in sorted(grouped):
            controller_drives = tuple(grouped[controller_id])
            control_device = self._resolve_control_device(
                controller_id,
                controller_drives,
                known_devices,
                len(grouped),
            )
            if not control_device:
                LOGGER.warning(
                    "MegaRAID controller %d was found but its control device could not be determined; "
                    "set HSM_MEGARAID_CONTROL_DEVICES or HSM_MEGARAID_CONTROL_DEVICE",
                    controller_id,
                )
                continue
            controllers.append(
                MegaRaidController(
                    controller_id=controller_id,
                    control_device=control_device,
                    drives=controller_drives,
                )
            )
        return controllers

    def _resolve_control_device(
        self,
        controller_id: int,
        drives: tuple[MegaRaidDrive, ...],
        known_devices: set[str],
        controller_count: int,
    ) -> str:
        configured = self.controller_devices.get(controller_id, "").strip()
        if configured:
            return configured

        reported = {
            drive.os_device
            for drive in drives
            if drive.os_device and drive.os_device in known_devices
        }
        if len(reported) == 1:
            return next(iter(reported))
        if len(reported) > 1:
            LOGGER.warning(
                "MegaRAID controller %d reports multiple possible control devices: %s",
                controller_id,
                ", ".join(sorted(reported)),
            )
            return ""

        if controller_count == 1 and self.fallback_control_device:
            return self.fallback_control_device
        if controller_count == 1 and len(known_devices) == 1:
            return next(iter(known_devices))
        return ""

    @staticmethod
    def _is_direct_ata(disk: Disk) -> bool:
        transport = disk.transport.upper()
        if transport in {"ATA", "SATA"}:
            return bool(disk.device)
        return transport == "UNKNOWN" and bool(_SD_DEVICE_PATTERN.fullmatch(disk.device))
