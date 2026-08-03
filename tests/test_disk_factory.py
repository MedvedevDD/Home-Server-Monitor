"""Unit tests for DiskFactory serialization."""

import unittest

from models.disk import Disk
from services.disk_factory import DiskFactory


class DiskFactoryTests(unittest.TestCase):
    """Verify conversion between Disk objects and cache dictionaries."""

    def setUp(self) -> None:
        self.disk = Disk(
            serial="SERIAL-001",
            vendor="Seagate",
            model="ST1000NM0011",
            display_name="Seagate ST1000NM0011 1 TB",
            capacity="1 TB",
            capacity_bytes=1_000_204_886_016,
            disk_type="HDD",
            transport="SAS",
            device="/dev/sda",
            temperature=None,
            smart_health=None,
            reallocated=0,
            pending=0,
            offline=0,
            crc=0,
        )

    def test_to_dict_contains_disk_fields(self) -> None:
        data = DiskFactory.to_dict(self.disk)
        self.assertEqual(data["serial"], "SERIAL-001")
        self.assertEqual(data["capacity_bytes"], 1_000_204_886_016)
        self.assertEqual(data["device"], "/dev/sda")

    def test_from_dict_restores_disk(self) -> None:
        restored = DiskFactory.from_dict(DiskFactory.to_dict(self.disk))
        self.assertIsInstance(restored, Disk)
        self.assertEqual(restored, self.disk)


class DiskFactoryInventoryQualityTests(unittest.TestCase):
    """Verify real-world vendor, size, display name, and transport rules."""

    def test_toshiba_hdwd_model_is_resolved(self) -> None:
        disk = DiskFactory.from_lsblk({"name": "sda", "model": "HDWD260", "size": 6_001_175_126_016})
        self.assertEqual(disk.vendor, "Toshiba")

    def test_samsung_vendor_is_not_duplicated_in_display_name(self) -> None:
        disk = DiskFactory.from_lsblk(
            {
                "name": "sda",
                "vendor": "Samsung",
                "model": "Samsung SSD 860 EVO 250GB",
                "size": 250_059_350_016,
                "rota": 0,
                "tran": "sata",
            }
        )
        self.assertEqual(disk.display_name, "Samsung SSD 860 EVO 250GB 250 GB")
        self.assertEqual(disk.capacity_bytes, 250_059_350_016)

    def test_usb_transport_sets_usb_disk_type(self) -> None:
        disk = DiskFactory.from_lsblk(
            {
                "name": "sdb",
                "model": "FLASH DRIVE",
                "size": 32_000_000_000,
                "rota": 0,
                "tran": "usb",
            }
        )
        self.assertEqual(disk.disk_type, "USB")
        self.assertEqual(disk.transport, "USB")

    def test_missing_transport_with_ata_vendor_uses_ata(self) -> None:
        disk = DiskFactory.from_lsblk(
            {
                "name": "sda",
                "vendor": "ATA",
                "model": "ST1000NM0011",
                "size": 1_000_204_886_016,
                "rota": 1,
                "tran": None,
            }
        )
        self.assertEqual(disk.vendor, "Seagate")
        self.assertEqual(disk.transport, "ATA")


if __name__ == "__main__":
    unittest.main()
