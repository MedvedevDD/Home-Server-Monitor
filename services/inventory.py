"""Disk inventory orchestration with resilient persistent cache support."""

from __future__ import annotations

import json

import config
import subprocess
from typing import Any

from exceptions import StorageError
from models.disk import Disk
from services.device_classifier import DeviceClass, DeviceClassifier
from services.disk_factory import DiskFactory
from services.inventory_cache import InventoryCache
from services.logger import get_logger


logger = get_logger(__name__)


class InventoryService:
    """Return physical disk inventory while preserving the last valid cache.

    If the initial ``lsblk`` check fails, the service returns the last valid
    cached inventory. If no valid cache exists, :class:`StorageError` is raised.
    A command or JSON parsing failure is never represented by an empty list;
    ``[]`` only means that a successful query found no physical disks.
    """

    _SIGNATURE_COLUMNS = "NAME,TYPE,MODEL,VENDOR,SERIAL,TRAN,RM,ROTA,HOTPLUG"
    _INVENTORY_COLUMNS = "NAME,TYPE,MODEL,VENDOR,SERIAL,SIZE,ROTA,TRAN,RM,HOTPLUG"

    def __init__(self, cache: InventoryCache | None = None) -> None:
        """Create an inventory service using the supplied cache service."""
        self.cache = cache or InventoryCache()

    def collect(self) -> list[Disk]:
        """Return current physical disks, using the cache during probe errors."""
        try:
            identity_rows = self._query_lsblk(self._SIGNATURE_COLUMNS)
        except StorageError as exc:
            return self._load_cache_after_error(exc)

        current_signature = self.cache.get_signature(identity_rows)
        if self.cache.is_valid(current_signature):
            cached_disks = self.cache.load()
            if cached_disks is not None:
                logger.debug("Disk inventory loaded from cache")
                return cached_disks

        try:
            inventory_rows = self._query_lsblk(self._INVENTORY_COLUMNS)
        except StorageError as exc:
            return self._load_cache_after_error(exc)

        inventory_rows = [row for row in inventory_rows if self._include_device(row)]
        disks = [DiskFactory.from_lsblk(row) for row in inventory_rows]
        inventory_signature = self.cache.get_signature(disks)
        self.cache.save(disks, inventory_signature)
        logger.debug("Disk inventory rebuilt and cached")
        return disks


    @staticmethod
    def _include_device(row: dict[str, Any]) -> bool:
        """Apply stable storage exclusions without relying on /dev/sdX names."""
        serial = str(row.get("serial") or "").strip().casefold()
        model = str(row.get("model") or "").strip().casefold()
        device_class = DeviceClassifier.classify(row)

        if serial and serial in config.STORAGE_EXCLUDE_SERIALS:
            return False
        if model and any(pattern in model for pattern in config.STORAGE_EXCLUDE_MODELS):
            return False
        if config.STORAGE_HIDE_USB_FLASH and device_class == DeviceClass.USB_FLASH:
            return False
        return device_class not in {
            DeviceClass.CDROM,
            DeviceClass.LOOP,
            DeviceClass.RAM,
            DeviceClass.ZRAM,
        }

    def _load_cache_after_error(self, error: StorageError) -> list[Disk]:
        """Return the last valid cache or re-raise a documented fatal error."""
        cached_disks = self.cache.load()
        if cached_disks is not None:
            logger.warning(
                "lsblk inventory check failed; using the last valid cache: %s",
                error,
            )
            return cached_disks

        logger.error("lsblk inventory check failed and no valid cache is available: %s", error)
        raise StorageError(
            "Unable to query disk inventory and no valid inventory cache is available"
        ) from error

    def _query_lsblk(self, columns: str) -> list[dict[str, Any]]:
        """Run ``lsblk`` and return physical disk rows.

        Raises:
            StorageError: If command execution, text decoding, JSON parsing, or
                response structure validation fails.
        """
        command = [
            "lsblk",
            "--json",
            "--nodeps",
            "--bytes",
            "--output",
            columns,
        ]

        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            payload = json.loads(completed.stdout)
        except (OSError, subprocess.CalledProcessError, UnicodeError, json.JSONDecodeError) as exc:
            raise StorageError(f"Unable to obtain disk inventory with lsblk: {exc}") from exc

        if not isinstance(payload, dict):
            raise StorageError("lsblk returned a JSON document that is not an object")

        devices = payload.get("blockdevices")
        if not isinstance(devices, list):
            raise StorageError("lsblk JSON does not contain a blockdevices list")

        return [
            item
            for item in devices
            if isinstance(item, dict) and item.get("type") == "disk"
        ]
