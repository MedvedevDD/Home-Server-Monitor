"""Normalized Proxmox storage data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProxmoxStorageStatus:
    """One Proxmox storage snapshot."""

    node: str
    storage: str
    storage_type: str
    content: str
    active: bool
    enabled: bool
    shared: bool
    total_bytes: int
    used_bytes: int
    available_bytes: int
    used_percent: float
    health_code: int
    health_status: str
