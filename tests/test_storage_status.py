"""Tests for combined storage_status metrics."""

from __future__ import annotations

import unittest

import collector
from models.disk import Disk
from models.disk_health import DiskHealth
from services.storage_status import evaluate_storage_status


def make_disk(**overrides: object) -> Disk:
    values = {
        "serial": "SERIAL1",
        "vendor": "Seagate",
        "model": "Model X",
        "display_name": "Seagate Model X 1 TB",
        "capacity": "1 TB",
        "capacity_bytes": 1_000_000_000_000,
        "disk_type": "HDD",
        "transport": "SATA",
        "device": "/dev/sda",
    }
    values.update(overrides)
    return Disk(**values)


def make_health(**overrides: object) -> DiskHealth:
    values = {
        "serial": "SERIAL1",
        "device": "/dev/sda",
        "smart_available": True,
        "health_passed": True,
        "temperature_c": 35,
        "reallocated_sectors": 0,
        "pending_sectors": 0,
        "offline_uncorrectable": 0,
        "crc_errors": 0,
        "smartctl_exit_code": 0,
    }
    values.update(overrides)
    return DiskHealth(**values)


class StorageStatusTests(unittest.TestCase):
    def test_healthy_status(self) -> None:
        status = evaluate_storage_status(make_health())
        self.assertEqual(status.status, "Healthy")
        self.assertEqual(status.health_score, 100)

    def test_warning_status_for_reallocated_sector(self) -> None:
        status = evaluate_storage_status(make_health(reallocated_sectors=1))
        self.assertEqual(status.status, "Warning")
        self.assertEqual(status.health_score, 70)

    def test_critical_status_for_pending_sector(self) -> None:
        status = evaluate_storage_status(make_health(pending_sectors=1))
        self.assertEqual(status.status, "Critical")
        self.assertEqual(status.health_score, 30)

    def test_unknown_status_without_health_result(self) -> None:
        status = evaluate_storage_status(None)
        self.assertEqual(status.status, "Unknown")
        self.assertEqual(status.health_score, 50)
        self.assertFalse(status.smart_available)

    def test_status_metric_combines_inventory_and_health(self) -> None:
        disk = make_disk()
        status = evaluate_storage_status(make_health(reallocated_sectors=1))
        metric = collector.disk_status_to_metric(disk, status)

        self.assertEqual(metric.measurement, "storage_status")
        self.assertEqual(metric.fields["status_code"], 2)
        self.assertEqual(metric.fields["capacity_bytes"], 1_000_000_000_000)
        self.assertEqual(metric.fields["temperature_c"], 35)
        self.assertEqual(metric.fields["health_score"], 70)

    def test_unknown_optional_values_are_omitted(self) -> None:
        disk = make_disk(device="/dev/sdz", serial="USB1", disk_type="USB")
        metric = collector.build_status_metrics([disk], [])[0]

        self.assertEqual(metric.fields["status_code"], 0)
        self.assertEqual(metric.fields["smart_available"], False)
        self.assertNotIn("temperature_c", metric.fields)
        self.assertNotIn("smartctl_exit_code", metric.fields)

    def test_status_join_prefers_serial(self) -> None:
        control = make_disk(serial="CONTROL", device="/dev/sda")
        physical = make_disk(serial="PHYSICAL", device="/dev/sdc")
        health = make_health(serial="PHYSICAL", device="/dev/sda")

        metrics = collector.build_status_metrics([control, physical], [health])

        self.assertEqual(metrics[0].fields["status_code"], 0)
        self.assertEqual(metrics[1].fields["status_code"], 1)


if __name__ == "__main__":
    unittest.main()
