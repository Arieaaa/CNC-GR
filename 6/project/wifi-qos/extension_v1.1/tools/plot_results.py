#!/usr/bin/env python3
"""Publication-style static figures from audited independent runs."""
import argparse
import json
import os
from pathlib import Path
import statistics
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/expc-v11-mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from postprocess import flatten,key,steady_queue_samples
from audit import log_path

COLORS={'baseline':'#64798B','qos':'#138F83','fq_codel':'#DB8B29','qos1200':'#7862A9'}
LABELS={'baseline':'FIFO','qos':'HTB 600','fq_codel':'FQ-CoDel','qos1200':'HTB 1200'}


def variant(c):return 'qos1200' if c['mode']=='qos' and c['rt_kbit']==1200 else c['mode']


def main(root):
    root=Path(root);out=root/'results/figures';out.mkdir(exist_ok=True)
    audit=json.loads((root/'results/audit.json').read_text())
    if not audit['checks_passed']:raise ValueError('raw-log audit must pass before plotting')
    records=[x for x in audit['records'] if x.get('audit_passed')]
    rows,phases=flatten(records)
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,
                         'axes.grid':True,'grid.alpha':.2,'savefig.dpi':200})
    def save(fig,name):
        fig.savefig(out/(name+'.png'));fig.savefig(out/(name+'.pdf'));plt.close(fig)
    def average(values):return statistics.mean(values),statistics.stdev(values) if len(values)>1 else 0
    def group_points(ax,groups,field,label):
        for i,(name,group) in enumerate(groups):
            values=[r[field] for r in group if r.get(field) is not None]
            mean,sd=average(values);color=COLORS[name]
            ax.bar(i,mean,width=.58,color=color,alpha=.55)
            ax.errorbar(i,mean,yerr=sd,fmt='none',capsize=4,color='#263542')
            ax.scatter(np.linspace(i-.13,i+.13,len(values)),values,color=color,edgecolors='white',zorder=4)
            ax.annotate(f'{mean:.3g}',(i,mean+sd),xytext=(0,6),textcoords='offset points',ha='center')
        ax.set_xticks(range(len(groups)),[LABELS[k] for k,g in groups]);ax.set_ylabel(label);ax.set_ylim(bottom=0)
    base=[r for r in rows if r['workload']=='static' and r['buffer_bytes']==32768 and r['rt_kbit']==600]
    groups=[(mode,[r for r in base if r['mode']==mode]) for mode in ['baseline','qos','fq_codel']]
    fig,axes=plt.subplots(2,2,figsize=(10.5,7),layout='constrained')
    for ax,(field,label) in zip(axes.flat,[('udp_loss_percent','UDP packet loss (%)'),('udp_jitter_ms','Reported UDP jitter (ms)'),
                         ('rtt_p95_ms','P95 probe RTT (ms)'),('tcp_received_mbps','TCP received payload (Mbit/s)')]):
        group_points(ax,groups,field,label)
    fig.suptitle('Three queueing schemes | 2 Mbit/s egress, UDP 300 kbit/s\nDots = independent runs; bars = mean; error bars = sample SD')
    save(fig,'01_static_comparison')

    fig,axes=plt.subplots(3,1,figsize=(11,8),sharex=True,sharey=True,layout='constrained')
    for ax,mode in zip(axes,['baseline','qos','fq_codel']):
        record=next(x for x in records if x['config']['mode']==mode and x['config']['workload']=='static'
                    and x['config']['buffer_bytes']==32768 and x['config']['rt_kbit']==600 and x['config']['repeat']==1)
        c=record['config'];t0=c['udp_start_lower_ns'];series=record['resources']['queue_series']
        for handle,label,color in [('10:','Realtime leaf','#138F83'),('20:','Shared/background leaf','#64798B' if mode=='qos' else COLORS[mode])]:
            points=[((s['mono_ns']-t0)/1e9,s['backlog_bytes'][handle]/1024) for s in series if handle in s['backlog_bytes']]
            if points:ax.plot([p[0] for p in points],[p[1] for p in points],label=label,color=color)
        ax.axvspan(0,10,color='#999999',alpha=.12);ax.set_ylabel('Backlog (KiB)');ax.set_title(LABELS[mode]+' | repeat 1')
        ax.legend(loc='upper right');ax.set_ylim(0,34)
    axes[-1].set_xlabel('Seconds relative to UDP launch (1 Hz queue snapshots)')
    fig.suptitle('Queue mechanism: sampled leaf backlog, 32 KiB capacity scale')
    save(fig,'02_queue_mechanism')

    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    sweep=[r for r in rows if r['workload']=='static' and r['mode']=='qos' and r['buffer_bytes']==32768]
    for ax,(field,label) in zip(axes.flat,[('udp_loss_percent','UDP loss (%)'),('udp_jitter_ms','Reported UDP jitter (ms)'),
                    ('rtt_p95_ms','P95 probe RTT (ms)'),('tcp_received_mbps','TCP payload (Mbit/s)')]):
        xs=[200,400,600,1000];means=[];sds=[]
        for x in xs:
            values=[r[field] for r in sweep if r['rt_kbit']==x];mean,sd=average(values);means.append(mean);sds.append(sd)
            ax.scatter([x]*len(values),values,color=COLORS['qos'],alpha=.6,s=18)
        ax.errorbar(xs,means,yerr=sds,marker='o',capsize=4,color=COLORS['qos'])
        if field=='udp_loss_percent':ax.axhline(1,ls='--',color='#BA514D',label='1% comparison threshold');ax.legend()
        ax.set_xticks(xs);ax.set_xlabel('Realtime HTB guarantee (kbit/s)');ax.set_ylabel(label);ax.set_ylim(bottom=0)
        if field=='tcp_received_mbps':ax.set_ylim(0,ax.get_ylim()[1]*1.12)
    fig.suptitle('Guarantee selection | UDP payload 300 kbit/s; total cap fixed at 2000 kbit/s')
    save(fig,'03_guarantee_sweep')

    dynamic=[x for x in records if x['config']['workload']=='dynamic']
    fig,axes=plt.subplots(3,1,figsize=(12,9),sharex=True,layout='constrained')
    for record in dynamic:
        c,m=record['config'],record['metrics']
        if c['repeat']!=1:continue
        name=variant(c);color=COLORS[name];series=m['series']
        axes[0].plot([x['start']+.5 for x in series],[x['delay_p95_ms'] for x in series],label=LABELS[name],color=color)
        axes[1].plot([x['start']+.5 for x in series],[x['loss_percent'] for x in series],label=LABELS[name],color=color)
        raw=log_path(audit,record['id'],'tcp-receiver.json')
        if raw.is_file():
            data=json.loads(raw.read_text());shift=((c['tcp_start_lower_ns']+c['tcp_start_upper_ns'])/2-c['udp_t0_ns'])/1e9
            xs=[];ys=[];streams=[]
            for interval in data['intervals']:
                s=interval['streams'][0];streams.append(s);xs.append(shift+(s['start']+s['end'])/2)
                ys.append(s['bytes']*8/(s['end']-s['start'])/1e6)
            axes[2].plot(xs,ys,color=color,alpha=.12,lw=.7)
            trailing=[]
            for i in range(4,len(streams)):
                window=streams[i-4:i+1];duration=sum(s['end']-s['start'] for s in window)
                trailing.append((shift+window[-1]['end'],sum(s['bytes'] for s in window)*8/duration/1e6))
            axes[2].plot([x for x,y in trailing],[y for x,y in trailing],color=color,label=LABELS[name],alpha=.9)
    for ax,label in zip(axes,['UDP packet P95 per second (ms)','UDP loss per second (%)','TCP payload, trailing 5 s (Mbit/s)']):
        ax.set_ylabel(label);ax.axvline(30,color='#333333',ls='--',alpha=.6);ax.axvline(60,color='#333333',ls='--',alpha=.6)
        ax.axvspan(30,60,color='#DB8B29',alpha=.07);ax.set_xlim(0,90);ax.set_ylim(bottom=0)
    axes[0].axhline(50,color='#BA514D',ls=':',label='50 ms comparison deadline')
    axes[0].legend(loc='lower center',bbox_to_anchor=(.5,1.02),ncol=5,fontsize=9)
    axes[-1].set_xlabel('Seconds | UDP offered load: 300 → 900 → 300 kbit/s')
    fig.suptitle('Dynamic response | pre-selected repeat 1; UDP keeps one five-tuple\nTCP: faint = raw intervals, bold = trailing 5-interval aggregate; start-time bounds recorded')
    save(fig,'04_dynamic_response')

    fig,ax=plt.subplots(figsize=(9,6),layout='constrained')
    for name in ['baseline','qos','qos1200','fq_codel']:
        data=[r for r in rows if r['workload']=='dynamic' and variant(r)==name]
        style={'marker':'D','s':115,'facecolors':'none','edgecolors':COLORS[name],'linewidths':1.8} if name=='qos1200' else {
               'marker':'^' if name=='qos' else 'o','s':55,'color':COLORS[name],'edgecolors':'white'}
        ax.scatter([r['tcp_received_mbps'] for r in data],[r['on_time_percent'] for r in data],label=LABELS[name],**style)
    ax.axhline(99,ls='--',color='#BA514D',label='99% effective delivery threshold')
    ax.set_xlabel('Background TCP received payload (Mbit/s)');ax.set_ylabel('UDP packets delivered within 50 ms (%)')
    ax.set_ylim(-3,103);ax.legend();ax.set_title('Realtime experience and background cost | high-demand phase [30,60)')
    save(fig,'05_experience_cost')

    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    lookup={r['id']:r for r in records}
    for ax,(field,label) in zip(axes.flat,[('rtt_p95_ms','P95 probe RTT (ms)'),('udp_jitter_ms','Reported UDP jitter (ms)'),
                    ('tcp_received_mbps','TCP payload (Mbit/s)'),('backlog_peak','Peak sampled leaf backlog (KiB)')]):
        for mode in ['baseline','qos','fq_codel']:
            means=[];sds=[]
            for buf in [16384,32768,65536]:
                data=[r for r in rows if r['workload']=='static' and r['mode']==mode and r['rt_kbit']==600 and r['buffer_bytes']==buf]
                values=[max(sum(s['backlog_bytes'].values()) for s in steady_queue_samples(lookup[r['id']]))/1024 if field=='backlog_peak' else r[field] for r in data]
                mean,sd=average(values);means.append(mean);sds.append(sd)
            ax.errorbar([16,32,64],means,yerr=sds,marker='o',capsize=4,label=LABELS[mode],color=COLORS[mode])
        if field=='rtt_p95_ms':ax.plot([16,32,64],[65.536,131.072,262.144],ls=':',color='#333333',label='B×8/C service-time scale')
        ax.set_xticks([16,32,64]);ax.set_xlabel('Nominal capacity scale (KiB)');ax.set_ylabel(label);ax.set_ylim(bottom=0);ax.legend(fontsize=8)
        if field=='tcp_received_mbps':ax.set_ylim(0,ax.get_ylim()[1]*1.15)
    fig.suptitle('Buffer sensitivity | FQ-CoDel packet limits = 11 / 22 / 44\nCapacity scales are approximate; observed bytes are reported separately')
    save(fig,'06_buffer_sensitivity')
    print('Saved six figure pairs (PNG/PDF).')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');a=p.parse_args();main(a.root)
