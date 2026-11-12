#!/usr/bin/env python3
"""整理真实PASS日志；不接受基础验收充当实验C结果。"""
import argparse
import csv
import json
from pathlib import Path
import statistics


def summarize(root, output):
    rows, rejected = [], []
    for directory in sorted(Path(root).glob('expC_*')):
        if not directory.is_dir():
            continue
        try:
            if (directory / 'status.txt').read_text().strip() != 'PASS':
                raise ValueError('状态非PASS')
            config = json.loads((directory / 'config.json').read_text())
            if config['mode'] == 'capacity':
                continue
            metric = json.loads((directory / 'metrics.json').read_text())
            row = {k: config[k] for k in ('mode', 'run', 'total_kbit', 'rt_kbit', 'udp_kbit', 'seconds', 'warmup', 'runner_sha256', 'topology_sha256')}
            row['directory'] = directory.name
            row.update(udp_received_mbps=metric['udp']['received_mbps'],
                       udp_loss_percent=metric['udp']['udp_loss_percent'],
                       udp_jitter_interval_mean_ms=metric['udp']['udp_jitter_interval_mean_ms'],
                       tcp_received_mbps=metric.get('tcp', {}).get('received_mbps'),
                       rtt_mean_ms=metric['rtt']['mean_ms'], rtt_p95_ms=metric['rtt']['p95_ms'])
            rows.append(row)
        except (ValueError, KeyError, OSError) as error:
            rejected.append({'directory': directory.name, 'reason': str(error)})
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name in ('runs.csv', 'summary.json', 'status.json'):
        (output / name).unlink(missing_ok=True)
    (output / 'rejected.json').write_text(json.dumps(rejected, ensure_ascii=False, indent=2))
    if not rows:
        (output / 'status.json').write_text(json.dumps({'valid_expC_runs': 0, 'message': '没有正式实验C结果，不能计算QoS收益'}, ensure_ascii=False, indent=2))
        print('没有正式实验C结果；未生成性能对比。')
        return
    with (output / 'runs.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    groups = {}
    for row in rows:
        keys = ('mode', 'total_kbit', 'rt_kbit', 'udp_kbit', 'seconds', 'warmup', 'runner_sha256', 'topology_sha256')
        key = tuple(row[k] for k in keys)
        groups.setdefault(key, []).append(row)
    summaries = []
    for key, runs in groups.items():
        result = dict(zip(keys, key))
        result.update(n=len(runs), unique_repeat_ids=len({r['run'] for r in runs}),
                      meets_repeat_minimum=len({r['run'] for r in runs}) >= 3)
        for field in ('udp_received_mbps', 'udp_loss_percent', 'udp_jitter_interval_mean_ms', 'tcp_received_mbps', 'rtt_mean_ms', 'rtt_p95_ms'):
            values = [r[field] for r in runs if r[field] is not None]
            result[field] = {'mean': statistics.mean(values), 'sample_sd': statistics.stdev(values) if len(values) > 1 else None} if values else None
        summaries.append(result)
    (output / 'summary.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2))
    (output / 'status.json').write_text(json.dumps({'valid_expC_runs': len(rows), 'groups': len(summaries),
                                                  'rejected_runs': len(rejected)}, ensure_ascii=False, indent=2))
    print(f'有效实验C运行 {len(rows)} 轮；分组汇总 {len(summaries)} 组；异常 {len(rejected)} 轮。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('logs')
    parser.add_argument('output')
    args = parser.parse_args()
    summarize(args.logs, args.output)
