"""Read-only Proxmox host collection."""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
from pathlib import Path

from models.proxmox_host import ProxmoxHostStatus


class ProxmoxHostCollectionError(RuntimeError):
    """Raised when required host data cannot be collected."""


class ProxmoxHostCollector:
    """Collect lightweight host metrics from procfs and pveversion."""

    def __init__(self, sample_interval: float = 0.10) -> None:
        self.sample_interval = sample_interval

    @staticmethod
    def _read_text(path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ProxmoxHostCollectionError(f"Cannot read {path}: {exc}") from exc

    @staticmethod
    def _cpu_times() -> tuple[int, int]:
        line = ProxmoxHostCollector._read_text("/proc/stat").splitlines()[0]
        parts = line.split()
        if not parts or parts[0] != "cpu" or len(parts) < 5:
            raise ProxmoxHostCollectionError("Invalid /proc/stat CPU line")
        values = [int(value) for value in parts[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle

    def _cpu_usage_percent(self) -> float:
        total1, idle1 = self._cpu_times()
        time.sleep(max(0.0, self.sample_interval))
        total2, idle2 = self._cpu_times()
        delta_total = total2 - total1
        delta_idle = idle2 - idle1
        if delta_total <= 0:
            return 0.0
        return round(max(0.0, min(100.0, 100.0 * (delta_total - delta_idle) / delta_total)), 2)

    @staticmethod
    def _meminfo() -> dict[str, int]:
        values: dict[str, int] = {}
        for line in ProxmoxHostCollector._read_text("/proc/meminfo").splitlines():
            name, separator, remainder = line.partition(":")
            if not separator:
                continue
            parts = remainder.strip().split()
            if not parts:
                continue
            try:
                value = int(parts[0])
            except ValueError:
                continue
            values[name] = value * 1024 if len(parts) > 1 and parts[1].lower() == "kb" else value
        return values

    @staticmethod
    def _cpu_model() -> str:
        for line in ProxmoxHostCollector._read_text("/proc/cpuinfo").splitlines():
            if line.lower().startswith("model name"):
                return line.partition(":")[2].strip() or "unknown"
        return platform.processor() or "unknown"

    @staticmethod
    def _pve_version(binary: str) -> str:
        try:
            result = subprocess.run(
                [binary], text=True, capture_output=True, timeout=10, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProxmoxHostCollectionError(f"Cannot run {binary}: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            raise ProxmoxHostCollectionError(f"{binary} failed: {detail}")
        output = result.stdout.strip().splitlines()
        return output[0].strip() if output else "unknown"

    def collect(self, pveversion_binary: str = "pveversion") -> ProxmoxHostStatus:
        mem = self._meminfo()
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", mem.get("MemFree", 0))
        used = max(0, total - available)
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = max(0, swap_total - swap_free)
        try:
            uptime = float(self._read_text("/proc/uptime").split()[0])
            load1, load5, load15 = (float(value) for value in self._read_text("/proc/loadavg").split()[:3])
        except (ValueError, IndexError) as exc:
            raise ProxmoxHostCollectionError(f"Invalid procfs host data: {exc}") from exc

        host = socket.gethostname() or "unknown"
        return ProxmoxHostStatus(
            host=host,
            node=host.split(".", 1)[0],
            pve_version=self._pve_version(pveversion_binary),
            kernel_version=platform.release() or "unknown",
            cpu_model=self._cpu_model(),
            cpu_count=os.cpu_count() or 1,
            uptime_seconds=uptime,
            cpu_usage_percent=self._cpu_usage_percent(),
            load1=load1,
            load5=load5,
            load15=load15,
            memory_total_bytes=total,
            memory_available_bytes=available,
            memory_used_bytes=used,
            memory_used_percent=round((100.0 * used / total) if total else 0.0, 2),
            swap_total_bytes=swap_total,
            swap_free_bytes=swap_free,
            swap_used_bytes=swap_used,
            swap_used_percent=round((100.0 * swap_used / swap_total) if swap_total else 0.0, 2),
        )
