#!/usr/bin/env python3
"""Normalize known wifi-lab smoke logs without changing raw files."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys


def write_csv(path, rows, fields):
    with path.open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description='将一次 smoke 原始目录整理成 CSV 和问题清单，不覆盖已有输出。')
    parser.add_argument('raw_dir', type=Path)
    parser.add_argument('--out', required=True, type=Path, help='新的输出目录；不得位于原始目录内')
    args = parser.parse_args()
    raw, out = args.raw_dir.resolve(), args.out.resolve()
    if not raw.is_dir():
        parser.error('原始目录不存在')
    if out == raw or raw in out.parents:
        parser.error('输出目录不得位于原始目录内')
    if out.exists():
        parser.error('输出目录已存在，不会覆盖')
    issues = []
    def issue(file, message):
        issues.append({'run_id': raw.name, 'source_ref': file, 'issue': message})
    def read(name):
        try:
            return (raw / name).read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            issue(name, '读取失败: ' + str(exc))
            return ''
    def read_json(name):
        text = read(name)
        if not text:
            return {}
        try:
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError('顶层不是对象')
            return obj
        except (ValueError, json.JSONDecodeError) as exc:
            issue(name, 'JSON 格式无效: ' + str(exc))
            return {}
    config = read_json('config.json')
    if config.get('kind') != 'smoke':
        parser.error('仅支持 config.json 中 kind 为 smoke 的基础验收；正式日志尚未适配')
    status = read('status.txt').strip()
    if status != 'PASS':
        issue('status.txt', '状态不是 PASS: ' + (status or '缺失'))
    count = config.get('stations')
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 100:
        parser.error('config.json 的 stations 缺失或无效')
    for name in ['run.log', 'source-versions.txt', 'iperf3-server.txt', 'ap1-iw-info.txt', 'ap2-iw-info.txt']:
        read(name)
    channels = config.get('channels', [])
    rows = []
    for n in range(1, count + 1):
        sta = 'sta' + str(n)
        link_file, ping_file = sta + '-iw-link.txt', sta + '-ping.txt'
        link, ping = read(link_file), read(ping_file)
        mac = re.search(r'Connected to\s+([0-9a-f:]{17})', link, re.I)
        signal = re.search(r'\bsignal:\s*(-?\d+(?:\.\d+)?)\s*dBm', link)
        packets = re.search(r'(\d+) packets transmitted,\s*(\d+) received,\s*([\d.]+)% packet loss', ping)
        rtt = re.search(r'rtt min/avg/max/mdev\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)\s*ms', ping)
        if not mac: issue(link_file, '未读取到实际关联 BSSID')
        if not packets: issue(ping_file, '未读取到 ping 汇总')
        if not rtt: issue(ping_file, '未读取到 RTT 汇总；无成功响应时可能不存在')
        iperf_name = sta + '-iperf3.json'
        received = duration = endpoint = ''
        if n <= 2:  # The documented smoke entry tests only the first two stations.
            data = read_json(iperf_name)
            if data.get('error'): issue(iperf_name, 'iperf3 报错: ' + str(data['error']))
            summary = data.get('end', {}).get('sum_received', {})
            if isinstance(summary.get('bits_per_second'), (float, int)):
                received = summary['bits_per_second'] / 1_000_000
                duration = summary.get('seconds', '')
            else: issue(iperf_name, '缺少接收端汇总吞吐')
            connected = data.get('start', {}).get('connected', [])
            if connected: endpoint = connected[0].get('local_host', '')
        rows.append({'run_id': raw.name, 'station': sta, 'bssid': mac.group(1) if mac else '',
                     'signal_model_dbm': signal.group(1) if signal else '',
                     'ping_sent': packets.group(1) if packets else '', 'ping_received': packets.group(2) if packets else '',
                     'ping_loss_pct': packets.group(3) if packets else '', 'rtt_mean_ms': rtt.group(2) if rtt else '',
                     'tcp_receiver_mbps': received, 'tcp_window_s': duration, 'tcp_client_ip': endpoint,
                     'source_ref': link_file + ';' + ping_file + (';' + iperf_name if n <= 2 else '')})
    run = {'run_id': raw.name, 'kind': config.get('kind', ''), 'operator': config.get('operator', ''),
           'started_utc': config.get('started_utc', ''), 'status': status, 'station_count': count,
           'ap_channels': '/'.join(str(x) for x in channels), 'ssid': config.get('ssid', ''),
           'channel_width_mhz': config.get('channel_width_mhz', ''), 'direction': config.get('iperf3_direction', ''),
           'raw_dir': str(raw), 'source_ref': 'config.json;status.txt'}
    if any(not run[k] for k in ('operator','started_utc','ssid','direction')):
        issue('config.json', '部分运行元信息缺失')
    out.mkdir(parents=True)
    write_csv(out / '运行记录.csv', [run], list(run))
    fields = ['run_id','station','bssid','signal_model_dbm','ping_sent','ping_received','ping_loss_pct','rtt_mean_ms','tcp_receiver_mbps','tcp_window_s','tcp_client_ip','source_ref']
    write_csv(out / '终端汇总.csv', rows, fields)
    write_csv(out / '问题清单.csv', issues, ['run_id','source_ref','issue'])
    manifest = {str(p.relative_to(raw)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(raw.rglob('*')) if p.is_file() and not p.is_symlink()}
    (out / '本地原始文件SHA256.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('整理目录:', out, '；终端数:', len(rows), '；问题数:', len(issues))
    return 1 if issues else 0


if __name__ == '__main__':
    sys.exit(main())
