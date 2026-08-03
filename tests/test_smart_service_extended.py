"""Extended behavior tests for SmartService."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from models.disk import Disk
from services.command_runner import (
    CommandNotFoundError,
    CommandPermissionError,
    CommandResult,
    CommandRunnerError,
    CommandTimeoutError,
)
from services.raid_discovery import RaidDiscoveryResult, RaidMode
from services.smart import SmartService, SmartctlUnavailableError


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "smart"


def fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def make_disk(**overrides: object) -> Disk:
    values = {
        "serial": "INV-001",
        "vendor": "Seagate",
        "model": "ST1000",
        "display_name": "Seagate ST1000 1 TB",
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


class DirectOnlyDiscovery:
    """Deterministic no-RAID discovery for ATA-focused unit tests."""

    def discover(self, disks):
        disk_list = tuple(disks)
        direct_disks = tuple(
            disk
            for disk in disk_list
            if disk.transport.upper() in {"ATA", "SATA"}
            or (disk.transport.upper() == "UNKNOWN" and disk.device.startswith("/dev/sd"))
        )
        mode = RaidMode.SATA if direct_disks else RaidMode.NONE
        return RaidDiscoveryResult(mode=mode, direct_disks=direct_disks)


def make_smart_service(**kwargs):
    kwargs.setdefault("discovery", DirectOnlyDiscovery())
    return SmartService(**kwargs)


class SmartServiceExtendedTests(unittest.TestCase):
    def test_supported_transport_matrix(self) -> None:
        runner = FakeRunner(
            [
                CommandResult(fixture_text("ata_ok.json"), "", 0),
                CommandResult(fixture_text("ata_ok.json"), "", 0),
                CommandResult(fixture_text("ata_ok.json"), "", 0),
            ]
        )
        disks = [
            make_disk(device="/dev/sda", transport="ATA"),
            make_disk(device="/dev/sdb", transport="SATA"),
            make_disk(device="/dev/sdc", transport="Unknown"),
            make_disk(device="/dev/sdd", transport="USB", disk_type="USB"),
            make_disk(device="/dev/nvme0n1", transport="NVMe", disk_type="NVMe"),
            make_disk(device="/dev/sde", transport="SAS"),
            make_disk(device="/dev/mapper/data", transport="Unknown"),
        ]
        health = make_smart_service(runner=runner).collect(disks)
        self.assertEqual(len(health), 3)
        self.assertEqual(len(runner.commands), 3)

    def test_exact_smartctl_command(self) -> None:
        runner = FakeRunner([CommandResult(fixture_text("ata_ok.json"), "", 0)])
        make_smart_service(runner=runner, binary="/usr/sbin/smartctl").collect([make_disk()])
        self.assertEqual(
            runner.commands,
            [["/usr/sbin/smartctl", "--json", "--all", "/dev/sda"]],
        )

    def test_timeout_is_isolated(self) -> None:
        runner = FakeRunner([CommandTimeoutError("timeout")])
        result = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertFalse(result.smart_available)
        self.assertEqual(result.smartctl_exit_code, -1)
        self.assertIn("timeout", result.error or "")

    def test_permission_denied_is_isolated(self) -> None:
        runner = FakeRunner([CommandPermissionError("permission denied")])
        result = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertFalse(result.smart_available)
        self.assertIn("permission denied", result.error or "")

    def test_generic_runner_error_is_isolated(self) -> None:
        runner = FakeRunner([CommandRunnerError("device error")])
        result = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertFalse(result.smart_available)
        self.assertIn("device error", result.error or "")

    def test_invalid_json_preserves_exit_code_and_stderr(self) -> None:
        runner = FakeRunner(
            [CommandResult(fixture_text("invalid_json.txt"), "cannot open device", 2)]
        )
        result = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertFalse(result.smart_available)
        self.assertEqual(result.smartctl_exit_code, 2)
        self.assertEqual(result.error, "cannot open device")

    def test_missing_json_preserves_exit_code(self) -> None:
        runner = FakeRunner([CommandResult("", "empty output", 4)])
        result = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertFalse(result.smart_available)
        self.assertEqual(result.smartctl_exit_code, 4)
        self.assertEqual(result.error, "empty output")

    def test_json_array_root_is_rejected(self) -> None:
        runner = FakeRunner([CommandResult(json.dumps([1, 2]), "", 2)])
        result = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertFalse(result.smart_available)
        self.assertEqual(result.smartctl_exit_code, 2)

    def test_nonzero_exit_with_valid_json_is_parsed(self) -> None:
        runner = FakeRunner([CommandResult(fixture_text("ata_fail.json"), "", 8)])
        result = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertTrue(result.smart_available)
        self.assertFalse(result.health_passed)
        self.assertEqual(result.smartctl_exit_code, 8)

    def test_one_failure_does_not_stop_five_disks(self) -> None:
        ok = CommandResult(fixture_text("ata_ok.json"), "", 0)
        runner = FakeRunner(
            [ok, CommandTimeoutError("timeout"), ok, ok, ok]
        )
        disks = [make_disk(device=f"/dev/sd{letter}") for letter in "abcde"]
        results = make_smart_service(runner=runner).collect(disks)
        self.assertEqual(len(results), 5)
        self.assertEqual(sum(result.smart_available for result in results), 4)
        self.assertFalse(results[1].smart_available)

    def test_serial_mismatch_logs_warning_but_keeps_inventory_serial(self) -> None:
        data = json.loads(fixture_text("ata_ok.json"))
        data["serial_number"] = "SMART-OTHER"
        runner = FakeRunner([CommandResult(json.dumps(data), "", 0)])
        with self.assertLogs("home_server_monitor.smart", level="WARNING") as logs:
            result = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertEqual(result.serial, "INV-001")
        self.assertTrue(any("does not match" in line for line in logs.output))

    def test_missing_executable_aborts_subsystem(self) -> None:
        runner = FakeRunner([CommandNotFoundError("missing")])
        with self.assertRaises(SmartctlUnavailableError):
            make_smart_service(runner=runner).collect([make_disk()])


if __name__ == "__main__":
    unittest.main()
