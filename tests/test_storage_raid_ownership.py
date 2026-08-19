import json
import unittest

from models.disk import Disk
from services.command_runner import CommandResult
from services.raid_discovery import RaidDiscoveryService
from services.storcli import StorCliService


class Runner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.commands = []

    def run(self, command):
        self.commands.append(list(command))
        return CommandResult(self.outputs.pop(0), "", 0)


class StorageRaidOwnershipTests(unittest.TestCase):
    def test_direct_attached_megaraid_serial_is_excluded_before_ata_smart(self):
        payload = {
            "Controllers": [{
                "Response Data": {
                    "Controller": 0,
                    "PD LIST": [{
                        "EID:Slt": ":5",
                        "DID": 20,
                        "State": "JBOD",
                        "Model": "ST1000NM0011",
                    }],
                    "Drive /c0/s5 - Detailed Information": {
                        "Drive /c0/s5 Device attributes": {
                            "SN": "Z1N344E0",
                            "Model Number": "ST1000NM0011",
                        }
                    },
                }
            }]
        }

        runner = Runner([json.dumps(payload)])
        storcli = StorCliService(runner=runner)
        discovery = RaidDiscoveryService(
            storcli=storcli,
            controller_devices={0: "/dev/sda"},
        )

        raid_disk = Disk(
            device="/dev/sdd",
            vendor="Seagate",
            model="ST1000NM0011",
            serial="Z1N344E0",
            capacity_bytes=1000204886016,
            disk_type="HDD",
            transport="ATA",
        )
        direct_disk = Disk(
            device="/dev/sdc",
            vendor="Seagate",
            model="ST500DM002-1SB10A",
            serial="ZA45KL6D",
            capacity_bytes=500107862016,
            disk_type="HDD",
            transport="SATA",
        )

        result = discovery.discover([raid_disk, direct_disk])

        self.assertEqual([disk.serial for disk in result.direct_disks], ["ZA45KL6D"])
        self.assertEqual(result.megaraid_drives[0].serial, "Z1N344E0")


if __name__ == "__main__":
    unittest.main()