"""Project configuration constants."""

from __future__ import annotations

import os
from pathlib import Path




def _load_environment_file(path: Path) -> None:
    """Load simple KEY=VALUE defaults without overriding process environment."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or name in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        os.environ[name] = value


_load_environment_file(
    Path(os.environ.get("HSM_ENV_FILE", "/etc/default/home-server-monitor"))
)

def _environment_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _environment_controller_devices() -> dict[int, str]:
    """Parse controller mappings such as 0=/dev/sda,1=/dev/sdb."""
    result: dict[int, str] = {}
    raw = os.environ.get("HSM_MEGARAID_CONTROL_DEVICES", "").strip()
    if raw:
        for item in raw.split(","):
            controller_text, separator, device = item.strip().partition("=")
            if not separator or not controller_text.strip() or not device.strip():
                raise ValueError(
                    "HSM_MEGARAID_CONTROL_DEVICES must use controller=/dev/path entries"
                )
            try:
                controller_id = int(controller_text.strip())
            except ValueError as exc:
                raise ValueError(
                    "HSM_MEGARAID_CONTROL_DEVICES controller IDs must be integers"
                ) from exc
            result[controller_id] = device.strip()
    return result


CACHE_VERSION = 3
CACHE_FILE = Path(
    os.environ.get(
        "HSM_CACHE_FILE",
        "/var/cache/home-server-monitor/storage_inventory.json",
    )
).expanduser()
CACHE_DIR = CACHE_FILE.parent

SMART_USE_SUDO = _environment_bool("HSM_SMART_USE_SUDO", False)
STORCLI_USE_SUDO = _environment_bool("HSM_STORCLI_USE_SUDO", False)
SMARTCTL_BINARY = os.environ.get("HSM_SMARTCTL_BINARY", "smartctl")
STORCLI_BINARY = os.environ.get("HSM_STORCLI_BINARY", "storcli")
MEGARAID_CONTROL_DEVICE = os.environ.get("HSM_MEGARAID_CONTROL_DEVICE", "").strip()
MEGARAID_CONTROL_DEVICES = _environment_controller_devices()
SMARTCTL_TIMEOUT_SECONDS = 30
STORCLI_TIMEOUT_SECONDS = 30
SMART_SUPPORTED_TRANSPORTS = frozenset({"ATA", "SATA"})

STORAGE_HIDE_USB_FLASH = _environment_bool("HSM_STORAGE_HIDE_USB_FLASH", True)
STORAGE_EXCLUDE_SERIALS = frozenset(
    value.strip().casefold()
    for value in os.environ.get("HSM_STORAGE_EXCLUDE_SERIALS", "").split(",")
    if value.strip()
)
STORAGE_EXCLUDE_MODELS = tuple(
    value.strip().casefold()
    for value in os.environ.get("HSM_STORAGE_EXCLUDE_MODELS", "").split(",")
    if value.strip()
)

UPS_ENABLED = _environment_bool("HSM_UPS_ENABLED", True)
UPS_REQUIRED = _environment_bool("HSM_UPS_REQUIRED", False)
UPS_NAME = os.environ.get("HSM_UPS_NAME", "ippon").strip()
UPSC_BINARY = os.environ.get("HSM_UPSC_BINARY", "upsc")
UPSC_TIMEOUT_SECONDS = 15
UPS_BATTERY_EMPTY_VOLTAGE = float(
    os.environ.get("HSM_UPS_BATTERY_EMPTY_VOLTAGE", "42.0")
)
UPS_BATTERY_FULL_VOLTAGE = float(
    os.environ.get("HSM_UPS_BATTERY_FULL_VOLTAGE", "54.4")
)

RAID_ENABLED = _environment_bool("HSM_RAID_ENABLED", True)
RAID_REQUIRED = _environment_bool("HSM_RAID_REQUIRED", False)
RAID_STORCLI_ENABLED = _environment_bool("HSM_RAID_STORCLI_ENABLED", True)
RAID_SSACLI_ENABLED = _environment_bool("HSM_RAID_SSACLI_ENABLED", True)
SSACLI_HELPER = os.environ.get(
    "HSM_SSACLI_HELPER",
    "/usr/local/libexec/hsm-hp-smartarray-helper",
).strip()
SSACLI_USE_SUDO = _environment_bool("HSM_SSACLI_USE_SUDO", True)
SSACLI_TIMEOUT_SECONDS = 15
RAID_TWCLI_ENABLED = _environment_bool("HSM_RAID_TWCLI_ENABLED", True)
TWCLI_BINARY = os.environ.get("HSM_TWCLI_BINARY", "tw_cli")
TWCLI_USE_SUDO = _environment_bool("HSM_TWCLI_USE_SUDO", False)
TWCLI_TIMEOUT_SECONDS = 30

PROXMOX_ENABLED = _environment_bool("HSM_PROXMOX_ENABLED", True)
PROXMOX_REQUIRED = _environment_bool("HSM_PROXMOX_REQUIRED", False)
PVEVERSION_BINARY = os.environ.get("HSM_PVEVERSION_BINARY", "pveversion")
PROXMOX_CPU_SAMPLE_SECONDS = float(os.environ.get("HSM_PROXMOX_CPU_SAMPLE_SECONDS", "0.10"))
