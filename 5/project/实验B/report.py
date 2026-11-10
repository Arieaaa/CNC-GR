"""基于正式轮次重建交接报告，先执行 analyze.py 和 plot.py。"""
import csv
import json
import statistics as st
import sys
from pathlib import Path


def span(values, digits=2):
    return f'{st.mean(values):.{digits}f}（{min(values):.{digits}f}–{max(values):.{digits}f}）'


def build(base):
    rows = list(csv.DictReader((base/'summary.csv').open()))
    formal = sorted((r for r in rows if r['phase']=='formal'), key=lambda r:(r['policy'],r['run']))
    if len(formal)!=6:
        raise ValueError('正式六轮尚未收齐')
    lines=['# 实验 B · 移动终端关联与业务连续性', '',
           '在公共双 AP 平台，sta1 从 (15,25) 沿直线走到 (70,25)。第 10 秒开始移动，速度 1 m/s，第 65 秒到达。两种策略共用 1/6 信道、同一有线服务器与 3 条 256 kbit/s 上行 UDP 背景流。每轮重建拓扑，起始 4 台站均在 AP1。', '',
           '## 六轮正式采集', '',
           '|策略 / 重复|首次观测 AP2 的位置 m|切换附近最大相邻回包间隔 ms|全轮探测丢失 / 发送|全轮 RTT 均值 / P95 ms|原始证据|',
           '|---|---:|---:|---:|---:|---|']
    bg_rates=[]
    normal=[]
    for r in formal:
        run=base/r['run']
        events=json.loads((run/'events.json').read_text())
        assert len(events)==1 and int(r['policy_change_requests'])>=1, run
        cfg=json.loads((run/'config.json').read_text())
        sampled=list(csv.DictReader((run/'observations/samples.csv').open()))
        assert [(sampled[i]['ap1_count'],sampled[i]['ap2_count']) for i in (0,-1)]==[('4','0'),('3','1')], run
        normal.append(st.median([float(b['start_s'])-float(a['start_s']) for a,b in zip(sampled,sampled[1:])]))
        for port in cfg['ports']:
            end=json.loads((run/f'srv-{port}.json').read_text())['end']['sum_received']
            bg_rates.append(end['bits_per_second']/1000)
        lines.append(f"|{r['policy'].upper()} / {cfg['repeat']}|{float(r['first_new_x_m']):.2f}|"
                     f"{float(r['first_event_gap_ms']):.1f}|{int(r['sent'])-int(r['received'])} / {r['sent']}|"
                     f"{float(r['mean_rtt_ms']):.2f} / {float(r['p95_rtt_ms']):.2f}|"
                     f"[时间线](实测/{run.name}/timeline.svg) · [事件](实测/{run.name}/events.json) · "
                     f"[探测](实测/{run.name}/observations/ping.txt)|")
    lines+=['', '## 重复间波动', '',
            '各项按轮统计，括号内为三轮最小值至最大值。', '',
            '|策略|切换位置均值 m|事件回包间隔均值 ms|全轮 RTT P95 均值 ms|',
            '|---|---:|---:|---:|']
    for policy in ['ssf','llf']:
        group=[r for r in formal if r['policy']==policy]
        cells=[span([float(r[k]) for r in group]) for k in ['first_new_x_m','first_event_gap_ms','p95_rtt_ms']]
        lines.append('|'+policy.upper()+'|'+'|'.join(cells)+'|')
    lines+=['','## 判读与复现','',
            '实际 BSSID、两台 AP 站表和内核连接返回共同确认了切换。六轮起止关联数均由 4/0 变为 3/1。'
            f'18 条背景流按接收端全程计算为 {min(bg_rates):.2f}–{max(bg_rates):.2f} kbit/s。','',
            'SSF 根据模型信号差作决定。LLF 使用关联数，当前 AP 比候选至少多 3 台时满足门槛，因此在本场景中可在进入重叠区时就选择 AP2。两者使用相同的连接执行代码，分别保留策略决定、内核关联和持续探测的证据。','',
            f'位置和关联目标采样周期 200 ms，各轮采样起点间隔的中位数为 {min(normal)*1000:.1f}–{max(normal)*1000:.1f} ms。iw 观测依次读取。首次看到新 BSSID 的位置有采样误差，事件文件给出了两次观测的时间边界。','',
            'ping 设置间隔 200 ms、-W 1，共 375 包。全轮 RTT 统计涵盖全部成功回包，P95 取排序后第 ceil(0.95×n) 项。事件指标取最后旧关联样本之前至首次新关联样本之后、两侧各延伸到最近成功回包的窗口，计算其最大相邻成功回包间隔。时间戳来自 ping -D 并与同机时间基准对齐。-O 提示待回包，最终丢失按发送与接收计数计算。业务停顿可能与排队、重关联和转发恢复等多个环节有关。','',
            '第一对诊断试跑中，策略内部请求切换但实际 BSSID 一直为 AP1，两轮原始日志保留。随后在策略选择目标之后执行显式频率/BSSID 的同步 iw connect，并保留返回结果。第二对试跑确认成功后，使用同一版本执行六轮正式采集。指标仅适用于此仿真配置和连接实现。','',
            '原始运行目录含脚本快照、版本、配置、背景流两端 iperf3 JSON、策略调用、iw 原文和逐包 ping。各轮 config.json 记录脚本 SHA256。交给 07 号核查数据，08 号可用 summary.csv 汇总，03/07 号可按相同参数抽样复跑。服务达标阈值由组内确认。']
    first=next(r for r in formal if r['policy']=='ssf' and '_ssf_1_' in r['run'])
    event=json.loads((base/first['run']/'events.json').read_text())[0]
    replies=event['nearby_replies']
    left,right=max(zip(replies,replies[1:]),key=lambda pair:pair[1]['t_s']-pair[0]['t_s'])
    lines+=['','## 汇报可用的原始案例','',
            f"SSF 第 1 轮在 {event['last_old_s']:.2f}–{event['first_new_s']:.2f} 秒之间观测到从 AP1 到 AP2 的变化。"
            f"切换附近，序号 {left['seq']} 与 {right['seq']} 两次成功回复相隔 {event['max_adjacent_reply_gap_ms']:.1f} ms。"
            f"结合原始 ping 日志与序号，可核对此处缺失 {event['missing_seq_near_event']} 个回包。"
            "全轮 P95 受大量稳定期样本影响，展示这段局部时间线更容易解释移动用户遇到的停顿。"]
    (base.parent/'实验B结果.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    build(Path(sys.argv[1]))
