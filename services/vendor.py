"""Vendor resolution helpers for disk model strings."""

from __future__ import annotations


class VendorResolver:
    """Resolve a normalized vendor name from a disk model prefix."""

    UNKNOWN_VENDOR = "Unknown"

    MODEL_PREFIXES: tuple[tuple[str, str], ...] = (
        ("SAMSUNG", "Samsung"),
        ("KINGSTON", "Kingston"),
        ("CRUCIAL", "Crucial"),
        ("INTEL", "Intel"),
        ("TOSHIBA", "Toshiba"),
        ("HDWD", "Toshiba"),
        ("HDWE", "Toshiba"),
        ("HDWG", "Toshiba"),
        ("MG", "Toshiba"),
        ("DT", "Toshiba"),
        ("MQ", "Toshiba"),
        ("WDC", "Western Digital"),
        ("WD", "Western Digital"),
        ("ST", "Seagate"),
    )

    @classmethod
    def resolve(cls, model: str) -> str:
        """Return a known vendor name or ``Unknown`` for an unmatched model."""
        normalized_model = (model or "").strip().upper()
        for prefix, vendor_name in cls.MODEL_PREFIXES:
            if normalized_model.startswith(prefix):
                return vendor_name
        return cls.UNKNOWN_VENDOR
