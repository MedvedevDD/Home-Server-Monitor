"""Unit tests for the persistent inventory cache."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import CACHE_VERSION
from models.disk import Disk
from services.inventory_cache import InventoryCache


class InventoryCacheTests(unittest.TestCase):
    """Verify cache persistence, validation, signatures, and recovery."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.temp_dir.name) / "storage_inventory.json"
        self.cache = InventoryCache(self.cache_path)
        self.disks = [
            Disk(
                serial="SERIAL-B",
                vendor="Toshiba",
                model="MG08ACA16TE",
                display_name="Toshiba MG08ACA16TE 16 TB",
                capacity="16 TB",
                capacity_bytes=16_000_900_661_248,
                disk_type="HDD",
                transport="SATA",
                device="/dev/sdb",
            ),
            Disk(
                serial="SERIAL-A",
                vendor="Samsung",
                model="SSD 870 EVO",
                display_name="Samsung SSD 870 EVO 500 GB",
                capacity="500 GB",
                capacity_bytes=500_107_862_016,
                disk_type="SSD",
                transport="SATA",
                device="/dev/sda",
            ),
        ]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_and_load_restore_disk_objects(self) -> None:
        self.assertTrue(self.cache.save(self.disks))
        restored = self.cache.load()
        self.assertEqual(restored, self.disks)
        self.assertTrue(all(isinstance(item, Disk) for item in restored or []))

    def test_signature_is_stable_when_order_changes(self) -> None:
        original = self.cache.get_signature(self.disks)
        reversed_order = self.cache.get_signature(list(reversed(self.disks)))
        self.assertEqual(original, reversed_order)

    def test_signature_changes_when_composition_changes(self) -> None:
        original = self.cache.get_signature(self.disks)
        changed = self.cache.get_signature(self.disks[:1])
        self.assertNotEqual(original, changed)

    def test_is_valid_compares_signature(self) -> None:
        signature = self.cache.get_signature(self.disks)
        self.cache.save(self.disks, signature)
        self.assertTrue(self.cache.is_valid(signature))
        self.assertFalse(self.cache.is_valid("0" * 64))

    def test_corrupt_json_is_removed(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text("{invalid json", encoding="utf-8")
        self.assertIsNone(self.cache.load())
        self.assertFalse(self.cache_path.exists())

    def test_wrong_version_is_removed(self) -> None:
        payload = {
            "version": CACHE_VERSION + 1,
            "generated": "2026-07-10T12:30:00Z",
            "signature": "0" * 64,
            "disks": [],
        }
        self.cache_path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertFalse(self.cache.is_valid())
        self.assertFalse(self.cache_path.exists())

    def test_version_one_cache_is_removed_as_obsolete(self) -> None:
        payload = {
            "version": 1,
            "generated": "2026-07-10T12:30:00Z",
            "signature": "0" * 64,
            "disks": [],
        }
        self.cache_path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertFalse(self.cache.is_valid())
        self.assertFalse(self.cache_path.exists())

    def test_unreadable_cache_does_not_raise(self) -> None:
        self.cache_path.write_text("{}", encoding="utf-8")
        with patch.object(Path, "open", side_effect=PermissionError("denied")):
            self.assertIsNone(self.cache.load())

    def test_invalidate_removes_cache(self) -> None:
        self.cache.save(self.disks)
        self.cache.invalidate()
        self.assertFalse(self.cache_path.exists())


if __name__ == "__main__":
    unittest.main()
