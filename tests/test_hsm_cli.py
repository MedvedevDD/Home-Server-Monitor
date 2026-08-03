from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hsm_cli", ROOT / "hsm.py")
assert SPEC and SPEC.loader
HSM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HSM)


class HsmCliTests(unittest.TestCase):
    def test_expected_dashboard_names(self):
        self.assertEqual(HSM.EXPECTED_DASHBOARDS, ("Home.json", "Storage.json", "RAID.json", "UPS.json", "Proxmox.json"))

    def test_sensitive_configuration_is_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "defaults"
            config.write_text("NORMAL=value\nAPI_TOKEN=secret\nPASSWORD=x\n", encoding="utf-8")
            with mock.patch.object(HSM, "DEFAULTS_FILE", config):
                rendered = HSM.redact_defaults()
        self.assertIn("NORMAL=value", rendered)
        self.assertIn("API_TOKEN=<redacted>", rendered)
        self.assertIn("PASSWORD=<redacted>", rendered)
        self.assertNotIn("secret", rendered)

    def test_find_telegraf_collector_configs_scans_main_and_dropins(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "telegraf.d").mkdir()
            (root / "telegraf.conf").write_text("# no collector here\n", encoding="utf-8")
            expected = root / "telegraf.d" / "custom.conf"
            expected.write_text(
                '[[inputs.exec]]\n  commands = ["python3 /opt/home-server-monitor/collector.py"]\n',
                encoding="utf-8",
            )
            unrelated = root / "telegraf.d" / "other.conf"
            unrelated.write_text('[[inputs.cpu]]\n', encoding="utf-8")
            with mock.patch.object(HSM, "INSTALL_DIR", Path("/opt/home-server-monitor")):
                matches = HSM.find_telegraf_collector_configs(root)
        self.assertEqual(matches, [expected])

    def test_telegraf_config_detail_handles_multiple_files(self):
        detail = HSM.telegraf_config_detail([Path("/a.conf"), Path("/b.conf")])
        self.assertIn("2 files", detail)
        self.assertIn("/a.conf", detail)

    def test_read_defaults_supports_quotes(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "defaults"
            config.write_text('A="one"\nB=two\n', encoding="utf-8")
            with mock.patch.object(HSM, "DEFAULTS_FILE", config):
                values = HSM.read_defaults()
        self.assertEqual(values, {"A": "one", "B": "two"})

    def test_main_routes_status_json(self):
        with mock.patch.object(HSM, "status", return_value=0) as command, \
             mock.patch("sys.argv", ["hsm", "status", "--json"]):
            self.assertEqual(HSM.main(), 0)
        command.assert_called_once_with(True)

    def test_main_routes_collectors_verbose_json(self):
        with mock.patch.object(HSM, "collectors", return_value=0) as command, \
             mock.patch("sys.argv", ["hsm", "collectors", "--verbose", "--json"]):
            self.assertEqual(HSM.main(), 0)
        command.assert_called_once_with(True, True)

    def test_info_json_is_machine_readable(self):
        class Manager:
            def discover(self):
                return []

        class Registry:
            def manager(self):
                return Manager()

        with mock.patch.object(HSM, "_runtime_registry", return_value=Registry()), \
             mock.patch("builtins.print") as output:
            self.assertEqual(HSM.info(as_json=True), 0)
        rendered = output.call_args.args[0]
        import json
        data = json.loads(rendered)
        self.assertEqual(data["name"], "Home Server Monitor")
        self.assertEqual(data["core_version"], "2.0")


if __name__ == "__main__":
    unittest.main()

class HsmBetaDiagnosticsTests(unittest.TestCase):
    def test_main_routes_doctor_json(self):
        with mock.patch.object(HSM, "doctor", return_value=0) as command, \
             mock.patch("sys.argv", ["hsm", "doctor", "--json"]):
            self.assertEqual(HSM.main(), 0)
        command.assert_called_once_with(as_json=True)

    def test_main_routes_benchmark_json(self):
        with mock.patch.object(HSM, "benchmark", return_value=0) as command, \
             mock.patch("sys.argv", ["hsm", "benchmark", "--json"]):
            self.assertEqual(HSM.main(), 0)
        command.assert_called_once_with(True)

    def test_managed_config_requires_exactly_one_module_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "90-home-server-monitor.conf"
            config.write_text("\n".join(
                f'commands = [\"/usr/local/bin/hsm-collect {name}\"]'
                for name in HSM.COLLECTOR_MANIFESTS
            ), encoding="utf-8")
            with mock.patch.object(HSM, "MANAGED_TELEGRAF_CONF", config), \
                 mock.patch.object(HSM, "TELEGRAF_ROOT", root):
                result = HSM.inspect_managed_telegraf_config()
        self.assertTrue(result["exists"])
        self.assertEqual(result["duplicates"], [])
