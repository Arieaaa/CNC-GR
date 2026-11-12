import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
try:
    import core
except ImportError:
    core = None


class CoreContract(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(core, 'extension core has not been implemented')

    def test_fq_keeps_total_shaper_and_separate_packet_limit(self):
        commands = core.queue_commands('srv-eth0', 'fq_codel', 600, 32768, '10.44.0.1')
        classes = [x for x in commands if x[1] == 'class']
        self.assertEqual(len(classes), 2)
        self.assertTrue(all(x[x.index('rate')+1] == '2000kbit' for x in classes))
        fq = commands[-1]
        self.assertEqual(fq[fq.index('limit')+1], '22')
        self.assertEqual(fq[fq.index('target')+1], '10ms')
        self.assertIn('noecn', fq)

    def test_underprovision_keeps_requested_200_and_remaining_1800(self):
        commands = core.queue_commands('srv-eth0', 'qos', 200, 16384, '10.44.0.1')
        classes = [x for x in commands if x[1] == 'class']
        self.assertEqual([x[x.index('rate')+1] for x in classes], ['2000kbit','200kbit','1800kbit'])
        leaves = [x for x in commands if 'bfifo' in x]
        self.assertEqual([x[-1] for x in leaves], ['4096','12288'])

    def test_management_interface_is_rejected(self):
        with self.assertRaises(ValueError):
            core.queue_commands('eth0', 'baseline', 600, 32768, '10.44.0.1')

    def test_packet_includes_header_inside_160_bytes(self):
        data = core.encode_packet(7, 2, 91, 1000)
        self.assertEqual(len(data), 160)
        self.assertEqual(core.decode_packet(data, 7), (2,91,1000))
        with self.assertRaises(ValueError):
            core.decode_packet(data, 8)
        with self.assertRaises(ValueError):
            core.decode_packet(b'incomplete', 7)

    def test_phase_boundaries_do_not_change_flow_or_extend_phase(self):
        self.assertEqual(core.phase_at(29.999, [30,30,30]), 0)
        self.assertEqual(core.phase_at(30, [30,30,30]), 1)
        self.assertEqual(core.phase_at(60, [30,30,30]), 2)
        self.assertIsNone(core.phase_at(90, [30,30,30]))

    def test_loss_duplicates_late_and_out_of_order_are_distinguished(self):
        sent = [dict(seq=i,send_ns=i*1_000_000_000,ok=True) for i in range(4)]
        rx = [dict(seq=2,recv_ns=2_060_000_000),dict(seq=0,recv_ns=10_000_000),
              dict(seq=0,recv_ns=20_000_000)]
        m = core.packet_metrics(sent, rx, 0, 4, 0)
        self.assertEqual(m['sent_packets'], 4)
        self.assertEqual(m['received_packets'], 2)
        self.assertEqual(m['loss_percent'], 50)
        self.assertEqual(m['on_time_percent'], 25)
        self.assertEqual(m['duplicates'], 1)
        self.assertEqual(m['delay_p95_ms'], 60)

    def test_complete_loss_has_no_fabricated_zero_delay(self):
        m=core.packet_metrics([dict(seq=0,send_ns=0,ok=True)], [], 0, 1, 0)
        self.assertEqual(m['loss_percent'], 100)
        self.assertIsNone(m['delay_p95_ms'])

    def test_send_errors_are_not_network_loss(self):
        m=core.packet_metrics([dict(seq=0,send_ns=0,ok=False)], [], 0, 1, 0)
        self.assertEqual(m['send_errors'], 1)
        self.assertEqual(m['sent_packets'], 0)
        self.assertIsNone(m['loss_percent'])

    def test_negative_delay_rejects_untrusted_clock(self):
        with self.assertRaises(ValueError):
            core.packet_metrics([dict(seq=0,send_ns=10,ok=True)], [dict(seq=0,recv_ns=9)], 0, 1, 0)

    def test_matrix_has_48_unique_runs_and_correct_duration(self):
        m=core.build_manifest(20261111)
        self.assertEqual(len(m),48)
        self.assertEqual(len({x['id'] for x in m}),48)
        self.assertEqual(sum(x['seconds'] for x in m),3240)
        self.assertEqual(sum(x['workload']=='dynamic' for x in m),12)


if __name__ == '__main__':
    unittest.main()
