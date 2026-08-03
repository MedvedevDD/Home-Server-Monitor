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


def rules(name: str, metric: Metric) -> set[str]:
    report = summarize_health([run_for(name, [metric])])
    return {finding.rule for finding in report.domains[0].findings}


def test_storage_unavailable_is_unknown() -> None:
    report = summarize_health([run_for("storage", [Metric("storage_health", tags={"device": "/dev/sda"}, fields={"smart_available": False})])])
    assert report.severity == Severity.UNKNOWN
    assert "smart-unavailable" in {item.rule for item in report.domains[0].findings}


def test_raid_predictive_failure_is_critical() -> None:
    found = rules("raid", Metric("raid_drive_status", tags={"drive_id": "252:0"}, fields={"status_code": 1, "predictive_failures": 1}))
    assert "raid-predictive-failure" in found


def test_raid_media_error_is_high() -> None:
    found = rules("raid", Metric("raid_drive_status", tags={"drive_id": "252:0"}, fields={"status_code": 1, "media_errors": 2}))
    assert "raid-media-errors" in found


def test_ups_replace_battery_is_high() -> None:
    found = rules("ups", Metric("ups_status", tags={"ups_name": "ups"}, fields={"online": True, "replace_battery": True}))
    assert "ups-replace-battery" in found


def test_ups_normal_temperature_42_is_ok() -> None:
    report = summarize_health([run_for("ups", [Metric("ups_status", fields={"online": True, "battery_charge_estimated": 100, "load_percent": 12, "internal_temp": 42})])])
    assert report.severity == Severity.OK


def test_proxmox_memory_high_is_high() -> None:
    found = rules("proxmox", Metric("proxmox_host_status", tags={"node": "pve01"}, fields={"memory_used_percent": 96, "cpu_count": 8, "load15": 1, "swap_total_bytes": 1, "swap_used_percent": 0, "cpu_usage_percent": 10}))
    assert "memory-high" in found


def test_proxmox_load_is_normalized_by_cpu_count() -> None:
    ok = summarize_health([run_for("proxmox", [Metric("proxmox_host_status", fields={"cpu_count": 8, "load15": 7.9})])])
    warning = summarize_health([run_for("proxmox", [Metric("proxmox_host_status", fields={"cpu_count": 8, "load15": 8.0})])])
    assert ok.severity == Severity.OK
    assert warning.severity == Severity.WARNING


def test_inactive_storage_does_not_also_report_capacity() -> None:
    report = summarize_health([run_for("proxmox", [Metric("proxmox_storage", tags={"storage": "offline"}, fields={"enabled": True, "active": False, "used_percent": 100, "health_code": 3})])])
    found = {item.rule for item in report.domains[0].findings}
    assert found == {"proxmox-storage-inactive"}
