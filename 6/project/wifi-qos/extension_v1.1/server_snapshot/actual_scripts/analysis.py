"""Receiver-side statistics; no silent replacement of missing measurements."""
import json
from pathlib import Path
from core import packet_metrics, percentile


def validate_clocks(tx,rx):
    for key in ('time_namespace','boot_id'):
        if not tx['environment'].get(key) or tx['environment'][key]!=rx['environment'].get(key):
            raise ValueError('untrusted shared clock: '+key)


def pacing_errors(tx):
    errors=[]
    for i,(duration,rate) in enumerate(zip(tx['durations'],tx['rates_kbit'])):
        rows=[x for x in tx['events'] if x['phase']==i]
        actual=sum(x['ok'] for x in rows)*160*8/duration/1000
        if abs(actual/rate-1)>.02:errors.append(f'phase{i}: rate {actual:.4f} vs {rate}')
        if not rows or sum(x['lateness_ns']>x['spacing_ns'] for x in rows)/len(rows)>.01:
            errors.append(f'phase{i}: more than 1% late slots')
        if any(not x['ok'] and x.get('error')!='schedule_miss' for x in rows):
            errors.append(f'phase{i}: send syscall error')
        if rows and abs(rows[0]['send_ns']-rows[0]['scheduled_ns'])>100_000_000:
            errors.append(f'phase{i}: transition timing error')
    return errors


def tcp_window(data,lower_ns,upper_ns,t0_ns,start,end):
    if data.get('error'):raise ValueError(data['error'])
    rows=[]
    for interval in data.get('intervals',[]):
        streams=interval.get('streams',[])
        if len(streams)!=1 or streams[0].get('sender') is not False:raise ValueError('TCP receiver required')
        x=streams[0]
        earliest_start=(lower_ns-t0_ns)/1e9+x['start']
        latest_end=(upper_ns-t0_ns)/1e9+x['end']
        if earliest_start>=start and latest_end<=end:rows.append(x)
    duration=sum(x['end']-x['start'] for x in rows)
    total=sum(x['bytes'] for x in rows)
    if duration<=0 or total<=0:raise ValueError('no TCP competition in selected window')
    rows.sort(key=lambda x:x['start'])
    uncertainty=(upper_ns-lower_ns)/1e9
    if uncertainty<0:raise ValueError('invalid TCP time bounds')
    if any(abs(b['start']-a['end'])>.1 for a,b in zip(rows,rows[1:])):
        raise ValueError('internal TCP interval gap or overlap')
    boundary_allowance=1.1+uncertainty
    if (lower_ns-t0_ns)/1e9+rows[0]['start']>start+boundary_allowance or (upper_ns-t0_ns)/1e9+rows[-1]['end']<end-boundary_allowance:
        raise ValueError('TCP receiver does not cover usable phase')
    if duration < (end-start)-2*boundary_allowance:raise ValueError('insufficient TCP interval coverage')
    return {'received_mbps':total*8/duration/1e6,'analyzed_seconds':duration,
            'interval_count':len(rows),'start_uncertainty_ms':(upper_ns-lower_ns)/1e6,
            'window_coverage_fraction':duration/(end-start)}


def dynamic_metrics(directory,config):
    directory=Path(directory)
    tx=json.loads((directory/'udp-sender.json').read_text())
    rx=json.loads((directory/'udp-receiver.json').read_text())
    validate_clocks(tx,rx)
    errors=pacing_errors(tx)
    if rx['socket_drops'] or rx['malformed']:errors.append('receiver socket overflow or malformed traffic')
    mapping={x['seq']:x for x in tx['events'] if x['ok']}
    for x in rx['events']:
        if x['seq'] not in mapping or x['send_ns']!=mapping[x['seq']]['send_ns'] or x['phase']!=mapping[x['seq']]['phase']:
            errors.append('receiver event does not match sender');break
    if errors:raise ValueError('; '.join(errors))
    t0=tx['t0_ns'];durations=tx['durations'];first=durations[0];second=first+durations[1];end=sum(durations)
    warmup=min(config.get('warmup',10),first/2)
    windows=[(warmup,first),(first,second),(second,end)]
    tcp=json.loads((directory/'tcp-receiver.json').read_text()) if (directory/'tcp-receiver.json').exists() else None
    phases=[]
    for i,(start,stop) in enumerate(windows):
        metrics=packet_metrics(tx['events'],rx['events'],start,stop,t0)
        metrics.update(phase=i,scheduled_packets=sum(x['phase']==i for x in tx['events']),
                       generation_missed_slots=sum(x['phase']==i and not x['ok'] for x in tx['events']))
        if tcp:metrics['tcp']=tcp_window(tcp,config['tcp_start_lower_ns'],config['tcp_start_upper_ns'],t0,start,stop)
        phases.append(metrics)
    series=[packet_metrics(tx['events'],rx['events'],i,i+1,t0) for i in range(int(end))]
    recovery=None
    for elapsed in range(max(0,int(durations[2])-4)):
        m=packet_metrics(tx['events'],rx['events'],second+elapsed,second+elapsed+5,t0)
        if m['loss_percent'] is not None and m['loss_percent']<=1 and m['delay_p95_ms'] is not None and m['delay_p95_ms']<=50 and m['on_time_percent']>=99:
            recovery=elapsed;break
    return {'phases':phases,'series':series,'recovery_seconds':recovery,
            'recovery_observation_limit_seconds':durations[2],'pacing':tx['pacing'],
            'clock':tx['environment'],'socket_drops':rx['socket_drops']}
