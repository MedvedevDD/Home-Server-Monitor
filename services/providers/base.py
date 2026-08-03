"""SMART provider interfaces and shared helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from models.disk import Disk
from models.disk_health import DiskHealth


class SmartProvider(ABC):
    """Read SMART data using one transport-specific strategy."""

    @abstractmethod
    def collect(self, disks: Iterable[Disk]) -> list[DiskHealth]:
        """Collect SMART health for the supplied disks."""
        raise NotImplementedError
