"""分析下载到指定目录的实测运行。"""
import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path


def analyze(run):
    obs = run/'observations'
    rows = list(csv.DictReader((obs/'samples.csv').open()))
    origin = json.loads((obs/'clock.json').read_text())['epoch']
    ping = (obs/'ping.txt').read_text()
    replies = [(float(t)-origin,int(seq),float(rtt)) for t,seq,rtt in
               re.findall(r'^\[([\d.]+)\] \d+ bytes from .*?icmp_seq=(\d+).*?time=([\d.]+) ms', ping, re.M)]
    tx, rx = map(int,re.search(r'(\d+) packets transmitted, (\d+) received',ping).groups())
    cfg = json.loads((run/'config.json').read_text())
    events = []
    prev = None
    for row in rows:
        if not row['bssid']:
            continue
        if prev and prev['bssid'] != row['bssid']:
            lo, hi = float(prev['start_s']), float(row['end_s'])
            before = [r for r in replies if r[0] < lo]
            after = [r for r in replies if r[0] > hi]
            window = []
            gap = None
            lost = None
            if before and after:
                window = [r for r in replies if before[-1][0]<=r[0]<=after[0][0]]
                gap = max(b[0]-a[0] for a,b in zip(window,window[1:]))*1000
                lost = after[0][1]-before[-1][1]+1-len(window)
            events.append(dict(old_bssid=prev['bssid'], new_bssid=row['bssid'],
                last_old_s=lo,first_new_s=hi,first_new_x_m=float(row['x_m']),
                last_old_signal_dBm=prev['signal_dBm'], first_new_signal_dBm=row['signal_dBm'],
                nearby_replies=[dict(t_s=t,seq=seq,rtt_ms=rtt) for t,seq,rtt in window],
                max_adjacent_reply_gap_ms=gap,missing_seq_near_event=lost))
        prev=row
    if not replies or len(replies)!=rx:
        raise ValueError(f'{run.name}: parsed {len(replies)} RTT records, ping reports {rx}')
    rtts=sorted(r[2] for r in replies)
    (run/'events.json').write_text(json.dumps(events,indent=2))
    decisions=[json.loads(line) for line in (run/'decisions.jsonl').read_text().splitlines()]
    changes=sum(d['change'] and d['current']!=d['candidate'] for d in decisions
                if d['sta']=='sta1-wlan0' and d['policy']==cfg['policy'])
    return dict(run=run.name, phase=cfg['phase'], policy=cfg['policy'],
                events=len(events), policy_change_requests=changes,
                first_new_x_m=events[0]['first_new_x_m'] if events else None,
                first_event_gap_ms=events[0]['max_adjacent_reply_gap_ms'] if events else None,
                sent=tx, received=rx, mean_rtt_ms=statistics.mean(rtts),
                p95_rtt_ms=rtts[math.ceil(.95*len(rtts))-1])


if __name__=='__main__':
    base=Path(sys.argv[1])
    results=[analyze(r) for r in sorted(base.glob('expB_*')) if (r/'status.txt').read_text().strip()=='COLLECTED']
    if results:
        with (base/'summary.csv').open('w') as f:
            writer=csv.DictWriter(f,fieldnames=results[0])
            writer.writeheader()
            writer.writerows(results)
        for row in results:
            print(row)
