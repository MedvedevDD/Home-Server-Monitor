"""Stable storage device classification based on lsblk metadata."""

from __future__ import annotations

from typing import Any, Mapping


class DeviceClass:
    """Canonical storage device classes used by inventory filtering."""

    HDD = "HDD"
    SSD = "SSD"
    NVME = "NVME"
    SAS = "SAS"
    USB_HDD = "USB_HDD"
    USB_SSD = "USB_SSD"
    USB_FLASH = "USB_FLASH"
    CDROM = "CDROM"
    LOOP = "LOOP"
    RAM = "RAM"
    ZRAM = "ZRAM"
    UNKNOWN = "UNKNOWN"


class DeviceClassifier:
    """Classify block devices without relying on unstable /dev/sdX names."""

    @staticmethod
    def classify(info: Mapping[str, Any]) -> str:
        name = DeviceClassifier._text(info.get("name")).casefold()
        device_type = DeviceClassifier._text(info.get("type")).casefold()
        transport = DeviceClassifier._text(info.get("tran")).casefold()
        model = DeviceClassifier._text(info.get("model")).casefold()
        vendor = DeviceClassifier._text(info.get("vendor")).casefold()
        removable = DeviceClassifier._bool(info.get("rm"))
        rotational = DeviceClassifier._optional_bool(info.get("rota"))

        if device_type == "rom":
            return DeviceClass.CDROM
        if device_type == "loop" or name.startswith("loop"):
            return DeviceClass.LOOP
        if name.startswith("zram"):
            return DeviceClass.ZRAM
        if name.startswith("ram"):
            return DeviceClass.RAM
        if name.startswith("nvme") or transport == "nvme":
            return DeviceClass.NVME

        if transport == "usb":
            # RM=1 is the strongest generic lsblk signal for a flash drive.
            # Model/vendor heuristics cover devices whose bridge reports RM=0.
            flash_tokens = (
                "flash drive",
                "flash_disk",
                "flash disk",
                "datatraveler",
                "cruzer",
                "thumb drive",
                "usb stick",
                "pendrive",
            )
            identity = f"{vendor} {model}".strip()
            if removable or any(token in identity for token in flash_tokens):
                return DeviceClass.USB_FLASH
            if rotational is True:
                return DeviceClass.USB_HDD
            if rotational is False:
                return DeviceClass.USB_SSD
            return DeviceClass.UNKNOWN

        if transport == "sas":
            return DeviceClass.SAS
        if rotational is True:
            return DeviceClass.HDD
        if rotational is False:
            return DeviceClass.SSD
        return DeviceClass.UNKNOWN

    @staticmethod
    def _text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _bool(value: Any) -> bool:
        return value in (1, "1", True, "true", "yes", "on")

    @staticmethod
    def _optional_bool(value: Any) -> bool | None:
        if value in (1, "1", True, "true", "yes", "on"):
            return True
        if value in (0, "0", False, "false", "no", "off"):
            return False
        return None
