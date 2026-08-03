import json
import unittest
from pathlib import Path
from unittest import mock

import config
from services.inventory import InventoryService
from services.raid_collectors import StorCliRaidCollector


class V731PolishTests(unittest.TestCase):
    def test_usb_removable_is_hidden_by_default(self):
        row = {"tran": "usb", "rm": True, "model": "USB FLASH DRIVE", "serial": "X"}
        with mock.patch.object(config, "STORAGE_HIDE_USB_FLASH", True), \
             mock.patch.object(config, "STORAGE_EXCLUDE_SERIALS", frozenset()), \
             mock.patch.object(config, "STORAGE_EXCLUDE_MODELS", tuple()):
            self.assertFalse(InventoryService._include_device(row))

    def test_usb_fixed_disk_is_kept(self):
        row = {"tran": "usb", "rm": False, "model": "External SSD", "serial": "X"}
        with mock.patch.object(config, "STORAGE_HIDE_USB_FLASH", True), \
             mock.patch.object(config, "STORAGE_EXCLUDE_SERIALS", frozenset()), \
             mock.patch.object(config, "STORAGE_EXCLUDE_MODELS", tuple()):
            self.assertTrue(InventoryService._include_device(row))

    def test_model_exclusion_is_case_insensitive(self):
        row = {"tran": "usb", "rm": False, "model": "Kingston DataTraveler 3.0", "serial": "X"}
        with mock.patch.object(config, "STORAGE_HIDE_USB_FLASH", False), \
             mock.patch.object(config, "STORAGE_EXCLUDE_SERIALS", frozenset()), \
             mock.patch.object(config, "STORAGE_EXCLUDE_MODELS", ("datatraveler",)):
            self.assertFalse(InventoryService._include_device(row))

    def test_storcli_detail_index_reads_serial_and_temperature(self):
        payload = {"Controllers": [{"Response Data": {
            "Drive /c0/e252/s2 - Detailed Information": {
                "Drive /c0/e252/s2 Device attributes": {
                    "SN": "SERIAL123", "Drive Temperature": "31C", "Model Number": "ST1000NM0011"
                }
            }
        }}]}
        index = StorCliRaidCollector._drive_detail_index(payload)
        self.assertEqual(index[("0", "252", "2")]["SN"], "SERIAL123")

    def test_critical_zero_threshold_is_green(self):
        root = Path(__file__).resolve().parents[1]
        dashboard = json.loads((root / "dashboard" / "Home.json").read_text())
        panel = next(item for item in dashboard["panels"] if item["title"] == "Storage critical")
        steps = panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
        self.assertEqual(steps[0]["color"], "green")
        self.assertEqual(steps[1], {"color": "red", "value": 1})


class V732StorageClassificationTests(unittest.TestCase):
    def test_real_usb_flash_signature_is_hidden(self):
        row = {
            "name": "sdh",
            "type": "disk",
            "model": "FLASH DRIVE",
            "vendor": "USB",
            "serial": "AAACD00589A26DFC",
            "tran": "usb",
            "rm": 1,
            "hotplug": 1,
            "rota": None,
        }
        with mock.patch.object(config, "STORAGE_HIDE_USB_FLASH", True), \
             mock.patch.object(config, "STORAGE_EXCLUDE_SERIALS", frozenset()), \
             mock.patch.object(config, "STORAGE_EXCLUDE_MODELS", tuple()):
            self.assertFalse(InventoryService._include_device(row))

    def test_usb_flash_is_hidden_even_when_bridge_reports_rm_zero(self):
        row = {
            "name": "sdc", "type": "disk", "model": "Kingston DataTraveler 3.0",
            "vendor": "Kingston", "serial": "X", "tran": "usb", "rm": 0,
            "hotplug": 1, "rota": None,
        }
        with mock.patch.object(config, "STORAGE_HIDE_USB_FLASH", True), \
             mock.patch.object(config, "STORAGE_EXCLUDE_SERIALS", frozenset()), \
             mock.patch.object(config, "STORAGE_EXCLUDE_MODELS", tuple()):
            self.assertFalse(InventoryService._include_device(row))

    def test_external_usb_ssd_is_kept(self):
        row = {
            "name": "sdc", "type": "disk", "model": "Samsung Portable SSD T7",
            "vendor": "Samsung", "serial": "X", "tran": "usb", "rm": 0,
            "hotplug": 1, "rota": 0,
        }
        with mock.patch.object(config, "STORAGE_HIDE_USB_FLASH", True), \
             mock.patch.object(config, "STORAGE_EXCLUDE_SERIALS", frozenset()), \
             mock.patch.object(config, "STORAGE_EXCLUDE_MODELS", tuple()):
            self.assertTrue(InventoryService._include_device(row))


if __name__ == "__main__":
    unittest.main()
