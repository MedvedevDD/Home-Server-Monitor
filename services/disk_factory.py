from models.disk import Disk
from services.vendor import VendorResolver
from services.display_name import DisplayNameBuilder
class DiskFactory:
    @staticmethod
    def from_lsblk(info):
        v=VendorResolver.resolve(info.get('model',''))
        return Disk(serial=info.get('serial',''),vendor=v,model=info.get('model',''),display_name=DisplayNameBuilder.build(v,info.get('model',''),info.get('size','')),capacity=info.get('size',''),capacity_bytes=0,disk_type='',transport='',device='/dev/'+info.get('name',''))
