"""Read-only Proxmox storage collection through a restricted root helper."""

from __future__ import annotations

import json
import subprocess

from models.proxmox_storage import ProxmoxStorageStatus


class ProxmoxStorageCollectionError(RuntimeError):
    """Raised when Proxmox storage data cannot be collected."""


def storage_health(active: bool, enabled: bool, used_percent: float) -> tuple[int, str]:
    if not enabled or not active:
        return 3, "UNAVAILABLE"
    if used_percent >= 95.0:
        return 3, "CRITICAL"
    if used_percent >= 90.0:
        return 2, "HIGH"
    if used_percent >= 80.0:
        return 1, "WARNING"
    return 0, "OK"


class ProxmoxStorageCollector:
    """Collect storage status from the local Proxmox API."""

    def __init__(self, helper_binary: str = "/usr/local/libexec/hsm-proxmox-storage-helper", timeout: int = 15) -> None:
        self.helper_binary = helper_binary
        self.timeout = timeout

    def collect(self, node: str | None = None) -> list[ProxmoxStorageStatus]:
        node = node or "unknown"
        command = ["sudo", "-n", self.helper_binary]
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProxmoxStorageCollectionError(f"Cannot run storage helper: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            raise ProxmoxStorageCollectionError(f"storage helper failed: {detail}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ProxmoxStorageCollectionError(f"Invalid storage helper JSON: {exc}") from exc
        if not isinstance(payload, list):
            raise ProxmoxStorageCollectionError("Unexpected storage helper response")

        items: list[ProxmoxStorageStatus] = []
        for raw in payload:
            if not isinstance(raw, dict) or not raw.get("storage"):
                continue
            total = max(0, int(raw.get("total", 0) or 0))
            used = max(0, int(raw.get("used", 0) or 0))
            avail = max(0, int(raw.get("avail", 0) or 0))
            fraction = raw.get("used_fraction")
            try:
                percent = float(fraction) * 100.0 if fraction is not None else (100.0 * used / total if total else 0.0)
            except (TypeError, ValueError):
                percent = 100.0 * used / total if total else 0.0
            percent = round(max(0.0, min(100.0, percent)), 2)
            active = bool(int(raw.get("active", 0) or 0))
            enabled = bool(int(raw.get("enabled", 0) or 0))
            code, status = storage_health(active, enabled, percent)
            items.append(ProxmoxStorageStatus(
                node=node, storage=str(raw["storage"]), storage_type=str(raw.get("type", "unknown")),
                content=str(raw.get("content", "")), active=active, enabled=enabled,
                shared=bool(int(raw.get("shared", 0) or 0)), total_bytes=total, used_bytes=used,
                available_bytes=avail, used_percent=percent, health_code=code, health_status=status,
            ))
        return items
