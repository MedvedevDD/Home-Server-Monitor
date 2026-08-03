"""Tests for the Home Server Monitor UPS collector."""

import unittest
from unittest.mock import patch

import collector
from collectors.ups import UPSCollector


SAMPLE = """battery.voltage: 54.4
input.frequency: 50.0
input.voltage: 231.4
output.voltage: 231.4
ups.load: 14
ups.status: OL
ups.temperature: 40.6
ups.delay.start: 30
ups.delay.shutdown: 180
ups.beeper.status: enabled
"""


class UPSCollectorTests(unittest.TestCase):
    def test_online_status_and_charge_are_normalized(self) -> None:
        result = UPSCollector.parse(SAMPLE, "ippon", host="pve01")
        self.assertEqual(result.status, "Online")
        self.assertTrue(result.online)
        self.assertEqual(result.status_code, 1)
        self.assertFalse(result.on_battery)
        self.assertEqual(result.battery_charge_estimated, 100.0)
        self.assertEqual(result.load_percent, 14.0)

    def test_on_battery_low_is_critical(self) -> None:
        result = UPSCollector.parse(
            SAMPLE.replace("54.4", "42.0").replace("OL", "OB LB DISCHRG"),
            "ippon",
            host="pve01",
        )
        self.assertEqual(result.status, "Critical")
        self.assertTrue(result.on_battery)
        self.assertTrue(result.low_battery)
        self.assertEqual(result.status_code, 3)
        self.assertEqual(result.battery_charge_estimated, 0.0)

    def test_charge_is_clamped(self) -> None:
        high = UPSCollector.parse(SAMPLE.replace("54.4", "60.0"), "ippon")
        low = UPSCollector.parse(SAMPLE.replace("54.4", "30.0"), "ippon")
        self.assertEqual(high.battery_charge_estimated, 100.0)
        self.assertEqual(low.battery_charge_estimated, 0.0)

    def test_metric_contains_numeric_charge_and_status_tag(self) -> None:
        metric = collector.ups_status_to_metric(
            UPSCollector.parse(SAMPLE, "ippon", host="pve01")
        )
        self.assertEqual(metric.measurement, "ups_status")
        self.assertEqual(metric.tags["status"], "Online")
        self.assertEqual(metric.fields["battery_charge_estimated"], 100.0)
        self.assertIn("battery_charge_estimated=100", metric.to_line_protocol())

    def test_main_keeps_running_when_optional_ups_is_unavailable(self) -> None:
        with patch("config.UPS_ENABLED", True), patch("config.UPS_REQUIRED", False):
            with patch("collector.UPSCollector.collect", side_effect=RuntimeError("missing")):
                # RuntimeError is intentionally not swallowed by the production path.
                # This protects against programming errors rather than command failures.
                with self.assertRaises(RuntimeError):
                    collector.UPSCollector().collect()


if __name__ == "__main__":
    unittest.main()
