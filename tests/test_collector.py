"""Unit tests for collector metric creation and command behavior."""

import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

import collector
from exceptions import StorageError
from metric import Metric
from models.disk import Disk
from models.disk_health import DiskHealth
from services.smart import SmartctlUnavailableError


class CollectorTests(unittest.TestCase):
    """Verify conversion to Metric and stdout-only Line Protocol output."""

    def setUp(self) -> None:
        self.disk = Disk(
            serial="Z1N344GW",
            vendor="Seagate",
            model="ST1000NM0011",
            display_name="Seagate ST1000NM0011 1 TB",
            capacity="1 TB",
            capacity_bytes=1_000_204_886_016,
            disk_type="HDD",
            transport="SAS",
            device="/dev/sda",
        )

    def test_disk_to_metric_creates_expected_metric(self) -> None:
        metric = collector.disk_to_metric(self.disk)

        self.assertIsInstance(metric, Metric)
        self.assertEqual(metric.measurement, "storage_inventory")
        self.assertEqual(metric.tags["serial"], "Z1N344GW")
        self.assertEqual(metric.fields["capacity_bytes"], 1_000_204_886_016)
        self.assertIs(metric.fields["present"], True)
        self.assertEqual(
            metric.to_line_protocol(),
            "storage_inventory,serial=Z1N344GW,vendor=Seagate,model=ST1000NM0011,"
            "display_name=Seagate\\ ST1000NM0011\\ 1\\ TB,disk_type=HDD,"
            "transport=SAS,device=/dev/sda capacity_bytes=1000204886016i,present=true",
        )

    def test_missing_serial_uses_device_fallback(self) -> None:
        disk = Disk(**{**self.disk.__dict__, "serial": "", "device": "/dev/sdz"})

        with self.assertLogs("home_server_monitor.collector", level="WARNING"):
            metric = collector.disk_to_metric(disk)

        self.assertEqual(metric.tags["serial"], "/dev/sdz")

    def test_main_writes_line_protocol_to_stdout(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        health = DiskHealth(
            serial=self.disk.serial,
            device=self.disk.device,
            smart_available=True,
            health_passed=True,
            temperature_c=31,
            reallocated_sectors=0,
            pending_sectors=0,
            offline_uncorrectable=0,
            crc_errors=0,
            smartctl_exit_code=0,
        )
        with patch("collector.StorageCollector.collect", return_value=[self.disk]):
            with patch("collector.SmartService.collect", return_value=[health]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = collector.main()

        self.assertEqual(result, 0)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("storage_inventory,"))
        self.assertTrue(lines[1].startswith("storage_health,"))
        self.assertTrue(lines[2].startswith("storage_status,"))
        self.assertEqual(stderr.getvalue(), "")

    def test_main_returns_nonzero_on_critical_error(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with patch("collector.StorageCollector.collect", side_effect=StorageError("failed")):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = collector.main()

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")

    def test_health_metric_omits_unknown_optional_fields(self) -> None:
        health = DiskHealth(
            serial=self.disk.serial,
            device=self.disk.device,
            smart_available=False,
            health_passed=None,
            temperature_c=None,
            reallocated_sectors=None,
            pending_sectors=None,
            offline_uncorrectable=None,
            crc_errors=None,
            smartctl_exit_code=2,
            error="permission denied",
        )

        metric = collector.disk_health_to_metric(self.disk, health)

        self.assertEqual(metric.measurement, "storage_health")
        self.assertEqual(
            metric.fields,
            {"smart_available": False, "smartctl_exit_code": 2},
        )
        self.assertNotIn("error", metric.fields)

    def test_health_metric_preserves_confirmed_smart_failure(self) -> None:
        health = DiskHealth(
            serial=self.disk.serial,
            device=self.disk.device,
            smart_available=True,
            health_passed=False,
            temperature_c=40,
            reallocated_sectors=1,
            pending_sectors=2,
            offline_uncorrectable=3,
            crc_errors=4,
            smartctl_exit_code=8,
        )

        metric = collector.disk_health_to_metric(self.disk, health)

        self.assertIs(metric.fields["health_passed"], False)
        self.assertEqual(metric.fields["smartctl_exit_code"], 8)
        self.assertIn("health_passed=false", metric.to_line_protocol())

    def test_build_health_metrics_ignores_unknown_device(self) -> None:
        health = DiskHealth(
            serial="OTHER",
            device="/dev/sdz",
            smart_available=False,
            health_passed=None,
            temperature_c=None,
            reallocated_sectors=None,
            pending_sectors=None,
            offline_uncorrectable=None,
            crc_errors=None,
            smartctl_exit_code=2,
        )

        with self.assertLogs("home_server_monitor.collector", level="WARNING"):
            metrics = collector.build_health_metrics([self.disk], [health])

        self.assertEqual(metrics, [])


    def test_storage_visible_disks_excludes_megaraid_serials(self) -> None:
        direct = Disk(**{**self.disk.__dict__, "serial": "DIRECT", "device": "/dev/sdb"})
        raid_health = DiskHealth(
            serial=self.disk.serial, device="/dev/bus/0", smart_available=True,
            health_passed=True, temperature_c=30, reallocated_sectors=0,
            pending_sectors=0, offline_uncorrectable=0, crc_errors=0,
            smartctl_exit_code=0, error=None,
        )
        visible = collector.storage_visible_disks([self.disk, direct], [raid_health])
        self.assertEqual([disk.serial for disk in visible], ["DIRECT"])

    def test_storage_visible_health_results_drops_non_storage_results(self) -> None:
        visible = Disk(**{**self.disk.__dict__, "serial": "DIRECT", "device": "/dev/sdb"})
        direct_health = DiskHealth(
            serial="DIRECT", device="/dev/sdb", smart_available=True,
            health_passed=True, temperature_c=30, reallocated_sectors=0,
            pending_sectors=0, offline_uncorrectable=0, crc_errors=0,
            smartctl_exit_code=0, error=None,
        )
        raid_health = DiskHealth(
            serial="RAID", device="/dev/sda", smart_available=True,
            health_passed=True, temperature_c=30, reallocated_sectors=0,
            pending_sectors=0, offline_uncorrectable=0, crc_errors=0,
            smartctl_exit_code=0, error=None,
        )

        results = collector.storage_visible_health_results([visible], [direct_health, raid_health])

        self.assertEqual(results, [direct_health])

    def test_main_emits_inventory_before_missing_smartctl_failure(self) -> None:
        stdout = StringIO()
        stderr = StringIO()

        with patch("collector.StorageCollector.collect", return_value=[self.disk]):
            with patch(
                "collector.SmartService.collect",
                side_effect=SmartctlUnavailableError("smartctl missing"),
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = collector.main()

        self.assertEqual(result, 1)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("storage_inventory,"))

    def test_health_metrics_join_megaraid_result_by_serial_before_control_device(self) -> None:
        control = Disk(
            serial="CONTROL", vendor="ControlVendor", model="ControlModel",
            display_name="Control Disk", capacity="1 TB", capacity_bytes=1,
            disk_type="HDD", transport="ATA", device="/dev/sda",
        )
        physical = Disk(
            serial="PHYSICAL", vendor="Seagate", model="PhysicalModel",
            display_name="Physical Disk", capacity="500 GB", capacity_bytes=1,
            disk_type="HDD", transport="ATA", device="/dev/sdc",
        )
        health = DiskHealth(
            serial="PHYSICAL", device="/dev/sda", smart_available=True,
            health_passed=True, temperature_c=30, reallocated_sectors=0,
            pending_sectors=0, offline_uncorrectable=0, crc_errors=0,
            smartctl_exit_code=0, error=None,
        )

        metrics = collector.build_health_metrics([control, physical], [health])

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].tags["serial"], "PHYSICAL")
        self.assertEqual(metrics[0].tags["device"], "/dev/sdc")
        self.assertEqual(metrics[0].tags["model"], "PhysicalModel")


if __name__ == "__main__":
    unittest.main()
