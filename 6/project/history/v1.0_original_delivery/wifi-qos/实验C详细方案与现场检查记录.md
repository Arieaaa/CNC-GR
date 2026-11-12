# 实验C混合业务与出口QoS保障实验报告及复现方案

编制时间：2026年11月09日 21:55，北京时间。负责人：6号。正式运行6轮，全部PASS，每组3次，每轮60秒，统计后50秒。

## 1 实验结果

在相同2 Mbit/s服务器仿真出口上限下，分类HTB降低了实时UDP的丢包、抖动和探测RTT。每轮P95 RTT的组均值由136.000 ms变为0.866 ms，降低99.36%；UDP逐秒jitter时间均值由5.4659 ms变为0.1095 ms。后台TCP均值由1.5519变为1.5519 Mbit/s，相对差异小于0.01%。

以下“均值±样本标准差”以3轮独立运行的指标为样本。P95列是各轮P95的组汇总，并非合并所有探测后重新计算的P95。

| 指标 | 同限速共享FIFO | 分类HTB保障 |
|---|---:|---:|
| UDP接收吞吐 Mbit/s | 0.2973 ± 0.0021 | 0.3000 ± 0.0000 |
| UDP丢包率 % | 0.9471 ± 0.6571 | 0.0000 ± 0.0000 |
| UDP逐秒jitter的时间均值 ms | 5.4659 ± 0.0742 | 0.1095 ± 0.0074 |
| 平均RTT ms | 98.163 ± 3.030 | 0.452 ± 0.093 |
| 每轮P95 RTT ms | 136.000 ± 6.000 | 0.866 ± 0.463 |
| 后台TCP接收吞吐 Mbit/s | 1.5519 ± 0.0000 | 1.5519 ± 0.0000 |

| 配置 | 重复 | UDP丢包 % | UDP jitter时间均值 ms | P95 RTT ms | TCP吞吐 Mbit/s |
|---|---:|---:|---:|---:|---:|
| 共享FIFO | 1 | 0.8269 | 5.3966 | 142.000 | 1.5519 |
| 共享FIFO | 2 | 0.3583 | 5.4568 | 130.000 | 1.5519 |
| 共享FIFO | 3 | 1.6560 | 5.5442 | 136.000 | 1.5519 |
| 分类HTB | 1 | 0.0000 | 0.1109 | 1.400 | 1.5519 |
| 分类HTB | 2 | 0.0000 | 0.1015 | 0.574 | 1.5519 |
| 分类HTB | 3 | 0.0000 | 0.1162 | 0.625 | 1.5519 |

图表位于results/expc_comparison.png及results/expc_timeseries.png，同时提供PDF用于导出。图中散点为单轮，误差线为样本标准差；灰色阴影是预热阶段。当前TCP每秒接收字节主要为131072或262144字节，单秒吞吐曲线呈离散台阶，解释长期吞吐时使用50秒汇总。

## 2 验证目标与数据路径

目标是在下载与实时小流量共存时，验证出口分类与最低带宽保障的作用，并观察后台吞吐的资源代价。使用合成UDP模拟实时负载，持续TCP模拟下载。

数据路径：srv → srv-eth0出口HTB → s1 → ap1/ap2 → sta1/sta2。UDP由srv下发sta1，TCP由srv下发sta2。两个终端分别关联两个AP，位置与关联在两种配置中不变。

队列位于服务器的仿真有线接口srv-eth0。公网SSH管理接口未设置tc，云实例公网3 Mbit/s带宽不是实验限速值。本实验验证服务器出口管理，不据此声称实现了空口EDCA或真实通话质量提升。

## 3 前序交接与现场参数

复用3号 `/opt/wifi-lab/topology.py` 的 `campus_topology(2,(1,6))`，未修改公共拓扑。AP1在(15,25,0)，AP2在(70,25,0)；sta1在(20,23,0)，sta2在(75,23,0)；srv为10.44.0.100，sta1为10.44.0.1，sta2为10.44.0.2。

无线配置为802.11g、2.4 GHz、20 MHz、信道1/6，共同SSID campus-lab；传播模型logDistance、指数3，wmediumd干扰模式，请求覆盖半径36m。AP实际发射功率由iw记录为1.00 dBm，而非2号建议表中的14 dBm；这源于已部署拓扑的range配置，两组均沿用相同值。完整无线输出随每轮日志保存。

2号参数表中的建议坐标、SSID、覆盖范围与已验收脚本存在差异。本实验以部署脚本及运行时输出为准，建议2号将实际参数回填。T-12总速率确定为2000 kbit/s；C-06已通过运行中HTB配置持久性、分类及独立UDP字节证据核查。

现场环境：Ubuntu24.04.4、内核6.8.0-138-generic、Mininet-WiFi2.7、iperf3 3.16、tc/iproute2 6.1.0、iw6.7、OVS3.3.9。完整源码提交和软件清单见每轮source-versions.txt。

运行器SHA256：`e2e53215afaf27f676affb838431e8f00437ff0a2d87445730414b79bc2d829d`。

公共拓扑SHA256：`ff61cd8fa0e91d72c8a953948d83053899a62e2cedf1e6757b0e60830dc62c19`。

## 4 先标定容量再固定瓶颈

首先完成双AP基础验收：两个终端各3次ping无丢包，短时上行TCP约35.59/35.92 Mbit/s，该结果只用于基础连通性确认。

随后分别进行30秒下行TCP标定，去掉前10秒后：capacity-sta1：35.9665 Mbit/s；capacity-sta2：35.9665 Mbit/s。2 Mbit/s实验上限约为单路径标定容量的1/18，使出口整形比下行无线容量更早形成瓶颈。

基线与保障各进行15秒短试跑，仅用于联调，不混入正式60秒结果。首次基线试跑因服务器HTB插件忽略tc的-j参数而返回文本，在统计解析阶段失败，原始FAIL目录保留。已增加文本规范化兼容、保留原始文本并通过回归测试；之后两种短试跑均通过，再冻结运行器版本开始正式6轮。

## 5 可复现的流量与队列配置

| 项目 | 共享FIFO基线 | 分类HTB保障 |
|---|---|---|
| 公共父类1:1 | rate=ceil=2000kbit/s | rate=ceil=2000kbit/s |
| UDP负载 | 300kbit/s，160字节payload，单流 | 完全相同 |
| TCP负载 | 一条持续下行TCP，不另设应用速率上限 | 完全相同 |
| UDP/TCP端口 | srv独立iperf3服务进程，5202/5203 | 完全相同 |
| 叶类 | 单一共享类1:20 | 实时类1:10，后台类1:20 |
| 最低份额 | 共享类2000kbit/s | 实时600kbit/s、后台1400kbit/s |
| 借用上限 | 2000kbit/s | 两类ceil均2000kbit/s |
| 总缓存预算 | bfifo32768字节 | 实时8192+后台24576字节 |
| 叶类quantum | 1514字节 | 均1514字节 |
| RTT探测 | sta1→srv，0.2秒一次 | 相同探测，srv的ICMP应答归实时类 |
| 测试与统计 | 60秒，前10秒预热，1秒业务报告 | 完全相同 |

使用iperf3 -R实现srv至终端的数据方向。UDP过滤条件是IP协议17、源端口5202、目的地址sta1；ICMP探测有单独过滤规则，不能仅靠UDP端口规则推断ping得到保障。

600kbit/s实时保障份额包含协议开销余量；它不是把UDP有效负载提升到600kbit/s。允许借用意味着实时类空闲份额可被后台使用，不把未使用的保障带宽全部闲置。

## 6 实际运行与复现步骤

1. 登录wifi06，使用已开放的sudo -i获得管理员权限；查看是否有人运行实验。运行器会尝试获取 `/var/lib/wifi-lab/run.lock`，忙时立即退出。
2. 本次使用临时systemd任务执行现有脚本，未安装新sudoers规则，也未修改公共拓扑。此前准备的install.sh不是本次实测前提。
3. 如需复现，先核对运行器、拓扑哈希及版本，再在服务器已有脚本位置启动单轮：

```bash
# 以下在sudo -i后的管理员终端执行
systemd-run --quiet --wait --pipe --collect \
  --property=PrivateTmp=yes --property=RuntimeMaxSec=300s \
  --property=TimeoutStopSec=30s \
  --setenv=MPLBACKEND=Agg --setenv=WIFI_OPERATOR=wifi06 \
  /usr/bin/python3 -IBu \
  /home/wifi06/expC_handoff_20261109/scripts/expc.py \
  baseline --run 4 --total-kbit 2000 --seconds 60
```

4. 将baseline改为qos即可复现保障组；capacity模式分别测两个终端的下行能力，udp-only可作无后台业务的补充实验。
5. 正式顺序为baseline1、qos1、qos2、baseline2、baseline3、qos3。每轮新建拓扑，退出时清理本轮业务进程及网络，启动至清理全程持锁。
6. 每条命令打印独立日志目录。检查status.txt、run.log及metrics.json，失败运行保留，不覆盖或计入正式样本。抽样复现时使用新重复编号。
7. 在个人电脑运行以下命令重新生成汇总和图表：

```bash
python scripts/restore_logs.py merged_logs logs
python scripts/summarize.py logs results
python scripts/audit_results.py .
python scripts/plot_results.py .
```

## 7 证据有效性与资源核查

运行器先启动UDP和TCP，前2秒不启动ping；实时类已有字节增长后再启动ping。因此独立命中证据不依赖ICMP计数。

各轮每秒保存tc qdisc/class/filter，比较根队列、类速率、缓存及过滤配置，6轮配置均持续有效；正式原始iperf3区间也重新核算并与metrics.json完全一致。两种策略使用同一个运行器及公共拓扑哈希。

| 配置/重复 | 运行中队列快照数 | 主机CPU忙碌 % | CPU steal % | 采样最大根队列积压 字节 | 最终根队列丢包计数 |
|---|---:|---:|---:|---:|---:|
| baseline / 1 | 60 | 54.47 | 0.00 | 32300 | 163 |
| baseline / 2 | 60 | 54.45 | 0.00 | 32098 | 82 |
| baseline / 3 | 60 | 54.39 | 0.00 | 32604 | 271 |
| qos / 1 | 60 | 53.50 | 0.00 | 24224 | 61 |
| qos / 2 | 60 | 56.46 | 0.00 | 24224 | 64 |
| qos / 3 | 60 | 54.02 | 0.00 | 24224 | 53 |

CPU百分比由/proc/stat起止差计算，统计区间为本轮业务及采集阶段，CPU忙碌范围53.50%至56.46%。队列积压每秒采样，最大值是采样值而非连续观测峰值。根队列丢包可能来自TCP等全部流量，不能直接当作UDP丢包；HTB overlimits是整形等待计数，不是丢包数。

## 8 指标计算与解释

接收吞吐按10至60秒接收字节和实际完整区间时长计算；拒绝发送端区间、缺测窗口、iperf错误和零吞吐后台TCP。UDP丢包率按稳态总丢失包数/总包数计算，不平均每秒百分比。

抖动来自iperf3接收端jitter；表中给出逐秒工具报告值的时间均值，再在3轮间求均值和标准差。RTT来自成功ping应答，按接收时间截取窗口，P95采用nearest-rank；均值、P95及样本数已从原始ping独立复算。基线3轮稳态内部应答序号缺口为2/0/1，保障组为0/0/0。探测间隔受调度影响，不能用“250减成功应答数”直接计算丢包；窗口边界未完成应答也不据此计算精确探测丢包率。不把成功样本P95当作含丢包的全体探测指标。

本配置中，保障组通过分离队列和带宽份额降低了实时流排队时延，具体降幅见结果表。TCP吞吐的实际变化也见结果表；应按实测描述代价，不能预设实时保护一定牺牲TCP吞吐。3次重复用于展示当前条件的稳定性，未进行大规模负载扫描或统计显著性检验。

如采用原方案示例门槛“P95 RTT<50ms且UDP丢包<1%”，可以根据每轮值演示判定；它是课堂实验约定，不是Wi-Fi通用标准。正式达标表应由1/2/7/8号共同确认阈值及统计窗口后使用。

## 9 交付清单与组内衔接

- scripts/expc.py：实际运行器；scripts/run_formal.sh：批次重跑示例；scripts/summarize.py、audit_results.py、plot_results.py：整理、审计与绘图。
- merged_logs/：每轮一个JSONL，完整保存容量标定、联调成功及失败记录、6轮正式原始数据和基础验收。先运行restore_logs.py还原为logs/，再按原分析脚本复算。
- results/formal_runs.csv：仅含审计通过的6轮正式指标；runs.csv、summary.json保留短试跑与正式分组；audit.json保存配置及资源证据。
- results/expc_comparison.png/pdf、expc_timeseries.png/pdf：可导出图表。
- 2号回填T-12=2000kbit/s、实际无线参数与C-06通过证据；7号核查字段与原始日志；8号接收汇总图表。
- 3号与7号的组内联合抽样复现仍需由对应成员执行；本次6号账号完成的3次重复不冒充其联合复现记录。9号可选已验证的基线/保障片段用于演示。

正式目录索引：

- `expC_baseline_c2000_run01_20261109T134207Z_4fs0o1wx`：baseline，重复1，PASS。
- `expC_baseline_c2000_run02_20261109T134607Z_47qrkol0`：baseline，重复2，PASS。
- `expC_baseline_c2000_run03_20261109T134726Z_1n9j2ujo`：baseline，重复3，PASS。
- `expC_qos_c2000_run01_20261109T134327Z__02q2oah`：qos，重复1，PASS。
- `expC_qos_c2000_run02_20261109T134447Z_0439qzhl`：qos，重复2，PASS。
- `expC_qos_c2000_run03_20261109T134846Z_izzzov02`：qos，重复3，PASS。

## 10 汇报安排

按11分钟准备：2分钟介绍业务目标；3分钟解释共同瓶颈、流量及同带宽对照；3分钟解读图表和队列证据；2分钟说明借用带宽与TCP资源取舍；1分钟交代合成流量及服务器出口管理的适用范围。

主要资料：3号交接手册及已部署topology.py；[2号参数交付](https://github.com/Arieaaa/CNC-GR/tree/4f7e4dc/2/project)；[iperf3使用说明](https://software.es.net/iperf/invoking.html)；[HTB手册](https://man7.org/linux/man-pages/man8/tc-htb.8.html)。
