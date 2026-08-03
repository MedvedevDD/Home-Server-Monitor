"""Collector lifecycle orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from core.discovery import Availability, ProviderDiscovery
from core.provider import Provider
from core.result import ProviderMessage, ProviderResult


@dataclass(slots=True)
class ProviderRun:
    """Discovery and collection outcome for one provider."""

    provider: Provider
    discovery: ProviderDiscovery
    result: ProviderResult | None = None


class CollectorManager:
    """Run discovery, dependency checks, and collection in registry order."""

    def __init__(self, providers: list[Provider]) -> None:
        self.providers = providers

    def discover(self) -> list[ProviderRun]:
        runs: list[ProviderRun] = []
        ready_names: set[str] = set()
        known_names = {provider.name for provider in self.providers}

        for provider in self.providers:
            missing = [name for name in provider.dependencies if name not in known_names]
            unavailable = [name for name in provider.dependencies if name not in ready_names and name in known_names]
            if missing or unavailable:
                names = missing + unavailable
                discovery = ProviderDiscovery(
                    provider=provider.name,
                    domain=provider.domain,
                    availability=Availability.SKIPPED,
                    detail="dependency not available: " + ", ".join(names),
                )
            else:
                try:
                    discovery = provider.discover()
                except (OSError, RuntimeError, ValueError, TypeError) as exc:
                    discovery = ProviderDiscovery(
                        provider=provider.name,
                        domain=provider.domain,
                        availability=Availability.ERROR,
                        detail=str(exc),
                    )
            if discovery.ready:
                ready_names.add(provider.name)
            runs.append(ProviderRun(provider=provider, discovery=discovery))
        return runs

    def collect(self) -> list[ProviderRun]:
        runs = self.discover()
        for run in runs:
            if not run.discovery.ready:
                continue
            try:
                run.result = run.provider.collect()
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                run.result = ProviderResult(
                    provider=run.provider.name,
                    errors=[ProviderMessage(run.provider.name, f"Unhandled collection failure: {exc}")],
                )
        return runs
