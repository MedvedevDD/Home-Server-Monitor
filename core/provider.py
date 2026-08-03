"""Provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from core.discovery import Capability, ProviderDiscovery
from core.result import ProviderResult


class Provider(ABC):
    """Independent source of Home Server Monitor metrics."""

    name = "provider"
    version = "1"
    domain = "other"
    capabilities: Sequence[str] = ()
    dependencies: Sequence[str] = ()

    def discover(self) -> ProviderDiscovery:
        """Describe availability and capabilities without collecting metrics."""
        return ProviderDiscovery(
            provider=self.name,
            domain=self.domain,
            capabilities=[Capability(name=item) for item in self.capabilities],
        )

    @abstractmethod
    def collect(self) -> ProviderResult:
        """Collect metrics without writing them to an output backend."""
