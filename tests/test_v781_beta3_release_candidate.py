from __future__ import annotations

import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hsm_beta3", ROOT / "hsm.py")
assert SPEC and SPEC.loader
HSM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HSM)


class Beta3ReleaseCandidateTests(unittest.TestCase):
    def test_parse_rfc3339_supports_z_suffix(self):
        value = HSM.parse_rfc3339("2026-08-03T14:12:03Z")
        self.assertEqual(value.tzinfo, dt.timezone.utc)
        self.assertEqual(value.year, 2026)

    def test_measurement_last_update_parses_influx_csv(self):
        output = "name,tags,time,value\nproxmox_host_status,,2026-08-03T14:12:03Z,1\n"
        completed = mock.Mock(returncode=0, stdout=output, stderr="")
        fixed_now = dt.datetime(2026, 8, 3, 14, 12, 33, tzinfo=dt.timezone.utc)
        real_datetime = HSM.dt.datetime

        class FixedDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

        with mock.patch.object(HSM, "run", return_value=completed), \
             mock.patch.object(HSM.dt, "datetime", FixedDateTime):
            result = HSM.measurement_last_update("proxmox_host_status", "raid")
        self.assertTrue(result["available"])
        self.assertEqual(result["age_seconds"], 30.0)

    def test_dashboard_checks_report_each_dashboard(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Home.json").write_text("{}", encoding="utf-8")
            with mock.patch.object(HSM, "GRAFANA_DASHBOARD_DIR", root):
                checks = HSM.dashboard_checks()
        self.assertEqual(len(checks), 5)
        self.assertTrue(checks[0]["present"])
        self.assertFalse(checks[1]["present"])
        self.assertEqual(checks[0]["name"], "Overview")

    def test_recent_errors_ignore_unrelated_upsd_failures(self):
        journal = "\n".join([
            "E! [inputs.upsd] Error in plugin: connection refused",
            "E! [inputs.exec] Error in plugin: command timed out for command /usr/local/bin/hsm-collect storage",
        ])
        completed = mock.Mock(returncode=0, stdout=journal, stderr="")
        with mock.patch.object(HSM, "run", return_value=completed):
            result = HSM.recent_hsm_telegraf_errors()
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("hsm-collect storage", result["errors"][0])

    def test_main_routes_verify_json(self):
        with mock.patch.object(HSM, "verify", return_value=0) as command, \
             mock.patch("sys.argv", ["hsm", "verify", "--json"]):
            self.assertEqual(HSM.main(), 0)
        command.assert_called_once_with(True)

    def test_benchmark_json_has_summary(self):
        samples = [
            {"module": "storage", "status": "PASS", "runtime_seconds": 2.0,
             "metrics": 18, "metrics_per_second": 9.0, "slow": False},
        ]
        with mock.patch.object(HSM, "benchmark_collectors", return_value=samples), \
             mock.patch("builtins.print") as output:
            self.assertEqual(HSM.benchmark(as_json=True), 0)
        payload = json.loads(output.call_args.args[0])
        self.assertEqual(payload["summary"]["metrics"], 18)
        self.assertEqual(payload["summary"]["metrics_per_second"], 9.0)


if __name__ == "__main__":
    unittest.main()
