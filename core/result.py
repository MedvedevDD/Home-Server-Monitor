"""Provider collection result models."""

from __future__ import annotations

from dataclasses import dataclass, field

from metric import Metric


@dataclass(slots=True)
class ProviderMessage:
    """One provider warning or error."""

    provider: str
    message: str


@dataclass(slots=True)
class ProviderResult:
    """Metrics and diagnostics returned by one provider."""

    provider: str
    metrics: list[Metric] = field(default_factory=list)
    warnings: list[ProviderMessage] = field(default_factory=list)
    errors: list[ProviderMessage] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
