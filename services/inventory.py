import json,subprocess
from services.disk_factory import DiskFactory
class InventoryService:
    def collect(self):
        data=json.loads(subprocess.check_output(['lsblk','-J','-d','-o','NAME,MODEL,SERIAL,SIZE'],text=True))
        return [DiskFactory.from_lsblk(x) for x in data['blockdevices']]
