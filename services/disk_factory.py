"""Creation and serialization helpers for :class:`models.disk.Disk`."""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Mapping

from models.disk import Disk
from services.device_classifier import DeviceClass, DeviceClassifier
from services.display_name import DisplayNameBuilder
from services.size_formatter import SizeFormatter
from services.vendor import VendorResolver


class DiskFactory:
    """Create ``Disk`` objects from inventory sources and cached dictionaries."""

    _DISK_FIELD_NAMES = frozenset(field.name for field in fields(Disk))

    @staticmethod
    def from_lsblk(info: Mapping[str, Any]) -> Disk:
        """Create a ``Disk`` from one normalized ``lsblk`` device mapping."""
        model = DiskFactory._clean_text(info.get("model"))
        reported_vendor = DiskFactory._clean_text(info.get("vendor"))
        vendor = reported_vendor or VendorResolver.resolve(model)
        if vendor.lower() in {"ata", "unknown"}:
            vendor = VendorResolver.resolve(model)

        capacity_bytes = DiskFactory._as_non_negative_int(info.get("size"))
        capacity = SizeFormatter.format(capacity_bytes)
        device_name = DiskFactory._clean_text(info.get("name"))
        device_class = DeviceClassifier.classify(info)
        disk_type = DiskFactory._resolve_disk_type(info, device_class)
        transport = DiskFactory._resolve_transport(info, disk_type, reported_vendor)

        return Disk(
            serial=DiskFactory._clean_text(info.get("serial")),
            vendor=vendor or "Unknown",
            model=model,
            display_name=DisplayNameBuilder.build(vendor or "Unknown", model, capacity),
            capacity=capacity,
            capacity_bytes=capacity_bytes,
            disk_type=disk_type,
            transport=transport,
            device=f"/dev/{device_name}" if device_name else "",
            device_class=device_class,
            removable=info.get("rm") in (1, "1", True),
            hotplug=info.get("hotplug") in (1, "1", True),
        )

    @staticmethod
    def to_dict(disk: Disk) -> dict[str, Any]:
        """Serialize a ``Disk`` into a JSON-compatible dictionary."""
        if not isinstance(disk, Disk):
            raise TypeError("disk must be an instance of Disk")

        return {field_name: getattr(disk, field_name) for field_name in DiskFactory._DISK_FIELD_NAMES}

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> Disk:
        """Restore a ``Disk`` from a dictionary produced by :meth:`to_dict`."""
        if not isinstance(data, Mapping):
            raise TypeError("data must be a mapping")

        values = {name: data[name] for name in DiskFactory._DISK_FIELD_NAMES if name in data}
        return Disk(**values)

    @staticmethod
    def _clean_text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _as_non_negative_int(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)

    @staticmethod
    def _resolve_disk_type(info: Mapping[str, Any], device_class: str = DeviceClass.UNKNOWN) -> str:
        name = DiskFactory._clean_text(info.get("name")).lower()
        transport = DiskFactory._clean_text(info.get("tran")).lower()
        rotational = info.get("rota")

        if transport == "usb":
            return "USB"
        if name.startswith("nvme") or transport == "nvme":
            return "NVMe"
        if rotational in (1, "1", True):
            return "HDD"
        if rotational in (0, "0", False):
            return "SSD"
        return "Unknown"

    @staticmethod
    def _resolve_transport(
        info: Mapping[str, Any],
        disk_type: str,
        reported_vendor: str,
    ) -> str:
        transport = DiskFactory._clean_text(info.get("tran")).lower()
        mapping = {
            "ata": "ATA",
            "sata": "SATA",
            "sas": "SAS",
            "nvme": "NVMe",
            "usb": "USB",
        }
        if transport in mapping:
            return mapping[transport]
        if disk_type == "NVMe":
            return "NVMe"
        if not transport and reported_vendor.casefold() == "ata":
            return "ATA"
        return "Unknown"
