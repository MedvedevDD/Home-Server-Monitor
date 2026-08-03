"""Tests for the Proxmox host provider."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from collector import proxmox_host_info_to_metric, proxmox_host_status_to_metric
from core.discovery import Availability
from models.proxmox_host import ProxmoxHostStatus
from providers.proxmox import ProxmoxProvider
from services.proxmox_host import ProxmoxHostCollector


def sample_status() -> ProxmoxHostStatus:
    return ProxmoxHostStatus(
        host="pve01",
        node="pve01",
        pve_version="pve-manager/8.4.1/test",
        kernel_version="6.8.12-test",
        cpu_model="Test CPU",
        cpu_count=8,
        uptime_seconds=3600.0,
        cpu_usage_percent=12.5,
        load1=0.5,
        load5=0.4,
        load15=0.3,
        memory_total_bytes=16_000,
        memory_available_bytes=6_000,
        memory_used_bytes=10_000,
        memory_used_percent=62.5,
        swap_total_bytes=8_000,
        swap_free_bytes=7_000,
        swap_used_bytes=1_000,
        swap_used_percent=12.5,
    )


class ProxmoxProviderTests(unittest.TestCase):
    def test_provider_returns_two_metrics(self) -> None:
        provider = ProxmoxProvider(
            collect_status=sample_status,
            info_metric=proxmox_host_info_to_metric,
            status_metric=proxmox_host_status_to_metric,
        )
        result = provider.collect()
        self.assertTrue(result.ok)
        self.assertEqual([item.measurement for item in result.metrics], [
            "proxmox_host_info", "proxmox_host_status"
        ])

    def test_discovery_is_unavailable_without_pveversion(self) -> None:
        provider = ProxmoxProvider(
            collect_status=sample_status,
            info_metric=proxmox_host_info_to_metric,
            status_metric=proxmox_host_status_to_metric,
        )
        with patch("providers.proxmox.shutil.which", return_value=None):
            discovery = provider.discover()
        self.assertEqual(discovery.availability, Availability.UNAVAILABLE)

    def test_metric_contains_resource_fields(self) -> None:
        line = proxmox_host_status_to_metric(sample_status()).to_line_protocol()
        self.assertIn("cpu_usage_percent=12.5", line)
        self.assertIn("memory_used_percent=62.5", line)
        self.assertIn("swap_used_percent=12.5", line)


class ProxmoxHostCollectorTests(unittest.TestCase):
    def test_cpu_usage_calculation(self) -> None:
        collector = ProxmoxHostCollector(sample_interval=0)
        with patch.object(collector, "_cpu_times", side_effect=[(1000, 600), (1100, 650)]):
            self.assertEqual(collector._cpu_usage_percent(), 50.0)


if __name__ == "__main__":
    unittest.main()
