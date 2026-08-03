"""UPS provider runtime adapter."""

from __future__ import annotations

from collections.abc import Callable

from core.provider import Provider
from core.result import ProviderMessage, ProviderResult
from metric import Metric
from models.ups_status import UPSStatus


class UPSProvider(Provider):
    """Collect one UPS through the configured NUT collector."""

    name = "ups"
    version = "1"
    domain = "hardware"
    capabilities = ("nut", "battery", "input-power", "load")

    def __init__(
        self,
        collect_status: Callable[[], UPSStatus],
        to_metric: Callable[[UPSStatus], Metric],
        required: bool,
    ) -> None:
        self.collect_status = collect_status
        self.to_metric = to_metric
        self.required = required

    def collect(self) -> ProviderResult:
        result = ProviderResult(provider=self.name)
        try:
            result.metrics.append(self.to_metric(self.collect_status()))
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            message = ProviderMessage(self.name, f"UPS collection failed: {exc}")
            (result.errors if self.required else result.warnings).append(message)
        return result
