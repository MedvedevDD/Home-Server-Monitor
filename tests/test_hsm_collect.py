from __future__ import annotations

import pytest

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


@pytest.mark.parametrize("module", hsm_collect.MODULES)
def test_select_registry_returns_only_requested_module(module: str) -> None:
    selected = hsm_collect.select_registry(module, registry())
    assert [provider.name for provider in selected] == [module]


def test_select_registry_all_preserves_all_modules() -> None:
    selected = hsm_collect.select_registry("all", registry())
    assert [provider.name for provider in selected] == list(hsm_collect.MODULES)


def test_disabled_module_is_explicit_error() -> None:
    with pytest.raises(ValueError, match="not enabled"):
        hsm_collect.select_registry("ups", ProviderRegistry([FakeProvider("storage")]))


def test_run_emits_only_selected_module(capsys: pytest.CaptureFixture[str]) -> None:
    assert hsm_collect.run("proxmox", registry()) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("proxmox_metric ")
    assert "storage_metric" not in captured.out
    assert captured.err == ""


def test_parser_rejects_unknown_module() -> None:
    with pytest.raises(SystemExit):
        hsm_collect.build_parser().parse_args(["unknown"])
