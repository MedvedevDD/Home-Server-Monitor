"""Tests for v5.8 provider architecture and MegaRAID support."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from collector import build_health_metrics
from models.disk import Disk
from services.command_runner import CommandNotFoundError, CommandResult
from services.providers.ata import AtaProvider
from services.providers.megaraid import MegaRaidProvider
from services.raid_discovery import RaidDiscoveryResult, RaidDiscoveryService, RaidMode
from services.smart import SmartService
from services.smart_exit_decoder import SmartExitDecoder
from services.storcli import MegaRaidDrive, StorCliError, StorCliService


FIXTURES = Path(__file__).parent / "fixtures"


def read_fixture(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


def make_disk(**overrides: object) -> Disk:
    values = {
        "serial": "VD-001",
        "vendor": "LSI",
        "model": "Virtual Disk",
        "display_name": "LSI Virtual Disk",
        "capacity": "1 TB",
        "capacity_bytes": 1_000_000_000_000,
        "disk_type": "HDD",
        "transport": "SATA",
        "device": "/dev/sda",
    }
    values.update(overrides)
    return Disk(**values)


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


class FakeStorCli:
    def __init__(self, drives: list[MegaRaidDrive] | Exception) -> None:
        self.drives = drives

    def list_physical_drives(self) -> list[MegaRaidDrive]:
        if isinstance(self.drives, Exception):
            raise self.drives
        return self.drives


class FixedDiscovery:
    def __init__(self, result: RaidDiscoveryResult) -> None:
        self.result = result

    def discover(self, disks: list[Disk]) -> RaidDiscoveryResult:
        return self.result


class SmartExitDecoderTests(unittest.TestCase):
    def test_zero_has_no_reasons(self) -> None:
        self.assertEqual(SmartExitDecoder.decode(0), [])

    def test_individual_reasons(self) -> None:
        self.assertEqual(
            SmartExitDecoder.decode(32),
            ["SMART error log contains records"],
        )
        self.assertEqual(
            SmartExitDecoder.decode(64),
            ["Self-test log contains records"],
        )

    def test_combined_bit_mask(self) -> None:
        reasons = SmartExitDecoder.decode(2 | 8 | 32)
        self.assertEqual(len(reasons), 3)
        self.assertIn("SMART overall-health self-assessment test failed", reasons)


class StorCliServiceTests(unittest.TestCase):
    def test_exact_json_command_and_drive_parsing(self) -> None:
        runner = FakeRunner(
            [CommandResult(read_fixture("storcli", "megaraid_two_drives.json"), "", 0)]
        )
        drives = StorCliService(runner=runner, binary="storcli64").list_physical_drives()
        self.assertEqual(
            runner.commands,
            [["storcli64", "/call", "/eall", "/sall", "show", "J"]],
        )
        self.assertEqual(len(drives), 2)
        self.assertEqual(drives[0].device_id, 0)
        self.assertEqual(drives[1].device_id, 3)
        self.assertEqual(drives[1].slot, 1)
        self.assertEqual(drives[0].serial, "MR-001")

    def test_invalid_json_is_rejected(self) -> None:
        runner = FakeRunner(
            [CommandResult(read_fixture("storcli", "invalid.json"), "", 0)]
        )
        with self.assertRaises(StorCliError):
            StorCliService(runner=runner).list_physical_drives()

    def test_empty_controller_list_is_not_megaraid(self) -> None:
        runner = FakeRunner(
            [CommandResult(read_fixture("storcli", "no_controllers.json"), "", 0)]
        )
        self.assertEqual(StorCliService(runner=runner).list_physical_drives(), [])


class RaidDiscoveryTests(unittest.TestCase):
    def test_megaraid_has_priority(self) -> None:
        drive = MegaRaidDrive(0, 252, 0, 7, "MR-001", "Disk")
        discovery = RaidDiscoveryService(storcli=FakeStorCli([drive]))
        result = discovery.discover([make_disk(device="/dev/sdb")])
        self.assertEqual(result.mode, RaidMode.MEGARAID)
        self.assertEqual(result.control_device, "/dev/sdb")
        self.assertEqual(result.megaraid_drives[0].device_id, 7)

    def test_direct_sata_when_storcli_is_missing(self) -> None:
        discovery = RaidDiscoveryService(
            storcli=FakeStorCli(CommandNotFoundError("missing"))
        )
        result = discovery.discover([make_disk()])
        self.assertEqual(result.mode, RaidMode.SATA)

    def test_no_raid_and_no_supported_disk(self) -> None:
        discovery = RaidDiscoveryService(storcli=FakeStorCli([]))
        result = discovery.discover(
            [make_disk(transport="USB", disk_type="USB", device="/dev/sdb")]
        )
        self.assertEqual(result.mode, RaidMode.NONE)


class ProviderTests(unittest.TestCase):
    def test_ata_provider_sudo_command(self) -> None:
        runner = FakeRunner(
            [CommandResult(read_fixture("smart", "ata_ok.json"), "", 0)]
        )
        result = AtaProvider(runner=runner, use_sudo=True).collect([make_disk()])
        self.assertTrue(result[0].smart_available)
        self.assertEqual(
            runner.commands[0],
            ["sudo", "smartctl", "--json", "--all", "/dev/sda"],
        )

    def test_megaraid_provider_uses_device_id(self) -> None:
        runner = FakeRunner(
            [CommandResult(read_fixture("megaraid", "drive_ok.json"), "", 0)]
        )
        drive = MegaRaidDrive(0, 252, 0, 11, "MR-001", "ST1000")
        provider = MegaRaidProvider([drive], "/dev/sda", runner=runner)
        result = provider.collect([make_disk()])
        self.assertTrue(result[0].smart_available)
        self.assertEqual(result[0].serial, "MR-001")
        self.assertEqual(
            runner.commands[0],
            ["smartctl", "-j", "-a", "-d", "megaraid,11", "/dev/sda"],
        )

    def test_megaraid_provider_sudo_command(self) -> None:
        runner = FakeRunner(
            [CommandResult(read_fixture("megaraid", "drive_ok.json"), "", 0)]
        )
        drive = MegaRaidDrive(0, 252, 0, 4)
        MegaRaidProvider([drive], "/dev/sda", runner=runner, use_sudo=True).collect(
            [make_disk()]
        )
        self.assertEqual(runner.commands[0][0:2], ["sudo", "smartctl"])
        self.assertIn("megaraid,4", runner.commands[0])


    def test_megaraid_health_metrics_keep_physical_serials(self) -> None:
        runner = FakeRunner([
            CommandResult(read_fixture("megaraid", "drive_ok.json"), "", 0),
            CommandResult(read_fixture("megaraid", "drive_ok.json"), "", 0),
        ])
        drives = [
            MegaRaidDrive(0, 252, 0, 0, "MR-001"),
            MegaRaidDrive(0, 252, 1, 1, "MR-002"),
        ]
        health = MegaRaidProvider(drives, "/dev/sda", runner=runner).collect([make_disk()])
        metrics = build_health_metrics([make_disk()], health)
        self.assertEqual([metric.tags["serial"] for metric in metrics], ["MR-001", "MR-002"])

    def test_smart_service_delegates_to_megaraid_provider(self) -> None:
        runner = FakeRunner(
            [CommandResult(read_fixture("megaraid", "drive_ok.json"), "", 0)]
        )
        drive = MegaRaidDrive(0, 252, 0, 2, "MR-002")
        discovery = FixedDiscovery(
            RaidDiscoveryResult(RaidMode.MEGARAID, (drive,), "/dev/sda")
        )
        result = SmartService(runner=runner, discovery=discovery).collect([make_disk()])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].serial, "MR-002")
        self.assertIn("megaraid,2", runner.commands[0])

    def test_smart_service_keeps_direct_sata_behavior(self) -> None:
        runner = FakeRunner(
            [CommandResult(read_fixture("smart", "ata_ok.json"), "", 0)]
        )
        discovery = FixedDiscovery(RaidDiscoveryResult(RaidMode.SATA))
        result = SmartService(runner=runner, discovery=discovery).collect([make_disk()])
        self.assertTrue(result[0].smart_available)
        self.assertEqual(
            runner.commands[0],
            ["smartctl", "--json", "--all", "/dev/sda"],
        )


if __name__ == "__main__":
    unittest.main()
