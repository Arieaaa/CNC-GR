#!/usr/bin/env python3
"""重新从原始日志核验正式6轮，输出配置、队列及资源审计。"""
from pathlib import Path
import json
import sys
import hashlib
import re
import math
import statistics
from datetime import datetime

from expc import interval_metrics, saved_queue_signature, class_bytes


def cpu(path):
    values = [int(x) for x in path.read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3]+values[4], values[7]


def audit(root):
    root = Path(root)
    records = []
    signatures = set()
    for directory in sorted((root/'logs').glob('expC_*')):
        config = json.loads((directory/'config.json').read_text())
        if config['mode'] not in ('baseline', 'qos') or config['run'] >= 90:
            continue
        assert config['seconds'] == 60 and config['warmup'] == 10
        assert (directory/'status.txt').read_text().strip() == 'PASS', directory.name
        assert config['total_kbit'] == 2000 and config['rt_kbit'] == 600 and config['udp_kbit'] == 300
        assert config['channels'] == [1,6] and config['server_interface'] == 'srv-eth0'
        signatures.add(tuple(config[key] for key in ('runner_sha256','topology_sha256')))
        expected = saved_queue_signature(directory, 'configured')
        samples = sorted(directory.glob('sample*-srv-class.json'))
        assert len(samples) >= 50, directory.name
        for path in samples:
            prefix = path.name.removesuffix('-srv-class.json')
            assert saved_queue_signature(directory, prefix) == expected
        assert saved_queue_signature(directory, 'after') == expected
        parent = next(row for row in expected['class'] if row['handle'] == '1:1')
        assert parent['options']['rate'] == '2Mbit' and parent['options']['ceil'] == '2Mbit'
        assert sum(r['options']['limit'] for r in expected['qdisc'] if r['kind'] == 'bfifo') == 32768
        if config['mode'] == 'qos':
            assert class_bytes(directory, 'before-icmp')['1:10'] > 0
        computed = {}
        for protocol in ('udp', 'tcp'):
            data = json.loads((directory/f'{protocol}-receiver.json').read_text())
            assert data['start']['test_start']['reverse'] == 1
            assert data['start']['test_start']['num_streams'] == 1
            computed[protocol] = interval_metrics(data, 10, 60, udp=protocol=='udp')
        stored = json.loads((directory/'metrics.json').read_text())
        assert computed['udp'] == stored['udp'] and computed['tcp'] == stored['tcp']
        started = datetime.fromisoformat(config['traffic_started_utc']).timestamp()
        probes=[]
        for line in (directory/'ping.txt').read_text().splitlines():
            match = re.search(r'^\[(\d+\.\d+)\].*icmp_seq=(\d+).*time[=<]([\d.]+) ms', line)
            if match and 10 <= float(match[1])-started < 60:
                probes.append((int(match[2]),float(match[3])))
        assert probes, '没有可复算的稳态RTT'
        assert len({seq for seq, _ in probes}) == len(probes), '存在重复ICMP应答'
        rtts=sorted(value for _,value in probes)
        assert abs(statistics.mean(rtts)-stored['rtt']['mean_ms']) < 1e-9
        assert rtts[math.ceil(.95*len(rtts))-1] == stored['rtt']['p95_ms']
        assert len(rtts) == stored['rtt']['successful_samples']
        sequence_numbers={seq for seq, _ in probes}
        internal_gaps=max(sequence_numbers)-min(sequence_numbers)+1-len(sequence_numbers)
        before = cpu(directory/'before-cpu.txt')
        after = cpu(directory/'after-cpu.txt')
        total = after[0]-before[0]
        host_cpu = 100*(1-(after[1]-before[1])/total)
        steal = 100*(after[2]-before[2])/total
        qdiscs = json.loads((directory/'after-srv-qdisc.json').read_text())
        root_qdisc = next(row for row in qdiscs if row['kind'] == 'htb')
        peak_backlog = max(next(r['backlog'] for r in json.loads((p.parent/p.name.replace('-class.json','-qdisc.json')).read_text()) if r['kind']=='htb') for p in samples)
        records.append({'directory': directory.name, 'mode': config['mode'], 'run': config['run'],
                        'queue_snapshots': len(samples), 'configuration_stable': True,
                        'cpu_busy_percent': host_cpu, 'cpu_steal_percent': steal,
                        'root_sent_bytes': root_qdisc['bytes'], 'root_drops': root_qdisc['drops'],
                        'root_overlimits': root_qdisc['overlimits'], 'peak_backlog_bytes': peak_backlog,
                        'class_bytes': class_bytes(directory, 'after'),
                        'rtt_recomputed': True, 'rtt_internal_sequence_gaps': internal_gaps,
                        'metrics': stored})
    assert len(records) == 6, f'正式轮次不为6: {len(records)}'
    for mode in ('baseline', 'qos'):
        assert {r['run'] for r in records if r['mode']==mode} == {1,2,3}
    assert len(signatures) == 1, '正式运行的代码版本不一致'
    code_sha, topology_sha = next(iter(signatures))
    assert code_sha == hashlib.sha256((root/'scripts/expc.py').read_bytes()).hexdigest()
    result={'formal_runs': 6, 'checks_passed': True, 'runner_sha256': code_sha,
            'topology_sha256': topology_sha, 'records': records}
    (root/'results/audit.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print('AUDIT PASS: 6 runs, same parameters and code, stable queues, independent UDP class proof, raw metrics reproduced')
    for row in records:
        print(row['mode'], row['run'], 'CPU%',round(row['cpu_busy_percent'],2),
              'steal%', round(row['cpu_steal_percent'],2), 'peak_backlog_bytes',row['peak_backlog_bytes'])


if __name__ == '__main__':
    audit(sys.argv[1])
