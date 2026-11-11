"""Build the paired comparison from member 7's original handoff ZIP (stdlib only)."""

import argparse
import csv
import hashlib
import io
from collections import Counter
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile


ZIP_SHA256 = "00647944231e1dac2a41d4c3e4a96f19316e2ac0bd2cd58b31ae09e6781c9314"
PAIRS = {
    "A": ("expA_n4_ch1-6_run01", "expA_n4_ch1-6_run04"),
    "B": (
        "expB_formal_llf_3_20261110T061812Z_6r0xpbng",
        "expB_formal_llf_4_20261111T055242Z_0q1vozbs",
    ),
    "C": (
        "expC_baseline_c2000_run02_20261109T134607Z_47qrkol0",
        "expC_baseline_c2000_run04_20261111T055440Z_vtjcuwro",
    ),
}


def read_zip_rows(zip_path):
    if hashlib.sha256(zip_path.read_bytes()).hexdigest() != ZIP_SHA256:
        raise ValueError("ZIP differs from the reviewed 2026-11-11 handoff")
    with ZipFile(zip_path) as archive:
        by_name = {}
        for member in archive.infolist():
            name = member.filename
            if not member.flag_bits & 0x800:
                name = name.encode("cp437").decode("gb18030")
            if not member.is_dir():
                by_name[name.rsplit("/", 1)[-1]] = member
        expected_fields = {
            "复算指标.csv": ["run_id", "station", "metric", "value", "unit", "window", "source"],
            "核查细节.csv": ["run_id", "check", "value", "note"],
        }
        output = []
        for name, fields in expected_fields.items():
            reader = csv.DictReader(io.StringIO(archive.read(by_name[name]).decode("utf-8-sig")))
            if reader.fieldnames != fields:
                raise ValueError(f"Unexpected CSV schema: {name}")
            output.append(list(reader))
        return output


def build_rows(raw, checks):
    per_round_counts = {"A": 33, "B": 6, "C": 14}
    counts = {run: per_round_counts[experiment] for experiment, runs in PAIRS.items() for run in runs}
    metrics = {(r["run_id"], r["station"], r["metric"]): r for r in raw}
    if len(raw) != 106 or len(metrics) != len(raw) or Counter(r["run_id"] for r in raw) != counts:
        raise ValueError("Unexpected six-run metric coverage")
    queue_check = "expC_qos_c2000_run02_20261109T134447Z_0439qzhl"
    if len(checks) != 13 or set(r["run_id"] for r in checks) != set(counts) | {queue_check}:
        raise ValueError("Unexpected queue-check coverage")
    out = []

    def collect(experiment, station, metric):
        return [metrics[(run, station, metric)] for run in PAIRS[experiment]]

    def append(experiment, config, label, unit, station, metric, window, places=6):
        a, b = collect(experiment, station, metric)
        if a["unit"] != b["unit"]:
            raise ValueError(f"Unit differs for {metric}")
        x, y = Decimal(a["value"]), Decimal(b["value"])
        out.append({
            "实验": experiment, "配置": config, "指标": label, "单位": unit,
            "原正式轮": format(x, f".{places}f"), "单次复跑": format(y, f".{places}f"),
            "变化（复跑减原轮）": format(y - x, f".{places}f"),
            "变化单位": "百分点" if unit == "%" else unit, "统计窗口": window,
            "原正式轮ID": a["run_id"], "复跑ID": b["run_id"],
            "原指标键": f"{station or '汇总'}/{metric}",
        })

    ac, bc, cc = "4 终端／信道 1/6", "LLF", "共享 FIFO（2 Mbit/s）"
    a_window = "iperf3 预热 10 s 后统计 60 s（该抽样对）"
    append("A", ac, "逐终端 TCP 接收吞吐之和", "Mbit/s", "", "tcp_sum_station_mbps", a_window)
    for i in range(1, 5):
        sta = f"sta{i}"
        append("A", ac, f"{sta} UDP 丢包率", "%", sta, "udp_loss_pct", a_window)
    append("B", bc, "首次观测到 AP2 的 X 坐标", "m", "sta1", "first_new_ap_position_m", "关联观测时间线", 5)
    append("B", bc, "最大相邻成功回包间隔", "ms", "sta1", "event_max_reply_gap_ms", "切换附近窗口", 3)
    append("B", bc, "成功应答 P95 RTT", "ms", "sta1", "rtt_p95_ms", "全轮成功应答，最近秩", 2)
    for label, metric in [("探测发送数", "ping_sent"), ("成功回包数", "ping_received")]:
        append("B", bc, label, "个", "sta1", metric, "全轮", 0)
    c_transport = "接收端 10–60 s，完整间隔"
    for label, metric in [("UDP 丢包数", "udp_udp_lost_packets"), ("UDP 总包数", "udp_udp_packets")]:
        append("C", cc, label, "个", "sta1", metric, c_transport, 0)
    append("C", cc, "UDP 丢包率", "%", "sta1", "udp_udp_loss_percent", c_transport)
    append("C", cc, "后台 TCP 接收吞吐", "Mbit/s", "sta2", "tcp_received_mbps", c_transport)
    append("C", cc, "成功应答 P95 RTT", "ms", "sta1", "rtt_p95_ms", "10 ≤ 相对回包时刻 < 60 s，最近秩", 0)
    append("C", cc, "成功应答样本数", "个", "sta1", "rtt_success_count", "10 ≤ 相对回包时刻 < 60 s", 0)

    for l, n, rate in zip(collect("C", "sta1", "udp_udp_lost_packets"),
                          collect("C", "sta1", "udp_udp_packets"),
                          collect("C", "sta1", "udp_udp_loss_percent")):
        if abs(100 * Decimal(l["value"]) / Decimal(n["value"]) - Decimal(rate["value"])) > Decimal("0.000000001"):
            raise ValueError("C UDP ratio disagrees with counts")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff_zip", type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("8号抽样复现对照_v0.2.csv"))
    args = parser.parse_args()
    rows = build_rows(*read_zip_rows(args.handoff_zip))
    with args.out.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} paired metrics, with formal rounds and reruns kept separate.")


if __name__ == "__main__":
    main()
