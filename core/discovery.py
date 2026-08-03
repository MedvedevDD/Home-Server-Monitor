"""Capability and collector discovery models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Availability(str, Enum):
    """Runtime availability of one collector."""

    READY = "ready"
    UNAVAILABLE = "unavailable"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Capability:
    """One capability advertised by a collector."""

    name: str
    available: bool = True
    detail: str = ""


@dataclass(slots=True)
class ProviderDiscovery:
    """Discovery result returned before metric collection."""

    provider: str
    domain: str
    availability: Availability = Availability.READY
    capabilities: list[Capability] = field(default_factory=list)
    detail: str = ""

    @property
    def ready(self) -> bool:
        return self.availability is Availability.READY
