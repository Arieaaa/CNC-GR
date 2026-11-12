"""双 AP 公共拓扑和基础连通性验收。"""

import argparse
import json
import os
import platform
import re
import signal
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, sleep

RUNS = Path("/var/lib/wifi-lab/runs")
SOURCE_VERSIONS = Path("/opt/wifi-lab/source-versions.txt")
SERVER_IP = "10.44.0.100"
SSID = "campus-lab"
AP_X = (15, 70)
AP_RANGE = 36
PROPAGATION_EXP = 3
PORT = "5201"


@contextmanager
def campus_topology(station_count, channels):
    """提供已配置的节点。调用方可以先设置移动策略，再调用 net.start()。"""
    from mininet.link import Link
    from mininet.node import OVSBridge
    from mn_wifi.link import wmediumd
    from mn_wifi.net import Mininet_wifi
    from mn_wifi.node import OVSBridgeAP
    from mn_wifi.wmediumdConnector import interference

    net = Mininet_wifi(
        build=False, controller=None, switch=OVSBridge, accessPoint=OVSBridgeAP,
        link=wmediumd, wmediumd_mode=interference, noise_th=-91, fading_cof=0,
    )
    try:
        aps = [
            net.addAccessPoint(
                f"ap{i + 1}", ssid=SSID, mode="g", channel=str(channel),
                position=f"{x},25,0", range=AP_RANGE,
            )
            for i, (x, channel) in enumerate(zip(AP_X, channels))
        ]
        stations = [
            net.addStation(
                f"sta{i + 1}", ip=f"10.44.0.{i + 1}/24",
                mac=f"02:44:00:00:00:{i + 1:02x}",
                position=f"{AP_X[i % 2] + 5},{23 + i // 2},0",
            )
            for i in range(station_count)
        ]
        switch = net.addSwitch("s1")
        server = net.addHost("srv", ip=f"{SERVER_IP}/24")
        net.setPropagationModel(model="logDistance", exp=PROPAGATION_EXP)
        net.configureNodes()
        for node in [*aps, server]:
            net.addLink(node, switch, cls=Link)
        yield net, aps, stations, server
    finally:
        net.stop()


def capture(node, command, output):
    stdout, stderr, result = node.pexec(command)
    output.write_text(stdout, encoding="utf-8")
    if stderr:
        output.with_suffix(output.suffix + ".stderr").write_text(stderr, encoding="utf-8")
    if result != 0:
        raise RuntimeError(f"{node.name}: {' '.join(command)} exited {result}")
    return stdout


def ap_radio(ap, channel, run_dir):
    intf = ap.params["wlan"][0]
    radio = capture(ap, ["iw", "dev", intf, "info"], run_dir / f"{ap.name}-iw-info.txt")
    address = re.search(r"\baddr ([0-9a-f:]+)", radio, re.IGNORECASE)
    expected_channel = rf"\bchannel {channel} \(\d+ MHz\), width: 20 MHz\b"
    if not address or not re.search(expected_channel, radio):
        raise RuntimeError(f"{ap.name}: expected channel {channel} and 20 MHz width")
    return address[1].lower()


def wait_association(sta, expected_bssid, run_dir):
    deadline = monotonic() + 10
    intf = sta.params["wlan"][0]
    while True:
        radio = capture(sta, ["iw", "dev", intf, "link"], run_dir / f"{sta.name}-iw-link.txt")
        if f"connected to {expected_bssid}" in radio.lower():
            return
        if monotonic() >= deadline:
            raise RuntimeError(f"{sta.name}: expected association to {expected_bssid}")
        sleep(0.5)


def smoke(station_count, channels, run_dir):
    from mininet.log import setLogLevel

    setLogLevel("info")
    with campus_topology(station_count, channels) as (net, aps, stations, server):
        net.start()
        bssids = [ap_radio(ap, channel, run_dir) for ap, channel in zip(aps, channels)]
        for i, sta in enumerate(stations):
            wait_association(sta, bssids[i % 2], run_dir)
            capture(sta, ["ping", "-n", "-c", "3", "-W", "1", "-w", "6", SERVER_IP],
                    run_dir / f"{sta.name}-ping.txt")

        with (run_dir / "iperf3-server.txt").open("w", encoding="utf-8") as log:
            process = server.popen(["iperf3", "-s", "-B", SERVER_IP, "-p", PORT, "--forceflush"],
                                   stdout=log, stderr=subprocess.STDOUT)
            try:
                sleep(0.5)
                if process.poll() is not None:
                    raise RuntimeError("iperf3 server exited before the test")
                for sta in stations[:2]:
                    raw = capture(sta, ["iperf3", "-c", SERVER_IP, "-p", PORT, "-t", "3", "-J",
                                        "--connect-timeout", "3000"],
                                  run_dir / f"{sta.name}-iperf3.json")
                    data = json.loads(raw)
                    if data.get("error") or data["end"]["sum_received"]["bytes"] <= 0:
                        raise RuntimeError(f"{sta.name}: iperf3 reported no received data")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def stop_on_signal(signum, _frame):
    raise SystemExit(128 + signum)


def main():
    parser = argparse.ArgumentParser(description="校园 Wi-Fi 基础验收")
    parser.add_argument("stations", type=int, choices=(2, 4, 8, 12))
    parser.add_argument("channels", choices=("1,1", "1,6"))
    parser.add_argument("operator")
    args = parser.parse_args()
    channels = tuple(map(int, args.channels.split(",")))
    now = datetime.now(timezone.utc)
    run_dir = Path(tempfile.mkdtemp(prefix=f"smoke_{now:%Y%m%dT%H%M%SZ}_", dir=RUNS))
    run_dir.chmod(0o2750)
    print(f"本次日志目录 {run_dir}", flush=True)
    with (run_dir / "run.log").open("w", encoding="utf-8") as log:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)

    status = run_dir / "status.txt"
    status.write_text("RUNNING\n", encoding="utf-8")
    signal.signal(signal.SIGTERM, stop_on_signal)
    try:
        from mn_wifi.net import VERSION

        config = {
            "kind": "smoke",
            "started_utc": now.isoformat(),
            "operator": args.operator,
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "mininet_wifi_version": VERSION,
            "stations": args.stations,
            "channels": channels,
            "ssid": SSID,
            "channel_width_mhz": 20,
            "mode": "802.11g",
            "medium": "wmediumd interference",
            "propagation": {"model": "logDistance", "exp": PROPAGATION_EXP},
            "ap_positions_m": [[x, 25, 0] for x in AP_X],
            "requested_ap_range_m": AP_RANGE,
            "station_positions_m": [[AP_X[i % 2] + 5, 23 + i // 2, 0] for i in range(args.stations)],
            "server_ip": SERVER_IP,
            "iperf3_direction": "station to server",
            "iperf3_seconds_per_station": 3,
        }
        (run_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        if SOURCE_VERSIONS.is_file():
            (run_dir / "source-versions.txt").write_bytes(SOURCE_VERSIONS.read_bytes())

        # Mininet and hostapd create temporary configuration files relative to cwd.
        previous_dir = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="wifi-lab-") as workdir:
            os.chdir(workdir)
            try:
                smoke(args.stations, channels, run_dir)
            finally:
                os.chdir(previous_dir)
    except BaseException:
        status.write_text("FAIL\n", encoding="utf-8")
        raise
    else:
        status.write_text("PASS\n", encoding="utf-8")


if __name__ == "__main__":
    main()
