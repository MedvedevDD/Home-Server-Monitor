"""Regression tests for v5.8.1 mixed-controller handling."""

from __future__ import annotations

import unittest

from models.disk import Disk
from services.command_runner import CommandResult, CommandRunnerError
from services.raid_discovery import RaidDiscoveryResult, RaidDiscoveryService, RaidMode
from services.smart import SmartService
from services.storcli import MegaRaidController, MegaRaidDrive, StorCliService


SMART_OK = '{"smart_status":{"passed":true},"temperature":{"current":31}}'
SMART_OK_WITH_IDENTITY = '{"serial_number":"SMART-SERIAL","model_name":"SMART MODEL","smart_status":{"passed":true},"temperature":{"current":31}}'


def disk(device: str, serial: str, transport: str = "SATA") -> Disk:
    return Disk(
        serial=serial,
        vendor="Test",
        model="Disk",
        display_name="Test Disk",
        capacity="1 TB",
        capacity_bytes=1_000_000_000_000,
        disk_type="HDD",
        transport=transport,
        device=device,
    )


class FakeRunner:
    def __init__(self, outcomes: list[CommandResult | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> CommandResult:
        self.commands.append(command)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FixedDiscovery:
    def __init__(self, result: RaidDiscoveryResult) -> None:
        self.result = result

    def discover(self, disks: list[Disk]) -> RaidDiscoveryResult:
        return self.result


class FakeStorCli:
    def __init__(self, drives: list[MegaRaidDrive]) -> None:
        self.drives = drives

    def list_physical_drives(self) -> list[MegaRaidDrive]:
        return self.drives


class MixedControllerTests(unittest.TestCase):
    def test_one_direct_sata_and_one_megaraid_are_both_collected(self) -> None:
        direct = disk("/dev/sda", "ATA-1")
        logical = disk("/dev/sdb", "VD-1")
        drive = MegaRaidDrive(0, 252, 0, 7, "MR-1", "Physical")
        controller = MegaRaidController(0, "/dev/sdb", (drive,))
        discovery = RaidDiscoveryResult(
            mode=RaidMode.MIXED,
            megaraid_controllers=(controller,),
            direct_disks=(direct,),
        )
        runner = FakeRunner([
            CommandResult(SMART_OK, "", 0),
            CommandResult(SMART_OK, "", 0),
        ])

        health = SmartService(runner=runner, discovery=FixedDiscovery(discovery)).collect(
            [direct, logical]
        )

        self.assertEqual([item.serial for item in health], ["ATA-1", "MR-1"])
        self.assertEqual(runner.commands[0][-1], "/dev/sdb")
        self.assertIn("megaraid,7", runner.commands[0])
        self.assertEqual(runner.commands[1][-1], "/dev/sda")

    def test_megaraid_logical_device_is_excluded_from_ata(self) -> None:
        direct = disk("/dev/sda", "ATA-1")
        logical = disk("/dev/sdb", "VD-1")
        drive = MegaRaidDrive(0, 252, 0, 3, "MR-1")
        result = RaidDiscoveryService(
            storcli=FakeStorCli([drive]),
            controller_devices={0: "/dev/sdb"},
        ).discover([direct, logical])

        self.assertEqual([item.device for item in result.direct_disks], ["/dev/sda"])
        self.assertEqual(result.megaraid_controllers[0].control_device, "/dev/sdb")

    def test_two_controllers_keep_separate_control_devices(self) -> None:
        drives = [
            MegaRaidDrive(0, 252, 0, 5, "MR-A"),
            MegaRaidDrive(1, 252, 0, 5, "MR-B"),
        ]
        result = RaidDiscoveryService(
            storcli=FakeStorCli(drives),
            controller_devices={0: "/dev/sdb", 1: "/dev/sdc"},
        ).discover([disk("/dev/sdb", "VD-A"), disk("/dev/sdc", "VD-B")])

        self.assertEqual(len(result.megaraid_controllers), 2)
        self.assertEqual(
            [item.control_device for item in result.megaraid_controllers],
            ["/dev/sdb", "/dev/sdc"],
        )
        self.assertEqual(
            [item.drives[0].device_id for item in result.megaraid_controllers],
            [5, 5],
        )

    def test_repeated_did_uses_each_controllers_own_device(self) -> None:
        controller_a = MegaRaidController(
            0, "/dev/sdb", (MegaRaidDrive(0, 252, 0, 5, "MR-A"),)
        )
        controller_b = MegaRaidController(
            1, "/dev/sdc", (MegaRaidDrive(1, 252, 0, 5, "MR-B"),)
        )
        discovery = RaidDiscoveryResult(
            mode=RaidMode.MEGARAID,
            megaraid_controllers=(controller_a, controller_b),
        )
        runner = FakeRunner([
            CommandResult(SMART_OK, "", 0),
            CommandResult(SMART_OK, "", 0),
        ])

        SmartService(runner=runner, discovery=FixedDiscovery(discovery)).collect(
            [disk("/dev/sdb", "VD-A"), disk("/dev/sdc", "VD-B")]
        )

        self.assertEqual(runner.commands[0][-1], "/dev/sdb")
        self.assertEqual(runner.commands[1][-1], "/dev/sdc")
        self.assertIn("megaraid,5", runner.commands[0])
        self.assertIn("megaraid,5", runner.commands[1])


    def test_megaraid_uses_smartctl_serial_when_storcli_serial_is_missing(self) -> None:
        logical = disk("/dev/sdb", "VD-1")
        controller = MegaRaidController(
            0, "/dev/sdb", (MegaRaidDrive(0, 252, 0, 7, "", ""),)
        )
        discovery = RaidDiscoveryResult(
            mode=RaidMode.MEGARAID,
            megaraid_controllers=(controller,),
        )
        runner = FakeRunner([CommandResult(SMART_OK_WITH_IDENTITY, "", 0)])

        health = SmartService(runner=runner, discovery=FixedDiscovery(discovery)).collect(
            [logical]
        )

        self.assertEqual(len(health), 1)
        self.assertEqual(health[0].serial, "SMART-SERIAL")

    def test_all_megaraid_jbod_os_devices_are_excluded_from_ata(self) -> None:
        direct = disk("/dev/sda", "ATA-1")
        jbod_a = disk("/dev/sdb", "JBOD-A")
        jbod_b = disk("/dev/sdc", "JBOD-B")
        logical = disk("/dev/sdd", "VD-1")
        drives = [
            MegaRaidDrive(0, 252, 0, 1, "MR-A", os_device="/dev/sdb"),
            MegaRaidDrive(0, 252, 1, 2, "MR-B", os_device="/dev/sdc"),
        ]

        result = RaidDiscoveryService(
            storcli=FakeStorCli(drives),
            controller_devices={0: "/dev/sdd"},
        ).discover([direct, jbod_a, jbod_b, logical])

        self.assertEqual([item.device for item in result.direct_disks], ["/dev/sda"])

    def test_jbod_os_device_is_excluded_even_when_controller_is_unmapped(self) -> None:
        direct = disk("/dev/sda", "ATA-1")
        jbod = disk("/dev/sdb", "JBOD-1")
        drives = [MegaRaidDrive(0, 252, 0, 1, "MR-1", os_device="/dev/sdb")]

        result = RaidDiscoveryService(
            storcli=FakeStorCli(drives),
            controller_devices={},
            fallback_control_device="",
        ).discover([direct, jbod])

        self.assertEqual([item.device for item in result.direct_disks], ["/dev/sda"])

    def test_storcli_can_run_through_sudo(self) -> None:
        runner = FakeRunner([CommandResult('{"Controllers":[]}', "", 0)])
        StorCliService(runner=runner, binary="/opt/storcli64", use_sudo=True).list_physical_drives()
        self.assertEqual(
            runner.commands[0],
            ["sudo", "/opt/storcli64", "/call", "/eall", "/sall", "show", "J"],
        )

    def test_unmapped_controller_is_skipped_without_random_sd_fallback(self) -> None:
        drives = [MegaRaidDrive(0, 252, 0, 1, "MR-1")]
        direct_a = disk("/dev/sda", "ATA-1")
        direct_b = disk("/dev/sdb", "ATA-2")
        result = RaidDiscoveryService(
            storcli=FakeStorCli(drives),
            controller_devices={},
            fallback_control_device="",
        ).discover([direct_a, direct_b])

        self.assertEqual(result.megaraid_controllers, ())
        self.assertEqual(
            [item.device for item in result.direct_disks],
            ["/dev/sda", "/dev/sdb"],
        )

    def test_direct_sata_survives_megaraid_smart_failure(self) -> None:
        direct = disk("/dev/sda", "ATA-1")
        logical = disk("/dev/sdb", "VD-1")
        controller = MegaRaidController(
            0, "/dev/sdb", (MegaRaidDrive(0, 252, 0, 4, "MR-1"),)
        )
        discovery = RaidDiscoveryResult(
            mode=RaidMode.MIXED,
            megaraid_controllers=(controller,),
            direct_disks=(direct,),
        )
        runner = FakeRunner([
            CommandRunnerError("MegaRAID read failed"),
            CommandResult(SMART_OK, "", 0),
        ])

        health = SmartService(runner=runner, discovery=FixedDiscovery(discovery)).collect(
            [direct, logical]
        )

        self.assertEqual(len(health), 2)
        self.assertTrue(health[0].smart_available)
        self.assertFalse(health[1].smart_available)
        self.assertEqual(health[0].serial, "ATA-1")

    def test_megaraid_serials_exclude_jbod_from_direct_ata_when_os_device_is_missing(self) -> None:
        jbod = disk("/dev/sdc", "MR-1")
        direct = disk("/dev/sde", "ATA-1")
        control = disk("/dev/sda", "CONTROL")
        controller = MegaRaidController(
            0, "/dev/sda", (MegaRaidDrive(0, 252, 0, 18, "", ""),)
        )
        discovery = RaidDiscoveryResult(
            mode=RaidMode.MIXED,
            megaraid_controllers=(controller,),
            direct_disks=(jbod, direct),
        )
        runner = FakeRunner([
            CommandResult(
                '{"serial_number":"MR-1","model_name":"Physical","smart_status":{"passed":true}}',
                "",
                0,
            ),
            CommandResult(SMART_OK, "", 0),
        ])

        health = SmartService(runner=runner, discovery=FixedDiscovery(discovery)).collect(
            [control, jbod, direct]
        )

        self.assertEqual([item.serial for item in health], ["ATA-1", "MR-1"])
        self.assertEqual(len(runner.commands), 2)
        self.assertIn("megaraid,18", runner.commands[0])
        self.assertEqual(runner.commands[1][-1], "/dev/sde")


if __name__ == "__main__":
    unittest.main()
