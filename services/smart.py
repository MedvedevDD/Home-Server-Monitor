"""SMART provider orchestration for direct and RAID-backed disks."""

from __future__ import annotations

from collections.abc import Iterable

from config import SMARTCTL_BINARY, SMART_USE_SUDO
from models.disk import Disk
from models.disk_health import DiskHealth
from parsers.smart.ata import AtaSmartParser
from services.command_runner import CommandRunner
from services.providers.ata import AtaProvider, SmartctlUnavailableError
from services.providers.megaraid import MegaRaidProvider
from services.raid_discovery import RaidDiscoveryResult, RaidDiscoveryService
from services.storcli import MegaRaidController


class SmartService:
    """Collect from every applicable provider and merge the results."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        parser: AtaSmartParser | None = None,
        binary: str = SMARTCTL_BINARY,
        use_sudo: bool = SMART_USE_SUDO,
        discovery: RaidDiscoveryService | None = None,
        include_megaraid: bool = True,
    ) -> None:
        self.runner = runner
        self.parser = parser or AtaSmartParser()
        self.binary = binary
        self.use_sudo = use_sudo
        self.discovery = discovery or RaidDiscoveryService()
        self.include_megaraid = include_megaraid

    def collect(self, disks: Iterable[Disk]) -> list[DiskHealth]:
        """Run direct ATA and all mapped MegaRAID providers independently."""
        disk_list = list(disks)
        discovery = self.discovery.discover(disk_list)
        direct_disks = list(discovery.direct_disks)
        controllers = list(discovery.megaraid_controllers)

        if not self.include_megaraid:
            raid_serials = {
                drive.serial.strip()
                for controller in controllers
                for drive in controller.drives
                if drive.serial.strip()
            }
            raid_os_devices = {
                drive.os_device.strip()
                for controller in controllers
                for drive in controller.drives
                if drive.os_device.strip()
            }
            direct_disks = [
                disk
                for disk in disk_list
                if RaidDiscoveryService._is_direct_ata(disk)
                and disk.device not in raid_os_devices
                and (
                    not disk.serial.strip()
                    or disk.serial.strip() not in raid_serials
                )
            ]

        # Backward compatibility for injected v5.8 discovery results used by clients/tests.
        if not direct_disks and not controllers:
            direct_disks, controllers = self._legacy_paths(disk_list, discovery)

        megaraid_results: list[DiskHealth] = []
        if self.include_megaraid:
            for controller in controllers:
                megaraid_results.extend(
                    MegaRaidProvider(
                        drives=controller.drives,
                        control_device=controller.control_device,
                        runner=self.runner,
                        parser=self.parser,
                        binary=self.binary,
                        use_sudo=self.use_sudo,
                    ).collect(disk_list)
                )

        # Some StorCLI versions omit OS device names for JBOD disks. In that
        # case discovery cannot exclude /dev/sdX paths reliably. Use the
        # physical serials returned by smartctl through MegaRAID as the final
        # de-duplication key before direct ATA polling.
        megaraid_serials = {
            health.serial.strip()
            for health in megaraid_results
            if health.serial.strip()
        }
        direct_disks = [
            disk
            for disk in direct_disks
            if not disk.serial.strip() or disk.serial.strip() not in megaraid_serials
        ]

        direct_results: list[DiskHealth] = []
        if direct_disks:
            direct_results.extend(
                AtaProvider(
                    runner=self.runner,
                    parser=self.parser,
                    binary=self.binary,
                    use_sudo=self.use_sudo,
                ).collect(direct_disks)
            )

        return [*direct_results, *megaraid_results]

    @staticmethod
    def _legacy_paths(
        disks: list[Disk],
        discovery: RaidDiscoveryResult,
    ) -> tuple[list[Disk], list[MegaRaidController]]:
        controllers: list[MegaRaidController] = []
        if discovery.megaraid_drives and discovery.control_device:
            controller_id = discovery.megaraid_drives[0].controller
            controllers.append(
                MegaRaidController(
                    controller_id=controller_id,
                    control_device=discovery.control_device,
                    drives=tuple(discovery.megaraid_drives),
                )
            )
            direct = [disk for disk in disks if disk.device != discovery.control_device]
            return direct, controllers
        return disks, controllers


__all__ = ["SmartService", "SmartctlUnavailableError"]
