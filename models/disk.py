from dataclasses import dataclass
@dataclass
class Disk:
    """Disk state model."""
    serial:str="" # Serial
    vendor:str="" # Vendor
    model:str="" # Model
    display_name:str="" # Display
    capacity:str="" # Human size
    capacity_bytes:int=0 # Bytes
    disk_type:str="" # Type
    transport:str="" # Bus
    device:str="" # Device
    temperature:float|None=None # Temp
    smart_health:str|None=None # SMART
    reallocated:int=0
    pending:int=0
    offline:int=0
    crc:int=0
