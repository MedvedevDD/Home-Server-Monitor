from influxdb_client import InfluxDBClient
class InfluxOutput:
    def __init__(self,url,token,org,bucket):
        self.client=InfluxDBClient(url=url,token=token,org=org); self.api=self.client.write_api(); self.bucket=bucket
    def write(self,metrics): self.api.write(bucket=self.bucket,record=[m.to_line_protocol() for m in metrics])
    def close(self): self.client.close()
    def __enter__(self): return self
    def __exit__(self,*a): self.close()
