#!/usr/bin/env python3
"""Run one Home Server Monitor provider or all enabled providers."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable

import collector
from core.pipeline import MetricsPipeline
from core.provider import Provider
from core.registry import ProviderRegistry
from metric import Metric

LOGGER = logging.getLogger("home_server_monitor.hsm_collect")
MODULES = ("storage", "raid", "ups", "proxmox")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hsm-collect",
        description="Collect metrics from one HSM module or all enabled modules.",
    )
    parser.add_argument(
        "module",
        choices=(*MODULES, "all"),
        help="Module to collect.",
    )
    return parser


def select_registry(module: str, registry: ProviderRegistry | None = None) -> ProviderRegistry:
    """Return a registry containing the requested enabled provider(s)."""
    source = registry or collector.build_provider_registry()
    if module == "all":
        return ProviderRegistry(source)

    selected: list[Provider] = [provider for provider in source if provider.name == module]
    if not selected:
        raise ValueError(f"Module is not enabled or unavailable in configuration: {module}")
    return ProviderRegistry(selected)


def write_metrics(metrics: Iterable[Metric]) -> None:
    """Write only Influx Line Protocol to stdout."""
    collector._write_metrics(metrics)


def run(module: str, registry: ProviderRegistry | None = None) -> int:
    """Collect the selected module and return a process exit code."""
    selected = select_registry(module, registry)
    runs = selected.manager().collect()
    MetricsPipeline(write_metrics).export(runs)

    failed = False
    for provider_run in runs:
        if not provider_run.discovery.ready:
            LOGGER.info(
                "Provider %s skipped: %s",
                provider_run.provider.name,
                provider_run.discovery.detail,
            )
            continue

        result = provider_run.result
        if result is None:
            continue
        for warning in result.warnings:
            LOGGER.warning("%s", warning.message)
        for error in result.errors:
            LOGGER.error("%s", error.message)
            failed = True

    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    collector.configure_logging()
    args = build_parser().parse_args(argv)
    try:
        return run(args.module)
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
