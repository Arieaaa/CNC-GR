#!/usr/bin/env bash
# 实验 A 正式采集矩阵：4 种配置 × 3 次重复 = 12 轮
#   阶段一（并发规模）：信道固定 1/6，终端数 4 / 8 / 12
#   阶段二（信道对照）：终端数固定 12，信道 1/1 与 1/6（n12_ch1-6 与阶段一共用）
# 每轮约 2.5–3 分钟（拓扑建立 + TCP 60s + UDP 60s），全程约 35–40 分钟。
# 使用前：确认无其他实验在跑（本脚本每轮都会自查 run.lock），并与 03 号约好时段。
set -euo pipefail
cd "$(dirname "$0")"

for run in 01 02 03; do
  for cfg in "4 1,6" "8 1,6" "12 1,6" "12 1,1"; do
    echo "=== expA $cfg run$run ==="
    sudo python3 expA.py $cfg "$run" wifi04
  done
done

echo "全部 12 轮完成，日志在 /var/lib/wifi-lab/runs/expA_*"
