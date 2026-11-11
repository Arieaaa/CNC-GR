#!/usr/bin/env python3
"""核对 08 号 v0.3 逐轮统计，并检查指定 A、C 原始异常轮。"""
import argparse
import collections
import csv
import json
import math
from pathlib import Path
import re
import statistics

def readcsv(path):
    with path.open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repo',required=True,type=Path);parser.add_argument('--out',required=True,type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parent.parent; raw=root/'原始日志'; repo=args.repo
    a=readcsv(repo/'4/project/expA_summary.csv');b=readcsv(repo/'5/project/实验B/实测/summary.csv');c=readcsv(repo/'6/project/wifi-qos/results/formal_runs.csv')
    assert len(a)==12 and len(c)==6
    b=[x for x in b if x['phase']=='formal']; assert len(b)==6
    groups=[]
    for stations,channel in [('4','1-6'),('8','1-6'),('12','1-6'),('12','1-1')]:
        rows=[x for x in a if x['stations']==stations and x['channels']==channel]; assert len(rows)==3 and len({x['run'] for x in rows})==3
        for metric in ('tcp_total_mbps','tcp_per_station_avg_mbps','rtt_p95_max_ms'):
            vals=[float(x[metric]) for x in rows];groups.append(dict(experiment='A',config=stations+'_'+channel,metric=metric,n=3,mean=statistics.mean(vals),sample_sd=statistics.stdev(vals),source='4/project/expA_summary.csv'))
    for policy in ('ssf','llf'):
        rows=[x for x in b if x['policy']==policy]; assert len(rows)==3 and len({x['run'] for x in rows})==3
        for metric,fn in [('first_new_x_m',lambda x:float(x['first_new_x_m'])),('first_event_gap_s',lambda x:float(x['first_event_gap_ms'])/1000),('p95_rtt_ms',lambda x:float(x['p95_rtt_ms'])),('ping_loss_pct',lambda x:100*(int(x['sent'])-int(x['received']))/int(x['sent']))]:
            vals=[fn(x) for x in rows];groups.append(dict(experiment='B',config=policy,metric=metric,n=3,mean=statistics.mean(vals),sample_sd=statistics.stdev(vals),source='5/project/实验B/实测/summary.csv'))
    for mode in ('baseline','qos'):
        rows=[x for x in c if x['mode']==mode]; assert len(rows)==3 and {x['run'] for x in rows}=={'1','2','3'}
        for metric in ('udp_loss_percent','udp_jitter_ms','rtt_p95_ms','tcp_received_mbps'):
            vals=[float(x[metric]) for x in rows];groups.append(dict(experiment='C',config=mode,metric=metric,n=3,mean=statistics.mean(vals),sample_sd=statistics.stdev(vals),source='6/project/wifi-qos/results/formal_runs.csv'))
    checks=[]; d=raw/'expA_n12_ch1-6_run02';summary=json.loads((d/'summary.json').read_text())
    for n in (7,8):
        name=f'sta{n}-ping.txt';text=(d/name).read_text();replies=[(int(m[1]),float(m[2])) for m in re.finditer(r'icmp_seq=(\d+).*?time[=<]([\d.]+) ms',text)]
        vals=[v for _,v in replies];first=[v for seq,v in replies if seq<=5];later=[v for seq,v in replies if seq>5]
        assert len(first)==5 and len(vals)==summary['rtt_ms'][f'sta{n}']['samples']
        assert round(statistics.mean(vals),3)==summary['rtt_ms'][f'sta{n}']['avg_ms']
        checks.append(dict(run_id=d.name,check=f'sta{n}_ping',evidence=json.dumps({'count':len(vals),'mean_ms':statistics.mean(vals),'first_5_by_seq_ms':dict(sorted((seq,v) for seq,v in replies if seq<=5)),'remaining_count':len(later),'remaining_mean_ms':statistics.mean(later)},ensure_ascii=False),source=name,note='按探测序号剔除前五项仅作描述，不用于正式统计；无逐包绝对时间'))
    for name in ['expC_baseline_c2000_run02_20261109T134607Z_47qrkol0','expC_baseline_c2000_run04_20261111T055440Z_vtjcuwro']:
        d=raw/name;j=json.loads((d/'udp-receiver.json').read_text()); rows=[x['streams'][0] for x in j['intervals'] if x['streams'][0]['start']>=9.98 and x['streams'][0]['end']<=60.1]
        assert len(rows)==50 and all(x['sender'] is False for x in rows)
        bins=collections.defaultdict(int)
        for x in rows:bins[min(4,max(0,int((x['start']-9.98)//10)))]+=x['lost_packets']
        checks.append(dict(run_id=name,check='udp_10_60s',evidence=json.dumps({'intervals':len(rows),'nonzero':sum(x['lost_packets']>0 for x in rows),'lost':sum(x['lost_packets'] for x in rows),'packets':sum(x['packets'] for x in rows),'five_10s_lost':[bins[i] for i in range(5)]}),source='udp-receiver.json:intervals[].streams[0]',note='10–60 s 完整区间；边界容差 20/100 ms'))
    assert not args.out.exists();args.out.mkdir(parents=True)
    for name,rows,fields in [('正式汇总统计核对.csv',groups,['experiment','config','metric','n','mean','sample_sd','source']),('异常轮核对.csv',checks,['run_id','check','evidence','source','note'])]:
        with (args.out/name).open('x',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    print('PASS:',len(groups),'group metrics;',len(checks),'raw log checks; 24 formal rows')

if __name__=='__main__': main()
