"""Metrics pipeline separating collection from serialization."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from core.manager import ProviderRun
from metric import Metric


class MetricsPipeline:
    """Flatten provider results and send metrics to one output callback."""

    def __init__(self, writer: Callable[[Iterable[Metric]], None]) -> None:
        self.writer = writer

    def export(self, runs: list[ProviderRun]) -> int:
        metrics = [metric for run in runs if run.result for metric in run.result.metrics]
        self.writer(metrics)
        return len(metrics)
