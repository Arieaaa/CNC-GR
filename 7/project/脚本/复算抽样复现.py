#!/usr/bin/env python3
"""独立复算 A/B/C 两轮抽样日志；仅读取原始目录。"""
import argparse
import csv
import json
import math
import re
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = {
    'A': ['expA_n4_ch1-6_run01', 'expA_n4_ch1-6_run04'],
    'B': ['expB_formal_llf_3_20261110T061812Z_6r0xpbng', 'expB_formal_llf_4_20261111T055242Z_0q1vozbs'],
    'C': ['expC_baseline_c2000_run02_20261109T134607Z_47qrkol0', 'expC_baseline_c2000_run04_20261111T055440Z_vtjcuwro'],
}

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))

def p95(values):
    values = sorted(values)
    return values[math.ceil(.95 * len(values)) - 1]

def item(rows, run, station, metric, value, unit, window, source):
    rows.append(dict(run_id=run, station=station, metric=metric, value=value,
                     unit=unit, window=window, source=source))

def calc_a(run, rows, checks):
    cfg = load(run/'config.json'); summ = load(run/'summary.json'); starts = {}
    tcp_total = 0
    for i in range(1, cfg['stations']+1):
        sta = f'sta{i}'; tf = f'{sta}-tcp-iperf3.json'; uf = f'{sta}-udp-iperf3.json'; pf = f'{sta}-ping.txt'
        tcp = load(run/tf); udp = load(run/uf)
        assert not tcp.get('error') and not udp.get('error')
        t = tcp['end']['sum_received']; u = udp['end']['sum']
        assert t['seconds'] > 0 and u['packets'] > 0
        rate = t['bytes']*8/t['seconds']/1e6
        assert abs(rate-t['bits_per_second']/1e6) < 1e-6
        assert round(rate,3) == summ['tcp_per_station_mbps'][sta]
        assert abs(100*u['lost_packets']/u['packets']-u['lost_percent']) < 1e-8
        window = f"iperf3 omit={cfg['omit_seconds']}s; measured={cfg['tcp_seconds']}s"
        item(rows,run.name,sta,'tcp_receiver_mbps',rate,'Mbit/s',window,tf+':end.sum_received')
        item(rows,run.name,sta,'udp_lost_packets',u['lost_packets'],'packets',window,uf+':end.sum')
        item(rows,run.name,sta,'udp_packets',u['packets'],'packets',window,uf+':end.sum')
        item(rows,run.name,sta,'udp_loss_pct',100*u['lost_packets']/u['packets'],'%',window,uf+':end.sum')
        item(rows,run.name,sta,'udp_jitter_ms',u['jitter_ms'],'ms',window,uf+':end.sum.jitter_ms')
        ping=(run/pf).read_text(encoding='utf-8'); values=[float(x) for x in re.findall(r'time=([\d.]+) ms',ping)]
        assert values and len(values)==summ['rtt_ms'][sta]['samples']
        assert round(statistics.mean(values),3)==summ['rtt_ms'][sta]['avg_ms'] and round(p95(values),3)==summ['rtt_ms'][sta]['p95_ms']
        for metric,value,unit in [('ping_success_count',len(values),'samples'),('rtt_mean_ms',statistics.mean(values),'ms'),('rtt_p95_ms',p95(values),'ms')]:
            item(rows,run.name,sta,metric,value,unit,'ping full phase; no warmup exclusion',pf)
        starts[sta]=tcp['start']['timestamp']['timesecs']; tcp_total += rate
    item(rows,run.name,'','tcp_sum_station_mbps',tcp_total,'Mbit/s','sum of per-station iperf3 reports; not exact common window', 'sta*-tcp-iperf3.json:end.sum_received')
    checks.append(dict(run_id=run.name,check='tcp_start_seconds',value=json.dumps(starts),note='iperf3 timestamp has 1-second resolution; exact overlap not verified'))

def calc_b(run, rows, checks):
    cfg=load(run/'config.json'); obs=run/'observations'; origin=load(obs/'clock.json')['epoch']
    samples=list(csv.DictReader((obs/'samples.csv').open(encoding='utf-8',newline='')))
    ping=(obs/'ping.txt').read_text(encoding='utf-8')
    replies=[(float(t)-origin,int(seq),float(rtt)) for t,seq,rtt in re.findall(r'^\[([\d.]+)\] \d+ bytes from .*?icmp_seq=(\d+).*?time=([\d.]+) ms',ping,re.M)]
    tx,rx=map(int,re.search(r'(\d+) packets transmitted,\s*(\d+) received',ping).groups())
    assert len(replies)==rx and len({r[1] for r in replies})==rx
    values=[r[2] for r in replies]; prev=None; events=[]
    for row in samples:
        if not row['bssid']: continue
        if prev and prev['bssid']!=row['bssid']:
            lo,hi=float(prev['start_s']),float(row['end_s'])
            before=[r for r in replies if r[0]<lo]; after=[r for r in replies if r[0]>hi]
            assert before and after
            window=[r for r in replies if before[-1][0]<=r[0]<=after[0][0]]
            gap=max((b[0]-a[0])*1000 for a,b in zip(window,window[1:]))
            events.append(dict(last_old_s=lo,first_new_s=hi,first_new_x_m=float(row['x_m']),old=prev['bssid'],new=row['bssid'],gap_ms=gap,first_seq=before[-1][1],last_seq=after[0][1],missing=after[0][1]-before[-1][1]+1-len(window)))
        prev=row
    assert events
    for metric,value,unit,window,source in [('ping_sent',tx,'packets','full run','observations/ping.txt'),('ping_received',rx,'packets','full run','observations/ping.txt'),('rtt_mean_ms',statistics.mean(values),'ms','full run successful replies','observations/ping.txt'),('rtt_p95_ms',p95(values),'ms','full run successful replies; nearest-rank','observations/ping.txt'),('first_new_ap_position_m',events[0]['first_new_x_m'],'m','first observed change','observations/samples.csv'),('event_max_reply_gap_ms',events[0]['gap_ms'],'ms','last old/first new samples with surrounding successful replies','observations/samples.csv;observations/ping.txt;observations/clock.json')]:
        item(rows,run.name,'sta1',metric,value,unit,window,source)
    checks.append(dict(run_id=run.name,check='association_events',value=json.dumps(events,ensure_ascii=False),note='gap includes normal probing interval; sampled association bounds'))
    for sta,port in zip((2,3,4),(5202,5203,5204)):
        d=load(run/f'srv-{port}.json'); assert not d.get('error')
        received=d.get('end',{}).get('sum_received',{})
        assert received.get('sender') is False and received.get('bytes',0)>0
        checks.append(dict(run_id=run.name,check=f'background_sta{sta}',value=json.dumps(received),note=f'receiver: srv-{port}.json end.sum_received; end.sum bytes may be zero'))

def interval(data, udp):
    assert data['start']['test_start']['reverse']==1 and not data.get('error')
    vals=[]
    for block in data['intervals']:
        assert len(block['streams'])==1
        r=block['streams'][0]; assert r['sender'] is False
        if r['start']>=9.98 and r['end']<=60.1: vals.append(r)
    vals.sort(key=lambda x:x['start'])
    assert vals and vals[0]['start']<=10.1 and vals[-1]['end']>=59.9
    assert all(abs(a['end']-b['start'])<=.1 for a,b in zip(vals,vals[1:]))
    seconds=sum(r['end']-r['start'] for r in vals)
    out={'received_mbps':sum(r['bytes'] for r in vals)*8/seconds/1e6,'analyzed_seconds':seconds,'interval_count':len(vals)}
    if udp:
        packets=sum(r['packets'] for r in vals); lost=sum(r['lost_packets'] for r in vals)
        assert packets>0 and 0<=lost<=packets
        out.update(udp_loss_percent=100*lost/packets,udp_packets=packets,udp_lost_packets=lost,udp_jitter_interval_mean_ms=statistics.mean(r['jitter_ms'] for r in vals),udp_jitter_last_ms=vals[-1]['jitter_ms'])
    return out

def queue_sig(run,prefix):
    counters={'stats','stats2','xstats','pcnt','bytes','packets','drops','overlimits','requeues','backlog','qlen','success','hit','lastuse','firstused','used'}
    def clean(v):
        if isinstance(v,dict): return {k:clean(x) for k,x in v.items() if k not in counters}
        if isinstance(v,list): return [clean(x) for x in v]
        return v
    fields=('kind','handle','parent','root','protocol','pref','chain','options')
    return {n:[clean({k:r[k] for k in fields if k in r}) for r in load(run/f'{prefix}-srv-{n}.json')] for n in ('qdisc','class','filter')}

def calc_c(run, rows, checks):
    cfg=load(run/'config.json'); stored=load(run/'metrics.json')
    for proto in ('udp','tcp'):
        fn=f'{proto}-receiver.json'; calculated=interval(load(run/fn),proto=='udp')
        for key,value in calculated.items():
            assert math.isclose(value,stored[proto][key],rel_tol=1e-10,abs_tol=1e-10),(run.name,proto,key)
            unit='Mbit/s' if key=='received_mbps' else '%' if key=='udp_loss_percent' else 'ms' if 'jitter' in key else 's' if key=='analyzed_seconds' else 'count'
            item(rows,run.name,'sta1' if proto=='udp' else 'sta2',proto+'_'+key,value,unit,'receiver 10–60 s; complete intervals',fn+':intervals[].streams[0]')
    start=datetime.fromisoformat(cfg['traffic_started_utc']).timestamp(); replies=[]
    for line in (run/'ping.txt').read_text(encoding='utf-8').splitlines():
        m=re.search(r'^\[(\d+\.\d+)\].*icmp_seq=(\d+).*time[=<]([\d.]+) ms',line)
        if m and 10<=float(m[1])-start<60: replies.append((int(m[2]),float(m[3])))
    assert replies and len({n for n,_ in replies})==len(replies)
    vals=[v for _,v in replies]; assert len(vals)==stored['rtt']['successful_samples'] and abs(statistics.mean(vals)-stored['rtt']['mean_ms'])<1e-9 and p95(vals)==stored['rtt']['p95_ms']
    for metric,value,unit in [('rtt_mean_ms',statistics.mean(vals),'ms'),('rtt_p95_ms',p95(vals),'ms'),('rtt_success_count',len(vals),'samples')]: item(rows,run.name,'sta1',metric,value,unit,'ping replies received 10–60 s; nearest-rank','ping.txt;config.json:traffic_started_utc')
    conf=queue_sig(run,'configured'); paths=sorted(run.glob('sample*-srv-class.json')); assert len(paths)>=50
    diffs=[]
    for path in paths:
        prefix=path.name.removesuffix('-srv-class.json')
        if queue_sig(run,prefix)!=conf: diffs.append(prefix)
    if queue_sig(run,'after')!=conf: diffs.append('after')
    cls={r['handle']:r for r in load(run/'configured-srv-class.json')}; qs=load(run/'configured-srv-qdisc.json'); filters=load(run/'configured-srv-filter.json')
    after={r['handle']:r for r in load(run/'after-srv-class.json')}
    assert cfg['mode']=='baseline' and cfg['server_interface']=='srv-eth0'
    assert cls['1:1']['options']['rate']=='2Mbit' and cls['1:1']['options']['ceil']=='2Mbit'
    assert cls['1:20']['options']['rate']=='2Mbit' and any(q['kind']=='bfifo' and q['parent']=='1:20' and q['options']['limit']==32768 for q in qs)
    assert not filters and after['1:20']['bytes']>0 and not diffs
    checks.append(dict(run_id=run.name,check='baseline_queue',value=json.dumps({'snapshots':len(paths),'diffs':diffs,'parent_rate':'2Mbit','default_class':'1:20','fifo_limit_bytes':32768,'filter_count':len(filters),'after_class_bytes':after['1:20']['bytes'],'after_class_packets':after['1:20']['packets']},ensure_ascii=False),note='baseline only; shared class counts do not prove per-protocol classification'))

def check_qos(run, checks):
    cfg=load(run/'config.json'); assert cfg['mode']=='qos' and (run/'status.txt').read_text().strip()=='PASS'
    conf=queue_sig(run,'configured'); paths=sorted(run.glob('sample*-srv-class.json'))
    assert len(paths)>=50
    assert all(queue_sig(run,p.name.removesuffix('-srv-class.json'))==conf for p in paths)
    assert queue_sig(run,'after')==conf
    cls={r['handle']:r for r in load(run/'configured-srv-class.json')}
    assert cls['1:1']['options']['rate']=='2Mbit' and cls['1:1']['options']['ceil']=='2Mbit'
    assert cls['1:10']['options']['rate']=='600Kbit' and cls['1:20']['options']['rate']=='1400Kbit'
    assert all(cls[k]['options']['ceil']=='2Mbit' for k in ('1:10','1:20'))
    limits={r['parent']:r['options']['limit'] for r in load(run/'configured-srv-qdisc.json') if r['kind']=='bfifo'}
    assert limits=={'1:10':8192,'1:20':24576}
    text=(run/'configured-srv-filter.txt').read_text(encoding='utf-8')
    blocks=re.findall(r'^filter .*?\*flowid 1:10[^\n]*\n((?:\s+match [^\n]*\n)+)',text,re.M)
    assert any(all(s in block for s in ('match 00110000/00ff0000 at 8','match 14520000/ffff0000 at 20','match 0a2c0001/ffffffff at 16')) for block in blocks)
    assert any(all(s in block for s in ('match 00010000/00ff0000 at 8','match 0a2c0001/ffffffff at 16')) for block in blocks)
    pre={r['handle']:r['bytes'] for r in load(run/'before-icmp-srv-class.json')}; final={r['handle']:r['bytes'] for r in load(run/'after-srv-class.json')}
    assert pre['1:10']>0 and final['1:10']>0 and final['1:20']>0
    checks.append(dict(run_id=run.name,check='qos_queue',value=json.dumps({'snapshots':len(paths),'parent_rate':'2Mbit','realtime_rate':'600Kbit','background_rate':'1400Kbit','limits':limits,'before_icmp_class_bytes':pre,'after_class_bytes':final},ensure_ascii=False),note='filter text retains all u32 match clauses; positive pre-ICMP class counter supports UDP classification, not a per-filter packet counter'))

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--out',required=True,type=Path); args=parser.parse_args()
    out=args.out.resolve(); raw=(ROOT/'原始日志').resolve()
    if out.exists() or out==raw or raw in out.parents: parser.error('output must be new and outside raw directory')
    rows=[]; checks=[]
    for group,names in RUNS.items():
        for name in names:
            run=raw/name; assert run.is_dir(); {'A':calc_a,'B':calc_b,'C':calc_c}[group](run,rows,checks)
    check_qos(raw/'expC_qos_c2000_run02_20261109T134447Z_0439qzhl',checks)
    out.mkdir(parents=True)
    for name,data,fields in [('复算指标.csv',rows,['run_id','station','metric','value','unit','window','source']),('核查细节.csv',checks,['run_id','check','value','note'])]:
        with (out/name).open('x',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(data)
    print(f'PASS: {sum(map(len,RUNS.values()))} runs; {len(rows)} metrics; {len(checks)} checks; {out}')

if __name__=='__main__': main()
