"""Fixture-driven tests for the ATA SMART parser."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from models.disk import Disk
from parsers.smart.ata import AtaSmartParser


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "smart"


def load_json(name: str) -> dict:
    with (FIXTURE_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def make_disk() -> Disk:
    return Disk(
        serial="INV-001",
        vendor="Seagate",
        model="ST1000",
        display_name="Seagate ST1000 1 TB",
        capacity="1 TB",
        capacity_bytes=1_000_000_000_000,
        disk_type="HDD",
        transport="SATA",
        device="/dev/sda",
    )


class AtaSmartParserFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = AtaSmartParser()
        self.disk = make_disk()

    def parse(self, name: str, exit_code: int = 0):
        return self.parser.parse(load_json(name), self.disk, exit_code)

    def test_healthy_fixture(self) -> None:
        health = self.parse("ata_ok.json")
        self.assertTrue(health.smart_available)
        self.assertTrue(health.health_passed)
        self.assertEqual(health.temperature_c, 31)
        self.assertEqual(health.reallocated_sectors, 2)
        self.assertEqual(health.pending_sectors, 3)
        self.assertEqual(health.offline_uncorrectable, 4)
        self.assertEqual(health.crc_errors, 5)

    def test_failed_health_is_valid_data(self) -> None:
        health = self.parse("ata_fail.json", exit_code=8)
        self.assertTrue(health.smart_available)
        self.assertFalse(health.health_passed)
        self.assertEqual(health.smartctl_exit_code, 8)

    def test_missing_temperature_stays_unknown(self) -> None:
        self.assertIsNone(self.parse("ata_no_temp.json").temperature_c)

    def test_temperature_fallback_194(self) -> None:
        self.assertEqual(self.parse("ata_temp194.json").temperature_c, 37)

    def test_temperature_fallback_190(self) -> None:
        self.assertEqual(self.parse("ata_temp190.json").temperature_c, 39)

    def test_invalid_temperatures_are_rejected(self) -> None:
        self.assertIsNone(self.parse("ata_invalid_temp.json").temperature_c)

    def test_missing_attribute_table_is_safe(self) -> None:
        health = self.parse("ata_missing_attributes.json")
        self.assertIsNone(health.reallocated_sectors)
        self.assertIsNone(health.pending_sectors)
        self.assertIsNone(health.offline_uncorrectable)
        self.assertIsNone(health.crc_errors)

    def test_raw_string_values_are_parsed_safely(self) -> None:
        health = self.parse("ata_raw_string.json")
        self.assertEqual(health.reallocated_sectors, 12)
        self.assertEqual(health.pending_sectors, 7)
        self.assertIsNone(health.offline_uncorrectable)
        self.assertEqual(health.crc_errors, -3)

    def test_old_smartctl_shape(self) -> None:
        health = self.parse("ata_old_smartctl.json")
        self.assertEqual(health.temperature_c, 34)
        self.assertEqual(health.reallocated_sectors, 0)

    def test_new_smartctl_shape(self) -> None:
        health = self.parse("ata_new_smartctl.json")
        self.assertEqual(health.temperature_c, 33)
        self.assertEqual(health.crc_errors, 1)

    def test_explicit_smart_unavailable_wins(self) -> None:
        health = self.parse("ata_unavailable.json", exit_code=2)
        self.assertFalse(health.smart_available)
        self.assertIsNone(health.health_passed)

    def test_empty_and_unknown_attributes_are_ignored(self) -> None:
        payload = {
            "smart_support": {"available": True},
            "ata_smart_attributes": {
                "table": [
                    {"id": 250, "raw": {"value": 99}},
                    {"id": 5},
                    "broken",
                    None,
                ]
            },
        }
        health = self.parser.parse(payload, self.disk, 0)
        self.assertIsNone(health.reallocated_sectors)
        self.assertIsNone(health.pending_sectors)

    def test_non_mapping_payload_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            self.parser.parse([], self.disk, 0)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
