"""Storage provider runtime adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from core.provider import Provider
from core.result import ProviderMessage, ProviderResult
from exceptions import CollectorError
from metric import Metric
from models.disk import Disk
from models.disk_health import DiskHealth
from services.raid_discovery import RaidDiscoveryResult, RaidDiscoveryService
from services.smart import SmartctlUnavailableError


class StorageProvider(Provider):
    """Collect OS-visible disk inventory, SMART data, and storage status."""

    name = "storage"
    version = "1"
    domain = "hardware"
    capabilities = ("inventory", "smart", "sata", "nvme", "usb-filtering")

    def __init__(
        self,
        inventory_collect: Callable[[], list[Disk]],
        discovery_service_factory: Callable[[], RaidDiscoveryService],
        smart_collect: Callable[[RaidDiscoveryService, list[Disk]], list[DiskHealth]],
        visible_disks: Callable[[Iterable[Disk], Iterable[DiskHealth], RaidDiscoveryResult | None], list[Disk]],
        visible_health: Callable[[Iterable[Disk], Iterable[DiskHealth]], list[DiskHealth]],
        inventory_metrics: Callable[[Iterable[Disk]], list[Metric]],
        health_metrics: Callable[[Iterable[Disk], Iterable[DiskHealth]], list[Metric]],
        status_metrics: Callable[[Iterable[Disk], Iterable[DiskHealth]], list[Metric]],
    ) -> None:
        self.inventory_collect = inventory_collect
        self.discovery_service_factory = discovery_service_factory
        self.smart_collect = smart_collect
        self.visible_disks = visible_disks
        self.visible_health = visible_health
        self.inventory_metrics = inventory_metrics
        self.health_metrics = health_metrics
        self.status_metrics = status_metrics

    def collect(self) -> ProviderResult:
        result = ProviderResult(provider=self.name)
        try:
            disks = self.inventory_collect()
        except (CollectorError, OSError, ValueError, TypeError) as exc:
            result.errors.append(ProviderMessage(self.name, f"Storage inventory collection failed: {exc}"))
            return result

        discovery_service = self.discovery_service_factory()
        discovery = discovery_service.discover(disks)
        try:
            health = self.smart_collect(discovery_service, disks)
        except SmartctlUnavailableError as exc:
            visible = self.visible_disks(disks, [], discovery)
            result.metrics.extend(self.inventory_metrics(visible))
            result.errors.append(ProviderMessage(self.name, f"SMART collection cannot start: {exc}"))
            return result

        visible = self.visible_disks(disks, health, discovery)
        visible_health = self.visible_health(visible, health)
        result.metrics.extend(self.inventory_metrics(visible))
        result.metrics.extend(self.health_metrics(visible, visible_health))
        result.metrics.extend(self.status_metrics(visible, visible_health))
        return result
