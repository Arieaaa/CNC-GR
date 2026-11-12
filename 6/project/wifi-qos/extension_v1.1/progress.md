# SDD ledger — plan: ../实验C扩展实验方案_v1.1_20261111.md

- Task 1: pending — 队列配置、单流动态收发器、统计边界测试。
- Task 2: pending — 运行器与固定矩阵、环境及原始记录。
- Task 3: pending — 服务器预检、短测、冻结版本。
- Task 4: pending — 48轮正式矩阵及必要补测。
- Task 5: pending — 审计、离线重算、图表与结果解释。

Ruling: 当前目录为无Git元数据的交付快照，扩展在独立extension_v1.1目录实施，不改旧脚本和旧结果；Git工作树/提交辅助工具不适用。代价：版本追踪依赖冻结哈希与快照。
Pre-flight: 队列配置供静态与动态共同调用；动态收发记录由同一离线统计器解释；所有正式轮冻结同一源码哈希。

Task 1: complete — 10项核心合同测试RED→GREEN，另有真实UDP回环测试RED→GREEN；动态审计与配置审查测试通过，共16项。
Task 2: implemented — runner.py / batch.py，等待服务器预检与独立审查。
Ruling: TCP按启动下界至观察到16384字节数据的上界界定开始时间，阶段统计只取确定完全落入窗口的接收端区间，避免用粗粒度iperf epoch冒充精确对齐；代价：阶段统计少量边界区间被排除。
Ruling: 发送系统调用错误始终判INVALID；偶发调度错过的槽位独立记录，仍须每阶段实际速率±2%、超过包间隔的迟到槽位≤1%。不把未发出的包计作网络丢包；代价：业务负载有已量化的小幅生成误差。

Final review: fresh reviewer /root/review_extension (gpt-6-astra high); 五项Important，均已补回归测试并修复，24/24通过。无Critical或Minor。
Final: fixed 批次锁前覆盖来源 — 已有批次拒绝覆盖，测试RED→GREEN。
Final: fixed 缺少类参数和叶缓存映射校验 — audit_classes与按handle缓存审查，测试RED→GREEN。
Final: fixed TCP部分区间也能通过 — 连续性与窗口覆盖检测，测试RED→GREEN。
Final: fixed 接收尾部溢出漏检 — 每网络命名空间SNMP前后计数，测试RED→GREEN。
Final: fixed 大包/内存阈值影响容量 — MTU=1500、maxpacket≤1514、drop_overmemory=0门限，测试RED→GREEN。
Ruling: 物理容量重测改为与正式组相同offload关闭条件，避免前置能力与实际数据路径配置不同；代价：预检额外运行约一分钟。
Ruling: tc的target/interval读回允许1微秒转换舍入，毫秒级偏差仍拒绝；代价：记录的实际目标与命令值有已知极小差异。
Task 2: complete — 本地24项测试通过，服务器最终短测进行中。

Ruling: 每轮改由独立Python子进程运行，继承父进程同一flock文件描述符；原因是Mininet-WiFi在同一解释器重复建网残留全局状态。代价：每轮增加少量进程启动开销。
Ruling: 常见offload开关关闭仍观察到18168字节GSO大包，新增srv数据接口gso_max_size=1514、gso_max_segs=1，并核查最终maxpacket≤1514。仅影响本轮仿真接口；代价：与v1.0结果的TCP发送形态不同，全部正式配置统一重测。
Ruling: tc -d会以4Kb/1输出burst，审查其4096字节主体并保留cell后缀原文；u32 JSON重复match键归一为matches列表，原文另存，防止协议/端口字段被JSON解析丢弃。
Ruling: 静态iperf在欠保障时正常关闭后，有队列尾包到达已关闭UDP端口（NoPorts增加27—30，InErrors/RcvbufErrors均0）。NoPorts单独记录，不当作接收缓冲溢出；动态接收器有2秒排空，仍严格要求NoPorts不增长。代价：静态尾部关闭效应须在结果中注明。

Task 3: 8/9最终预检PASS，统一GSO约束下的双链路容量重测中；预检完成自动执行48轮。正式统计主要指标与补测触发规则已另存analysis_preregistration.md。

Task 3: complete — pilot_gate7 9/9 PASS；单流动态、两个HTB份额、FQ、观测开销、同offload链路容量全部通过。
Task 4: in progress — formal 48轮，wifi-expc-v11-full7临时systemd单元。

Offline review: /root/review_extension completed read-only review of new tools, six Important plus missing-delay contributing-count limitation. All fixed; new regression failures observed first; complete suite42/42 passes.
- Frozen supplement triggers from initial repeats1–3, expanded comparison membership including shared E1 references; required repeats4/5 remain latched.
- Final CSV and summary use raw-audited records; interim compact outputs explicitly marked unaudited.
- Sustained resource conditions are warnings requiring a recorded disposition before publication, not automatic data exclusions.
- Export rejects cross-batch filename collisions before writing; restoration rejects duplicate index entries.
- Matrix audit rejects duplicate configuration/repeat identities and requires all triggered supplemental repeats before publication.
- Plot uses audited restored-log location and fails when expected TCP logs are missing.
- Report shows contributing counts if delay values are missing.
Ruling: 共享HTB600参考组的初始3次jitter CV触发规则会同时影响E1、E2、E4，因此按比较范围补测所有12个静态配置至5次，而不是只补E1。代价：至少新增24轮60秒测试；原始数据全部保留。

补测按重复4/5分块、固定种子随机顺序；避免按方法连续运行导致时间偏差。对应回归测试RED→GREEN。

核心30轮全部采集PASS；动态四配置各3次稳定，未触发额外动态重复。最终补测清单固定24轮静态，保存server_snapshot/supplement_manifest.json。基础总48+补测24=72轮。

基础formal48/48 COMPLETE，无INVALID。已核对同一源码哈希，启动wifi-expc-v11-supplement临时单元24轮；目标72。

Task 4: complete — 基础48+补测24=72轮全部PASS，无采集INVALID；静态12配置×5，动态4配置×3。
Task 5: complete — 95份JSONL、67230原文件无损校验还原；72轮指标从原始记录重算通过，源码/拓扑一致，CPU/采样/接收检查通过，无待处理告警、无剩余补测。六组PNG/PDF已视觉检查，报告已生成。
Final verification: 完整44项测试通过；服务器临时单元成功退出，iperf3/wmediumd、实验接口与桥均清理，共享锁可用。发布目录不含压缩包。
Ruling: 工作区无Git元数据，按独立文件交付保存，开发分支合并/PR流程不适用；本次未进行外部发布。代价：后续仓库同步应以交付校验清单为准。
