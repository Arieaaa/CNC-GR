import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


class UDPIntegration(unittest.TestCase):
    def test_real_socket_retains_one_flow_and_accounts_all_phases(self):
        script=Path(__file__).resolve().parents[1]/'scripts/udp_phase.py'
        self.assertTrue(script.exists(), 'UDP phase runner missing')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1];probe.close()
            probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            probe.bind(('127.0.0.1',0));source=probe.getsockname()[1];probe.close()
            t0=time.monotonic_ns()+500_000_000
            common=[sys.executable,str(script),'--nonce','42','--t0-ns',str(t0),
                    '--durations','0.3,0.3,0.3','--rates','300,900,300','--port',str(port)]
            receiver=subprocess.Popen(common+['receive','--bind','127.0.0.1','--output',str(root/'rx.json')])
            time.sleep(.1)
            sender=subprocess.run(common+['send','--bind','127.0.0.1','--source-port',str(source),
                                          '--destination','127.0.0.1','--output',str(root/'tx.json')],timeout=5)
            self.assertEqual(sender.returncode,0)
            self.assertEqual(receiver.wait(timeout=5),0)
            tx=json.loads((root/'tx.json').read_text());rx=json.loads((root/'rx.json').read_text())
            self.assertTrue(tx['events'])
            self.assertEqual({x['phase'] for x in tx['events']},{0,1,2})
            self.assertEqual({x['source'] for x in rx['events']},{f'127.0.0.1:{source}'})
            self.assertEqual(len(rx['events']),sum(x['ok'] for x in tx['events']))
            self.assertEqual(rx['malformed'],0)
            self.assertEqual([x['seq'] for x in rx['events']], sorted(x['seq'] for x in rx['events']))


if __name__=='__main__':unittest.main()
