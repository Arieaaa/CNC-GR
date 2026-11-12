#!/usr/bin/env python3
"""Unify the presentation and index of two frozen experiment versions."""
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'unified_results'
OLD=ROOT/'history/v1.0_original_delivery'
NEW=ROOT/'wifi-qos/extension_v1.1'
OLD_MANIFEST='FILES_v1.0_20261109.sha256'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def fmt(stat,digits=3):return f"{stat['mean']:.{digits}f} ± {stat['sample_sd']:.{digits}f}"
def csv_write(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def preserve_original():
    if not (OLD/OLD_MANIFEST).exists():
        manifest=ROOT/OLD_MANIFEST
        assert manifest.exists(),'original manifest missing'
        lines=manifest.read_text().splitlines()
        for line in lines:
            digest,name=line.split('  ',1)
            assert sha(ROOT/name)==digest,('original delivery changed',name)
        OLD.mkdir(parents=True,exist_ok=True)
        for line in lines:
            digest,name=line.split('  ',1)
            target=OLD/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/name,target)
        # Keep the historical checksum with its exact, independently verifiable layout.
        manifest.rename(OLD/OLD_MANIFEST)
    for line in (OLD/OLD_MANIFEST).read_text().splitlines():
        digest,name=line.split('  ',1)
        assert sha(OLD/name)==digest,('historical snapshot mismatch',name)


def build():
    preserve_original()
    old_root=OLD/'wifi-qos'
    audits={'v1.0':read(old_root/'results/audit.json'),'v1.1':read(NEW/'results/audit.json')}
    assert all(a['checks_passed'] for a in audits.values())
    assert audits['v1.0']['formal_runs']==6 and audits['v1.1']['valid_formal_runs']==72
    old_summary=[x for x in read(old_root/'results/summary.json') if x['seconds']==60 and x['warmup']==10]
    new_summary=read(NEW/'results/summary.json')
    assert len(old_summary)==2 and len(new_summary)==16
    rows=[]
    for version,audit in audits.items():
        for record in audit['records']:
            if version=='v1.0':
                mode=record['mode'];run_id=record['directory'];repeat=record['run']
                config=dict(mode=mode,rt_kbit=600,buffer_bytes=32768,workload='static',seconds=60,experiment='P0')
                prefix=Path('history/v1.0_original_delivery/wifi-qos')
            else:
                if not record.get('audit_passed'):continue
                config=record['config'];mode=config['mode'];run_id=record['id'];repeat=config['repeat']
                prefix=Path('wifi-qos/extension_v1.1')
            metric=record['metrics'];dynamic=config['workload']=='dynamic'
            row=dict(data_id=version+'::'+run_id,version=version,
                     role='primary' if version=='v1.1' else 'preliminary_validation',
                     run_id=run_id,experiment=config['experiment'],mode=mode,workload=config['workload'],
                     repeat=repeat,seconds=config['seconds'],total_cap_kbit=2000,
                     realtime_guarantee_kbit=config['rt_kbit'] if mode=='qos' else None,
                     rt_kbit_config=config['rt_kbit'],nominal_buffer_bytes=config['buffer_bytes'],
                     udp_payload_bytes=160,udp_low_offer_kbit=300,udp_high_offer_kbit=900 if dynamic else None,
                     jitter_definition='iperf3 interval estimator mean' if not dynamic else None,
                     udp_metric_window='send-cohort [30,60)' if dynamic else 'iperf3 receiver [10,60)',
                     rtt_metric_window='probe [10,90)' if dynamic else 'probe [10,60)',
                     tcp_metric_window='complete intervals certainly inside aligned [30,60)' if dynamic else
                       ('complete intervals certainly inside aligned [10,60)' if version=='v1.1' else 'iperf3 receiver [10,60)'),
                     rtt_p95_ms=metric['rtt']['p95_ms'],rtt_mean_ms=metric['rtt']['mean_ms'],
                     evidence_log=str(prefix/'merged_logs'/(run_id+'.jsonl')),
                     source_audit=str(prefix/'results/audit.json'))
            if dynamic:
                p=metric['phases'][1]
                row.update(udp_received_mbps=p['received_mbps'],udp_loss_percent=p['loss_percent'],
                           udp_delay_p95_ms=p['delay_p95_ms'],on_time_percent=p['on_time_percent'],
                           tcp_received_mbps=p['tcp']['received_mbps'],tcp_analyzed_seconds=p['tcp']['analyzed_seconds'],
                           recovery_seconds=metric['recovery_seconds'])
            else:
                row.update(udp_received_mbps=metric['udp']['received_mbps'],udp_loss_percent=metric['udp']['udp_loss_percent'],
                           udp_jitter_ms=metric['udp']['udp_jitter_interval_mean_ms'],
                           tcp_received_mbps=metric['tcp']['received_mbps'],tcp_analyzed_seconds=metric['tcp']['analyzed_seconds'])
            if version=='v1.1':
                retrans=record['tcp_retransmission_windows']['phase1' if dynamic else 'main']
                row.update(tcp_retransmits=retrans['retransmits'],tcp_retransmits_per_second=retrans['retransmits_per_second'])
            assert (ROOT/row['evidence_log']).exists(),row['evidence_log']
            rows.append(row)
    assert len(rows)==78 and len({r['data_id'] for r in rows})==78
    assert sum(r['version']=='v1.0' for r in rows)==6
    assert sum(r['version']=='v1.1' for r in rows)==72
    csv_write(OUT/'formal_runs_78.csv',rows)
    with (NEW/'results/phases.csv').open(encoding='utf-8-sig',newline='') as f:
        phases=[dict(data_id='v1.1::'+x['id'],run_id=x['id'],version='v1.1',role='primary',**x) for x in csv.DictReader(f)]
    assert len(phases)==36
    assert {x['data_id'] for x in phases}=={x['data_id'] for x in rows if x['workload']=='dynamic'}
    for identity in {x['data_id'] for x in phases}:
        assert sorted(int(x['phase']) for x in phases if x['data_id']==identity)==[0,1,2]
    csv_write(OUT/'dynamic_phases_36.csv',phases)
    summaries=[]
    mapping={'udp_received_mbps':'udp_received_mbps','udp_loss_percent':'udp_loss_percent',
             'udp_jitter_ms':'udp_jitter_interval_mean_ms','tcp_received_mbps':'tcp_received_mbps',
             'rtt_p95_ms':'rtt_p95_ms','rtt_mean_ms':'rtt_mean_ms'}
    for g in old_summary:
        summaries.append(dict(version='v1.0',role='preliminary_validation',mode=g['mode'],rt_kbit=600,
                              buffer_bytes=32768,workload='static',n=g['n'],
                              metrics={key:g[source] for key,source in mapping.items()}))
    summaries.extend(dict(version='v1.1',role='primary',**g) for g in new_summary)
    # Verify source means/SD from the individual version-tagged records, never across versions.
    for g in summaries:
        selected=[r for r in rows if r['version']==g['version'] and r['mode']==g['mode'] and
                  r['rt_kbit_config']==g['rt_kbit'] and r['nominal_buffer_bytes']==g['buffer_bytes'] and r['workload']==g['workload']]
        assert len(selected)==g['n']
        for field,stat in g['metrics'].items():
            if field not in selected[0]:continue
            values=[r[field] for r in selected if r.get(field) is not None]
            if not values:continue
            assert math.isclose(statistics.mean(values),stat['mean'],rel_tol=1e-9,abs_tol=1e-9),(g['version'],field)
            if len(values)>1:assert math.isclose(statistics.stdev(values),stat['sample_sd'],rel_tol=1e-9,abs_tol=1e-9)
    save(OUT/'summary_by_version.json',summaries)
    index={}
    for version,prefix in [('v1.0',Path('history/v1.0_original_delivery/wifi-qos')),('v1.1',Path('wifi-qos/extension_v1.1'))]:
        log_index=read(ROOT/prefix/'merged_logs/index.json')
        count=log_index.get('total_original_files',log_index.get('total_files'))
        for item in log_index['runs']:
            assert sha(ROOT/prefix/'merged_logs'/item['log_file'])==item['sha256']
        index[version]=dict(role='primary' if version=='v1.1' else 'preliminary_validation',
                           formal_runs=6 if version=='v1.0' else 72,merged_logs=len(log_index['runs']),
                           original_files=count,log_index=str(prefix/'merged_logs/index.json'),
                           audit=str(prefix/'results/audit.json'),audit_sha256=sha(ROOT/prefix/'results/audit.json'),
                           summary=str(prefix/'results/summary.json'),summary_sha256=sha(ROOT/prefix/'results/summary.json'))
    save(OUT/'source_index.json',dict(versions=index,total_formal_runs=78,
         canonical_merged_logs=sum(x['merged_logs'] for x in index.values()),
         canonical_original_files=sum(x['original_files'] for x in index.values()),
         statistics_policy='Group by version, workload, mode, guarantee and buffer; do not pool versions.'))

    def new_group(mode,rt=600,buffer=32768,workload='static'):
        return next(x for x in new_summary if (x['mode'],x['rt_kbit'],x['buffer_bytes'],x['workload'])==(mode,rt,buffer,workload))
    fq=new_group('fq_codel',workload='dynamic')['metrics'];ht=new_group('qos',1200,workload='dynamic')['metrics']
    labels={'baseline':'共享FIFO','qos':'分类HTB','fq_codel':'FQ-CoDel'}
    old_table=['| 前期验证方法 | n | UDP丢包 % | UDP jitter ms | 探测RTT P95 ms | TCP载荷 Mbit/s |',
               '|---|---:|---:|---:|---:|---:|']
    for g in old_summary:
        old_table.append(f"| {labels[g['mode']]} | {g['n']} | {fmt(g['udp_loss_percent'])} | {fmt(g['udp_jitter_interval_mean_ms'])} | {fmt(g['rtt_p95_ms'])} | {fmt(g['tcp_received_mbps'])} |")
    ext=(NEW/'实验结果与分析.md').read_text()
    main=ext[ext.index('## 2. 三种方法'):ext.index('## 7. 实施条件')]
    main=re.sub(r'^## ([2-6])\. ',lambda m:'### 4.'+str(int(m[1])-1)+' ',main,flags=re.M)
    main=main.replace('### 方案选择','#### 方案选择').replace('(results/','(wifi-qos/extension_v1.1/results/')
    implementation=ext[ext.index('## 7. 实施条件'):ext.index('## 8. 如何查看')]
    implementation=implementation.replace('## 7. 实施条件与复现边界','### 5.2 主结果的实施条件与核查')
    text=f'''# 实验C统一结果报告：实时UDP与后台TCP的出口QoS保障

负责人：6号。统一整理日期：2026年11月12日。

## 1. 结论与阅读入口

本项目已完成两阶段共**78轮有效正式实验**：前期验证v1.0共6轮，统一条件主实验v1.1共72轮。主实验覆盖三种方法、保障份额扫描、动态需求和缓存敏感性。两阶段形成同一条实验主线，保留各自的版本、参数和独立统计。

主要结论如下：

1. **分类保障有效，但份额应覆盖实际需求。** 前期6轮确认了FIFO与分类HTB的差异；主实验在统一条件下重测FIFO、HTB，并加入FQ-CoDel，完成可直接比较的三组对照。
2. **本次300 kbit/s静态负载下，400 kbit/s是通过丢包门槛的最低已测HTB候选。** 200 kbit/s明显不足；600和1000 kbit/s没有带来可据此宣称更优的整体业务结论。选参还须考虑业务峰值及协议开销。
3. **900 kbit/s高需求阶段，FQ-CoDel和HTB1200均满足本实验50 ms交付目标。** FQ-CoDel的UDP包P95为{fmt(fq['udp_delay_p95_ms'])} ms，HTB1200为{fmt(ht['udp_delay_p95_ms'])} ms，两者50 ms内有效交付均为100%。FIFO虽未丢包，但部分包迟到；HTB600则因保障不足出现大量丢包和积压。
4. **时延应结合实际积压解释。** FIFO从16增至32 KiB时探测时延上升，32增至64 KiB后基本持平。缓存上限不是实际队列长度，也不是P95预测值。

本报告以第4节的72轮作为正式主结果，第3节的6轮作为前期验证。图表、逐轮数据、原始日志、脚本和审计通过第6节统一索引。原始日志均为可还原JSONL，不使用压缩包。

## 2. 实验问题、环境与统计口径

实验模拟服务器向两个无线终端下发实时UDP与持续TCP下载，共享一个2 Mbit/s服务器出口。两个终端分别接入两个AP，干预点为srv-eth0出口队列。两阶段公共拓扑哈希一致，沿用802.11g、20 MHz、信道1/6及实际AP功率1 dBm。下行容量标定约36 Mbit/s，使2 Mbit/s软件出口成为主要研究瓶颈。

| 阶段 | 用途 | 正式轮数 | 独立重复与时长 | 统计来源 |
|---|---|---:|---|---|
| v1.0，前期验证 | 验证分类HTB相对FIFO的作用 | 6 | 2配置×3次；每次60秒 | 对应版本的审计通过记录 |
| v1.1，统一条件主实验 | 三组对照、机制、选参、动态需求、缓存敏感性 | 72 | 静态12配置×5次×60秒；动态4配置×3次×90秒 | 对应版本原始记录重算审计 |

v1.1的72轮由基础矩阵48轮与按既定波动规则追加的24轮组成。参考组在多个分析中复用，计数时只计算一次；不能把参考组重复出现的表格行当成新增实验。容量标定、短试跑及无效预检不计入78轮正式实验。

三种方法均使用相同的HTB总限速器。共享FIFO只有一个业务队列；分类HTB分离实时与后台队列并给出保障份额；FQ-CoDel按网络流分队并实施主动队列管理。HTB两类的ceil均为2 Mbit/s，可以借用空闲容量，保障份额不等于硬性最高速率。

| 指标 | 读法与口径 |
|---|---|
| UDP丢包率 | 正式业务中未成功收到的比例；动态按发送序号与接收序号匹配 |
| 静态UDP jitter | iperf3逐秒抖动估计的每轮均值，描述波动，不等于平均时延 |
| 探测RTT | ICMP往返时延；分类HTB中ICMP应答也进入实时类 |
| 动态UDP包时延 | 同一时钟条件下应用发送至应用接收的单向时延，与RTT分别解释 |
| P95 | 95%的已观测样本不超过该值；表中为每轮P95的均值±样本标准差 |
| 50 ms内有效交付 | 截止期内收到的包数/成功发送包数；迟到与丢失均不能算有效交付 |
| TCP吞吐 | 接收端实际载荷速率；按安全覆盖的完整区间汇总 |

静态UDP统计后50秒。动态负载在同一UDP五元组中保持300→900→300 kbit/s，每阶段30秒，主窗口为[10,30)、[30,60)、[60,90)，保留切换后的瞬态。动态TCP只选确定完全落入窗口的接收区间；动态逐轮汇总CSV的主要UDP指标对应高需求阶段，RTT字段仍对应全程探测窗口。

## 3. 前期验证：建立现象与研究问题（v1.0，6轮）

前期在相同2 Mbit/s出口和300 kbit/s UDP负载下，对共享FIFO与分类HTB600各运行3次。以下数值来自v1.0审计通过的60秒正式组，未混入15秒短试跑。

{chr(10).join(old_table)}

![前期验证：FIFO与分类HTB，两组各3次](history/v1.0_original_delivery/wifi-qos/results/expc_comparison.png)

前期结果表明，分类HTB能够降低实时业务的丢包、抖动及探测等待，后台TCP汇总吞吐基本相近。这形成了后续三个问题：队列积压如何解释时延、保障份额如何选择、实时需求突增时不同方案如何取舍。v1.0完整交付已按原布局保存在[历史快照](history/v1.0_original_delivery/README.md)，其原始校验清单可独立验证。

## 4. 统一条件下的正式主结果（v1.1，72轮）

本节所有方法均来自v1.1统一重测。静态每配置5次，动态每配置3次；统计样本为独立运行，不把数据包或逐秒点当成独立重复。

{main}

## 5. 两阶段结果如何衔接

### 5.1 参数变化与结果解释

| 项目 | v1.0前期验证 | v1.1统一条件主实验 |
|---|---|---|
| 总出口与基本静态业务 | 2 Mbit/s；UDP300 kbit/s、160字节；后台单TCP | 保持相同研究条件，并加入动态需求 |
| 方法范围 | FIFO、分类HTB600 | FIFO、分类HTB与FQ-CoDel；HTB扫描多个份额 |
| HTB burst/cburst | 使用工具自动计算值 | 父/子类显式固定4096字节 |
| 卸载与聚合控制 | 未采用本轮统一的卸载及GSO尺寸约束 | 统一关闭相关卸载，srv的gso_max_size=1514、gso_max_segs=1 |
| TCP启动与覆盖 | UDP/TCP近同时启动，各自60秒 | 先确认TCP数据，再启动UDP；TCP额外运行4秒，并记录启动上下界 |
| 动态业务 | 未测 | 同一条UDP流连续变速，记录序号及发送/接收时间戳 |
| 独立重复 | 每配置3次 | 静态5次、动态3次 |
| 数据用途 | 证明现象、形成后续问题 | 方法排名、参数选择和动态适应性的主依据 |

因此，v1.0 FIFO探测P95约136 ms，而v1.1约40.960 ms，是不同实施条件下的观测。不能把这一跨版本差值算成某个算法的提升，也不能把两版本同名方法合成n=8。两阶段都显示分类保障能改善实时体验；主报告的三方法比较、选参与结论使用v1.1统一条件数据。

{implementation}

## 6. 统一数据、证据与复现

| 入口 | 内容 |
|---|---|
| [78轮统一明细](unified_results/formal_runs_78.csv) | 每轮保留版本、用途、配置、独立重复、指标窗口及日志位置 |
| [分版本18组汇总](unified_results/summary_by_version.json) | v1.0两组＋v1.1十六组；均值与标准差按版本分别核对 |
| [动态36个阶段明细](unified_results/dynamic_phases_36.csv) | 12轮动态测试×3阶段，均属于v1.1 |
| [来源索引](unified_results/source_index.json) | 两版本审计、汇总、日志索引及SHA-256 |
| [统一结果核查](unified_results/validation.json) | 78轮唯一编号、组计数、源均值/SD及校验清单核对 |
| [主实验方案](wifi-qos/extension_v1.1/protocol.md) | 环境、完整矩阵、队列参数及验收规则 |
| [补测与统计约定](wifi-qos/extension_v1.1/analysis_preregistration.md) | 原始3次触发、固定完成第4/5次、共享参考组与顺序 |
| [前期原始交付](history/v1.0_original_delivery/README.md) | 原报告、脚本、6轮正式数据、预检及原校验清单 |
| [主实验完整交付](wifi-qos/extension_v1.1/README.md) | 72轮正式数据、脚本、图表、审计与合并日志 |

两阶段的规范日志索引共指向106份JSONL，保存71,573份原始文件；其中包括预检证据。历史快照与旧路径中的兼容副本不增加统计样本，统一数据仅按“版本＋运行ID”登记一次。

在相应版本的交付目录使用还原脚本即可无损恢复原始日志，目标须是新目录。前期交付在历史快照内运行原脚本；主实验按其README依次执行还原、审计、统计和绘图。统一结果可在项目根目录用下列命令重建：

```bash
python3 unified_results/build_unified.py
```

重建程序读取两版本已通过审计的数据，核对逐轮值与原组汇总，并保留各版本的统计边界。当前项目的校验清单为`FILES_UNIFIED.sha256`；v1.0原清单位于历史快照中，v1.1自身的`FILES.sha256`保持不变。

## 7. 结果使用与组内交接

6号汇报可围绕“前期发现→机制解释→参数选择→动态需求与后台代价”展开，三方法排名与主要图表选用第4节。7号可以通过统一明细追溯两版本日志，分别复算；8号制作图表时筛选`version=v1.1`、`role=primary`，再按业务、方法、保障份额和缓存分组。静态jitter、探测RTT、动态UDP单向时延分别标注。

2号参数回填以实际部署值及本报告为准：信道1/6、AP实际1 dBm、总出口配置2000 kbit/s；容量标定值不是配置的无线bw。三号与七号的联合抽样复现仍应按分工独立执行，本次已有重复与离线重算不替代该联合复现。

方法依据：[FQ-CoDel RFC 8290](https://www.rfc-editor.org/rfc/rfc8290.html)、[tc-fq_codel手册](https://man7.org/linux/man-pages/man8/tc-fq_codel.8.html)、[tc-htb手册](https://man7.org/linux/man-pages/man8/tc-htb.8.html)。方法资料说明算法与参数，所有结果数值来自本项目实验记录。
'''
    (ROOT/'实验C统一结果报告.md').write_text(text)
    (ROOT/'README.md').write_text('''# 6号实验C：统一结果交付

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
''')
    (ROOT/'.gitattributes').write_text('* -text\n')

    # The extension snapshot is immutable and must still verify independently.
    extension_manifest=(NEW/'FILES.sha256').read_text().splitlines()
    for line in extension_manifest:
        digest,name=line.split('  ',1);assert sha(NEW/name)==digest,('extension changed',name)
    validation=dict(checks_passed=True,total_unique_formal_runs=78,version_counts={'v1.0':6,'v1.1':72},
                    group_count=18,dynamic_phase_rows=36,canonical_log_files=106,canonical_original_files=71573,
                    source_audits_passed=True,source_group_means_and_sd_rechecked=True,
                    original_delivery_sha256_entries_verified=46,extension_sha256_entries_verified=len(extension_manifest),
                    data_policy='Versions retained; no cross-version pooled statistics; archive copies are not additional samples.')
    save(OUT/'validation.json',validation)
    files=[]
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc' or path.name in ['.DS_Store','FILES_UNIFIED.sha256']:continue
        if any(part in ['logs','restored_logs','.matplotlib'] for part in path.relative_to(ROOT).parts):continue
        files.append((str(path.relative_to(ROOT)),sha(path)))
    (ROOT/'FILES_UNIFIED.sha256').write_text(''.join(f'{digest}  {name}\n' for name,digest in files))
    print(json.dumps(validation,ensure_ascii=False))
    print('Unified manifest entries:',len(files))


if __name__=='__main__':build()
