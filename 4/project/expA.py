#!/usr/bin/env python3
"""实验 A：并发接入与信道规划（04 号正式采集脚本）。

拓扑复用公共平台 /opt/wifi-lab/topology.py 的 campus_topology()，
不改动任何公共文件。每轮 = 一种配置的一次重复，含两个分轮（负载不混用）：
  1) TCP 吞吐量轮：各终端经独立端口向 srv 并发打流，期间同步 ping 采集 RTT；
  2) 定速 UDP 轮：各终端以固定速率并发 UDP，由 iperf3 报告丢包率与抖动。

用法（实验机上，需 sudo）：
    sudo python3 expA.py <stations> <ch1,ch2> <run_no> [operator]
示例：
    sudo python3 expA.py 12 1,6 01 wifi04
试跑（缩短时长、用保留编号 00，不作正式数据）：
    sudo python3 expA.py 2 1,6 00 wifi04 --tcp-seconds 20 --udp-seconds 20 --omit-seconds 5

日志目录：/var/lib/wifi-lab/runs/expA_n<stations>_ch<a>-<b>_run<nn>/
"""

import argparse
import fcntl
import json
import math
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from time import sleep

sys.path.insert(0, "/opt/wifi-lab")
from topology import (AP_X, SERVER_IP, SSID, ap_radio, campus_topology,
                      wait_association)

RUNS = Path("/var/lib/wifi-lab/runs")
LOCK = Path("/var/lib/wifi-lab/run.lock")
SOURCE_VERSIONS = Path("/opt/wifi-lab/source-versions.txt")
BASE_PORT = 5201          # sta(i+1) 使用 5201+i，每终端独立服务进程与端口
PING_INTERVAL = 0.2       # RTT 探测周期（秒），写入 config 供 07 号核查


def acquire_lock():
    """与公共平台共用同一把运行锁；被占用时直接退出，不强行运行。"""
    fd = os.open(LOCK, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit("实验机忙：run.lock 被占用，等当前运行结束后再试（不要强杀他人实验）")
    return fd


def host_snapshot(run_dir, tag):
    out = subprocess.run(
        "cat /proc/loadavg; free -m", shell=True, capture_output=True, text=True
    ).stdout
    with (run_dir / "host-snapshot.txt").open("a", encoding="utf-8") as f:
        f.write(f"--- {tag} {datetime.now(timezone.utc).isoformat()} ---\n{out}\n")


def start_servers(server, count, run_dir):
    """每个终端一个独立 iperf3 服务进程和端口，避免并发被拒计入无线丢包。"""
    procs = []
    for i in range(count):
        port = BASE_PORT + i
        log = (run_dir / f"iperf3-server-{port}.txt").open("w", encoding="utf-8")
        p = server.popen(
            ["iperf3", "-s", "-B", SERVER_IP, "-p", str(port), "--forceflush"],
            stdout=log, stderr=subprocess.STDOUT,
        )
        procs.append((p, log))
    sleep(0.5)
    for p, _ in procs:
        if p.poll() is not None:
            raise RuntimeError("iperf3 server exited before the test")
    return procs


def stop_servers(procs):
    for p, log in procs:
        p.terminate()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        log.close()


def run_clients(stations, duration, omit, extra_args, run_dir, tag):
    """全部终端同时启动 iperf3 客户端，收集 JSON 结果并落盘。"""
    procs = {}
    for i, sta in enumerate(stations):
        cmd = ["iperf3", "-c", SERVER_IP, "-p", str(BASE_PORT + i),
               "-t", str(duration), "-O", str(omit), "-J",
               "--connect-timeout", "5000", *extra_args]
        procs[sta.name] = sta.popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
    results = {}
    for name, p in procs.items():
        out, _ = p.communicate()
        (run_dir / f"{name}-{tag}-iperf3.json").write_text(out, encoding="utf-8")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            raise RuntimeError(f"{name}: iperf3 {tag} 输出不是 JSON，原始输出已保存")
        if data.get("error"):
            raise RuntimeError(f"{name}: iperf3 {tag} 报错: {data['error']}")
        results[name] = data
    return results


def start_pings(stations, duration):
    count = max(1, int(duration / PING_INTERVAL))
    return {
        sta.name: sta.popen(
            ["ping", "-n", "-i", str(PING_INTERVAL), "-c", str(count),
             "-W", "1", SERVER_IP],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        for sta in stations
    }


def ping_stats(text):
    times = [float(x) for x in re.findall(r"time=([\d.]+) ms", text)]
    if not times:
        return {"samples": 0}
    ordered = sorted(times)
    p95 = ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]
    return {"avg_ms": round(sum(times) / len(times), 3),
            "p95_ms": round(p95, 3), "samples": len(times)}


def stop_on_signal(signum, _frame):
    raise SystemExit(128 + signum)


def main():
    parser = argparse.ArgumentParser(description="实验 A 并发接入与信道规划")
    parser.add_argument("stations", type=int, choices=(2, 4, 8, 12),
                        help="终端数；2 仅用于流程试跑")
    parser.add_argument("channels", choices=("1,1", "1,6"),
                        help="ap1,ap2 信道")
    parser.add_argument("run", help="重复编号，如 01；00 保留给试跑")
    parser.add_argument("operator", nargs="?", default="wifi04")
    parser.add_argument("--tcp-seconds", type=int, default=60)
    parser.add_argument("--udp-seconds", type=int, default=60)
    parser.add_argument("--omit-seconds", type=int, default=10,
                        help="iperf3 预热舍弃时间")
    parser.add_argument("--udp-rate", default="2M",
                        help="每终端固定 UDP 速率，组内所有配置保持一致")
    parser.add_argument("--udp-datagram", type=int, default=1400)
    args = parser.parse_args()
    channels = tuple(map(int, args.channels.split(",")))

    acquire_lock()
    now = datetime.now(timezone.utc)
    run_dir = RUNS / f"expA_n{args.stations}_ch{channels[0]}-{channels[1]}_run{args.run:0>2}"
    if run_dir.exists():
        sys.exit(f"{run_dir} 已存在：原始日志不覆盖，请换重复编号")
    run_dir.mkdir(mode=0o2750)
    run_dir.chmod(0o2750)
    print(f"本次日志目录 {run_dir}", flush=True)
    with (run_dir / "run.log").open("w", encoding="utf-8") as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)

    status = run_dir / "status.txt"
    status.write_text("RUNNING\n", encoding="utf-8")
    signal.signal(signal.SIGTERM, stop_on_signal)
    try:
        from mininet.log import setLogLevel
        from mn_wifi.net import VERSION
        setLogLevel("info")

        config = {
            "kind": "expA",
            "started_utc": now.isoformat(),
            "operator": args.operator,
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "mininet_wifi_version": VERSION,
            "stations": args.stations,
            "channels": channels,
            "run": args.run,
            "ssid": SSID,
            "channel_width_mhz": 20,
            "mode": "802.11g",
            "medium": "wmediumd interference",
            "propagation": {"model": "logDistance", "exp": 3},
            "ap_positions_m": [[x, 25, 0] for x in AP_X],
            "station_positions_m": [[AP_X[i % 2] + 5, 23 + i // 2, 0]
                                    for i in range(args.stations)],
            "server_ip": SERVER_IP,
            "direction": "station to server",
            "tcp_seconds": args.tcp_seconds,
            "udp_seconds": args.udp_seconds,
            "omit_seconds": args.omit_seconds,
            "udp_rate_per_station": args.udp_rate,
            "udp_datagram_bytes": args.udp_datagram,
            "ping_interval_s": PING_INTERVAL,
            "iperf3_ports": [BASE_PORT + i for i in range(args.stations)],
            "phases": {},
        }
        (run_dir / "config.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8")
        if SOURCE_VERSIONS.is_file():
            (run_dir / "source-versions.txt").write_bytes(SOURCE_VERSIONS.read_bytes())

        host_snapshot(run_dir, "start")
        # hostapd 等在当前目录写临时配置，与公共入口保持一致做法
        previous_dir = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="wifi-expA-") as workdir:
            os.chdir(workdir)
            try:
                with campus_topology(args.stations, channels) as (net, aps, stations, server):
                    net.start()
                    # 先验证信道与关联确实生效，再打流
                    bssids = [ap_radio(ap, ch, run_dir)
                              for ap, ch in zip(aps, channels)]
                    for i, sta in enumerate(stations):
                        wait_association(sta, bssids[i % 2], run_dir)

                    servers = start_servers(server, len(stations), run_dir)
                    try:
                        # 分轮 1：并发 TCP 吞吐量 + 同步 ping RTT
                        config["phases"]["tcp"] = {
                            "start_utc": datetime.now(timezone.utc).isoformat()}
                        pings = start_pings(stations, args.tcp_seconds)
                        tcp = run_clients(stations, args.tcp_seconds,
                                          args.omit_seconds, [], run_dir, "tcp")
                        rtt = {}
                        for name, p in pings.items():
                            text, _ = p.communicate()
                            (run_dir / f"{name}-ping.txt").write_text(
                                text, encoding="utf-8")
                            rtt[name] = ping_stats(text)
                        config["phases"]["tcp"]["end_utc"] = \
                            datetime.now(timezone.utc).isoformat()

                        # 分轮 2：定速并发 UDP，丢包率与抖动由 iperf3 报告
                        config["phases"]["udp"] = {
                            "start_utc": datetime.now(timezone.utc).isoformat()}
                        udp = run_clients(
                            stations, args.udp_seconds, args.omit_seconds,
                            ["-u", "-b", args.udp_rate, "-l",
                             str(args.udp_datagram)],
                            run_dir, "udp")
                        config["phases"]["udp"]["end_utc"] = \
                            datetime.now(timezone.utc).isoformat()
                    finally:
                        stop_servers(servers)
            finally:
                os.chdir(previous_dir)

        summary = {
            "experiment": "expA",
            "stations": args.stations,
            "channels": list(channels),
            "run": args.run,
            "tcp_per_station_mbps": {
                n: round(d["end"]["sum_received"]["bits_per_second"] / 1e6, 3)
                for n, d in tcp.items()},
            "tcp_total_mbps": round(
                sum(d["end"]["sum_received"]["bits_per_second"]
                    for d in tcp.values()) / 1e6, 3),
            "udp_per_station": {
                n: {"lost_percent": d["end"]["sum"]["lost_percent"],
                    "jitter_ms": d["end"]["sum"]["jitter_ms"],
                    "received_mbps": round(
                        d["end"]["sum"]["bits_per_second"] / 1e6, 3)}
                for n, d in udp.items()},
            "rtt_ms": rtt,
        }
        (run_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        (run_dir / "config.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8")
        host_snapshot(run_dir, "end")
    except BaseException:
        status.write_text("FAIL\n", encoding="utf-8")
        raise
    else:
        status.write_text("PASS\n", encoding="utf-8")


if __name__ == "__main__":
    main()
