import json
import unittest

from collector import raid_array_to_metric, raid_controller_to_metric, raid_drive_to_metric
from services.command_runner import CommandResult
from services.raid_collectors import StorCliRaidCollector, ThreeWareRaidCollector
from services.hp_smartarray import HpSmartArrayRaidCollector


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

    def test_storcli_direct_attached_slots_get_detail_by_controller_slot(self):
        main_payload = {
            "Controllers": [{
                "Command Status": {"Controller": 0, "Status": "Success"},
                "Response Data": {
                    "Controller": 0,
                    "Basics": {"Model": "LSI 9267-8i", "Serial Number": "ABC", "Status": "Optimal"},
                    "PD LIST": [{
                        "EID:Slt": ":1", "DID": 19, "State": "JBOD",
                        "Size": "1.819 TB", "Model": "ST2000DM001-1ER164",
                    }],
                },
            }]
        }
        enclosure_payload = {"Controllers": []}
        direct_payload = {
            "Controllers": [{
                "Command Status": {"Controller": 0, "Status": "Success"},
                "Response Data": {
                    "Drive /c0/s1 - Detailed Information": {
                        "Drive /c0/s1 State": {
                            "Media Error Count": 0,
                            "Other Error Count": 340,
                            "Drive Temperature": "33C",
                            "Predictive Failure Count": 0,
                        },
                        "Drive /c0/s1 Device attributes": {
                            "SN": "S4Z04V2V",
                            "Model Number": "ST2000DM001-1ER164",
                        },
                    }
                },
            }]
        }

        runner = QueueRunner([
            json.dumps(main_payload),
            json.dumps(enclosure_payload),
            json.dumps(direct_payload),
        ])
        collector = StorCliRaidCollector(runner)
        controllers, arrays, drives = collector.collect()

        self.assertEqual(len(drives), 1)
        drive = drives[0]
        self.assertEqual(drive.drive_id, "19")
        self.assertEqual(drive.enclosure, "")
        self.assertEqual(drive.slot, "1")
        self.assertEqual(drive.serial, "S4Z04V2V")
        self.assertEqual(drive.temperature_c, 33.0)
        self.assertEqual(drive.other_errors, 340)
        self.assertTrue(
            any(
                command[-5:] == ["/c0", "/sall", "show", "all", "J"]
                for command in runner.commands
            )
        )
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


    def test_hp_smartarray_controller_only(self):
        detail = """
Smart Array P410 in Slot 3
   Bus Interface: PCI
   Slot: 3
   Serial Number: PACCR9SZ32Z6
   Controller Status: OK
   Firmware Version: 6.64
   Cache Status: Not Configured
   Battery/Capacitor Status: OK
"""
        collector = HpSmartArrayRaidCollector(QueueRunner([detail]))
        controllers, arrays, drives = collector.collect()

        self.assertEqual(len(controllers), 1)
        controller = controllers[0]
        self.assertEqual(controller.provider, "hp-smartarray")
        self.assertEqual(controller.controller, "slot3")
        self.assertEqual(controller.model, "Smart Array P410")
        self.assertEqual(controller.serial, "PACCR9SZ32Z6")
        self.assertEqual(controller.firmware, "6.64")
        self.assertEqual(controller.status, "Healthy")
        self.assertEqual(controller.health_score, 100)
        self.assertEqual(controller.cache_status, "Not Configured")
        self.assertEqual(controller.battery_status, "OK")
        self.assertEqual(controller.virtual_drive_count, 0)
        self.assertEqual(controller.physical_drive_count, 0)
        self.assertFalse(controller.jbod_mode)
        self.assertEqual(arrays, [])
        self.assertEqual(drives, [])
if __name__ == "__main__":
    unittest.main()
