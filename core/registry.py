"""Provider registration and collection orchestration."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from core.manager import CollectorManager
from core.provider import Provider
from core.result import ProviderResult


class ProviderRegistry:
    """Ordered registry of independent metric providers."""

    def __init__(self, providers: Iterable[Provider] = ()) -> None:
        self._providers: list[Provider] = []
        for provider in providers:
            self.register(provider)

    def register(self, provider: Provider) -> None:
        if any(item.name == provider.name for item in self._providers):
            raise ValueError(f"Provider already registered: {provider.name}")
        self._providers.append(provider)

    def __iter__(self) -> Iterator[Provider]:
        return iter(self._providers)

    def manager(self) -> CollectorManager:
        return CollectorManager(list(self._providers))

    def collect(self) -> list[ProviderResult]:
        return [run.result for run in self.manager().collect() if run.result is not None]

    def capabilities(self) -> dict[str, tuple[str, ...]]:
        return {provider.name: tuple(provider.capabilities) for provider in self._providers}
