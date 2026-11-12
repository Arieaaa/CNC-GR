import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
try:
    import analysis
except ImportError:
    analysis=None


class AnalysisContract(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(analysis, 'dynamic audit missing')

    def test_mismatched_time_namespaces_are_rejected(self):
        tx={'environment':{'time_namespace':'a','boot_id':'b'}}
        rx={'environment':{'time_namespace':'c','boot_id':'b'}}
        with self.assertRaises(ValueError):analysis.validate_clocks(tx,rx)

    def test_tcp_window_keeps_only_intervals_certainly_inside_phase(self):
        data={'intervals':[{'streams':[{'start':i,'end':i+1,'bytes':125000,'sender':False}]} for i in range(6)]}
        m=analysis.tcp_window(data,0,200_000_000,0,1,5)
        self.assertEqual(m['interval_count'],3)
        self.assertEqual(m['received_mbps'],1)
        self.assertEqual(m['analyzed_seconds'],3)

    def test_pacing_failure_is_invalid_even_when_received_loss_is_zero(self):
        tx={'durations':[1,1,1],'rates_kbit':[300,900,300],'t0_ns':0,
            'events':[{'seq':0,'phase':0,'send_ns':0,'scheduled_ns':0,'spacing_ns':1,'lateness_ns':2,'ok':False}]}
        errors=analysis.pacing_errors(tx)
        self.assertTrue(errors)

    def test_missing_tcp_coverage_is_rejected(self):
        data={'intervals':[{'streams':[{'start':15,'end':16,'bytes':125000,'sender':False}]}]}
        with self.assertRaises(ValueError):analysis.tcp_window(data,0,100_000_000,0,0,30)

    def test_internal_tcp_gap_is_rejected(self):
        data={'intervals':[{'streams':[{'start':i,'end':i+1,'bytes':125000,'sender':False}]} for i in [0,1,3,4,5]]}
        with self.assertRaises(ValueError):analysis.tcp_window(data,0,0,0,0,6)


if __name__=='__main__':unittest.main()
