"""RAID provider runtime adapter."""

from __future__ import annotations

from collections.abc import Callable

from core.provider import Provider
from core.result import ProviderMessage, ProviderResult
from metric import Metric
from models.raid import RaidArrayStatus, RaidControllerStatus, RaidDriveStatus

RaidCollection = tuple[list[RaidControllerStatus], list[RaidArrayStatus], list[RaidDriveStatus]]


class RaidProvider(Provider):
    """Collect controller, array, and physical-drive RAID metrics."""

    name = "raid"
    version = "1"
    domain = "hardware"
    capabilities = ("megaraid", "storcli", "controllers", "arrays", "physical-drives")

    def __init__(
        self,
        collect_status: Callable[[], RaidCollection],
        controller_metric: Callable[[RaidControllerStatus], Metric],
        array_metric: Callable[[RaidArrayStatus], Metric],
        drive_metric: Callable[[RaidDriveStatus], Metric],
        required: bool,
    ) -> None:
        self.collect_status = collect_status
        self.controller_metric = controller_metric
        self.array_metric = array_metric
        self.drive_metric = drive_metric
        self.required = required

    def collect(self) -> ProviderResult:
        result = ProviderResult(provider=self.name)
        try:
            controllers, arrays, drives = self.collect_status()
            result.metrics.extend(self.controller_metric(item) for item in controllers)
            result.metrics.extend(self.array_metric(item) for item in arrays)
            result.metrics.extend(self.drive_metric(item) for item in drives)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            message = ProviderMessage(self.name, f"RAID collection failed: {exc}")
            (result.errors if self.required else result.warnings).append(message)
        return result
