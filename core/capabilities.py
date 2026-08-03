"""Capability inventory helpers."""

from __future__ import annotations

from collections import defaultdict

from core.manager import ProviderRun


def group_capabilities(runs: list[ProviderRun]) -> dict[str, list[tuple[str, bool, str]]]:
    """Group discovered capabilities by domain for CLI and reports."""
    grouped: dict[str, list[tuple[str, bool, str]]] = defaultdict(list)
    for run in runs:
        for capability in run.discovery.capabilities:
            grouped[run.discovery.domain].append(
                (capability.name, capability.available and run.discovery.ready, capability.detail)
            )
    return dict(grouped)
