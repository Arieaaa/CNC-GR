from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import audit
from core import build_manifest


class EvidenceContract(unittest.TestCase):
    def test_missing_formal_matrix_member_cannot_pass_audit(self):
        self.assertTrue(hasattr(audit,'matrix_issues'),'matrix coverage audit missing')
        manifest=build_manifest()
        self.assertEqual(audit.matrix_issues(manifest),[])
        self.assertTrue(audit.matrix_issues(manifest[1:]))

    def test_dynamic_wrong_source_flow_is_rejected(self):
        self.assertTrue(hasattr(audit,'audit_dynamic_contract'),'dynamic contract audit missing')
        tx=dict(nonce=42,durations=[30,30,30],rates_kbit=[300,900,300],payload_bytes=160)
        rx=dict(nonce=42,events=[{'source':'10.44.0.2:5202'}])
        config=dict(nonce=42,server_ip='10.44.0.100')
        with self.assertRaises(ValueError):audit.audit_dynamic_contract(tx,rx,config)

    def test_duplicate_config_repeat_with_different_names_is_rejected(self):
        manifest=build_manifest();duplicate=manifest[0]|{'id':'different','planned_id':'different'}
        self.assertTrue(audit.matrix_issues(manifest+[duplicate]))

    def test_audited_log_location_is_used_and_missing_data_fails(self):
        import tempfile
        self.assertTrue(hasattr(audit,'log_path'),'audited log resolver missing')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'custom-restoration';run=root/'one';run.mkdir(parents=True);path=run/'tcp-receiver.json';path.write_text('{}')
            self.assertEqual(audit.log_path({'logs_root':str(root)},'one','tcp-receiver.json'),path)
            with self.assertRaises(FileNotFoundError):audit.log_path({'logs_root':str(root)},'two','tcp-receiver.json')

    def test_sustained_resource_warning_does_not_automatically_exclude_data(self):
        import tempfile,json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in range(7):
                prefix=f'sample{i:03}';begin=i*1_000_000_000+(1_000_000_000 if i else 0)
                (root/(prefix+'-time.json')).write_text(json.dumps({'begin_ns':begin,'end_ns':begin+1_000_000}))
                (root/(prefix+'-cpu.txt')).write_text('cpu '+' '.join(str(x*i) for x in [30,0,20,44,0,0,0,6])+'\n')
                (root/(prefix+'-srv-qdisc.json')).write_text('[{"handle":"20:","backlog":0,"qlen":0}]')
            result=audit.resource_evidence(root)
            self.assertEqual(result['issues'],[])
            self.assertEqual(len(result['warnings']),2)

    def test_tcp_retransmissions_use_sender_and_bounded_phase(self):
        self.assertTrue(hasattr(audit,'sender_retransmissions'),'sender retransmission extraction missing')
        data={'intervals':[{'streams':[{'start':i,'end':i+1,'retransmits':i,'sender':True}]} for i in range(6)]}
        result=audit.sender_retransmissions(data,0,200_000_000,0,1,5)
        self.assertEqual(result['retransmits'],6)
        self.assertEqual(result['analyzed_seconds'],3)
        self.assertEqual(result['retransmits_per_second'],2)
        data['intervals'][1]['streams'][0]['sender']=False
        with self.assertRaises(ValueError):audit.sender_retransmissions(data,0,200_000_000,0,1,5)


if __name__=='__main__':unittest.main()
