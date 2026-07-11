class VendorResolver:
    MAP={'ST':'Seagate','WDC':'Western Digital','WD':'Western Digital','MG':'Toshiba','SAMSUNG':'Samsung','KINGSTON':'Kingston','CRUCIAL':'Crucial','INTEL':'Intel'}
    @classmethod
    def resolve(cls,model:str)->str:
        u=(model or '').upper()
        for k,v in cls.MAP.items():
            if u.startswith(k): return v
        return 'Unknown'
