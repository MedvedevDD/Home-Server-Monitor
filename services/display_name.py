class DisplayNameBuilder:
    @staticmethod
    def build(vendor,model,size): return ' '.join(x for x in [vendor,model,size] if x)
