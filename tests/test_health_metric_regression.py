"""Regression tests for storage inventory and health Line Protocol."""

from __future__ import annotations

import unittest

import collector
from models.disk import Disk
from models.disk_health import DiskHealth


def make_disk(**overrides: object) -> Disk:
    values = {
        "serial": "SERIAL 1",
        "vendor": "Vendor",
        "model": "Model X",
        "display_name": "Vendor Model X 1 TB",
        "capacity": "1 TB",
        "capacity_bytes": 1_000_000_000_000,
        "disk_type": "HDD",
        "transport": "SATA",
        "device": "/dev/sda",
    }
    values.update(overrides)
    return Disk(**values)


class HealthMetricRegressionTests(unittest.TestCase):
    def test_inventory_schema_is_unchanged(self) -> None:
        metric = collector.disk_to_metric(make_disk())
        self.assertEqual(metric.measurement, "storage_inventory")
        self.assertEqual(
            set(metric.tags),
            {
                "serial",
                "vendor",
                "model",
                "display_name",
                "disk_type",
                "transport",
                "device",
            },
        )
        self.assertEqual(set(metric.fields), {"capacity_bytes", "present"})

    def test_complete_health_metric_fields(self) -> None:
        disk = make_disk()
        health = DiskHealth(
            serial=disk.serial,
            device=disk.device,
            smart_available=True,
            health_passed=False,
            temperature_c=42,
            reallocated_sectors=1,
            pending_sectors=2,
            offline_uncorrectable=3,
            crc_errors=4,
            smartctl_exit_code=8,
        )
        metric = collector.disk_health_to_metric(disk, health)
        self.assertEqual(metric.measurement, "storage_health")
        self.assertEqual(
            set(metric.fields),
            {
                "smart_available",
                "health_passed",
                "temperature_c",
                "reallocated_sectors",
                "pending_sectors",
                "offline_uncorrectable",
                "crc_errors",
                "smartctl_exit_code",
            },
        )
        line = metric.to_line_protocol()
        self.assertIn("smart_available=true", line)
        self.assertIn("health_passed=false", line)
        self.assertIn("temperature_c=42i", line)
        self.assertIn("smartctl_exit_code=8i", line)

    def test_unknown_health_values_are_omitted(self) -> None:
        disk = make_disk()
        health = DiskHealth(
            serial=disk.serial,
            device=disk.device,
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
        metric = collector.disk_health_to_metric(disk, health)
        self.assertEqual(
            metric.fields,
            {"smart_available": False, "smartctl_exit_code": 2},
        )
        line = metric.to_line_protocol()
        self.assertNotIn("temperature_c", line)
        self.assertNotIn("health_passed", line)
        self.assertNotIn("error", line)

    def test_health_error_is_never_published(self) -> None:
        disk = make_disk()
        health = DiskHealth(
            serial=disk.serial,
            device=disk.device,
            smart_available=False,
            health_passed=None,
            temperature_c=None,
            reallocated_sectors=None,
            pending_sectors=None,
            offline_uncorrectable=None,
            crc_errors=None,
            smartctl_exit_code=-1,
            error="secret diagnostic text",
        )
        self.assertNotIn(
            "secret diagnostic text",
            collector.disk_health_to_metric(disk, health).to_line_protocol(),
        )

    def test_device_fallback_is_stable_for_missing_serial(self) -> None:
        disk = make_disk(serial="")
        metric = collector.disk_to_metric(disk)
        self.assertEqual(metric.tags["serial"], "/dev/sda")


if __name__ == "__main__":
    unittest.main()
