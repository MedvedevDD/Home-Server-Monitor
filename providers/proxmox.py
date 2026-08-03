"""Proxmox host and storage provider."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from core.discovery import Availability, Capability, ProviderDiscovery
from core.provider import Provider
from core.result import ProviderMessage, ProviderResult
from metric import Metric
from models.proxmox_host import ProxmoxHostStatus
from models.proxmox_storage import ProxmoxStorageStatus
from services.proxmox_host import ProxmoxHostCollectionError
from services.proxmox_storage import ProxmoxStorageCollectionError


class ProxmoxProvider(Provider):
    """Collect read-only Proxmox host and storage metrics."""

    name = "proxmox"
    version = "2"
    domain = "platform"
    capabilities = ("proxmox", "host", "cpu", "memory", "swap", "load-average", "storage", "dir-storage", "lvmthin-storage")

    def __init__(self, collect_status: Callable[[], ProxmoxHostStatus], info_metric: Callable[[ProxmoxHostStatus], Metric],
                 status_metric: Callable[[ProxmoxHostStatus], Metric], collect_storage: Callable[[str], list[ProxmoxStorageStatus]] | None = None,
                 storage_metric: Callable[[ProxmoxStorageStatus], Metric] | None = None, pveversion_binary: str = "pveversion",
                 pvesh_binary: str = "pvesh", required: bool = False) -> None:
        self.collect_status = collect_status
        self.info_metric = info_metric
        self.status_metric = status_metric
        self.collect_storage = collect_storage or (lambda _node: [])
        self.storage_metric = storage_metric or (lambda _item: Metric("proxmox_storage", fields={"present": True}))
        self.pveversion_binary = pveversion_binary
        self.pvesh_binary = pvesh_binary
        self.required = required

    def discover(self) -> ProviderDiscovery:
        pve = shutil.which(self.pveversion_binary) is not None or Path(self.pveversion_binary).is_file()
        pvesh = shutil.which(self.pvesh_binary) is not None or Path(self.pvesh_binary).is_file()
        if not pve:
            return ProviderDiscovery(provider=self.name, domain=self.domain, availability=Availability.ERROR if self.required else Availability.UNAVAILABLE,
                capabilities=[Capability(name=item, available=False) for item in self.capabilities], detail=f"pveversion not found: {self.pveversion_binary}")
        caps = [Capability(name=item, available=(pvesh or item not in {"storage", "dir-storage", "lvmthin-storage"}),
                           detail="pvesh not found" if not pvesh and item in {"storage", "dir-storage", "lvmthin-storage"} else "") for item in self.capabilities]
        return ProviderDiscovery(provider=self.name, domain=self.domain, availability=Availability.READY, capabilities=caps,
                                 detail="" if pvesh else "host metrics only; pvesh unavailable")

    def collect(self) -> ProviderResult:
        result = ProviderResult(provider=self.name)
        try:
            status = self.collect_status()
        except (ProxmoxHostCollectionError, OSError, ValueError, TypeError) as exc:
            message = ProviderMessage(self.name, f"Proxmox host collection failed: {exc}")
            (result.errors if self.required else result.warnings).append(message)
            return result
        result.metrics.extend((self.info_metric(status), self.status_metric(status)))
        try:
            stores = self.collect_storage(status.node)
            result.metrics.extend(self.storage_metric(item) for item in stores)
        except (ProxmoxStorageCollectionError, OSError, ValueError, TypeError) as exc:
            result.warnings.append(ProviderMessage(self.name, f"Proxmox storage collection failed: {exc}"))
        return result
