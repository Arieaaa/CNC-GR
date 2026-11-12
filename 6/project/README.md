# 6号实验C：统一结果交付

已将原实验与拓展实验整理为一份统一报告。两阶段共78轮有效正式实验：v1.0前期验证6轮，v1.1主实验72轮。主结论使用v1.1统一条件下的三方法对照、保障份额扫描、动态需求与缓存敏感性；前期结果作为研究起点保留。

## 先看这些文件

- **[实验C统一结果报告](实验C统一结果报告.md)**：完整结论、全部主要图表、版本关系和复现入口。
- [78轮统一数据](unified_results/formal_runs_78.csv)：版本、配置、指标窗口与证据位置。
- [分版本汇总](unified_results/summary_by_version.json)：18个配置组，分别统计。
- [来源与日志索引](unified_results/source_index.json)、[统一核查结果](unified_results/validation.json)。

## 主要结果

900 kbit/s高需求阶段，FQ-CoDel和HTB1200的50 ms内有效交付均为100%；UDP包P95分别约6.01 ms、0.28 ms。FIFO约82.85%的包能按时到达；HTB600的保障份额不足。动态各配置3次，静态各配置5次。

两版本的HTB突发参数、聚合控制和测量入口有差异，数据保留版本标签，不混合求均值。三方法排名使用v1.1数据。

## 原始交付与校验

- [v1.0原始交付快照](history/v1.0_original_delivery/README.md)：原布局与原SHA-256清单完整保留。
- [v1.1完整交付](wifi-qos/extension_v1.1/README.md)：72轮、六组PNG/PDF、脚本和可还原合并日志。
- 旧`wifi-qos/`路径的v1.0文件保留兼容；统计时不把历史副本重复计数。
- 两版本规范索引共106份JSONL，保存71,573份原始文件；无压缩包。
- `FILES_UNIFIED.sha256`校验当前统一交付。可用`python3 unified_results/build_unified.py`重新生成报告与统一索引。
