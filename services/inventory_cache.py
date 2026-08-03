"""Persistent JSON cache for disk inventory data."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from config import CACHE_FILE, CACHE_VERSION
from models.disk import Disk
from services.disk_factory import DiskFactory
from services.logger import get_logger


logger = get_logger(__name__)


class InventoryCache:
    """Load, validate, save, and invalidate the disk inventory cache.

    Cache document format::

        {
            "version": 2,
            "generated": "2026-07-10T12:30:00Z",
            "signature": "<sha256>",
            "disks": [{...}]
        }

    ``DiskFactory`` owns conversion between ``Disk`` objects and dictionaries,
    so this service does not depend on the internal field layout of ``Disk``.
    """

    def __init__(self, cache_file: str | os.PathLike[str] = CACHE_FILE) -> None:
        """Create a cache service using ``cache_file`` as persistent storage."""
        self.cache_file = Path(cache_file).expanduser()

    def load(self) -> list[Disk] | None:
        """Load cached disks, returning ``None`` when the cache is unusable."""
        payload = self._read_payload()
        if payload is None:
            return None

        try:
            return [DiskFactory.from_dict(item) for item in payload["disks"]]
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Inventory cache contains invalid disk data: %s", exc)
            self.invalidate()
            return None

    def save(self, disks: Sequence[Disk], signature: str | None = None) -> bool:
        """Atomically save ``disks`` and their inventory signature.

        Returns ``True`` on success. Filesystem errors are logged and converted
        to ``False`` so monitoring can continue without a persistent cache.
        """
        disk_list = list(disks)
        cache_signature = signature or self.get_signature(disk_list)
        payload = {
            "version": CACHE_VERSION,
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "signature": cache_signature,
            "disks": [DiskFactory.to_dict(disk) for disk in disk_list],
        }

        temporary_path: Path | None = None
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.cache_file.name}.",
                suffix=".tmp",
                dir=self.cache_file.parent,
                text=True,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary_path, self.cache_file)
            return True
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("Unable to save inventory cache %s: %s", self.cache_file, exc)
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return False

    def invalidate(self) -> None:
        """Remove the cache file if it exists, suppressing filesystem errors."""
        try:
            self.cache_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Unable to remove inventory cache %s: %s", self.cache_file, exc)

    def is_valid(self, signature: str | None = None) -> bool:
        """Return whether the cache is structurally valid and optionally current."""
        payload = self._read_payload()
        if payload is None:
            return False
        return signature is None or payload["signature"] == signature

    def get_signature(self, disks: Iterable[Disk | Mapping[str, Any]]) -> str:
        """Return a stable SHA-256 signature for the current disk composition.

        Stable identity and classification fields participate in the signature.
        Entries are sorted so Linux device enumeration order does not matter.
        """
        identities: list[dict[str, str]] = []
        for disk in disks:
            if isinstance(disk, Disk):
                serial = disk.serial
                model = disk.model
                transport = disk.transport
                removable = disk.removable
                device_class = disk.device_class
            elif isinstance(disk, Mapping):
                serial = disk.get("serial", "")
                model = disk.get("model", "")
                transport = disk.get("tran", disk.get("transport", ""))
                removable = disk.get("rm", disk.get("removable", False))
                device_class = disk.get("device_class", "")
            else:
                raise TypeError("signature entries must be Disk objects or mappings")

            identities.append(
                {
                    "serial": self._normalize_identity_value(serial),
                    "model": self._normalize_identity_value(model),
                    "transport": self._normalize_identity_value(transport),
                    "removable": "1" if removable in (1, "1", True) else "0",
                    "device_class": self._normalize_identity_value(device_class),
                }
            )

        identities.sort(key=lambda item: (item["serial"], item["model"], item["transport"], item["removable"], item["device_class"]))
        canonical = {
            "count": len(identities),
            "disks": identities,
        }
        encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _read_payload(self) -> dict[str, Any] | None:
        if not self.cache_file.is_file():
            return None

        try:
            with self.cache_file.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Inventory cache %s cannot be read: %s", self.cache_file, exc)
            self.invalidate()
            return None

        if not self._validate_payload(payload):
            logger.warning("Inventory cache %s is invalid or obsolete", self.cache_file)
            self.invalidate()
            return None

        return payload

    @staticmethod
    def _validate_payload(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return False
        if payload.get("version") != CACHE_VERSION:
            return False
        if not isinstance(payload.get("generated"), str) or not payload["generated"]:
            return False
        signature = payload.get("signature")
        if not isinstance(signature, str) or len(signature) != 64:
            return False
        if any(character not in "0123456789abcdef" for character in signature.lower()):
            return False
        disks = payload.get("disks")
        return isinstance(disks, list) and all(isinstance(item, dict) for item in disks)

    @staticmethod
    def _normalize_identity_value(value: Any) -> str:
        return "" if value is None else str(value).strip().casefold()
