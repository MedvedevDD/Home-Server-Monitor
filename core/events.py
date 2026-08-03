"""Small synchronous event bus used by current and future notifiers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class Event:
    name: str
    source: str
    severity: str
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], None]] = []

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def publish(self, event: Event) -> None:
        for callback in tuple(self._subscribers):
            callback(event)
