import unittest

from collector import storage_visible_disks
from models.disk import Disk
from models.disk_health import DiskHealth
from services.raid_discovery import RaidDiscoveryResult, RaidMode
from services.storcli import MegaRaidController, MegaRaidDrive


class StorageControlDeviceTests(unittest.TestCase):
    def test_control_device_is_not_treated_as_raid_owned_disk(self):
        samsung = Disk(
            device="/dev/sda",
            vendor="Samsung",
            model="Samsung SSD 860 EVO 250GB",
            serial="S3Y9NX0M629284D",
            capacity_bytes=250059350016,
            disk_type="SSD",
            transport="SATA",
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

        discovery = RaidDiscoveryResult(
            mode=RaidMode.MIXED,
            megaraid_controllers=(
                MegaRaidController(
                    controller_id=0,
                    control_device="/dev/sda",
                    drives=(
                        MegaRaidDrive(
                            controller=0,
                            enclosure=None,
                            slot=5,
                            device_id=20,
                            serial="Z1N344E0",
                            model="ST1000NM0011",
                            os_device="",
                        ),
                    ),
                ),
            ),
            direct_disks=(samsung,),
        )

        # Even if an ATA SMART result happens to use the same path as the
        # configured MegaRAID control device, it must not make the Samsung
        # RAID-owned.
        health = (
            DiskHealth(
                device="/dev/sda",
                serial="S3Y9NX0M629284D",
                smart_available=True,
                smartctl_exit_code=0,
                health_passed=True,
                temperature_c=34,
                reallocated_sectors=0,
                pending_sectors=0,
                offline_uncorrectable=0,
                crc_errors=0,
            ),
        )

        visible = storage_visible_disks(
            [samsung, raid_disk],
            health,
            discovery,
        )

        self.assertEqual(
            [disk.serial for disk in visible],
            ["S3Y9NX0M629284D"],
        )

    def test_sd_name_changes_do_not_change_ownership(self):
        raid_serial = "Z1N344E0"

        first_boot = Disk(
            device="/dev/sdd",
            vendor="Seagate",
            model="ST1000NM0011",
            serial=raid_serial,
            capacity_bytes=1000204886016,
            disk_type="HDD",
            transport="ATA",
        )
        second_boot = Disk(
            device="/dev/sdb",
            vendor="Seagate",
            model="ST1000NM0011",
            serial=raid_serial,
            capacity_bytes=1000204886016,
            disk_type="HDD",
            transport="ATA",
        )
        samsung = Disk(
            device="/dev/sda",
            vendor="Samsung",
            model="Samsung SSD 860 EVO 250GB",
            serial="S3Y9NX0M629284D",
            capacity_bytes=250059350016,
            disk_type="SSD",
            transport="SATA",
        )

        discovery = RaidDiscoveryResult(
            mode=RaidMode.MIXED,
            megaraid_controllers=(
                MegaRaidController(
                    controller_id=0,
                    control_device="/dev/sda",
                    drives=(
                        MegaRaidDrive(
                            controller=0,
                            enclosure=None,
                            slot=5,
                            device_id=20,
                            serial=raid_serial,
                            model="ST1000NM0011",
                            os_device="",
                        ),
                    ),
                ),
            ),
        )

        visible_first = storage_visible_disks(
            [samsung, first_boot],
            (),
            discovery,
        )
        visible_second = storage_visible_disks(
            [samsung, second_boot],
            (),
            discovery,
        )

        self.assertEqual(
            [disk.serial for disk in visible_first],
            ["S3Y9NX0M629284D"],
        )
        self.assertEqual(
            [disk.serial for disk in visible_second],
            ["S3Y9NX0M629284D"],
        )


if __name__ == "__main__":
    unittest.main()