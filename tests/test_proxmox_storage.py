from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from services.proxmox_storage import ProxmoxStorageCollector, storage_health


class Completed:
    returncode = 0
    stderr = ""
    stdout = json.dumps([{
        "active": 1, "enabled": 1, "shared": 0, "storage": "local-lvm",
        "type": "lvmthin", "content": "rootdir,images", "total": 180195688448,
        "used": 179817277502, "avail": 378410946, "used_fraction": 0.9979,
    }])


class ProxmoxStorageTests(unittest.TestCase):
    def test_health_thresholds(self):
        self.assertEqual(storage_health(True, True, 79.9), (0, "OK"))
        self.assertEqual(storage_health(True, True, 80), (1, "WARNING"))
        self.assertEqual(storage_health(True, True, 90), (2, "HIGH"))
        self.assertEqual(storage_health(True, True, 95), (3, "CRITICAL"))
        self.assertEqual(storage_health(False, True, 10), (3, "UNAVAILABLE"))

    @patch("services.proxmox_storage.subprocess.run", return_value=Completed())
    def test_collects_storage(self, _run):
        item = ProxmoxStorageCollector().collect("pve01")[0]
        self.assertEqual(item.storage, "local-lvm")
        self.assertEqual(item.used_percent, 99.79)
        self.assertEqual(item.health_status, "CRITICAL")

if __name__ == "__main__":
    unittest.main()
