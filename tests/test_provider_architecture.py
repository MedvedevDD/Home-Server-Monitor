"""Regression tests for the provider registry architecture."""

from __future__ import annotations

import unittest

from core.provider import Provider
from core.registry import ProviderRegistry
from core.result import ProviderMessage, ProviderResult
from metric import Metric


class DummyProvider(Provider):
    name = "dummy"
    capabilities = ("one", "two")

    def collect(self) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            metrics=[Metric("dummy_metric", fields={"value": 1})],
        )


class WarningProvider(Provider):
    name = "warning"

    def collect(self) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            warnings=[ProviderMessage(self.name, "test warning")],
        )


class ProviderRegistryTests(unittest.TestCase):
    def test_registry_collects_in_registration_order(self) -> None:
        registry = ProviderRegistry([DummyProvider(), WarningProvider()])
        results = registry.collect()
        self.assertEqual([item.provider for item in results], ["dummy", "warning"])
        self.assertEqual(results[0].metrics[0].measurement, "dummy_metric")
        self.assertTrue(results[0].ok)
        self.assertTrue(results[1].ok)

    def test_registry_rejects_duplicate_provider_names(self) -> None:
        registry = ProviderRegistry([DummyProvider()])
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(DummyProvider())

    def test_registry_exposes_capabilities(self) -> None:
        registry = ProviderRegistry([DummyProvider()])
        self.assertEqual(registry.capabilities(), {"dummy": ("one", "two")})


if __name__ == "__main__":
    unittest.main()
