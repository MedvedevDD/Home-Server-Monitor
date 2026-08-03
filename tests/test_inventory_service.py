"""Unit tests for InventoryService cache and error behavior."""

import unittest
from unittest.mock import Mock, patch

from exceptions import StorageError
from models.disk import Disk
from services.inventory import InventoryService


class InventoryServiceTests(unittest.TestCase):
    """Verify inventory refresh, fallback, and cache preservation rules."""

    def test_valid_cache_avoids_full_inventory_query(self) -> None:
        cached_disk = Disk(serial="SERIAL-1", model="MODEL-1")
        cache = Mock()
        cache.get_signature.return_value = "signature"
        cache.is_valid.return_value = True
        cache.load.return_value = [cached_disk]
        service = InventoryService(cache=cache)

        identity_rows = [{"type": "disk", "serial": "SERIAL-1", "model": "MODEL-1"}]
        with patch.object(service, "_query_lsblk", return_value=identity_rows) as query:
            result = service.collect()

        self.assertEqual(result, [cached_disk])
        query.assert_called_once_with(service._SIGNATURE_COLUMNS)
        cache.save.assert_not_called()

    def test_stale_cache_rebuilds_and_saves_inventory(self) -> None:
        cache = Mock()
        cache.get_signature.side_effect = ["old-signature", "new-signature"]
        cache.is_valid.return_value = False
        service = InventoryService(cache=cache)
        identity_rows = [{"type": "disk", "serial": "SERIAL-1", "model": "MODEL-1"}]
        inventory_rows = [
            {
                "name": "sda",
                "type": "disk",
                "model": "ST1000NM0011",
                "vendor": "",
                "serial": "SERIAL-1",
                "size": 1_000_204_886_016,
                "rota": 1,
                "tran": "sas",
            }
        ]

        with patch.object(service, "_query_lsblk", side_effect=[identity_rows, inventory_rows]) as query:
            result = service.collect()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].serial, "SERIAL-1")
        self.assertEqual(query.call_count, 2)
        cache.save.assert_called_once_with(result, "new-signature")

    def test_lsblk_error_with_valid_cache_returns_cached_disks(self) -> None:
        cached_disks = [Disk(serial="SERIAL-CACHED", device="/dev/sda")]
        cache = Mock()
        cache.load.return_value = cached_disks
        service = InventoryService(cache=cache)

        with patch.object(service, "_query_lsblk", side_effect=StorageError("temporary failure")):
            result = service.collect()

        self.assertEqual(result, cached_disks)
        cache.save.assert_not_called()
        cache.invalidate.assert_not_called()

    def test_lsblk_error_without_cache_raises_storage_error(self) -> None:
        cache = Mock()
        cache.load.return_value = None
        service = InventoryService(cache=cache)

        with patch.object(service, "_query_lsblk", side_effect=StorageError("temporary failure")):
            with self.assertRaises(StorageError):
                service.collect()

        cache.save.assert_not_called()
        cache.invalidate.assert_not_called()

    def test_successful_empty_lsblk_response_is_not_an_error(self) -> None:
        cache = Mock()
        cache.get_signature.side_effect = ["empty-signature", "empty-signature"]
        cache.is_valid.return_value = False
        service = InventoryService(cache=cache)

        with patch.object(service, "_query_lsblk", side_effect=[[], []]) as query:
            result = service.collect()

        self.assertEqual(result, [])
        self.assertEqual(query.call_count, 2)
        cache.save.assert_called_once_with([], "empty-signature")

    def test_cache_is_not_overwritten_when_full_inventory_query_fails(self) -> None:
        cached_disks = [Disk(serial="OLD", device="/dev/sda")]
        cache = Mock()
        cache.get_signature.return_value = "changed-signature"
        cache.is_valid.return_value = False
        cache.load.return_value = cached_disks
        service = InventoryService(cache=cache)

        with patch.object(
            service,
            "_query_lsblk",
            side_effect=[[{"type": "disk", "serial": "NEW", "model": "MODEL"}], StorageError("failure")],
        ):
            result = service.collect()

        self.assertEqual(result, cached_disks)
        cache.save.assert_not_called()
        cache.invalidate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
