from dataclasses import dataclass,field
def escape_tag(v): return str(v).replace("\\","\\\\").replace(" ","\\ ").replace(",","\\,").replace("=","\\=")
def escape_string(v): return str(v).replace("\\","\\\\").replace('"','\\"')
def encode_field(v):
    if isinstance(v,bool): return "true" if v else "false"
    if isinstance(v,int): return f"{v}i"
    if isinstance(v,float): return format(v,"g")
    return f'"{escape_string(v)}"'
@dataclass
class Metric:
    """Influx metric."""
    measurement:str; tags:dict=field(default_factory=dict); fields:dict=field(default_factory=dict); timestamp:int|None=None
    def __post_init__(self):
        if not self.fields: raise ValueError("Metric requires at least one field")
    def to_line_protocol(self):
        """Serialize."""
        t=",".join(f"{escape_tag(k)}={escape_tag(v)}" for k,v in self.tags.items())
        f=",".join(f"{escape_tag(k)}={encode_field(v)}" for k,v in self.fields.items())
        s=self.measurement+(","+t if t else "")+" "+f
        return s if self.timestamp is None else s+" "+str(self.timestamp)
    def line_protocol(self): """Compatibility."""; return self.to_line_protocol()
