import json
import unittest
from services.command_runner import CommandResult
from services.storcli import StorCliService

class QueueRunner:
    def __init__(self, outputs):
        self.outputs=list(outputs); self.commands=[]
    def run(self, command):
        self.commands.append(list(command))
        return CommandResult(self.outputs.pop(0), "", 0)

class StorCliDirectDiscoveryTests(unittest.TestCase):
    def test_direct_attached_fallback(self):
        first={"Controllers":[{"Response Data":{"Controller":0}}]}
        second={"Controllers":[{"Response Data":{"Controller":0,"PD LIST":[
            {"EID:Slt":":4","DID":21,"State":"JBOD","Model":"ST4000VX000-1F4168"},
            {"EID:Slt":":5","DID":20,"State":"JBOD","Model":"ST1000NM0011"}
        ]}}]}
        r=QueueRunner([json.dumps(first),json.dumps(second)])
        drives=StorCliService(runner=r).list_physical_drives()
        self.assertEqual([(d.enclosure,d.slot,d.device_id) for d in drives],[(None,4,21),(None,5,20)])
        self.assertTrue(any(c[-5:] == ["/call", "/sall", "show", "all", "J"] for c in r.commands))

    def test_enclosure_path_keeps_single_query(self):
        first={"Controllers":[{"Response Data":{"Controller":0,"PD LIST":[
            {"EID:Slt":"252:4","DID":21,"State":"JBOD"}
        ]}}]}
        r=QueueRunner([json.dumps(first)])
        drives=StorCliService(runner=r).list_physical_drives()
        self.assertEqual((drives[0].enclosure,drives[0].slot),(252,4))
        self.assertEqual(len(r.commands),1)

if __name__=="__main__":
    unittest.main()