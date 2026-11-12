#!/bin/bash
# 临时systemd任务调用；单轮运行器自行持有公共锁。第一处失败即停止批次。
set -euo pipefail
export MPLBACKEND=Agg
export WIFI_OPERATOR=wifi06
task_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
for condition in baseline:1 qos:1 qos:2 baseline:2 baseline:3 qos:3; do
    mode=${condition%:*}
    repeat=${condition#*:}
    printf 'BEGIN %s %s %s\n' "$mode" "$repeat" "$(date -u +%FT%TZ)"
    /usr/bin/python3 -IBu "$task_dir/expc.py" "$mode" --run "$repeat" --total-kbit 2000 --seconds 60
    printf 'END %s %s %s\n' "$mode" "$repeat" "$(date -u +%FT%TZ)"
done
printf 'BATCH_PASS\n'
