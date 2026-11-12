#!/usr/bin/env python3
"""Offline group statistics and pre-registered repeat recommendations."""
import argparse
import csv
import json
from pathlib import Path
import statistics
import sys
import random
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from core import build_manifest


def describe(values):
    values=[x for x in values if x is not None]
    return {'n':len(values),'mean':statistics.mean(values) if values else None,
            'sample_sd':statistics.stdev(values) if len(values)>1 else None}


def key(row):return (row['mode'],row['rt_kbit'],row['buffer_bytes'],row['workload'])


def steady_queue_samples(record):
    c=record['config'];t0=c.get('udp_t0_ns',c['udp_start_lower_ns'])
    samples=[s for s in record['resources']['queue_series'] if c['warmup']<=(s['mono_ns']-t0)/1e9<c['seconds']]
    if not samples:raise ValueError('no queue samples in measurement window')
    return samples


def supplement_manifest(rows):
    groups={}
    for row in rows:groups.setdefault(key(row),[]).append(row)
    base=build_manifest();canonical={key(x):x for x in base}
    members={exp:{key(x) for x in base if x['experiment']==exp} for exp in ['E1','E2','E3','E4']}
    members['E2'].add(('qos',600,32768,'static'))
    members['E4']|=members['E1']
    triggered=set()
    for group_key,all_rows in groups.items():
        group=[x for x in all_rows if x['repeat']<=3]
        if len(group)<3:continue
        dynamic=group[0]['workload']=='dynamic'
        values=[x.get('udp_delay_p95_ms') if dynamic else x.get('udp_jitter_ms') for x in group]
        stats=describe(values);mean,sd=stats['mean'],stats['sample_sd']
        high_cv=mean is not None and mean>0 and sd is not None and sd/mean>.2
        def passes(x):
            if x.get('udp_loss_percent') is None:return False
            if not dynamic:return x['udp_loss_percent']<=1
            return x['udp_loss_percent']<=1 and x.get('udp_delay_p95_ms') is not None and x['udp_delay_p95_ms']<=50 and x.get('on_time_percent',0)>=99
        mixed=len({passes(x) for x in group})>1
        if high_cv or mixed:
            triggered|={experiment for experiment,keys in members.items() if group_key in keys}
    needed={group_key:canonical[group_key] for experiment in triggered for group_key in members[experiment]}
    extra=[]
    rng=random.Random(20261111)
    for repeat in [4,5]:
        order=sorted(needed);rng.shuffle(order)
        for k in order:
            spec=needed[k];existing={x['repeat'] for x in groups.get(k,[])}
            if repeat not in existing:
                extra.append(spec|{'repeat':repeat,'id':f"SUP_{spec['mode']}_r{spec['rt_kbit']}_b{spec['buffer_bytes']}_{spec['workload']}_n{repeat}"})
    return extra


def load_records(root,compact=None):
    out=Path(root)/'results'
    if compact is not None:
        return json.loads(Path(compact).read_text())['runs'],'ACQUISITION_INTERIM_UNAUDITED'
    if (out/'audit.json').exists():
        audit=json.loads((out/'audit.json').read_text())
        if not audit.get('integrity_passed',audit.get('checks_passed',False)):
            raise ValueError('raw audit integrity failed; cannot produce canonical summaries')
        records=[x for x in audit['records'] if x.get('audit_passed',True)]
        return records,'FINAL' if audit['checks_passed'] else 'AUDITED_INTERIM_PENDING_PUBLICATION_GATES'
    return json.loads((out/'compact.json').read_text())['runs'],'ACQUISITION_INTERIM_UNAUDITED'


def flatten(records):
    rows=[];phases=[]
    for record in records:
        if record['status']!='PASS' or record['config'].get('kind')!='formal':continue
        c,m=record['config'],record['metrics']
        row={k:c[k] for k in ['id','experiment','mode','rt_kbit','buffer_bytes','workload','repeat','seconds']}
        row['rtt_p95_ms']=m['rtt']['p95_ms'];row['rtt_mean_ms']=m['rtt']['mean_ms']
        if c['workload']=='static':
            u=m['udp'];row.update(udp_received_mbps=u['received_mbps'],udp_loss_percent=u['udp_loss_percent'],
                udp_jitter_ms=u['udp_jitter_interval_mean_ms'],tcp_received_mbps=m['tcp']['received_mbps'])
            retx=record.get('tcp_retransmission_windows',{}).get('main')
            if retx:row.update(tcp_retransmits=retx['retransmits'],tcp_retransmits_per_second=retx['retransmits_per_second'])
        else:
            row.update(udp_received_mbps=m['phases'][1]['received_mbps'],udp_loss_percent=m['phases'][1]['loss_percent'],
                udp_delay_p95_ms=m['phases'][1]['delay_p95_ms'],on_time_percent=m['phases'][1]['on_time_percent'],
                tcp_received_mbps=m['phases'][1]['tcp']['received_mbps'],recovery_seconds=m['recovery_seconds'],main_phase=1)
            retx=record.get('tcp_retransmission_windows',{}).get('phase1')
            if retx:row.update(tcp_retransmits=retx['retransmits'],tcp_retransmits_per_second=retx['retransmits_per_second'])
            for p in m['phases']:
                phase_row=row|{k:v for k,v in p.items() if k!='tcp'}|{'tcp_received_mbps':p['tcp']['received_mbps'],
                              'udp_received_mbps':p['received_mbps'],'udp_loss_percent':p['loss_percent'],
                              'udp_delay_p95_ms':p['delay_p95_ms'],'main_phase':p['phase'],
                              'tcp_analyzed_seconds':p['tcp']['analyzed_seconds'],'tcp_coverage':p['tcp']['window_coverage_fraction']}
                phase_retx=record.get('tcp_retransmission_windows',{}).get('phase'+str(p['phase']))
                if phase_retx:phase_row.update(tcp_retransmits=phase_retx['retransmits'],tcp_retransmits_per_second=phase_retx['retransmits_per_second'])
                phases.append(phase_row)
        rows.append(row)
    return rows,phases


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='',encoding='utf-8-sig') as out:
        writer=csv.DictWriter(out,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def run(root,compact=None):
    root=Path(root);out=root/'results';out.mkdir(exist_ok=True)
    records,state=load_records(root,compact)
    (out/'analysis_status.json').write_text(json.dumps({'state':state},indent=2)+'\n')
    rows,phases=flatten(records)
    write_csv(out/'formal_runs.csv',rows);write_csv(out/'phases.csv',phases)
    groups={}
    for row in rows:groups.setdefault(key(row),[]).append(row)
    summaries=[]
    fields=['udp_received_mbps','udp_loss_percent','udp_jitter_ms','udp_delay_p95_ms','on_time_percent',
            'tcp_received_mbps','rtt_p95_ms','recovery_seconds','tcp_retransmits','tcp_retransmits_per_second']
    for k,group in groups.items():
        summaries.append(dict(zip(['mode','rt_kbit','buffer_bytes','workload'],k))|{'n':len(group),
                         'metrics':{f:describe([r.get(f) for r in group]) for f in fields if any(f in r for r in group)}})
    (out/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2)+'\n')
    extra=supplement_manifest(rows)
    (out/'supplement_manifest.json').write_text(json.dumps(extra,indent=2)+'\n')
    print(json.dumps({'valid_formal_runs':len(rows),'groups':len(groups),'recommended_extra_runs':len(extra)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root');parser.add_argument('--compact');args=parser.parse_args()
    run(args.root,args.compact)
