# 实验C完整交付

本包包含2026年11月9日实际完成的校园Wi-Fi实验C结果。正式对照两组各3轮，每轮60秒、统计后50秒，全部PASS。

先阅读 `实验C详细方案与现场检查记录.md`。结果图在 `results/expc_comparison.png`、`results/expc_timeseries.png`，同时有PDF。正式6轮指标为 `results/formal_runs.csv`，审计为 `results/audit.json`，参数交接为 `results/参数回填与核查说明.md`。

`merged_logs/`按轮合并原始正式日志、容量标定、成功短试跑和一次解析兼容问题导致的失败记录。11个JSONL完整保存4,343份原文件。执行`python scripts/restore_logs.py merged_logs logs`可校验并还原原目录。`results/runs.csv`与summary.json保留短试跑/正式分组，图表和报告仅使用审计通过的6轮。

`scripts/expc.py`与`server_snapshot/expc.py`为相同的实际运行器。公共拓扑快照在server_snapshot/topology.py。其他scripts包含汇总、审计、绘图和报告生成脚本。绘图需要本地matplotlib，网络实验仅用服务器已有依赖。

本次由wifi06通过已授权的sudo -i管理员会话启动临时systemd任务，未安装新的sudoers或修改公共拓扑。早期准备的install.sh与wifi-expc是可选固定入口部署材料，本次实测没有使用。

复算顺序：

```bash
python scripts/restore_logs.py merged_logs logs
python scripts/summarize.py logs results
python scripts/audit_results.py .
python scripts/plot_results.py .
python scripts/write_report.py .
python -m unittest discover -s tests -v
```

报告中的数字来自真实原始日志，raw日志不覆盖。正式运行的服务器端目录列在详细报告末尾。所有原始文件直接归档，可按上述命令独立复算。
