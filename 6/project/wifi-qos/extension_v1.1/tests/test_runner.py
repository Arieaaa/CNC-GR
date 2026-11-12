from pathlib import Path
import sys
import unittest
import tempfile
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
try:
    import runner
except ImportError:
    runner=None


class RuntimeAudit(unittest.TestCase):
    def test_wrong_fq_limit_is_rejected_before_traffic(self):
        self.assertIsNotNone(runner,'runner missing')
        rows=[{'kind':'htb','handle':'1:','root':True},
              {'kind':'fq_codel','handle':'20:','options':{'limit':10240,'target':10000,'interval':100000,'ecn':False}}]
        with self.assertRaises(ValueError):runner.audit_qdisc(rows,{'mode':'fq_codel','buffer_bytes':32768})

    def test_valid_fq_configuration_is_accepted(self):
        self.assertIsNotNone(runner,'runner missing')
        rows=[{'kind':'htb','handle':'1:','root':True},
              {'kind':'fq_codel','handle':'20:','options':{'limit':22,'target':10000,'interval':100000,'ecn':False,
                                                        'quantum':1514,'flows':1024,'memory_limit':1048576}}]
        runner.audit_qdisc(rows,{'mode':'fq_codel','buffer_bytes':32768})

    def test_tc_microsecond_rounding_is_accepted_but_millisecond_drift_is_not(self):
        rows=[{'kind':'htb','handle':'1:','root':True},
              {'kind':'fq_codel','handle':'20:','options':{'limit':22,'target':9999,'interval':99999,
                    'quantum':1514,'flows':1024,'memory_limit':1048576}}]
        runner.audit_qdisc(rows,{'mode':'fq_codel','buffer_bytes':32768})
        rows[1]['options']['target']=9000
        with self.assertRaises(ValueError):runner.audit_qdisc(rows,{'mode':'fq_codel','buffer_bytes':32768})

    def test_reversed_realtime_and_background_buffers_are_rejected(self):
        rows=[{'kind':'htb','handle':'1:','root':True},
              {'kind':'bfifo','handle':'10:','options':{'limit':24576}},
              {'kind':'bfifo','handle':'20:','options':{'limit':8192}}]
        with self.assertRaises(ValueError):runner.audit_qdisc(rows,{'mode':'qos','buffer_bytes':32768})

    def test_wrong_rate_is_rejected_even_with_valid_qdiscs(self):
        rows=[{'kind':'htb','handle':'1:1','root':True,'options':{'rate':'2Mbit','ceil':'2Mbit','burst':'4Kb','cburst':'4Kb'}},
              {'kind':'htb','handle':'1:20','parent':'1:1','options':{'rate':'3Mbit','ceil':'3Mbit','burst':'4Kb','cburst':'4Kb','quantum':'1514','prio':'0'}}]
        self.assertTrue(hasattr(runner,'audit_classes'),'class audit missing')
        with self.assertRaises(ValueError):runner.audit_classes(rows,{'mode':'baseline','rt_kbit':600})

    def test_trailing_receiver_overflow_is_rejected_from_snmp_delta(self):
        self.assertTrue(hasattr(runner,'audit_udp_errors'),'SNMP audit missing')
        before='Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors\nUdp: 1 0 0 1 0\n'
        after='Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors\nUdp: 5 0 2 1 2\n'
        with self.assertRaises(ValueError):runner.audit_udp_errors(before,after)

    def test_oversized_fq_packet_and_memory_drops_are_invalid(self):
        self.assertTrue(hasattr(runner,'audit_final_fq'),'FQ capacity audit missing')
        with self.assertRaises(ValueError):runner.audit_final_fq([{'kind':'fq_codel','maxpacket':65000,'drop_overmemory':0}])
        with self.assertRaises(ValueError):runner.audit_final_fq([{'kind':'fq_codel','maxpacket':1514,'drop_overmemory':1}])

    def test_existing_batch_provenance_is_never_overwritten(self):
        import batch
        self.assertTrue(hasattr(batch,'prepare_batch'),'safe batch init missing')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'batch';root.mkdir();p=root/'manifest.json';p.write_text('[1]')
            with self.assertRaises(FileExistsError):batch.prepare_batch(root,[2],{})
            self.assertEqual(p.read_text(),'[1]')

    def test_tc_detailed_burst_keeps_size_before_cell_suffix(self):
        rows=[{'kind':'htb','handle':'1:1','root':True,'options':{'rate':'2Mbit','ceil':'2Mbit','burst':'4Kb/1','cburst':'4Kb/1'}},
              {'kind':'htb','handle':'1:20','parent':'1:1','options':{'rate':'2Mbit','ceil':'2Mbit','burst':'4Kb/1','cburst':'4Kb/1','quantum':'1514','prio':'0'}}]
        runner.audit_classes(rows,{'mode':'baseline','rt_kbit':600})

    def test_duplicate_tc_match_keys_preserve_protocol_and_source_port(self):
        self.assertTrue(hasattr(runner,'preserve_matches'),'u32 normalization missing')
        raw='{"options":{"match":{"value":"110000","off":8},"match":{"value":"14520000","off":20}}}'
        value=json.loads(raw,object_pairs_hook=runner.preserve_matches)
        self.assertEqual([x['off'] for x in value['options']['matches']],[8,20])

    def test_static_iperf_shutdown_noports_is_recorded_separately_from_overflow(self):
        before='Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors\nUdp: 1 0 0 1 0\n'
        after='Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors\nUdp: 5 30 0 1 0\n'
        delta=runner.audit_udp_errors(before,after,allow_noports=True)
        self.assertEqual(delta['NoPorts'],30)
        with self.assertRaises(ValueError):runner.audit_udp_errors(before,after)


if __name__=='__main__':unittest.main()
