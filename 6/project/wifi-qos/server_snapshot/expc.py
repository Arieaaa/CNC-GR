#!/usr/bin/env python3
"""实验C单轮运行器。管理员审核部署后，以固定入口运行。仅依赖标准库。"""

import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import statistics
import subprocess
import tempfile
import time
import traceback
from datetime import datetime, timezone


def queue_commands(interface, mode, total_kbit, realtime_kbit, station_ip):
    """两臂同父类上限、同总bfifo缓存；仅改变分类与保障。"""
    if not re.fullmatch(r'srv-eth\d+', interface):
        raise ValueError('只能整形srv仿真接口，禁止使用管理接口')
    if mode not in ('baseline', 'qos', 'udp-only'):
        raise ValueError('无效的队列模式')
    if not 0 < realtime_kbit < total_kbit:
        raise ValueError('实时保障必须大于0且小于总速率')
    total = f'{total_kbit}kbit'
    commands = [
        ['tc', 'qdisc', 'replace', 'dev', interface, 'root', 'handle', '1:', 'htb', 'default', '20'],
        ['tc', 'class', 'add', 'dev', interface, 'parent', '1:', 'classid', '1:1', 'htb', 'rate', total, 'ceil', total],
    ]
    def add_class(minor, rate, queue_bytes):
        commands.append(['tc', 'class', 'add', 'dev', interface, 'parent', '1:1', 'classid', f'1:{minor}', 'htb',
                         'rate', f'{rate}kbit', 'ceil', total, 'quantum', '1514'])
        commands.append(['tc', 'qdisc', 'add', 'dev', interface, 'parent', f'1:{minor}',
                         'handle', f'{minor}:', 'bfifo', 'limit', str(queue_bytes)])
    if mode == 'qos':
        add_class(10, realtime_kbit, 8192)
        add_class(20, total_kbit - realtime_kbit, 24576)
        base = ['tc', 'filter', 'add', 'dev', interface, 'protocol', 'ip', 'parent', '1:', 'prio']
        commands.append(base + ['1', 'u32', 'match', 'ip', 'protocol', '17', '0xff',
                                'match', 'ip', 'sport', '5202', '0xffff',
                                'match', 'ip', 'dst', f'{station_ip}/32', 'flowid', '1:10'])
        commands.append(base + ['2', 'u32', 'match', 'ip', 'protocol', '1', '0xff',
                                'match', 'ip', 'dst', f'{station_ip}/32', 'flowid', '1:10'])
    else:
        add_class(20, total_kbit, 32768)
    return commands


def interval_metrics(data, window_start=10, window_end=60, udp=False):
    """只取接收端完整区间；缺失或跨边界区间不按比例猜测。"""
    if data.get('error'):
        raise ValueError(data['error'])
    rows = []
    for interval in data.get('intervals', []):
        streams = interval.get('streams', [])
        if len(streams) != 1:
            raise ValueError('本实验要求每业务只有一条流')
        row = streams[0]
        if row.get('sender') is not False:
            raise ValueError('需要接收端区间，不能使用发送端吞吐代替')
        if row['start'] >= window_start - 0.02 and row['end'] <= window_end + 0.1:
            rows.append(row)
    if not rows:
        raise ValueError('没有稳态区间')
    rows.sort(key=lambda x: x['start'])
    if rows[0]['start'] > window_start + 0.1 or rows[-1]['end'] < window_end - 0.1:
        raise ValueError('稳态窗口覆盖不完整')
    for a, b in zip(rows, rows[1:]):
        if abs(a['end'] - b['start']) > 0.1:
            raise ValueError('稳态时间序列有间断或重叠')
    seconds = sum(r['end'] - r['start'] for r in rows)
    if seconds <= 0:
        raise ValueError('无效时长')
    if not udp and sum(r['bytes'] for r in rows) <= 0:
        raise ValueError('TCP稳态零吞吐，不能证明容量或后台竞争有效')
    result = {'received_mbps': sum(r['bytes'] for r in rows) * 8 / seconds / 1e6,
              'analyzed_seconds': seconds, 'interval_count': len(rows)}
    if udp:
        if any(not all(k in r for k in ('packets', 'lost_packets', 'jitter_ms')) for r in rows):
            raise ValueError('接收端UDP区间缺少丢包或抖动字段')
        packets = sum(r['packets'] for r in rows)
        lost = sum(r['lost_packets'] for r in rows)
        if packets <= 0 or not 0 <= lost <= packets:
            raise ValueError('UDP包数无效或乱序导致计数需人工核查')
        result.update(udp_loss_percent=100 * lost / packets, udp_packets=packets, udp_lost_packets=lost,
                      udp_jitter_interval_mean_ms=statistics.mean(r['jitter_ms'] for r in rows),
                      udp_jitter_last_ms=rows[-1]['jitter_ms'])
    return result


def checked(node, argv):
    out, err, code = node.pexec(argv)
    if code:
        raise RuntimeError(f'{node.name}: {argv!r}: {code}: {err or out}')
    return out


def node_snapshot(node, directory, prefix):
    for name, command in [('addresses', ['ip', '-j', 'addr']), ('routes', ['ip', '-j', 'route']),
                          ('qdisc', ['tc', '-s', 'qdisc', 'show']), ('class', ['tc', '-s', 'class', 'show']),
                          ('links', ['ip', '-s', 'link'])]:
        (directory / f'{prefix}-{node.name}-{name}.txt').write_text(checked(node, command))


def queue_snapshot(server, interface, directory, prefix):
    result = {}
    for name in ('qdisc', 'class', 'filter'):
        command = ['tc', '-s', name, 'show', 'dev', interface]
        result[name] = checked(server, command)
        (directory / f'{prefix}-srv-{name}.txt').write_text(result[name])
        raw = checked(server, ['tc', '-j', '-s', name, 'show', 'dev', interface])
        if name == 'class' and not raw.lstrip().startswith('['):
            raw = json.dumps(parse_htb_classes(raw), indent=2) + '\n'
        (directory / f'{prefix}-srv-{name}.json').write_text(raw)
    return result


def parse_htb_classes(raw):
    """部分tc的HTB插件忽略-j；从原始文本规范化，不丢弃配置和计数。"""
    blocks = re.findall(r'^class htb ([0-9a-f]+:[0-9a-f]+) (.*?)(?=^class |\Z)', raw, re.M | re.S)
    if not blocks:
        raise ValueError('无法解析HTB类统计')
    rows = []
    for handle, block in blocks:
        header = block.splitlines()[0]
        options = {}
        for key in ('rate', 'ceil', 'prio', 'quantum', 'burst', 'cburst', 'leaf'):
            match = re.search(rf'\b{key} (\S+)', header)
            if match:
                options[key] = match[1]
        count = re.search(r'\bSent (\d+) bytes (\d+) pkt', block)
        if count is None or not all(key in options for key in ('rate', 'ceil')):
            raise ValueError('HTB类缺少速率或字节计数')
        row = {'kind': 'htb', 'handle': handle, 'options': options,
               'bytes': int(count[1]), 'packets': int(count[2])}
        parent = re.search(r'\bparent (\S+)', header)
        if parent:
            row['parent'] = parent[1]
        elif header.startswith('root '):
            row['root'] = True
        rows.append(row)
    return rows


def resource_snapshot(directory, prefix):
    for name, path in [('cpu', '/proc/stat'), ('mem', '/proc/meminfo'), ('load', '/proc/loadavg')]:
        (directory / f'{prefix}-{name}.txt').write_text(Path(path).read_text())


def stop_processes(processes):
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def class_bytes(directory, prefix):
    rows = json.loads((directory / f'{prefix}-srv-class.json').read_text())
    return {r.get('handle', r.get('classid')): r.get('bytes', r.get('stats', {}).get('bytes', 0)) for r in rows}


def verify_udp_class(counts, ping_started):
    if ping_started or counts.get('1:10', 0) <= 0:
        raise ValueError('需要启动ICMP之前的实时类UDP字节证据')


def queue_signature(snapshot):
    """保留结构与options，去掉累计统计，检测同handle下的配置更改。"""
    counters = {'stats', 'stats2', 'xstats', 'pcnt', 'bytes', 'packets', 'drops', 'overlimits',
                'requeues', 'backlog', 'qlen', 'success', 'hit', 'lastuse', 'firstused', 'used'}
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in counters}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value
    fields = ('kind', 'handle', 'parent', 'root', 'protocol', 'pref', 'chain', 'options')
    return {name: [clean({k: row[k] for k in fields if k in row}) for row in rows]
            for name, rows in snapshot.items()}


def saved_queue_signature(directory, prefix):
    return queue_signature({name: json.loads((directory / f'{prefix}-srv-{name}.json').read_text())
                            for name in ('qdisc', 'class', 'filter')})


def run(args, directory, config):
    spec = importlib.util.spec_from_file_location('wifi_lab_topology', '/opt/wifi-lab/topology.py')
    topology = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(topology)
    from mininet.log import setLogLevel
    setLogLevel('info')
    processes, handles = [], []
    with topology.campus_topology(2, (1, 6)) as (net, aps, stations, server):
        try:
            net.start()
            bssids = [topology.ap_radio(ap, ch, directory) for ap, ch in zip(aps, (1, 6))]
            for i, sta in enumerate(stations):
                topology.wait_association(sta, bssids[i], directory)
                checked(sta, ['ping', '-n', '-c', '3', '-W', '1', server.IP()])
            interface = str(server.defaultIntf())
            config.update(server_ip=server.IP(), station_ips=[s.IP() for s in stations],
                          server_interface=interface, stations=2, channels=[1, 6],
                          ap_positions=[str(ap.position) for ap in aps],
                          station_positions=[str(sta.position) for sta in stations],
                          topology_sha256=hashlib.sha256(Path('/opt/wifi-lab/topology.py').read_bytes()).hexdigest())
            (directory / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
            for node in [server, *aps, *stations]:
                node_snapshot(node, directory, 'before')
            for node in [*aps, *stations]:
                (directory / f'{node.name}-iw-dev.txt').write_text(checked(node, ['iw', 'dev']))
            resource_snapshot(directory, 'before')

            def spawn(node, argv, name):
                handle = (directory / name).open('w')
                handles.append(handle)
                process = node.popen(argv, stdout=handle, stderr=subprocess.STDOUT)
                processes.append(process)
                return process

            def start_server(port, tag):
                process = spawn(server, ['iperf3', '-s', '-1', '-B', server.IP(), '-p', str(port), '-J'],
                                f'{tag}-server.json')
                for _ in range(30):
                    if process.poll() is not None:
                        raise RuntimeError('iperf服务端提前退出')
                    if f':{port} ' in checked(server, ['ss', '-lnt']):
                        return process
                    time.sleep(0.1)
                raise RuntimeError('iperf服务端没有监听')

            def client(sta, port, seconds, tag, udp=False):
                command = ['iperf3', '-4', '-c', server.IP(), '-p', str(port), '-R', '-P', '1',
                           '-t', str(seconds), '-i', '1', '-J', '--get-server-output', '--connect-timeout', '3000']
                if udp:
                    command += ['-u', '-b', f'{args.udp_kbit}k', '-l', '160']
                return spawn(sta, command, f'{tag}-receiver.json')

            if args.mode == 'capacity':
                results = {}
                for i, sta in enumerate(stations):
                    tag = f'capacity-sta{i+1}'
                    srv_process = start_server(5203, tag)
                    process = client(sta, 5203, args.seconds, tag)
                    if process.wait(timeout=args.seconds + 15):
                        raise RuntimeError('下行容量测试失败')
                    srv_process.wait(timeout=5)
                    for handle in handles:
                        handle.flush()
                    data = json.loads((directory / f'{tag}-receiver.json').read_text())
                    results[tag] = interval_metrics(data, args.warmup, args.seconds)
                (directory / 'metrics.json').write_text(json.dumps(results, indent=2))
                return

            commands = queue_commands(interface, args.mode, args.total_kbit, args.rt_kbit, stations[0].IP())
            (directory / 'tc-commands.json').write_text(json.dumps(commands, indent=2))
            for command in commands:
                checked(server, command)
            queue_snapshot(server, interface, directory, 'configured')
            configured_signature = saved_queue_signature(directory, 'configured')
            start_server(5202, 'udp')
            if args.mode != 'udp-only':
                start_server(5203, 'tcp')
            udp = client(stations[0], 5202, args.seconds, 'udp', udp=True)
            tcp = client(stations[1], 5203, args.seconds, 'tcp') if args.mode != 'udp-only' else None
            ping = None
            begun = time.monotonic()
            config['traffic_started_utc'] = datetime.now(timezone.utc).isoformat()
            (directory / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
            index = 0
            while udp.poll() is None or (tcp is not None and tcp.poll() is None):
                if time.monotonic() - begun > args.seconds + 20:
                    raise TimeoutError('业务超时')
                snapshot = queue_snapshot(server, interface, directory, f'sample{index:03}')
                if saved_queue_signature(directory, f'sample{index:03}') != configured_signature:
                    raise RuntimeError('运行中的限速、缓存或分类配置发生变化')
                if 'htb 1:' not in snapshot['qdisc']:
                    raise RuntimeError('HTB根队列被替换')
                if args.mode == 'qos' and not all(f'class htb 1:{n}' in snapshot['class'] for n in (10, 20)):
                    raise RuntimeError('保障类丢失')
                resource_snapshot(directory, f'sample{index:03}')
                if ping is None and time.monotonic() - begun >= 2:
                    queue_snapshot(server, interface, directory, 'before-icmp')
                    if args.mode == 'qos':
                        verify_udp_class(class_bytes(directory, 'before-icmp'), ping_started=False)
                    ping = spawn(stations[0], ['ping', '-n', '-D', '-i', '0.2', '-W', '1', server.IP()], 'ping.txt')
                index += 1
                time.sleep(1)
            if udp.returncode or (tcp is not None and tcp.returncode):
                raise RuntimeError('业务进程失败，不能作为丢包结果')
            if ping is None:
                raise RuntimeError('业务提前结束，未启动RTT探测')
            ping.terminate()
            ping.wait(timeout=3)
            final = queue_snapshot(server, interface, directory, 'after')
            if saved_queue_signature(directory, 'after') != configured_signature:
                raise RuntimeError('最终队列配置与初始配置不一致')
            for handle in handles:
                handle.flush()
            metrics = {'udp': interval_metrics(json.loads((directory / 'udp-receiver.json').read_text()),
                                               args.warmup, args.seconds, udp=True)}
            if tcp:
                metrics['tcp'] = interval_metrics(json.loads((directory / 'tcp-receiver.json').read_text()),
                                                 args.warmup, args.seconds)
            if args.mode == 'qos':
                counts = class_bytes(directory, 'after')
                if not all(counts.get(f'1:{n}', 0) > 0 for n in (10, 20)):
                    raise RuntimeError(f'保障/后台类没有业务字节证据: {counts}')
            stamp = datetime.fromisoformat(config['traffic_started_utc']).timestamp()
            rtts = []
            for line in (directory / 'ping.txt').read_text().splitlines():
                match = re.search(r'^\[(\d+\.\d+)\].*time[=<]([\d.]+) ms', line)
                if match and args.warmup <= float(match[1]) - stamp < args.seconds:
                    rtts.append(float(match[2]))
            if not rtts:
                raise ValueError('稳态没有有效RTT样本')
            rtts.sort()
            metrics['rtt'] = {'mean_ms': statistics.mean(rtts), 'p95_ms': rtts[math.ceil(.95 * len(rtts)) - 1],
                              'successful_samples': len(rtts), 'probe_interval_seconds': .2,
                              'note': 'P95仅含成功应答，缺失探测需结合原始ping日志核查'}
            (directory / 'metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
            resource_snapshot(directory, 'after')
            for node in [server, *aps, *stations]:
                node_snapshot(node, directory, 'after')
        finally:
            stop_processes(processes)
            for handle in handles:
                handle.close()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('capacity', 'udp-only', 'baseline', 'qos'))
    p.add_argument('--seconds', type=int, default=60, choices=range(15, 91))
    p.add_argument('--warmup', type=int, default=10)
    p.add_argument('--total-kbit', type=int, default=2000)
    p.add_argument('--rt-kbit', type=int, default=600)
    p.add_argument('--udp-kbit', type=int, default=300)
    p.add_argument('--run', type=int, default=1, choices=range(1, 100))
    return p


def main():
    args = parser().parse_args()
    if not 0 <= args.warmup < args.seconds:
        raise SystemExit('预热时间无效')
    if not 100 <= args.total_kbit <= 100000 or not 0 < args.udp_kbit < args.rt_kbit < args.total_kbit:
        raise SystemExit('速率参数无效')
    if os.geteuid() != 0:
        raise SystemExit('需要管理员部署的正式入口；普通账号不能直接运行')
    os.umask(0o027)
    with open('/var/lib/wifi-lab/run.lock', 'r+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('实验机忙，本轮未启动')
        now = datetime.now(timezone.utc)
        prefix = f'expC_{args.mode}_c{args.total_kbit}_run{args.run:02}_{now:%Y%m%dT%H%M%SZ}_'
        directory = Path(tempfile.mkdtemp(prefix=prefix, dir='/var/lib/wifi-lab/runs'))
        directory.chmod(0o2750)
        print(f'本次日志目录 {directory}', flush=True)
        config = vars(args) | {'kind': 'expC', 'started_utc': now.isoformat(),
                               'operator': os.environ.get('WIFI_OPERATOR', os.environ.get('SUDO_USER', 'root')),
                               'direction': 'srv to stations; iperf3 reverse', 'udp_payload_bytes': 160,
                               'rtt_class': 'realtime in qos; shared in baseline',
                               'baseline_buffer_bytes': 32768, 'qos_buffer_bytes': [8192, 24576],
                               'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        (directory / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
        (directory / 'status.txt').write_text('RUNNING\n')
        versions = Path('/opt/wifi-lab/source-versions.txt')
        if versions.exists():
            (directory / versions.name).write_bytes(versions.read_bytes())
        def terminate(signum, _):
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, terminate)
        previous = Path.cwd()
        with (directory / 'run.log').open('w', buffering=1) as log:
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            try:
                with tempfile.TemporaryDirectory(prefix='wifi-expc-') as work:
                    os.chdir(work)
                    try:
                        run(args, directory, config)
                    finally:
                        os.chdir(previous)
            except BaseException:
                (directory / 'status.txt').write_text('FAIL\n')
                traceback.print_exc()
                raise
            else:
                (directory / 'status.txt').write_text('PASS\n')


if __name__ == '__main__':
    main()
