#!/usr/bin/env python3
"""Recompute formal metrics and inspect raw configuration/resource evidence offline."""
import argparse
import json
import math
from pathlib import Path
import re
import statistics
import sys
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import legacy
import runner
from analysis import dynamic_metrics,tcp_window
from core import build_manifest


def matrix_issues(configs):
    def identity(c):return tuple(c[k] for k in ['mode','rt_kbit','buffer_bytes','workload','repeat'])
    counts=Counter(identity(c) for c in configs);base=build_manifest();issues=[]
    allowed={identity(c)[:-1] for c in base}
    missing=[x['id'] for x in base if identity(x) not in counts]
    if missing:issues.append({'missing_formal_runs':missing})
    if any(v>1 for v in counts.values()):issues.append({'duplicate_replicate_identities':[list(k) for k,v in counts.items() if v>1]})
    for c in configs:
        if identity(c)[:-1] not in allowed or c['repeat'] not in [1,2,3,4,5] or c['seconds']!=(90 if c['workload']=='dynamic' else 60):
            issues.append({'invalid_formal_identity':c['id']})
    return issues


def log_path(audit_record,run_id,name):
    path=Path(audit_record['logs_root'])/run_id/name
    if not path.is_file():raise FileNotFoundError('expected audited source log missing: '+str(path))
    return path


def sender_retransmissions(data,lower_ns,upper_ns,t0_ns,start,end):
    rows=[]
    if data.get('error'):raise ValueError('sender report error')
    for interval in data.get('intervals',[]):
        streams=interval.get('streams',[])
        if len(streams)!=1 or streams[0].get('sender') is not True or 'retransmits' not in streams[0]:
            raise ValueError('TCP sender retransmission intervals required')
        s=streams[0]
        if (lower_ns-t0_ns)/1e9+s['start']>=start and (upper_ns-t0_ns)/1e9+s['end']<=end:rows.append(s)
    seconds=sum(s['end']-s['start'] for s in rows)
    if seconds<=0 or seconds<(end-start)-2*(1.1+(upper_ns-lower_ns)/1e9):raise ValueError('insufficient sender interval coverage')
    if any(abs(b['start']-a['end'])>.1 for a,b in zip(rows,rows[1:])):raise ValueError('sender interval gap')
    count=sum(s['retransmits'] for s in rows)
    return {'retransmits':count,'analyzed_seconds':seconds,'retransmits_per_second':count/seconds,'interval_count':len(rows)}


def audit_dynamic_contract(tx,rx,config):
    if tx['nonce']!=rx['nonce'] or tx['nonce']!=config['nonce']:raise ValueError('dynamic nonce mismatch')
    if tx['durations']!=[30,30,30] or tx['rates_kbit']!=[300,900,300] or tx['payload_bytes']!=160:
        raise ValueError('dynamic offered schedule differs from protocol')
    sources={x['source'] for x in rx['events']}
    if sources and sources!={config['server_ip']+':5202'}:raise ValueError('not one expected UDP source flow')


def equal(a,b,path='root'):
    if isinstance(a,dict):
        if set(a)!=set(b):raise ValueError('metric keys differ '+path)
        for k in a:equal(a[k],b[k],path+'.'+k)
    elif isinstance(a,list):
        if len(a)!=len(b):raise ValueError('metric list length differs '+path)
        for i,(x,y) in enumerate(zip(a,b)):equal(x,y,path+f'[{i}]')
    elif isinstance(a,(float,int)) and isinstance(b,(float,int)):
        if not math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10):raise ValueError('metric differs '+path)
    elif a!=b:raise ValueError('metric differs '+path)


def resource_evidence(directory):
    samples=[];last=None;busy=[];steal=[];times=[];qseries=[]
    for path in sorted(directory.glob('sample*-time.json')):
        prefix=path.name.split('-')[0];stamp=json.loads(path.read_text());times.append(stamp)
        cpu=[int(x) for x in (directory/(prefix+'-cpu.txt')).read_text().splitlines()[0].split()[1:9]]
        if last:
            d=[b-a for a,b in zip(last,cpu)];total=sum(d)
            if total>0:
                busy.append(100*(total-d[3]-d[4]-d[7])/total);steal.append(100*d[7]/total)
        last=cpu
        qs=json.loads((directory/(prefix+'-srv-qdisc.json')).read_text())
        leaves={x['handle']:x for x in qs if x.get('handle') in ('10:','20:')}
        qseries.append({'mono_ns':stamp['begin_ns'],'duration_ms':(stamp['end_ns']-stamp['begin_ns'])/1e6,
                        'backlog_bytes':{k:x.get('backlog',0) for k,x in leaves.items()},
                        'queue_packets':{k:x.get('qlen',0) for k,x in leaves.items()}})
    if not times:raise ValueError('missing formal resource/time samples')
    late=[(x['begin_ns']-times[0]['begin_ns'])/1e9-i for i,x in enumerate(times)]
    def consecutive(values,threshold):
        count=0
        for x in values:
            count=count+1 if x>threshold else 0
            if count>=5:return True
        return False
    warnings=[]
    if consecutive(steal,5):warnings.append('steal >5% for five samples')
    if consecutive(late,.5):warnings.append('sampling >500ms late for five samples')
    return {'sample_count':len(times),'cpu_busy_mean_percent':statistics.mean(busy) if busy else None,
            'cpu_busy_max_percent':max(busy) if busy else None,'steal_max_percent':max(steal) if steal else None,
            'sample_lateness_max_ms':max(late)*1000,'queue_series':qseries,'issues':[],'warnings':warnings}


def audit(root,logs):
    root,logs=Path(root),Path(logs);records=[];source_versions=set();topology_versions=set();planned=set();issues=[]
    blockers=[];review_path=root/'results/resource_review.json'
    reviews=json.loads(review_path.read_text()) if review_path.exists() else {}
    for directory in sorted(logs.iterdir()):
        if not directory.is_dir() or not (directory/'config.json').exists():continue
        config=json.loads((directory/'config.json').read_text())
        if config.get('kind')!='formal':continue
        status=(directory/'status.txt').read_text().strip()
        if status!='PASS':
            records.append({'id':directory.name,'status':status,'config':config});continue
        failures=[]
        try:
            original=json.loads((directory/'metrics.json').read_text())
            tcp_metadata=json.loads((directory/'tcp-receiver.json').read_text())
            source_versions.add(json.dumps(config['source_hashes'],sort_keys=True));topology_versions.add(config['topology_sha256'])
            identity=config.get('planned_id',config['id'])
            if identity in planned:raise ValueError('duplicate successful planned run')
            planned.add(identity)
            for name,expected in config['source_hashes'].items():
                import hashlib
                if hashlib.sha256((root/'scripts'/name).read_bytes()).hexdigest()!=expected:raise ValueError('local/server source mismatch '+name)
            signature=legacy.saved_queue_signature(directory,'configured')
            runner.audit_qdisc(json.loads((directory/'configured-srv-qdisc.json').read_text()),config)
            runner.audit_classes(json.loads((directory/'configured-srv-class.json').read_text()),config)
            runner.audit_filters(json.loads((directory/'configured-srv-filter.json').read_text()),config,config['station_ips'][0])
            for path in directory.glob('sample*-srv-qdisc.json'):
                prefix=path.name.split('-')[0]
                if legacy.saved_queue_signature(directory,prefix)!=signature:raise ValueError('sample config changed')
            if legacy.saved_queue_signature(directory,'after')!=signature:raise ValueError('final config changed')
            if config['mode']=='fq_codel':runner.audit_final_fq(json.loads((directory/'after-srv-qdisc.json').read_text()))
            if config['mode']=='qos':legacy.verify_udp_class(legacy.class_bytes(directory,'before-icmp'),False)
            deltas=runner.audit_udp_errors((directory/'before-sta1-snmp.txt').read_text(),
                       (directory/'after-sta1-snmp.txt').read_text(),config['workload']=='static')
            offloads=json.loads((directory/'offloads.json').read_text())
            for item in offloads:
                if item['link']['mtu']!=1500:raise ValueError('MTU mismatch')
                if item['node']=='srv' and (item['link'].get('gso_max_size')!=1514 or item['link'].get('gso_max_segs')!=1):raise ValueError('GSO limit mismatch')
            if config['workload']=='dynamic':
                audit_dynamic_contract(json.loads((directory/'udp-sender.json').read_text()),
                                       json.loads((directory/'udp-receiver.json').read_text()),config)
                calculated=dynamic_metrics(directory,config)
                calculated['rtt']=original['rtt']
            else:
                calculated={'udp':legacy.interval_metrics(json.loads((directory/'udp-receiver.json').read_text()),10,60,True),
                    'tcp':tcp_window(json.loads((directory/'tcp-receiver.json').read_text()),config['tcp_start_lower_ns'],
                            config['tcp_start_upper_ns'],config['udp_start_lower_ns'],10,60),'rtt':original['rtt']}
            # Probe timestamps have a recorded monotonic/wall-clock bridge.
            rtts=[];sequences=[]
            for line in (directory/'ping.txt').read_text().splitlines():
                match=re.search(r'^\[(\d+\.\d+)\].*icmp_seq=(\d+).*time[=<]([\d.]+) ms',line)
                if not match:continue
                mono=config['ping_start_mono_ns']+(float(match[1])*1e9-config['ping_start_wall_ns'])
                relative=(mono-config.get('udp_t0_ns',config['udp_start_lower_ns']))/1e9
                if 10<=relative<config['seconds']:rtts.append(float(match[3]));sequences.append(int(match[2]))
            if not rtts:raise ValueError('no independently selected probe samples')
            calculated['rtt']={'mean_ms':statistics.mean(rtts),'p95_ms':sorted(rtts)[math.ceil(.95*len(rtts))-1],
                'successful_samples':len(rtts),'interior_sequence_gaps':max(sequences)-min(sequences)+1-len(set(sequences))}
            equal(calculated,original)
            sender=json.loads((directory/'tcp-server.json').read_text())
            t0=config.get('udp_t0_ns',config['udp_start_lower_ns'])
            windows={'main':(10,60)} if config['workload']=='static' else {'phase0':(10,30),'phase1':(30,60),'phase2':(60,90)}
            retransmissions={name:sender_retransmissions(sender,config['tcp_start_lower_ns'],config['tcp_start_upper_ns'],
                            t0,start,end) for name,(start,end) in windows.items()}
            final_queues=json.loads((directory/'after-srv-qdisc.json').read_text())
            leaf_counters={q['handle']:{k:q.get(k,0) for k in ['drops','drop_overlimit','drop_overmemory','maxpacket']} for q in final_queues if q.get('handle') in ['10:','20:']}
            resources=resource_evidence(directory)
            failures.extend(resources['issues'])
            if resources['warnings']:
                decision=reviews.get(directory.name,{})
                resources['disposition']=decision
                if decision.get('decision')!='retain' or not decision.get('reason'):
                    blockers.append({'id':directory.name,'resource_warnings_require_review':resources['warnings']})
            records.append({'id':directory.name,'status':status,'config':config,'metrics':original,
                            'udp_error_deltas':deltas,'resources':resources,'audit_passed':not failures,
                            'tcp_receiver_block_bytes':tcp_metadata.get('start',{}).get('test_start',{}).get('blksize'),
                            'tcp_congestion_control':tcp_metadata.get('end',{}).get('sender_tcp_congestion'),
                            'tcp_retransmission_windows':retransmissions,'queue_final_counters':leaf_counters,
                            'tcp_total_retransmits':sender['end']['sum_sent']['retransmits']})
        except Exception as exc:
            failures.append(f'{type(exc).__name__}: {exc}')
            records.append({'id':directory.name,'status':status,'config':config,'audit_passed':False,'issues':failures})
        if failures:issues.append({'id':directory.name,'issues':failures})
    valid=[x for x in records if x.get('audit_passed')]
    issues.extend(matrix_issues([x['config'] for x in valid]))
    if len(source_versions)!=1:issues.append({'issues':['formal source versions are not exactly one']})
    if len(topology_versions)!=1:issues.append({'issues':['formal topology versions are not exactly one']})
    tcp_controls={x.get('tcp_congestion_control') for x in valid}
    if len(tcp_controls)!=1 or None in tcp_controls:issues.append({'issues':['TCP congestion control identity missing or inconsistent']})
    from postprocess import flatten,supplement_manifest
    rows,_=flatten(valid);supplements=supplement_manifest(rows)
    if supplements:blockers.append({'required_supplements':[x['id'] for x in supplements]})
    result={'integrity_passed':not issues,'checks_passed':not issues and not blockers,
            'logs_root':str(logs.resolve()),'formal_attempts':len(records),'valid_formal_runs':len(valid),
            'issues':issues,'publication_blockers':blockers,'required_supplements':supplements,'records':records}
    (root/'results/audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'checks_passed':result['checks_passed'],'valid_formal_runs':len(valid),'issues':issues},ensure_ascii=False))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('logs');a=p.parse_args();audit(a.root,a.logs)
