import importlib.util
from pathlib import Path
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import summarize
import tempfile
import json

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('expc', ROOT / 'scripts' / 'expc.py')
expc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(expc)


class ExperimentContract(unittest.TestCase):
    def test_reverse_udp_matches_source_port_and_not_management_interface(self):
        commands = expc.queue_commands('srv-eth0', 'qos', 2000, 600, '10.44.0.1')
        flat = [' '.join(c) for c in commands]
        self.assertTrue(any('ip sport 5202 0xffff' in c and 'ip protocol 17 0xff' in c for c in flat))
        self.assertTrue(any('ip protocol 1 0xff' in c and 'flowid 1:10' in c for c in flat))
        with self.assertRaises(ValueError):
            expc.queue_commands('eth0', 'qos', 2000, 600, '10.44.0.1')

    def test_same_total_rate_and_buffer_budget(self):
        baseline = expc.queue_commands('srv-eth0', 'baseline', 2000, 600, '10.44.0.1')
        qos = expc.queue_commands('srv-eth0', 'qos', 2000, 600, '10.44.0.1')
        for commands in (baseline, qos):
            self.assertIn(['tc', 'class', 'add', 'dev', 'srv-eth0', 'parent', '1:', 'classid', '1:1', 'htb', 'rate', '2000kbit', 'ceil', '2000kbit'], commands)
        def buffer_bytes(commands):
            return sum(int(c[-1]) for c in commands if 'bfifo' in c)
        self.assertEqual(buffer_bytes(baseline), 32768)
        self.assertEqual(buffer_bytes(qos), 32768)
        self.assertTrue(any('1400kbit' in c for c in qos))

    def test_invalid_guarantee_rejected(self):
        for guarantee in (0, 2000, 3000):
            with self.assertRaises(ValueError):
                expc.queue_commands('srv-eth0', 'qos', 2000, guarantee, '10.44.0.1')

    def test_warmup_excluded_and_loss_weighted_by_packets(self):
        data = {'intervals': [
            {'streams': [{'sender': False, 'start': 0, 'end': 10, 'bytes': 100000, 'lost_packets': 100, 'packets': 100, 'jitter_ms': 90}]},
            {'streams': [{'sender': False, 'start': 10, 'end': 11, 'bytes': 1000, 'lost_packets': 1, 'packets': 10, 'jitter_ms': 2}]},
            {'streams': [{'sender': False, 'start': 11, 'end': 12, 'bytes': 3000, 'lost_packets': 0, 'packets': 90, 'jitter_ms': 4}]},
        ]}
        result = expc.interval_metrics(data, 10, 12, udp=True)
        self.assertAlmostEqual(result['received_mbps'], 0.016)
        self.assertAlmostEqual(result['udp_loss_percent'], 1.0)
        self.assertEqual(result['udp_jitter_interval_mean_ms'], 3)

    def test_iperf_error_is_not_packet_loss(self):
        with self.assertRaises(ValueError):
            expc.interval_metrics({'error': 'server busy'}, 10, 60, udp=True)

    def test_missing_udp_fields_not_reported_as_zero(self):
        data = {'intervals': [{'streams': [{'sender': False, 'start': 10, 'end': 11, 'bytes': 10}]}]}
        with self.assertRaisesRegex(ValueError, 'UDP区间缺少'):
            expc.interval_metrics(data, 10, 11, udp=True)

    def test_partial_window_rejected(self):
        data = {'intervals': [{'streams': [{'sender': False, 'start': 10, 'end': 11, 'bytes': 10}]}]}
        with self.assertRaisesRegex(ValueError, '窗口覆盖不完整'):
            expc.interval_metrics(data, 10, 60, udp=False)

    def test_udp_class_proof_cannot_use_counts_after_ping_started(self):
        with self.assertRaises(ValueError):
            expc.verify_udp_class({'1:10': 10000}, ping_started=True)
        with self.assertRaises(ValueError):
            expc.verify_udp_class({'1:10': 0}, ping_started=False)
        expc.verify_udp_class({'1:10': 10000}, ping_started=False)

    def test_requires_explicit_receiver(self):
        for sender in (None, True):
            row = {'start': 10, 'end': 11, 'bytes': 10000}
            if sender is not None:
                row['sender'] = sender
            with self.assertRaises(ValueError):
                expc.interval_metrics({'intervals': [{'streams': [row]}]}, 10, 11)

    def test_zero_background_tcp_is_not_valid_competition(self):
        data = {'intervals': [{'streams': [{'sender': False, 'start': 10, 'end': 11, 'bytes': 0}]}]}
        with self.assertRaises(ValueError):
            expc.interval_metrics(data, 10, 11)

    def test_queue_config_ignores_stats_but_detects_rate_and_filter_changes(self):
        a = {'qdisc': [{'kind': 'htb', 'handle': '1:', 'options': {'default': 32}, 'bytes': 10}],
             'class': [{'kind': 'htb', 'handle': '1:1', 'options': {'rate': 250000}, 'bytes': 10}],
             'filter': [{'kind': 'u32', 'options': {'flowid': '1:10', 'pcnt': {'success': 10}}}]}
        b = json.loads(json.dumps(a))
        b['class'][0]['bytes'] = 9999
        b['filter'][0]['options']['pcnt']['success'] = 9999
        self.assertEqual(expc.queue_signature(a), expc.queue_signature(b))
        b['class'][0]['options']['rate'] = 1000000
        self.assertNotEqual(expc.queue_signature(a), expc.queue_signature(b))
        b = json.loads(json.dumps(a))
        b['filter'] = []
        self.assertNotEqual(expc.queue_signature(a), expc.queue_signature(b))

    def test_no_runs_does_not_leave_stale_formal_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            out.mkdir()
            (out/'runs.csv').write_text('old formal results')
            (out/'summary.json').write_text('["old"]')
            summarize.summarize(Path(tmp)/'logs', out)
            self.assertFalse((out/'runs.csv').exists())
            self.assertFalse((out/'summary.json').exists())
            self.assertEqual(json.loads((out/'status.json').read_text())['valid_expC_runs'], 0)

    def test_htb_text_fallback_preserves_rates_and_counters(self):
        raw = ('class htb 1:1 root rate 2Mbit ceil 2Mbit burst 1600b cburst 1600b \n'
               ' Sent 1234 bytes 12 pkt (dropped 0, overlimits 0 requeues 0)\n'
               'class htb 1:10 parent 1:1 leaf 10: prio 0 rate 600Kbit ceil 2Mbit burst 1600b cburst 1600b\n'
               ' Sent 1000 bytes 10 pkt (dropped 0, overlimits 0 requeues 0)\n')
        rows = expc.parse_htb_classes(raw)
        self.assertEqual(rows[1]['handle'], '1:10')
        self.assertEqual(rows[1]['options']['rate'], '600Kbit')
        self.assertEqual(rows[1]['bytes'], 1000)
        self.assertEqual(rows[0]['options']['ceil'], '2Mbit')
        with self.assertRaises(ValueError):
            expc.parse_htb_classes('warning: unknown class format')


if __name__ == '__main__':
    unittest.main()
