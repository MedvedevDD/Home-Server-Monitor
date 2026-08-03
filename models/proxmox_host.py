"""Normalized Proxmox host data."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProxmoxHostStatus:
    """One Proxmox host snapshot."""

    host: str
    node: str
    pve_version: str
    kernel_version: str
    cpu_model: str
    cpu_count: int
    uptime_seconds: float
    cpu_usage_percent: float
    load1: float
    load5: float
    load15: float
    memory_total_bytes: int
    memory_available_bytes: int
    memory_used_bytes: int
    memory_used_percent: float
    swap_total_bytes: int
    swap_free_bytes: int
    swap_used_bytes: int
    swap_used_percent: float
