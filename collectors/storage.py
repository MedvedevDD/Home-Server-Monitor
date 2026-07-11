from collectors.base import BaseCollector
from services.inventory import InventoryService
class StorageCollector(BaseCollector):
    def collect(self): return InventoryService().collect()