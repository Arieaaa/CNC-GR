# 实验C扩展交付 v1.1

已完成72轮有效正式实验：基础矩阵48轮，按预先约定规则追加24轮；静态12种配置各5次，动态4种配置各3次。原始日志重算与配置审计通过。

- [实验结果与分析](实验结果与分析.md)：数据表、机制解释、参数选择及六组图。
- [实验方案](protocol.md)：三种方法、控制变量、完整矩阵和验收标准。
- [统计与补测约定](analysis_preregistration.md)：指标口径、触发规则及补测顺序。
- [实施记录](progress.md)：现场兼容处理、版本冻结和核查记录。

## 文件说明

- `scripts/`：本轮冻结的运行脚本；`runner.py`单轮，`batch.py`串行批次，`core.py`队列/协议/矩阵，`udp_phase.py`单流动态发生器，`analysis.py`包统计，`legacy.py`前版辅助解析。
- `results/formal_runs.csv`：逐轮汇总；动态行的主要UDP指标对应高需求阶段。
- `results/phases.csv`：动态三阶段数据；TCP重传来自发送端，吞吐来自接收端。
- `results/summary.json`：组均值、样本标准差和有效次数。
- `results/audit.json`：原始指标重算、版本/队列/资源和矩阵完整性审计。
- `results/figures/`：六组PNG/PDF图表。
- `merged_logs/`：每轮一个可校验还原的JSONL；同时保留预检、无效开发短测的证据。正式结论仅统计72轮有效正式数据。
- `server_snapshot/`：实际脚本、公共拓扑、环境版本及基础/补测的manifest、index、progress。
- `FILES.sha256`：此目录逐文件校验值，不包含其自身。

FIFO和FQ-CoDel行的`rt_kbit=600`是配置结构占位，只有分类HTB组具有对应保障份额。三组均经过同一个2 Mbit/s总出口整形器。

## 离线复现

Python 3.9以上可进行还原、审计与统计；绘图另需matplotlib、numpy。还原目标必须是新目录。

```bash
python3 tools/restore_logs.py merged_logs restored_logs
python3 tools/audit.py . restored_logs
python3 tools/postprocess.py .
python3 tools/plot_results.py .
python3 tools/write_report.py .
python3 -m unittest discover -s tests -v
```

日志内容保留原路径、UTF-8原文及SHA-256，无需解压。审计完成后会记录实际还原位置，绘图使用该位置。

## 实机重跑

需要03号已部署的公共Mininet-WiFi环境、管理员权限以及`/var/lib/wifi-lab/run.lock`。在新批次目录中，通过临时systemd任务运行`batch.py --root <新目录> --manifest <已审核清单>`；它持有共享锁并为每轮启动独立进程。实际基础和补测清单保存在server_snapshot中。正式脚本与公共拓扑的哈希须保持一致。

本目录完整保留独立文件与合并日志，不使用压缩包。旧v1.0交付另行保留。
