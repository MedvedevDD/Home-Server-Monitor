"""Human-readable formatting for storage capacities."""

from __future__ import annotations


class SizeFormatter:
    """Format decimal disk capacities using common manufacturer nominal sizes."""

    _BYTES_PER_GB = 1_000_000_000
    _BYTES_PER_TB = 1_000_000_000_000
    _NOMINAL_GB = (120, 128, 240, 250, 256, 300, 320, 400, 480, 500, 512, 600, 640, 750, 800, 960)
    _NOMINAL_TB = (1, 2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24)
    _NOMINAL_TOLERANCE = 0.02

    @classmethod
    def format(cls, size: int | str | None) -> str:
        """Return a concise nominal capacity such as ``1 TB`` or ``500 GB``."""
        try:
            size_bytes = int(size or 0)
        except (TypeError, ValueError):
            return ""

        if size_bytes <= 0:
            return ""

        nominal = cls._find_nominal(size_bytes)
        if nominal is not None:
            value, unit = nominal
            return f"{value} {unit}"

        if size_bytes >= cls._BYTES_PER_TB:
            value = size_bytes / cls._BYTES_PER_TB
            return f"{value:.1f} TB"
        if size_bytes >= cls._BYTES_PER_GB:
            value = size_bytes / cls._BYTES_PER_GB
            return f"{value:.1f} GB"
        if size_bytes >= 1_000_000:
            return f"{size_bytes / 1_000_000:.1f} MB"
        if size_bytes >= 1_000:
            return f"{size_bytes / 1_000:.1f} KB"
        return f"{size_bytes} B"

    @classmethod
    def _find_nominal(cls, size_bytes: int) -> tuple[int, str] | None:
        candidates = [
            *((value * cls._BYTES_PER_GB, value, "GB") for value in cls._NOMINAL_GB),
            *((value * cls._BYTES_PER_TB, value, "TB") for value in cls._NOMINAL_TB),
        ]
        expected_bytes, value, unit = min(candidates, key=lambda item: abs(size_bytes - item[0]))
        relative_difference = abs(size_bytes - expected_bytes) / expected_bytes
        if relative_difference <= cls._NOMINAL_TOLERANCE:
            return value, unit
        return None
