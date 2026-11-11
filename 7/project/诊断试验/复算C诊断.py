#!/usr/bin/env python3
"""核查六轮额外诊断，仅读取原始日志，不修改现有实验结果。"""
from pathlib import Path
from datetime import datetime
import csv
import importlib.util
import json
import math
import re
import statistics
import sys

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('previous_audit',ROOT/'脚本/复算抽样复现.py')
audit=importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
names=[
 'expC_baseline_c2000_run91_20261111T081218Z_kfgfiezu',
 'expC_qos_c2000_run91_20261111T081339Z_dqeo4lqq',
 'expC_baseline_c2000_run92_20261111T081500Z_cwk7asta',
 'expC_qos_c2000_run92_20261111T081620Z_n66pfhki',
 'expC_baseline_c2000_run93_20261111T081741Z_c8_hpoz0',
 'expC_qos_c2000_run93_20261111T081901Z_f9k3dom6',
]

def cpu(path):
    x=[int(x) for x in path.read_text().splitlines()[0].split()[1:9]]
    return sum(x),x[3]+x[4],x[7]

def main():
    out=Path(sys.argv[1]); assert not out.exists(); rows=[]
    for name in names:
        d=ROOT/'原始日志'/name; c=audit.load(d/'config.json'); saved=audit.load(d/'metrics.json')
        assert (d/'status.txt').read_text().strip()=='PASS'
        assert (c['seconds'],c['warmup'],c['total_kbit'],c['udp_kbit'],c['rt_kbit'],c['channels'])==(60,10,2000,300,600,[1,6])
        assert c['runner_sha256']=='e2e53215afaf27f676affb838431e8f00437ff0a2d87445730414b79bc2d829d'
        assert c['topology_sha256']=='ff61cd8fa0e91d72c8a953948d83053899a62e2cedf1e6757b0e60830dc62c19'
        computed={k:audit.interval(audit.load(d/f'{k}-receiver.json'),k=='udp') for k in ('udp','tcp')}
        for k,values in computed.items():
            for key,value in values.items(): assert math.isclose(value,saved[k][key],rel_tol=1e-10,abs_tol=1e-10),(name,k,key)
        start=datetime.fromisoformat(c['traffic_started_utc']).timestamp(); replies=[]
        for line in (d/'ping.txt').read_text().splitlines():
            m=re.search(r'^\[(\d+\.\d+)\].*icmp_seq=(\d+).*time[=<]([\d.]+) ms',line)
            if m and 10<=float(m[1])-start<60: replies.append((int(m[2]),float(m[3])))
        assert len(replies)==saved['rtt']['successful_samples'] and len(set(n for n,_ in replies))==len(replies)
        assert abs(statistics.mean(v for _,v in replies)-saved['rtt']['mean_ms'])<1e-9
        assert audit.p95([v for _,v in replies])==saved['rtt']['p95_ms']
        sig=audit.queue_sig(d,'configured'); samples=sorted(d.glob('sample*-srv-class.json')); assert len(samples)>=50
        assert all(audit.queue_sig(d,x.name.removesuffix('-srv-class.json'))==sig for x in samples) and audit.queue_sig(d,'after')==sig
        configured={x['handle']:x for x in audit.load(d/'configured-srv-class.json')}; after={x['handle']:x for x in audit.load(d/'after-srv-class.json')}
        assert configured['1:1']['options']['rate']=='2Mbit' and configured['1:1']['options']['ceil']=='2Mbit'
        if c['mode']=='qos':
            assert configured['1:10']['options']['rate']=='600Kbit' and configured['1:20']['options']['rate']=='1400Kbit'
            assert {x['parent']:x['options']['limit'] for x in audit.load(d/'configured-srv-qdisc.json') if x['kind']=='bfifo'}=={'1:10':8192,'1:20':24576}
            filt=(d/'configured-srv-filter.txt').read_text(); blocks=re.findall(r'^filter .*?\*flowid 1:10[^\n]*\n((?:\s+match [^\n]*\n)+)',filt,re.M)
            assert any(all(s in b for s in ('match 00110000/00ff0000 at 8','match 14520000/ffff0000 at 20','match 0a2c0001/ffffffff at 16')) for b in blocks)
            assert any(all(s in b for s in ('match 00010000/00ff0000 at 8','match 0a2c0001/ffffffff at 16')) for b in blocks)
            pre={x['handle']:x['bytes'] for x in audit.load(d/'before-icmp-srv-class.json')}; assert pre['1:10']>0 and after['1:10']['bytes']>0 and after['1:20']['bytes']>0
        else:
            assert configured['1:20']['options']['rate']=='2Mbit' and not audit.load(d/'configured-srv-filter.json')
            assert any(x['kind']=='bfifo' and x['parent']=='1:20' and x['options']['limit']==32768 for x in audit.load(d/'configured-srv-qdisc.json'))
        q=audit.load(d/'after-srv-qdisc.json'); htb=next(x for x in q if x['kind']=='htb'); before=cpu(d/'before-cpu.txt'); end=cpu(d/'after-cpu.txt'); total=end[0]-before[0]; assert total>0
        rows.append({'run_id':name,'mode':c['mode'],'repeat_diagnostic':c['run'],'udp_lost':computed['udp']['udp_lost_packets'],'udp_packets':computed['udp']['udp_packets'],'udp_loss_pct':computed['udp']['udp_loss_percent'],'udp_jitter_ms':computed['udp']['udp_jitter_interval_mean_ms'],'tcp_mbps':computed['tcp']['received_mbps'],'rtt_p95_ms':saved['rtt']['p95_ms'],'rtt_success':len(replies),'queue_snapshots':len(samples),'queue_drops_all_traffic':htb['drops'],'cpu_busy_pct':100*(1-(end[1]-before[1])/total),'cpu_steal_pct':100*(end[2]-before[2])/total,'raw_sources':'config.json;udp-receiver.json;tcp-receiver.json;ping.txt;configured/sample*/after-srv-{class,qdisc,filter}.json'})
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    for mode in ('baseline','qos'):
        part=[r for r in rows if r['mode']==mode]
        print(mode,'loss %', [round(x['udp_loss_pct'],4) for x in part], 'mean',round(statistics.mean(x['udp_loss_pct'] for x in part),4),'queue drops', [x['queue_drops_all_traffic'] for x in part], 'rtt p95', [x['rtt_p95_ms'] for x in part])
    print('PASS: 6 runs, receiver interval metrics, RTT, queue rules and snapshots')

if __name__=='__main__': main()
