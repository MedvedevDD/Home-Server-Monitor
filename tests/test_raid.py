import json
import unittest

from collector import raid_array_to_metric, raid_controller_to_metric, raid_drive_to_metric
from services.command_runner import CommandResult
from services.raid_collectors import StorCliRaidCollector, ThreeWareRaidCollector


class QueueRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.commands = []

    def run(self, command):
        self.commands.append(list(command))
        return CommandResult(self.outputs.pop(0), "", 0)


class RaidTests(unittest.TestCase):
    def test_storcli_normalizes_controller_array_and_drive(self):
        payload = {
            "Controllers": [{
                "Response Data": {
                    "Controller": 0,
                    "Basics": {
                        "Model": "LSI 9267-8i",
                        "Serial Number": "ABC",
                        "FW Package Build": "23.34",
                        "Status": "Optimal",
                        "ROC temperature(Degree Celsius)": "48 C",
                        "BBU Status": "Optimal",
                    },
                    "VD LIST": [{"DG/VD": "0/0", "TYPE": "RAID5", "State": "Optl", "Size": "5.45 TB"}],
                    "PD LIST": [{
                        "EID:Slt": "252:0", "DID": 18, "State": "Onln",
                        "Size": "465.761 GB", "Model": "ST500DM002",
                        "SN": "SER1", "Media Error Count": 0,
                        "Other Error Count": 225220,
                        "Predictive Failure Count": 0,
                    }],
                }
            }]
        }
        collector = StorCliRaidCollector(QueueRunner([json.dumps(payload)]))
        controllers, arrays, drives = collector.collect()
        self.assertEqual(controllers[0].status, "Healthy")
        self.assertEqual(arrays[0].raid_level, "RAID5")
        self.assertEqual(drives[0].slot, "0")
        self.assertEqual(drives[0].other_errors, 225220)
        self.assertIn("status_code=1i", raid_controller_to_metric(controllers[0]).to_line_protocol())
        self.assertIn("health_score=100i", raid_array_to_metric(arrays[0]).to_line_protocol())
        self.assertIn("other_errors=225220i", raid_drive_to_metric(drives[0]).to_line_protocol())


    def test_jbod_and_success_are_healthy(self):
        payload = {
            "Controllers": [{
                "Command Status": {"Controller": 0, "Status": "Success"},
                "Response Data": {
                    "Basics": {"Model": "LSI 9267-8i", "Serial Number": "ABC"},
                    "PD LIST": [{"EID:Slt": "252:0", "DID": 16, "State": "JBOD", "Size": "465.761 GB"}],
                },
            }]
        }
        controllers, arrays, drives = StorCliRaidCollector(QueueRunner([json.dumps(payload)])).collect()
        self.assertEqual(controllers[0].status, "Healthy")
        self.assertEqual(controllers[0].virtual_drive_count, 0)
        self.assertEqual(controllers[0].physical_drive_count, 1)
        self.assertTrue(controllers[0].jbod_mode)
        self.assertEqual(drives[0].status, "Healthy")
        self.assertEqual(drives[0].health_score, 100)

    def test_threeware_parses_basic_rows(self):
        listing = "c0  9690SA-4I  Slots=4"
        detail = """
/c0 Model = 9690SA-4I
/c0 Firmware Version = FE9X 4.10.00.027
/c0 Serial Number = 1234
/c0 Status = OK

Unit  UnitType  Status  %RCmpl  %V/I/M  Stripe  Size(GB)
u0    RAID-5    VERIFYING  88      -       64K     5450

Port   Status  Unit  Size  Blocks  Serial  Model
p0     OK      u0    2.0 TB  -     S1      TOSHIBA HDWD260
"""
        collector = ThreeWareRaidCollector(QueueRunner([listing, detail]))
        controllers, arrays, drives = collector.collect()
        self.assertEqual(controllers[0].status, "Healthy")
        self.assertEqual(arrays[0].status, "Warning")
        self.assertEqual(drives[0].slot, "0")


if __name__ == "__main__":
    unittest.main()
