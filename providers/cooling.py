"""Cooling provider runtime adapter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import config
from core.discovery import Capability, ProviderDiscovery
from core.provider import Provider
from core.result import ProviderMessage, ProviderResult
from metric import Metric
from models.cooling import CoolingStatus


class CoolingProvider(Provider):
    name = "cooling"
    version = "1"
    domain = "cooling"
    capabilities = ("x8fan", "fan-rpm", "pwm", "hdd-temperature-control")

    def __init__(
        self,
        collect_status: Callable[[], CoolingStatus],
        status_metric: Callable[[CoolingStatus], Metric],
        fan_metrics: Callable[[CoolingStatus], list[Metric]],
        required: bool,
    ) -> None:
        self.collect_status = collect_status
        self.status_metric = status_metric
        self.fan_metrics = fan_metrics
        self.required = required

    def discover(self) -> ProviderDiscovery:
        helper = Path(config.COOLING_X8FAN_HELPER)
        available = helper.is_file()
        return ProviderDiscovery(
            provider=self.name,
            domain=self.domain,
            capabilities=[
                Capability(name, available=available, detail=str(helper))
                for name in self.capabilities
            ],
            detail="" if available else f"x8fan helper unavailable: {helper}",
        )

    def collect(self) -> ProviderResult:
        result = ProviderResult(provider=self.name)
        try:
            status = self.collect_status()
            result.metrics.append(self.status_metric(status))
            result.metrics.extend(self.fan_metrics(status))
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            message = ProviderMessage(self.name, f"Cooling collection failed: {exc}")
            (result.errors if self.required else result.warnings).append(message)
        return result
