#!/usr/bin/env python3
"""用已核查的正式60秒日志生成可导出的科学图表。"""
import csv
import json
from pathlib import Path
import statistics
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def plot(root):
    root = Path(root)
    output = root / 'results'
    audit = json.loads((output/'audit.json').read_text())
    assert audit['checks_passed'] and audit['formal_runs'] == 6
    rows=[]
    for record in audit['records']:
        config=json.loads((root/'logs'/record['directory']/'config.json').read_text())
        assert config['seconds']==60 and config['warmup']==10
        metric=record['metrics']
        rows.append(config | {'directory':record['directory'],
                    'udp_loss_percent':metric['udp']['udp_loss_percent'],
                    'udp_jitter_interval_mean_ms':metric['udp']['udp_jitter_interval_mean_ms'],
                    'rtt_p95_ms':metric['rtt']['p95_ms'],
                    'tcp_received_mbps':metric['tcp']['received_mbps']})
    groups = {mode: [r for r in rows if r['mode'] == mode] for mode in ('baseline', 'qos')}
    if any(len(v) < 3 for v in groups.values()):
        raise SystemExit('需要两组各至少3轮正式结果')
    signatures = {(r['total_kbit'], r['rt_kbit'], r['udp_kbit'], r['runner_sha256'], r['topology_sha256']) for r in rows}
    if len(signatures) != 1:
        raise SystemExit('正式数据含多个参数/代码版本，请先筛选一致配置')
    plt.rcParams.update({'font.size': 11, 'axes.spines.top': False, 'axes.spines.right': False,
                         'savefig.dpi': 200, 'axes.grid': True, 'grid.alpha': .2})
    colors = ['#6c7a89', '#147d92']
    panels = [('udp_loss_percent', 'UDP packet loss (%)'),
              ('udp_jitter_interval_mean_ms', 'Mean reported UDP jitter (ms)'),
              ('rtt_p95_ms', 'P95 probe RTT (ms)'),
              ('tcp_received_mbps', 'Background TCP goodput (Mbit/s)')]
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    for ax, (field, label) in zip(axes.flat, panels):
        for i, (mode, runs) in enumerate(groups.items()):
            values = [float(r[field]) for r in runs]
            mean, sd = statistics.mean(values), statistics.stdev(values)
            ax.bar(i, mean, width=.55, color=colors[i], alpha=.65)
            ax.errorbar(i, mean, yerr=sd, color='#24313b', capsize=5, fmt='none')
            offsets = [(-.12 + .24 * j / max(1, len(values)-1)) for j in range(len(values))]
            ax.scatter([i+x for x in offsets], values, color=colors[i], edgecolors='white', zorder=3)
            ax.annotate(f'{mean:.3g}', (i, mean+sd), xytext=(0, 8), textcoords='offset points', ha='center')
        ax.set_xticks([0, 1], ['Shared FIFO', 'Classified HTB'])
        ax.set_ylabel(label)
        ax.set_ylim(bottom=0)
    cap = rows[0]['total_kbit']
    fig.suptitle(f'Experiment C: same {cap} kbit/s server egress cap\n60 s per run; 10 s warm-up excluded; n = 3/group; error bars = sample SD')
    fig.savefig(output / 'expc_comparison.png')
    fig.savefig(output / 'expc_comparison.pdf')
    plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, constrained_layout=True)
    for mode, runs in groups.items():
        representative = next((r for r in runs if int(r['run']) == 1), runs[0])
        directory = root / 'logs' / representative['directory']
        color = colors[0 if mode == 'baseline' else 1]
        label = 'Shared FIFO' if mode == 'baseline' else 'Classified HTB'
        for filename, field, ax, factor in [('udp-receiver.json', 'jitter_ms', axes[0], 1),
                                            ('tcp-receiver.json', 'bytes', axes[2], 8/1e6)]:
            data = json.loads((directory / filename).read_text())
            streams = [interval['streams'][0] for interval in data['intervals']]
            ax.plot([s['end'] for s in streams],
                    [s[field]*factor/(s['end']-s['start']) if field == 'bytes' else s[field] for s in streams],
                    color=color, label=label)
        import re
        from datetime import datetime
        config = json.loads((directory / 'config.json').read_text())
        start = datetime.fromisoformat(config['traffic_started_utc']).timestamp()
        pairs=[]
        for line in (directory / 'ping.txt').read_text().splitlines():
            match = re.search(r'^\[(\d+\.\d+)\].*time[=<]([\d.]+) ms', line)
            if match:
                pairs.append((float(match[1])-start, float(match[2])))
        axes[1].plot([a for a,b in pairs], [b for a,b in pairs], color=color, label=label, alpha=.8)
    for ax in axes:
        ax.axvspan(0, 10, color='#aaaaaa', alpha=.15)
        ax.set_ylim(bottom=0)
        ax.legend(loc='upper right')
    axes[0].set_ylabel('UDP jitter (ms)')
    axes[1].set_ylabel('Probe RTT (ms)')
    axes[2].set_ylabel('TCP goodput (Mbit/s)')
    axes[2].set_xlabel('Seconds from traffic start (shading = warm-up)')
    fig.suptitle('Representative run 01: receiver-side time series')
    fig.savefig(output / 'expc_timeseries.png')
    fig.savefig(output / 'expc_timeseries.pdf')
    plt.close(fig)
    print('Generated comparison and time-series PNG/PDF figures')


if __name__ == '__main__':
    plot(sys.argv[1])
