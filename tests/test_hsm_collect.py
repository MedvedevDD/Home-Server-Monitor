from __future__ import annotations

import contextlib
import io
import unittest

import hsm_collect
from core.provider import Provider
from core.registry import ProviderRegistry
from core.result import ProviderResult
from metric import Metric


class FakeProvider(Provider):
    version = "1"
    domain = "test"
    capabilities = ()

    def __init__(self, name: str) -> None:
        self.name = name

    def collect(self) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            metrics=[Metric(f"{self.name}_metric", fields={"value": 1})],
        )


def registry() -> ProviderRegistry:
    return ProviderRegistry(FakeProvider(name) for name in hsm_collect.MODULES)


class HsmCollectTests(unittest.TestCase):
    def test_select_registry_returns_only_requested_module(self) -> None:
        for module in hsm_collect.MODULES:
            with self.subTest(module=module):
                selected = hsm_collect.select_registry(module, registry())
                self.assertEqual(
                    [provider.name for provider in selected],
                    [module],
                )

    def test_select_registry_all_preserves_all_modules(self) -> None:
        selected = hsm_collect.select_registry("all", registry())
        self.assertEqual(
            [provider.name for provider in selected],
            list(hsm_collect.MODULES),
        )

    def test_disabled_module_is_explicit_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "not enabled"):
            hsm_collect.select_registry(
                "ups",
                ProviderRegistry([FakeProvider("storage")]),
            )

    def test_run_emits_only_selected_module(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = hsm_collect.run("proxmox", registry())

        self.assertEqual(result, 0)
        self.assertTrue(stdout.getvalue().startswith("proxmox_metric "))
        self.assertNotIn("storage_metric", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_parser_rejects_unknown_module(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                hsm_collect.build_parser().parse_args(["unknown"])


if __name__ == "__main__":
    unittest.main()