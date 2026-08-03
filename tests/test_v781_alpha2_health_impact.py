from __future__ import annotations

from types import SimpleNamespace

from core.discovery import Availability, ProviderDiscovery
from core.health import Severity, summarize_health
from core.manager import ProviderRun
from core.result import ProviderResult
from metric import Metric


def run_for(name: str, metrics: list[Metric]) -> ProviderRun:
    provider = SimpleNamespace(name=name)
    discovery = ProviderDiscovery(provider=name, domain="test", availability=Availability.READY)
    return ProviderRun(provider=provider, discovery=discovery, result=ProviderResult(provider=name, metrics=metrics))


def test_domain_order_is_stable() -> None:
    report = summarize_health([
        run_for("proxmox", []),
        run_for("ups", []),
        run_for("storage", []),
        run_for("raid", []),
    ])
    assert [domain.name for domain in report.domains] == ["storage", "raid", "ups", "proxmox"]


def test_impacts_drive_scores_and_primary_finding() -> None:
    report = summarize_health([
        run_for("storage", [Metric("storage_health", tags={"device": "/dev/sdk"}, fields={"smart_available": True, "health_passed": True, "smartctl_exit_code": 64})]),
        run_for("proxmox", [Metric("proxmox_storage", tags={"storage": "local-lvm"}, fields={"used_percent": 99.79, "health_code": 3})]),
    ])
    assert report.score == 55
    assert report.primary_finding is not None
    assert report.primary_finding.rule == "proxmox-storage-critical"
    assert report.primary_finding.impact == 40
    assert report.warning_count == 1
    assert report.critical_count == 1
    assert report.severity == Severity.CRITICAL


def test_json_contains_impact_counts_and_primary_finding() -> None:
    report = summarize_health([
        run_for("storage", [Metric("storage_health", tags={"device": "/dev/sdk"}, fields={"smart_available": True, "health_passed": True, "smartctl_exit_code": 64})]),
    ])
    data = report.as_dict()
    assert data["counts"]["warning"] == 1
    assert data["primary_finding"]["impact"] == 5
    assert data["domains"][0]["findings"][0]["impact"] == 5
