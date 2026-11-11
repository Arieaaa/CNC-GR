"""Generate the v1.0 formal-by-run and diagnostic tables from local CSV snapshots."""

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parent
inputs = ROOT / "inputs"
tables = ROOT / "tables"
tables.mkdir(exist_ok=True)

with (inputs / "formal_run_metrics.csv").open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))
with (inputs / "formal_runs.csv").open(encoding="utf-8-sig", newline="") as f:
    runs = list(csv.DictReader(f))
with (inputs / "C交错复测_20261111.csv").open(encoding="utf-8-sig", newline="") as f:
    diagnostic = list(csv.DictReader(f))

assert len(runs) == 24 and len({r["run_id"] for r in runs}) == 24
assert len(rows) == 186 and len({(r["run_id"], r["metric_id"]) for r in rows}) == 186
assert len(diagnostic) == 6 and [r["mode"] for r in diagnostic] == ["baseline", "qos"] * 3

metrics = defaultdict(list)
for row in rows:
    metrics[(row["experiment"], row["config_id"], row["metric_id"])].append(row)

configs = {
    "A": ["A_n04_ch1-6", "A_n08_ch1-6", "A_n12_ch1-6", "A_n12_ch1-1"],
    "B": ["B_ssf", "B_llf"],
    "C": ["C_baseline", "C_qos"],
}
spec = {
    "A": [
        ("tcp_total", "TCP 接收吞吐之和", "Mbit/s", 3),
        ("tcp_station_avg", "单终端平均 TCP 接收吞吐", "Mbit/s", 3),
        ("rtt_p95_station_max", "最差终端 P95 RTT", "ms", 3),
        ("udp_loss_station_mean", "终端 UDP 丢包率的均值", "%", 4),
        ("udp_loss_station_max", "最差终端 UDP 丢包率", "%", 4),
        ("udp_jitter_station_max", "终端 UDP 抖动的最大值", "ms", 3),
    ],
    "B": [
        ("event_reply_gap", "切换附近最大相邻成功回包间隔", "ms", 3),
        ("ping_loss", "全轮探测丢失率", "%", 3),
        ("ap2_first_x", "首次观测 AP2 的 X 坐标", "m", 4),
        ("rtt_p95", "全轮成功应答 P95 RTT（辅助）", "ms", 3),
    ],
    "C": [
        ("udp_loss", "UDP 业务丢包率", "%", 3),
        ("udp_jitter", "UDP 逐秒抖动的时间均值", "ms", 3),
        ("rtt_p95", "成功应答 P95 RTT", "ms", 3),
        ("tcp_received", "后台 TCP 接收吞吐", "Mbit/s", 6),
    ],
}

output_rows = []
for exp, group in configs.items():
    for config in group:
        for metric, label, unit, digits in spec[exp]:
            found = sorted(metrics[(exp, config, metric)], key=lambda x: int(x["repeat"]))
            assert len(found) == 3 and [r["repeat"] for r in found] == ["1", "2", "3"], (exp, config, metric)
            vals = [float(r["value"]) for r in found if r["value"] != ""]
            assert len(vals) == 3 and all(r["unit"] == unit for r in found)
            output_rows.append({"实验": exp, "配置": found[0]["config_label"], "指标": label, "单位": unit,
                                "第1轮": format(vals[0], f".{digits}f"), "第2轮": format(vals[1], f".{digits}f"),
                                "第3轮": format(vals[2], f".{digits}f"), "有效轮数": len(vals),
                                "均值": format(mean(vals), f".{digits}f"),
                                "样本标准差": format(stdev(vals), f".{digits}f"),
                                "原指标键": metric})

with (tables / "正式实验逐轮与统计.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(output_rows[0]))
    writer.writeheader()
    writer.writerows(output_rows)

def formal_table(exp):
    lines = ["| 配置 | 指标（单位） | 第 1 轮 | 第 2 轮 | 第 3 轮 | 有效轮数 | 均值 ± 样本标准差 |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in output_rows:
        if r["实验"] == exp:
            lines.append(f"| {r['配置']} | {r['指标']}（{r['单位']}） | {r['第1轮']} | {r['第2轮']} | {r['第3轮']} | {r['有效轮数']} | {r['均值']} ± {r['样本标准差']} |")
    return "\n".join(lines)

def diag_table():
    labels = {"baseline": "共享 FIFO", "qos": "分类 HTB"}
    lines = ["| 诊断顺序 | 队列 | 编号 | UDP 丢包数 / 总包数 | UDP 丢包率（%） | 抖动（ms） | 成功 P95 RTT（ms） | TCP（Mbit/s） | 全业务队列累计丢包（包） |",
             "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for i, r in enumerate(diagnostic, 1):
        loss, packets = int(r["udp_lost"]), int(r["udp_packets"])
        assert abs(100 * loss / packets - float(r["udp_loss_pct"])) < 1e-9
        lines.append(f"| {i} | {labels[r['mode']]} | {r['repeat_diagnostic']} | {loss} / {packets} | {float(r['udp_loss_pct']):.4f} | {float(r['udp_jitter_ms']):.4f} | {float(r['rtt_p95_ms']):.3f} | {float(r['tcp_mbps']):.6f} | {r['queue_drops_all_traffic']} |")
    return "\n".join(lines)

def diag_summaries():
    items = [("udp_loss_pct", "UDP 丢包率", "%", 4), ("udp_jitter_ms", "UDP 逐秒抖动的时间均值", "ms", 4),
             ("rtt_p95_ms", "成功应答 P95 RTT", "ms", 3), ("tcp_mbps", "后台 TCP 接收吞吐", "Mbit/s", 6)]
    lines = ["| 诊断队列 | 指标（单位） | 有效轮数 | 均值 ± 样本标准差 |",
             "| --- | --- | ---: | ---: |"]
    for mode, label in [("baseline", "FIFO"), ("qos", "HTB")]:
        subset = [r for r in diagnostic if r["mode"] == mode]
        assert len(subset) == 3
        for field, name, unit, digits in items:
            vals = [float(r[field]) for r in subset]
            lines.append(f"| {label} | {name}（{unit}） | 3 | {mean(vals):.{digits}f} ± {stdev(vals):.{digits}f} |")
    return "\n".join(lines)

report = """# 8 号实验统计与诊断补充 v1.0

更新日期：2026-11-11。依据 1 号提供的《CNC-GR 实验统计与汇报口径 v1.0》及 7 号《08 号问题核对答复》。1 号口径为本次汇报统一规则；7 号答复中的核查和诊断用于补充证据。

**本次正式服务达标率留空。** 50 ms、1% 是原方案示例，不参与本次判定。运行状态 `PASS`、`COLLECTED` 表示采集状态，不能代替业务达标。本报告按照目标、条件、观察和局限组织，不以示例阈值计算达标率。C 不设 TCP 下限、联合条件或相对改善门槛。

## 数据范围和汇总方法

正式记录 24 轮：A 12、B 6、C 6，8 个配置每个 3 轮。下列各项的有效轮数均为 3。A 试跑 `run00` 和 B 的 pilot 不纳入；7 号对 A/B/C 各复跑 1 次、后续 B 路线诊断与 C 交错诊断均单列。抽样原轮已经在 24 轮中，不重复计数。

每轮 P95 直接引用实验负责人发布的正式汇总值，再对配置内 3 个逐轮值计算均值和样本标准差。它不是合并所有包后计算的 P95。单独复算原始样本时用最近秩第 `ceil(0.95×n)` 个有效样本；如与原汇总使用的口径不同，分别标注，不混合。缺测留空、运行失败单列；B 未观测切换或回包不足时，事件间隔记为不可测，不能记作 0。未来多事件轮保留逐事件结果，轮级汇总取有效事件最大间隔，并标明事件数和缺测。

7 号已核对正式汇总表到配置统计的均值和样本标准差一致。这不表示 24 轮原始日志已全部独立复算。数据和逐轮运行编号见 [正式运行索引](inputs/formal_runs.csv) 和 [正式指标明细](inputs/formal_run_metrics.csv)。

## A 并发与信道：正式轮

条件：4、8、12 终端在信道 1/6，另有 12 终端在信道 1/1；每配置 3 轮。TCP 和 UDP 分轮，各先预热 10 秒再统计 60 秒；UDP 每终端 2 Mbit/s、1400 B。ping 在 TCP 流启动前开始，约 60 秒，不剔除预热。各终端 TCP 接收吞吐的统计窗口未严格对齐，下面称为接收吞吐之和。RTT、TCP、UDP 使用各自窗口，不作跨分轮联合判定。

UDP 的“均值”是同一轮各终端丢包率的均值；“最差”是同一轮各终端值的最大值，随后再跨 3 轮统计。“最差终端 P95”先取同一轮终端 P95 的最大值，再跨轮统计。

{table_a}

图：[A TCP 与 RTT](figures/A_正式_TCP与RTT.png) · [A UDP 丢包与抖动](figures/A_正式_UDP丢包与抖动.png)。

信道 1/6 下，终端由 4 台增至 12 台时，单终端平均吞吐下降，最差终端 P95 增加。12 台下 1/1 与 1/6 仅报告观察差异，现有结果不足以确认稳定收益。若未来判断所有终端均达标，需同轮逐终端原始值和完整名单；缺测时联合判定不可用。

## B 移动与关联：正式轮

条件：同一路线、信道和背景负载下，SSF 与 LLF 各 3 轮；全轮每次发送 375 个探测包，探测周期约 0.2 秒。事件窗口沿用 5 号定义，两侧延伸到最近成功回包。全轮 P95 仅含成功应答，作为辅助描述。切换附近的间隔包含正常探测间隔，不等于协议切换耗时。

{table_b}

图：[B 移动与关联](figures/B_移动与关联.png)。

LLF 首次观测到 AP2 更早；SSF 的事件附近最大相邻成功回包间隔均值较短。全轮 P95 和局部事件间隔衡量不同现象。

## C 实时业务与后台业务：正式轮

条件：服务器出口上限 2 Mbit/s、300 kbit/s UDP 与持续后台 TCP。正式轮 60 秒，UDP、RTT 和 TCP 分别按各自来源统计后 50 秒，RTT P95 只含成功应答；FIFO 与 HTB 各 3 轮。UDP 业务丢包和 ping 探测丢失是不同指标。

{table_c}

图：[C 正式混合业务与 QoS](figures/C_混合业务与QoS.png)。

当前负载与出口下，正式 HTB 三轮的实时 UDP 丢包率、抖动和成功 P95 RTT 较低，后台 TCP 吞吐接近。三轮 UDP 观测为 0% 不代表所有业务零丢包，结论不外推至无线空口 EDCA 或真实音视频体验。

## 7 号核查和补充诊断（不并入正式 24 轮）

### A：指定异常轮

`expA_n12_ch1-6_run02` 中，sta7 的 294 个成功应答平均 RTT 为 34.854 ms，sta8 的 292 个为 34.514 ms。7 号核查发现高值集中在序号 1–5；仅为定位影响，分别去除这些序号后描述性均值为 24.336 ms（289 个）和 24.024 ms（287 个）。正式数据未删除这些值，也不将这种描述性计算当作正式窗口。部分回包重排，日志缺少逐包绝对时间，不能将高值精确对齐到预热边界或认定单一原因，保留该轮并请 4 号结合运行器与系统日志继续核查。

### B：信号异常及路线 pilot

原始记录的 `121 dBm` 保留，不用于解释策略差异。7 号检查发现原路线与 AP 坐标重合，模型中的 `log10(d)` 在零或极近距离存在边界问题；路线 y 从 25 改为 27 m 后，LLF 和 SSF 各 1 轮 pilot 均为 0/375 正信号并观察到关联变化，SSF 仍有 3 个探测包未收到。这支持极近距离引发模型边界异常，但不能确定具体数值转换环节。新路线是诊断配置，不替代原 6 轮；是否重新采集由 3/5 号确认。

### C：单次复跑和交错诊断

原 FIFO 抽样正式轮 UDP 丢包 42/11721 = 0.358331%，一次复跑 232/11718 = 1.979860%；50 个约 1 秒完整区间中有丢包者为 8 个与 32 个。总队列丢包 82 与 334 包覆盖所有业务且窗口不同，不能与 UDP 丢包逐包对应。队列计数及后台竞争支持出口拥塞与队列竞争是主要机制，但不能判定每个包的丢失位置或排除调度等其他影响。

后续额外进行了 FIFO、HTB 各 3 轮交错诊断，运行顺序如下。这 6 轮不是原正式记录，不用于重算正式组均值或正式样本数。UDP 与 RTT 取 60 秒中的后 50 秒；全业务队列丢包为累计计数，范围与 UDP 后 50 秒不全相同。

{diag_table}

{diag_stats}

图：[C 交错诊断的实时 UDP 与全业务队列](figures/C_交错诊断_实时UDP与队列.png)。

诊断的 HTB 三轮 UDP 丢包均为 0%，但全业务队列累计分别丢 50、55、59 包，不能说所有业务零丢包。分类同时涉及队列和带宽份额，不能将观察归因于单条过滤规则。7 号抽查的正式 HTB 第 2 轮中，文本规则及启动 ping 之前的实时类字节计数支持 UDP 进入实时类；这不是每条过滤规则的独立命中证明。

## 来源和后续核对

- [A 正式汇总](https://github.com/Arieaaa/CNC-GR/blob/65e4e94f447a485de9c8217b094fe414d74cab06/4/project/expA_summary.csv) · [B 正式汇总](https://github.com/Arieaaa/CNC-GR/blob/65e4e94f447a485de9c8217b094fe414d74cab06/5/project/实验B/实测/summary.csv) · [C 正式汇总](https://github.com/Arieaaa/CNC-GR/blob/65e4e94f447a485de9c8217b094fe414d74cab06/6/project/wifi-qos/results/formal_runs.csv)。
- [7 号 B/C 诊断记录](https://github.com/Arieaaa/CNC-GR/blob/65e4e94f447a485de9c8217b094fe414d74cab06/7/project/诊断试验/B信号与C丢包诊断_20261111.md) · [C 诊断逐轮来源](https://github.com/Arieaaa/CNC-GR/blob/65e4e94f447a485de9c8217b094fe414d74cab06/7/project/诊断试验/C交错复测_20261111.csv)。
- 本次使用的 1 号 v1.0 口径由组内消息提供；截至本次核查，尚未在该仓库的上述提交中看到它。7 号答复来自组内交接。
- 后续请 7 号复核更新后的统计，2 号核对配置和解释，10 号据此汇总三项目标的证据及边界。轻量扩展仅在有可核查对照、日志和指标时作为独立补充。

图表需标明单位、有效样本数、误差线含义、条件和来源。PPT 后续再修改；不要沿用旧稿中“需先确定阈值再计算本次达标率”的表述。

本地运行 `python generate_report.py` 可用 `inputs/` 重建本文逐轮表和 `tables/正式实验逐轮与统计.csv`。
"""

report = report.format(table_a=formal_table("A"), table_b=formal_table("B"),
                       table_c=formal_table("C"), diag_table=diag_table(), diag_stats=diag_summaries())
(ROOT / "8号正式统计与诊断说明_v1.0_2026-11-11.md").write_text(report, encoding="utf-8")
print(f"Generated {len(output_rows)} formal metric rows and {len(diagnostic)} separate diagnostic runs.")
