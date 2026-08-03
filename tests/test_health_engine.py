from __future__ import annotations

import unittest
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


class HealthEngineTests(unittest.TestCase):
    def test_proxmox_full_storage_is_critical(self):
        report = summarize_health([run_for("proxmox", [Metric("proxmox_storage", tags={"storage": "local-lvm"}, fields={"used_percent": 99.79, "health_code": 3})])])
        self.assertEqual(report.severity, Severity.CRITICAL)
        self.assertIn("99.79%", report.domains[0].findings[0].reason)

    def test_smart_self_test_bit_is_warning(self):
        report = summarize_health([run_for("storage", [Metric("storage_health", tags={"device": "/dev/sdk"}, fields={"smart_available": True, "health_passed": True, "smartctl_exit_code": 64})])])
        self.assertEqual(report.severity, Severity.WARNING)
        self.assertEqual(report.domains[0].findings[0].subject, "/dev/sdk")

    def test_pending_sector_is_high(self):
        report = summarize_health([run_for("storage", [Metric("storage_health", tags={"device": "/dev/sda"}, fields={"smart_available": True, "health_passed": True, "pending_sectors": 1, "smartctl_exit_code": 0})])])
        self.assertEqual(report.severity, Severity.HIGH)

    def test_healthy_domains_are_ok(self):
        report = summarize_health([
            run_for("raid", [Metric("raid_controller_status", fields={"status_code": 1})]),
            run_for("ups", [Metric("ups_status", fields={"online": True, "on_battery": False, "low_battery": False, "overload": False, "battery_charge_estimated": 100})]),
        ])
        self.assertEqual(report.severity, Severity.OK)
        self.assertEqual(report.score, 100)


if __name__ == "__main__":
    unittest.main()
