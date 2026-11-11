"""Rebuild the C FIFO appendix from the two archived UDP receiver logs."""

import argparse
import base64
import csv
import hashlib
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPException
from pathlib import Path


COMMIT = "eb8f6c1b4a5adaadc336f1485405f0316c6bb116"
RUNS = (
    (
        "expC_baseline_c2000_run02_20261109T134607Z_47qrkol0",
        "a218f88efeb1c39c27a689e6de3091adc935ee50d85b5704a483e17929198510",
    ),
    (
        "expC_baseline_c2000_run04_20261111T055440Z_vtjcuwro",
        "3190f349cd00c303ecc44821182c3b4673883274bce4a50b48d48d25889ed0c7",
    ),
)
VERIFIED_COUNTS = (
    (0, 4, 0, 0, 0, 0, 0, 6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 9, 0, 0, 0, 8,
     0, 3, 0, 0, 6, 2, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
    (10, 0, 0, 5, 0, 0, 1, 8, 2, 0, 9, 9, 3, 0, 4, 0, 16, 0, 0, 1, 3, 8, 3, 3, 11,
     0, 1, 2, 11, 0, 12, 0, 0, 22, 6, 2, 0, 32, 0, 4, 0, 1, 4, 5, 0, 3, 0, 7, 2, 22),
)
VERIFIED_PACKET_TOTALS = (11721, 11718)


def read_archive(run, local):
    run_id, checksum = run
    if local:
        raw = (local / f"{run_id}.jsonl").read_bytes()
        if hashlib.sha256(raw).hexdigest() != checksum:
            raise ValueError(f"Archive SHA-256 mismatch: {run_id}")
        return raw

    encoded_path = urllib.parse.quote(f"7/project/原始归档/{run_id}.jsonl")
    for ref in (COMMIT, "refs/heads/main", COMMIT):
        url = f"https://raw.githubusercontent.com/Arieaaa/CNC-GR/{ref}/{encoded_path}"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "CNC-GR analysis"})
            with urllib.request.urlopen(request, timeout=12) as response:
                raw = response.read()
            if hashlib.sha256(raw).hexdigest() != checksum:
                raise ValueError(f"Archive SHA-256 mismatch: {run_id}")
            return raw
        except (OSError, HTTPException, ValueError) as exc:
            last_error = exc
    raise RuntimeError(f"Could not verify archive {run_id}") from last_error


def receiver_intervals(raw):
    entries = [json.loads(line) for line in raw.splitlines()]
    [receiver] = [entry for entry in entries if entry["path"] == "udp-receiver.json"]
    payload = base64.b64decode(receiver["base64"], validate=True)
    if hashlib.sha256(payload).hexdigest() != receiver["sha256"]:
        raise ValueError("UDP receiver SHA-256 mismatch")

    intervals = [item["sum"] for item in json.loads(payload)["intervals"]]
    # Match the 50 complete one-second intervals, allowing timestamp jitter.
    selected = [item for item in intervals if item["start"] >= 9.90 and item["end"] <= 60.05]
    if [round(item["start"]) for item in selected] != list(range(10, 60)):
        raise ValueError("Expected one interval per second from 10 to 59")
    for item in selected:
        if (
            item["omitted"]
            or not 0.95 <= item["end"] - item["start"] <= 1.05
            or not 0 <= item["lost_packets"] <= item["packets"]
        ):
            raise ValueError(f"Unexpected interval: {item}")
    return selected


def write_csv(path, original, rerun):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "receiver_nominal_start_s", "receiver_nominal_end_s",
            "original_run_id", "original_lost_packets", "rerun_run_id", "rerun_lost_packets",
        ])
        for start, (old, new) in enumerate(zip(original, rerun), start=10):
            writer.writerow([start, start + 1, RUNS[0][0], old, RUNS[1][0], new])


def write_plot(path, original, rerun, font):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties, fontManager

    fontManager.addfont(font)
    plt.rcParams.update({
        "font.family": FontProperties(fname=font).get_name(),
        "font.size": 14,
        "text.color": "#152337",
        "xtick.color": "#3A4C61",
        "ytick.color": "#3A4C61",
        "axes.labelcolor": "#25364A",
        "axes.edgecolor": "#9BAABA",
        "axes.unicode_minus": False,
    })
    fig, axes = plt.subplots(2, 1, figsize=(14.4, 8.1), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.092, right=0.963, top=0.766, bottom=0.155, hspace=0.42)
    fig.text(0.092, 0.936, "C 组 FIFO 原轮与复跑的逐秒 UDP 丢包", fontsize=27, weight="bold")
    fig.text(0.092, 0.885, "两轮均取 UDP 接收端第 10–60 秒的完整区间", fontsize=15, color="#3A4C61")

    for axis, losses, sent_total, name, color in zip(
        axes, (original, rerun), VERIFIED_PACKET_TOTALS,
        ("抽样原轮", "7 号单次复跑"), ("#25658D", "#A94626")
    ):
        lost_total = sum(losses)
        affected = sum(loss > 0 for loss in losses)
        axis.set_title(f"{name}   {lost_total:,} / {sent_total:,} 包（{100 * lost_total / sent_total:.3f}%）",
                       loc="left", pad=10, fontsize=16, fontweight="bold")
        axis.set_title(f"{affected} / 50 个区间有丢包", loc="right", pad=10, fontsize=14, color=color)
        axis.bar([second + 0.5 for second in range(10, 60)], losses, width=0.78, color=color, zorder=3)
        peak = max(losses)
        peak_index = losses.index(peak)
        axis.annotate(f"{peak} 包", xy=(peak_index + 10.5, peak), xytext=(0, 3),
                      textcoords="offset points", ha="center", va="bottom", color=color,
                      fontsize=11, fontweight="bold")
        axis.set(ylim=(0, 35), xlim=(10, 60), yticks=(0, 10, 20, 30), xticks=range(10, 61, 5))
        axis.grid(axis="y", color="#DDE5EC", linewidth=0.85, zorder=0)
        axis.tick_params(axis="both", length=0, pad=6)
        for spine in ("top", "right", "left"):
            axis.spines[spine].set_visible(False)

    axes[-1].set_xlabel("相对 UDP 接收端启动的时间（秒）", labelpad=11)
    fig.supylabel("每区间丢包数（包）", x=0.035, y=0.46, fontsize=15)
    fig.text(0.092, 0.042, "数据来自 7 号公开归档的 udp-receiver.json。复跑作为单次复现证据。",
             fontsize=11, color="#3A4C61")
    fig.savefig(path, dpi=160, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archives", type=Path, help="Directory with verified source JSONL files; omit to fetch GitHub")
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/msyh.ttc"))
    parser.add_argument("--verified-counts", action="store_true", help="Use the recorded, verified loss counts offline")
    args = parser.parse_args()
    if args.verified_counts:
        original, rerun = VERIFIED_COUNTS
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            intervals = list(pool.map(lambda run: receiver_intervals(read_archive(run, args.archives)), RUNS))
        counts = tuple(tuple(item["lost_packets"] for item in values) for values in intervals)
        packet_totals = tuple(sum(item["packets"] for item in values) for values in intervals)
        if counts != VERIFIED_COUNTS or packet_totals != VERIFIED_PACKET_TOTALS:
            raise ValueError("Receiver data differs from the recorded verified values")
        original, rerun = counts
    output_dir = Path(__file__).resolve().parent
    write_csv(output_dir / "C_FIFO_逐秒丢包.csv", original, rerun)
    write_plot(output_dir / "C_FIFO_逐秒丢包.png", original, rerun, args.font)


if __name__ == "__main__":
    main()
