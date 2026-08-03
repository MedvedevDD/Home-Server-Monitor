"""Tests for the v5.7.2 SMART foundation layer."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from models.disk import Disk
from models.disk_health import DiskHealth
from parsers.smart.ata import AtaSmartParser
from services.command_runner import (
    CommandNotFoundError,
    CommandResult,
    CommandRunner,
    CommandTimeoutError,
)
from services.raid_discovery import RaidDiscoveryResult, RaidMode
from services.smart import SmartService, SmartctlUnavailableError


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


def payload(*, passed: bool | None = True, temperature: int | None = 31) -> dict:
    result: dict = {
        "smart_support": {"available": True, "enabled": True},
        "ata_smart_attributes": {
            "table": [
                {"id": 5, "raw": {"value": 2, "string": "2"}},
                {"id": 197, "raw": {"string": "3 sectors"}},
                {"id": 198, "raw": {"value": 4}},
                {"id": 199, "raw": {"string": "5"}},
                {"id": 194, "raw": {"value": 40}},
                {"id": 190, "raw": {"value": 41}},
            ]
        },
    }
    if passed is not None:
        result["smart_status"] = {"passed": passed}
    if temperature is not None:
        result["temperature"] = {"current": temperature}
    return result


class AtaSmartParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = AtaSmartParser()
        self.disk = make_disk()

    def test_parses_health_and_attributes(self) -> None:
        health = self.parser.parse(payload(), self.disk, 0)
        self.assertTrue(health.smart_available)
        self.assertTrue(health.health_passed)
        self.assertEqual(health.temperature_c, 31)
        self.assertEqual(health.reallocated_sectors, 2)
        self.assertEqual(health.pending_sectors, 3)
        self.assertEqual(health.offline_uncorrectable, 4)
        self.assertEqual(health.crc_errors, 5)

    def test_smart_fail_is_valid_monitoring_result(self) -> None:
        health = self.parser.parse(payload(passed=False), self.disk, 8)
        self.assertTrue(health.smart_available)
        self.assertFalse(health.health_passed)
        self.assertEqual(health.smartctl_exit_code, 8)

    def test_missing_smart_status_stays_unknown(self) -> None:
        health = self.parser.parse(payload(passed=None), self.disk, 0)
        self.assertIsNone(health.health_passed)

    def test_temperature_falls_back_to_194_then_190(self) -> None:
        data = payload(temperature=None)
        health = self.parser.parse(data, self.disk, 0)
        self.assertEqual(health.temperature_c, 40)
        data["ata_smart_attributes"]["table"] = [
            {"id": 190, "raw": {"string": "41 (Min/Max 20/50)"}}
        ]
        health = self.parser.parse(data, self.disk, 0)
        self.assertEqual(health.temperature_c, 41)

    def test_invalid_temperature_is_not_reported(self) -> None:
        data = payload(temperature=255)
        data["ata_smart_attributes"]["table"] = []
        health = self.parser.parse(data, self.disk, 0)
        self.assertIsNone(health.temperature_c)

    def test_broken_attribute_does_not_break_parser(self) -> None:
        data = payload()
        data["ata_smart_attributes"]["table"].append({"id": 201, "raw": object()})
        health = self.parser.parse(data, self.disk, 0)
        self.assertEqual(health.reallocated_sectors, 2)


class FakeRunner:
    def __init__(self, results: list[CommandResult | Exception]) -> None:
        self.results = list(results)
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> CommandResult:
        self.commands.append(command)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


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


class SmartServiceTests(unittest.TestCase):
    def test_collects_sata_and_ata_but_skips_usb(self) -> None:
        result = CommandResult(json.dumps(payload()), "", 0)
        runner = FakeRunner([result, result])
        service = make_smart_service(runner=runner)
        disks = [
            make_disk(device="/dev/sda", transport="SATA"),
            make_disk(device="/dev/sdb", transport="ATA"),
            make_disk(device="/dev/sdc", transport="USB", disk_type="USB"),
        ]
        health = service.collect(disks)
        self.assertEqual(len(health), 2)
        self.assertEqual(len(runner.commands), 2)
        self.assertEqual(runner.commands[0], ["smartctl", "--json", "--all", "/dev/sda"])

    def test_unknown_regular_sd_device_is_attempted(self) -> None:
        runner = FakeRunner([CommandResult(json.dumps(payload()), "", 0)])
        health = make_smart_service(runner=runner).collect(
            [make_disk(transport="Unknown", device="/dev/sdz")]
        )
        self.assertEqual(len(health), 1)

    def test_invalid_json_returns_unavailable_and_continues(self) -> None:
        runner = FakeRunner(
            [
                CommandResult("not-json", "open failed", 2),
                CommandResult(json.dumps(payload()), "", 0),
            ]
        )
        health = make_smart_service(runner=runner).collect(
            [make_disk(device="/dev/sda"), make_disk(device="/dev/sdb")]
        )
        self.assertEqual(len(health), 2)
        self.assertFalse(health[0].smart_available)
        self.assertTrue(health[1].smart_available)

    def test_nonzero_exit_code_with_json_is_parsed(self) -> None:
        runner = FakeRunner([CommandResult(json.dumps(payload(passed=False)), "", 8)])
        health = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertTrue(health.smart_available)
        self.assertFalse(health.health_passed)
        self.assertEqual(health.smartctl_exit_code, 8)

    def test_timeout_returns_unavailable(self) -> None:
        runner = FakeRunner([CommandTimeoutError("timeout")])
        health = make_smart_service(runner=runner).collect([make_disk()])[0]
        self.assertFalse(health.smart_available)
        self.assertEqual(health.smartctl_exit_code, -1)

    def test_missing_smartctl_is_global_subsystem_error(self) -> None:
        runner = FakeRunner([CommandNotFoundError("missing")])
        with self.assertRaises(SmartctlUnavailableError):
            make_smart_service(runner=runner).collect([make_disk()])

    def test_result_uses_inventory_serial(self) -> None:
        data = payload()
        data["serial_number"] = "SMART-OTHER"
        runner = FakeRunner([CommandResult(json.dumps(data), "", 0)])
        health = make_smart_service(runner=runner).collect([make_disk(serial="INV-001")])[0]
        self.assertEqual(health.serial, "INV-001")


class CommandRunnerTests(unittest.TestCase):
    def test_returns_completed_process_data(self) -> None:
        completed = __import__("subprocess").CompletedProcess(
            args=["tool"], returncode=4, stdout="out", stderr="err"
        )
        with patch("services.command_runner.subprocess.run", return_value=completed) as run:
            result = CommandRunner(timeout_seconds=7).run(["tool", "arg"])
        self.assertEqual(result, CommandResult("out", "err", 4))
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_file_not_found_is_normalized(self) -> None:
        with patch(
            "services.command_runner.subprocess.run",
            side_effect=FileNotFoundError("missing"),
        ):
            with self.assertRaises(CommandNotFoundError):
                CommandRunner().run(["smartctl"])


class DiskHealthTests(unittest.TestCase):
    def test_model_is_independent_from_disk(self) -> None:
        health = DiskHealth(
            serial="SERIAL",
            device="/dev/sda",
            smart_available=False,
            health_passed=None,
            temperature_c=None,
            reallocated_sectors=None,
            pending_sectors=None,
            offline_uncorrectable=None,
            crc_errors=None,
            smartctl_exit_code=2,
            error="unavailable",
        )
        self.assertEqual(health.error, "unavailable")


if __name__ == "__main__":
    unittest.main()
