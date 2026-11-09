#!/bin/bash
set -euo pipefail
export MPLBACKEND=Agg
export WIFI_OPERATOR=wifi06
for condition in baseline:1 qos:1 qos:2 baseline:2 baseline:3 qos:3; do
    mode=${condition%:*}
    repeat=${condition#*:}
    printf 'BEGIN %s %s\n' "$mode" "$repeat"
    /usr/bin/python3 -IBu /home/wifi06/expC_handoff_20261109/scripts/expc.py "$mode" --run "$repeat" --total-kbit 2000 --seconds 60
    printf 'END %s %s\n' "$mode" "$repeat"
done
printf 'BATCH_PASS\n'
