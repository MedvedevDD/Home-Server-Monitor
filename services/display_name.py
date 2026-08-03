"""Human-readable disk display name construction."""

from __future__ import annotations


class DisplayNameBuilder:
    """Build a compact display name from existing inventory values."""

    @staticmethod
    def build(vendor: str, model: str, size: str) -> str:
        """Join vendor, model, and size without duplicating the vendor name."""
        normalized_vendor = (vendor or "").strip()
        normalized_model = (model or "").strip()
        normalized_size = (size or "").strip()

        components: list[str] = []
        if normalized_vendor and not normalized_model.casefold().startswith(normalized_vendor.casefold()):
            components.append(normalized_vendor)
        if normalized_model:
            components.append(normalized_model)
        if normalized_size:
            components.append(normalized_size)

        return " ".join(components)
