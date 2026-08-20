import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from collector import cooling_fan_metrics, cooling_status_to_metric
from models.cooling import CoolingStatus
from services.command_runner import CommandResult
from services.cooling import CoolingCollector, X8FanClient, bmc_sensor_health


class QueueRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.commands = []

    def run(self, command):
        self.commands.append(list(command))
        stdout, return_code = self.outputs.pop(0)
        return CommandResult(stdout, "", return_code)


class TemperatureSource:
    def __init__(self, value):
        self.value = value

    def maximum_temperature(self):
        return self.value


class FakeX8Fan:
    def __init__(self):
        self.auto_values = []

    def auto(self, value):
        self.auto_values.append(value)

    def status(self):
        return CoolingStatus(
            board="Supermicro X8DTN+-F",
            controller="W83795ADG",
            mode="quiet",
            pwm2_raw=0,
            pwm2_percent=0.0,
            cpu_max_c=47.0,
            system_temp_c=31.0,
            source="auto",
            fans={"1": None, "2": 961, "3": 2304, "4": 2916,
                  "5": 1600, "6": None, "7": 1024, "8": 1089},
            status_polled=True,
        )


class CoolingTests(unittest.TestCase):
    def test_temperature_is_forwarded_to_x8fan(self):
        x8fan = FakeX8Fan()
        with tempfile.TemporaryDirectory() as directory:
            status = CoolingCollector(
                TemperatureSource(36.0),
                x8fan,
                state_file=Path(directory) / "cooling.json",
            ).collect()
        self.assertEqual(x8fan.auto_values, [36.0])
        self.assertTrue(status.hdd_input_available)
        self.assertTrue(status.auto_applied)
        self.assertEqual(status.hdd_input_c, 36.0)

    def test_missing_temperature_does_not_call_auto(self):
        x8fan = FakeX8Fan()
        with tempfile.TemporaryDirectory() as directory:
            status = CoolingCollector(
                TemperatureSource(None),
                x8fan,
                state_file=Path(directory) / "cooling.json",
            ).collect()
        self.assertEqual(x8fan.auto_values, [])
        self.assertFalse(status.hdd_input_available)
        self.assertFalse(status.auto_applied)

    def test_x8fan_status_preserves_zero_and_null_fans(self):
        payload = json.dumps({
            "board": "Supermicro X8DTN+-F",
            "controller": "W83795ADG",
            "bios_fan_profile": "Quiet",
            "mode": "quiet",
            "pwm2_raw": 0,
            "pwm2_percent": 0.0,
            "cpu_max": 47.0,
            "system_temp": 31.0,
            "hdd_max": None,
            "source": "manual",
            "fans": {"1": 0, "2": 961, "6": None},
        })
        runner = QueueRunner([(payload, 0)])
        status = X8FanClient(runner).status()
        self.assertEqual(status.fans["1"], 0)
        self.assertEqual(status.fans["2"], 961)
        self.assertIsNone(status.fans["6"])

    def test_metrics_include_all_eight_fan_channels(self):
        status = FakeX8Fan().status()
        fan_metrics = cooling_fan_metrics(status)
        self.assertEqual(len(fan_metrics), 8)
        lines = [metric.to_line_protocol() for metric in fan_metrics]
        fan1 = next(line for line in lines if "fan=FAN1" in line)
        fan2 = next(line for line in lines if "fan=FAN2" in line)
        self.assertIn("available=false", fan1)
        self.assertNotIn("rpm=", fan1)
        self.assertIn("rpm=961i", fan2)

    def test_status_metric_exposes_control_input(self):
        status = CoolingStatus(
            board="Supermicro X8DTN+-F",
            controller="W83795ADG",
            mode="low",
            source="auto",
            hdd_input_available=True,
            hdd_input_c=38.0,
            auto_applied=True,
        )
        line = cooling_status_to_metric(status).to_line_protocol()
        self.assertIn("hdd_input_available=true", line)
        self.assertIn("hdd_input_c=38", line)
        self.assertIn("auto_applied=true", line)


    def test_status_metric_preserves_integer_timestamps(self):
        status = CoolingStatus(
            board="Supermicro X8DTN+-F",
            controller="W83795ADG",
            mode="quiet",
            source="hdd_temperature",
            last_change=1786830330.5974474,
            last_update=1786834410.2498512,
        )
        line = cooling_status_to_metric(status).to_line_protocol()
        self.assertIn("last_change_unix=1786830330i", line)
        self.assertIn("last_update_unix=1786834410i", line)
        self.assertNotIn("e+09", line)

    def test_status_metric_exposes_mode_and_source_fields(self):
        status = CoolingStatus(
            board="Supermicro X8DTN+-F",
            controller="W83795ADG",
            mode="quiet",
            source="hdd_temperature",
        )
        line = cooling_status_to_metric(status).to_line_protocol()
        self.assertIn('mode_name="quiet"', line)
        self.assertIn('source_name="hdd_temperature"', line)
    def test_invalid_system_temperature_sentinel_is_ignored(self):
        payload = json.dumps({
            "board": "Supermicro X8DTN+-F",
            "controller": "W83795ADG",
            "mode": "quiet",
            "cpu_max": 51.0,
            "system_temp": -124.0,
            "hdd_max": 32.0,
            "source": "hdd_temperature",
            "fans": {},
        })
        runner = QueueRunner([(payload, 0)])
        status = X8FanClient(runner).status()
        self.assertEqual(status.cpu_max_c, 51.0)
        self.assertIsNone(status.system_temp_c)
        self.assertEqual(status.hdd_max_c, 32.0)

    def test_status_metric_exposes_mode_and_source_codes(self):
        status = CoolingStatus(
            board="Supermicro X8DTN+-F",
            controller="W83795ADG",
            mode="quiet",
            source="hdd_temperature",
        )
        line = cooling_status_to_metric(status).to_line_protocol()
        self.assertIn("mode_code=1i", line)
        self.assertIn("source_code=2i", line)
    def test_hdd_threshold_crossing_detection(self):
        self.assertFalse(CoolingCollector._crossed_hdd_boundary(30.0, 39.0))
        self.assertTrue(CoolingCollector._crossed_hdd_boundary(39.0, 40.0))
        self.assertFalse(CoolingCollector._crossed_hdd_boundary(40.0, 44.0))
        self.assertTrue(CoolingCollector._crossed_hdd_boundary(44.0, 45.0))
        self.assertFalse(CoolingCollector._crossed_hdd_boundary(40.0, 39.0))
        self.assertTrue(CoolingCollector._crossed_hdd_boundary(38.0, 36.0))

    def test_cpu_emergency_hysteresis(self):
        event, emergency = CoolingCollector._cpu_transition(False, 84.0)
        self.assertFalse(event)
        self.assertFalse(emergency)
        event, emergency = CoolingCollector._cpu_transition(False, 85.0)
        self.assertTrue(event)
        self.assertTrue(emergency)
        event, emergency = CoolingCollector._cpu_transition(True, 82.0)
        self.assertFalse(event)
        self.assertTrue(emergency)
        event, emergency = CoolingCollector._cpu_transition(True, 79.0)
        self.assertTrue(event)
        self.assertFalse(emergency)


    @patch("services.cooling.subprocess.run")
    def test_partial_bmc_sensor_collapse_is_detected(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = """FAN 1 | na | RPM | na
FAN 2 | na | RPM | na
FAN 3 | na | RPM | na
FAN 4 | na | RPM | na
FAN 5 | na | RPM | na
FAN 6 | na | RPM | na
FAN 7 | na | RPM | na
FAN 8 | na | RPM | na
System Temp | na | degrees C | na
P2-DIMM2A | 35.000 | degrees C | ok
"""
        all_na, collapse = bmc_sensor_health()
        self.assertFalse(all_na)
        self.assertTrue(collapse)
    def test_backoff_schedule(self):
        self.assertEqual(CoolingCollector._backoff_seconds(1), 60)
        self.assertEqual(CoolingCollector._backoff_seconds(2), 300)
        self.assertEqual(CoolingCollector._backoff_seconds(3), 900)
        self.assertEqual(CoolingCollector._backoff_seconds(10), 900)
if __name__ == "__main__":
    unittest.main()
