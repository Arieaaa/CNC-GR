#!/usr/bin/env python3
"""One isolated topology per run. Called under the shared batch flock."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import statistics
import subprocess
import tempfile
import time
import traceback
from datetime import datetime,timezone
from types import SimpleNamespace

import legacy
from core import queue_commands
from analysis import dynamic_metrics,tcp_window

SCRIPTS=Path(__file__).resolve().parent


def audit_qdisc(rows,spec):
    if not any(x['kind']=='htb' and x.get('root') for x in rows):raise ValueError('missing common HTB root')
    leaves=[x for x in rows if x.get('handle') in ('10:','20:')]
    if spec['mode']=='fq_codel':
        fq=next((x for x in leaves if x['kind']=='fq_codel'),None)
        if fq is None:raise ValueError('FQ-CoDel not installed')
        opts=fq.get('options',{})
        expected={'limit':{16384:11,32768:22,65536:44}[spec['buffer_bytes']],
                  'target':10000,'interval':100000,'quantum':1514,'flows':1024,'memory_limit':1048576}
        def same(key,value):
            actual=opts.get(key)
            return isinstance(actual,(int,float)) and abs(actual-value)<=1 if key in ('target','interval') else actual==value
        if any(not same(k,v) for k,v in expected.items()) or opts.get('ecn',False):
            raise ValueError('FQ-CoDel settings differ from protocol: '+repr(opts))
    else:
        limits={x['handle']:x.get('options',{}).get('limit') for x in leaves if x['kind']=='bfifo'}
        size=spec['buffer_bytes']
        expected={'10:':size//4,'20:':3*size//4} if spec['mode']=='qos' else {'20:':size}
        if limits!=expected:raise ValueError('FIFO limits differ from protocol: '+repr(limits))
    for leaf in leaves:
        if leaf.get('parent') is not None and leaf['parent']!='1:'+leaf['handle'][:-1]:
            raise ValueError('wrong leaf parent')


def audit_classes(rows,spec):
    expected={'1:1':2000,'1:20':2000}
    if spec['mode']=='qos':expected|={'1:10':spec['rt_kbit'],'1:20':2000-spec['rt_kbit']}
    if {r['handle'] for r in rows}!=set(expected):raise ValueError('unexpected HTB class hierarchy')
    def rate(value):
        match=re.fullmatch(r'([0-9.]+)([KMG]?)bit',value)
        if not match:raise ValueError('invalid tc rate '+value)
        return float(match[1])*{'':1,'K':1000,'M':1000000,'G':1000000000}[match[2]]
    for row in rows:
        opts=row['options'];handle=row['handle']
        if rate(opts['rate'])!=expected[handle]*1000 or rate(opts['ceil'])!=2000000:
            raise ValueError('wrong class rate/ceil '+handle)
        if any(opts.get(k,'').split('/')[0]!='4Kb' for k in ('burst','cburst')):
            raise ValueError('wrong token burst '+handle)
        if handle=='1:1':
            if not row.get('root'):raise ValueError('parent class not root')
        elif row.get('parent')!='1:1' or opts.get('quantum')!='1514' or opts.get('prio')!='0':
            raise ValueError('wrong class parent/quantum/priority '+handle)


def audit_udp_errors(before,after,allow_noports=False):
    def parse(raw):
        lines=[x.split()[1:] for x in raw.splitlines() if x.startswith('Udp:')]
        if len(lines)!=2:raise ValueError('missing UDP error counters')
        return {key:int(value) for key,value in zip(*lines)}
    a,b=parse(before),parse(after)
    deltas={k:b[k]-a[k] for k in a}
    if any(deltas.get(k,0)>0 for k in ('RcvbufErrors','MemErrors','InErrors')) or (not allow_noports and deltas.get('NoPorts',0)>0):
        raise ValueError('receiver-side UDP error '+repr(deltas))
    return deltas


def audit_final_fq(rows):
    fq=next((x for x in rows if x['kind']=='fq_codel'),None)
    if fq is None:raise ValueError('missing final FQ statistics')
    if fq.get('maxpacket',0)>1514:raise ValueError('FQ saw oversized/aggregated packet')
    if fq.get('drop_overmemory',0)>0:raise ValueError('FQ memory cap confounds packet-cap treatment')


def preserve_matches(pairs):
    result={}
    for key,value in pairs:
        if key=='match':result.setdefault('matches',[]).append(value)
        else:result[key]=value
    return result


def audit_filters(rows,spec,station_ip):
    actual=[r for r in rows if r.get('options',{}).get('flowid')]
    if spec['mode']!='qos':
        if actual:raise ValueError('unexpected external classification')
        return
    import ipaddress
    ip=int(ipaddress.IPv4Address(station_ip))
    expected={1:{(0x110000,0xff0000,8),(5202<<16,0xffff0000,20),(ip,0xffffffff,16)},
              2:{(0x10000,0xff0000,8),(ip,0xffffffff,16)}}
    if len(actual)!=2:raise ValueError('missing or extra real-time filter')
    for row in actual:
        opts=row['options']
        matches={(int(x['value'],16),int(x['mask'],16),x['off']) for x in opts.get('matches',[])}
        if row.get('parent')!='1:' or opts['flowid']!='1:10' or matches!=expected.get(row['pref']):
            raise ValueError('incorrect realtime classification')


def queue_snapshot(server,interface,directory,prefix):
    for name in ('qdisc','class','filter'):
        raw=legacy.checked(server,['tc','-d','-s',name,'show','dev',interface])
        (directory/f'{prefix}-srv-{name}.txt').write_text(raw)
        js=legacy.checked(server,['tc','-j','-d','-s',name,'show','dev',interface])
        if name=='class' and not js.lstrip().startswith('['):js=json.dumps(legacy.parse_htb_classes(js))
        if name=='filter':
            (directory/f'{prefix}-srv-filter.raw.json').write_text(js)
            js=json.dumps(json.loads(js,object_pairs_hook=preserve_matches))
        (directory/f'{prefix}-srv-{name}.json').write_text(js)


def freeze_hashes():
    return {x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(SCRIPTS.glob('*.py'))}


def configure_offloads(nodes,directory):
    evidence=[]
    for node in nodes:
        for interface in node.intfList():
            name=str(interface)
            if name=='lo':continue
            before=legacy.checked(node,['ethtool','-k',name])
            attempts=[]
            for option in ['tso','gso','gro','lro']:
                out,err,code=node.pexec(['ethtool','-K',name,option,'off'])
                attempts.append({'option':option,'exit':code,'out':out,'err':err})
            after=legacy.checked(node,['ethtool','-k',name])
            if node.name=='srv':
                legacy.checked(node,['ip','link','set','dev',name,'gso_max_size','1514','gso_max_segs','1'])
            link=json.loads(legacy.checked(node,['ip','-j','-d','link','show','dev',name]))[0]
            if link['mtu']!=1500:raise ValueError('unexpected MTU '+name)
            if node.name=='srv' and (link.get('gso_max_size')!=1514 or link.get('gso_max_segs')!=1):
                raise ValueError('GSO generation limits not applied')
            for feature in ['tcp-segmentation-offload','generic-segmentation-offload','generic-receive-offload','large-receive-offload']:
                if re.search(r'^'+feature+r': on',after,re.M):raise ValueError('aggregation still enabled '+name+' '+feature)
            evidence.append(dict(node=node.name,interface=name,before=before,after=after,attempts=attempts,link=link))
    (directory/'offloads.json').write_text(json.dumps(evidence,indent=2))


def execute(spec,directory,config):
    module_spec=importlib.util.spec_from_file_location('wifi_lab_topology','/opt/wifi-lab/topology.py')
    topology=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(topology)
    from mininet.log import setLogLevel
    setLogLevel('info')
    processes=[];handles=[]
    def save_config(): (directory/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    with topology.campus_topology(2,(1,6)) as (net,aps,stations,server):
        try:
            net.start()
            for ap,ch in zip(aps,(1,6)):topology.ap_radio(ap,ch,directory)
            for i,sta in enumerate(stations):
                radio=(directory/f'ap{i+1}-iw-info.txt').read_text()
                bssid=re.search(r'\baddr ([0-9a-f:]+)',radio)[1]
                topology.wait_association(sta,bssid,directory)
                legacy.checked(sta,['ping','-n','-c','3','-W','1',server.IP()])
            interface=str(server.defaultIntf())
            config.update(server_interface=interface,server_ip=server.IP(),station_ips=[s.IP() for s in stations],
                          topology_sha256=hashlib.sha256(Path('/opt/wifi-lab/topology.py').read_bytes()).hexdigest())
            configure_offloads([server,*aps,*stations,net.get('s1')],directory)
            for node in [server,*aps,*stations]:legacy.node_snapshot(node,directory,'before')
            for node in [*aps,*stations]:
                (directory/f'{node.name}-iw-dev.txt').write_text(legacy.checked(node,['iw','dev']))
            (directory/'versions.txt').write_text(subprocess.check_output(['bash','-c',
                'uname -a; tc -V; iperf3 --version; sysctl net.ipv4.tcp_congestion_control net.ipv4.tcp_ecn'],text=True))
            def spawn(node,command,filename):
                handle=(directory/filename).open('w');handles.append(handle)
                proc=node.popen(command,stdout=handle,stderr=subprocess.STDOUT);processes.append(proc);return proc
            def start_iperf(port,tag):
                proc=spawn(server,['iperf3','-s','-1','-B',server.IP(),'-p',str(port),'-J'],f'{tag}-server.json')
                for _ in range(30):
                    if proc.poll() is not None:raise RuntimeError('iperf server exited')
                    if f':{port} ' in legacy.checked(server,['ss','-lnt']):return
                    time.sleep(.1)
                raise RuntimeError('iperf server not listening')
            if spec['workload']=='capacity':
                metrics={}
                for i,sta in enumerate(stations,1):
                    tag=f'capacity-sta{i}';start_iperf(5203,tag)
                    proc=spawn(sta,['iperf3','-4','-c',server.IP(),'-p','5203','-R','-P','1',
                               '-t',str(spec['seconds']),'-i','1','-J','--get-server-output'],tag+'-receiver.json')
                    if proc.wait(timeout=spec['seconds']+15):raise RuntimeError('capacity client failed')
                    for h in handles:h.flush()
                    metrics[tag]=legacy.interval_metrics(json.loads((directory/(tag+'-receiver.json')).read_text()),config['warmup'],spec['seconds'])
                    if metrics[tag]['received_mbps']<10:raise ValueError('physical capacity headroom insufficient')
                (directory/'metrics.json').write_text(json.dumps(metrics,indent=2));return
            commands=queue_commands(interface,spec['mode'],spec['rt_kbit'],spec['buffer_bytes'],stations[0].IP())
            (directory/'tc-commands.json').write_text(json.dumps(commands,indent=2))
            for command in commands:legacy.checked(server,command)
            queue_snapshot(server,interface,directory,'configured')
            signature=legacy.saved_queue_signature(directory,'configured')
            audit_qdisc(json.loads((directory/'configured-srv-qdisc.json').read_text()),spec)
            audit_classes(json.loads((directory/'configured-srv-class.json').read_text()),spec)
            audit_filters(json.loads((directory/'configured-srv-filter.json').read_text()),spec,stations[0].IP())
            receiver_snmp_before=legacy.checked(stations[0],['cat','/proc/net/snmp'])
            (directory/'before-sta1-snmp.txt').write_text(receiver_snmp_before)
            tcp=None;tcp_data={}
            if not spec.get('no_tcp'):
                start_iperf(5203,'tcp')
                config['tcp_start_lower_ns']=time.monotonic_ns()
                tcp=spawn(stations[1],['iperf3','-4','-c',server.IP(),'-p','5203','-R','-P','1',
                          '-t',str(spec['seconds']+4),'-i','1','-J','--get-server-output','--connect-timeout','3000'],
                          'tcp-receiver.json')
                for _ in range(30):
                    raw=legacy.checked(server,['tc','-s','class','show','dev',interface])
                    rows=legacy.parse_htb_classes(raw)
                    if any(x['handle']=='1:20' and x['bytes']>16384 for x in rows):break
                    if tcp.poll() is not None:raise RuntimeError('TCP exited before UDP')
                    time.sleep(.05)
                else:raise RuntimeError('no background TCP data')
                config['tcp_start_upper_ns']=time.monotonic_ns()
                if config['tcp_start_upper_ns']-config['tcp_start_lower_ns']>2_000_000_000:
                    raise RuntimeError('TCP start uncertainty too large')
            config['udp_start_wall_before_ns']=time.time_ns()
            config['udp_start_lower_ns']=time.monotonic_ns()
            if spec['workload']=='dynamic':
                durations=spec.get('durations',[30,30,30]);rates=spec.get('rates',[300,900,300])
                config['udp_t0_ns']=time.monotonic_ns()+1_000_000_000
                config['nonce']=secrets.randbits(64)
                common=['/usr/bin/python3',str(SCRIPTS/'udp_phase.py'),'--nonce',str(config['nonce']),
                        '--t0-ns',str(config['udp_t0_ns']),'--durations',','.join(map(str,durations)),
                        '--rates',','.join(map(str,rates))]
                receiver=spawn(stations[0],common+['receive','--bind',stations[0].IP(),
                                  '--output',str(directory/'udp-receiver.json')],'udp-receiver-process.txt')
                udp=spawn(server,common+['send','--bind',server.IP(),'--destination',stations[0].IP(),
                                  '--output',str(directory/'udp-sender.json')],'udp-sender-process.txt')
                begun=config['udp_t0_ns']/1e9
            else:
                start_iperf(5202,'udp')
                config['udp_start_lower_ns']=time.monotonic_ns()
                config['udp_start_wall_before_ns']=time.time_ns()
                udp=spawn(stations[0],['iperf3','-4','-c',server.IP(),'-p','5202','-R','-P','1',
                          '-t',str(spec['seconds']),'-i','1','-J','--get-server-output','--connect-timeout','3000',
                          '-u','-b','300k','-l','160'],'udp-receiver.json')
                receiver=None;begun=config['udp_start_lower_ns']/1e9
            save_config();ping=None;index=0;next_sample=time.monotonic()
            active=[udp]+([receiver] if receiver else [])+([tcp] if tcp else [])
            sampling=spec.get('sample',True)
            while any(p.poll() is None for p in active):
                if time.monotonic()-begun>spec['seconds']+20:raise TimeoutError('traffic timeout')
                if sampling:
                    stamp={'begin_ns':time.monotonic_ns(),'wall_ns':time.time_ns()}
                    prefix=f'sample{index:03}'
                    queue_snapshot(server,interface,directory,prefix)
                    if legacy.saved_queue_signature(directory,prefix)!=signature:raise RuntimeError('queue configuration changed')
                    legacy.resource_snapshot(directory,prefix)
                    stamp['end_ns']=time.monotonic_ns()
                    (directory/f'{prefix}-time.json').write_text(json.dumps(stamp))
                    index+=1
                if ping is None and time.monotonic()-begun>=2:
                    queue_snapshot(server,interface,directory,'before-icmp')
                    if spec['mode']=='qos':legacy.verify_udp_class(legacy.class_bytes(directory,'before-icmp'),False)
                    config['ping_start_mono_ns']=time.monotonic_ns();config['ping_start_wall_ns']=time.time_ns()
                    ping=spawn(stations[0],['ping','-n','-D','-i','0.2','-W','1',server.IP()],'ping.txt')
                    save_config()
                next_sample+=1
                time.sleep(max(0,next_sample-time.monotonic()))
            if any(p.returncode for p in active):raise RuntimeError('traffic process failed')
            if ping is None:raise RuntimeError('no probe started')
            ping.terminate();ping.wait(timeout=3)
            for handle in handles:handle.flush()
            queue_snapshot(server,interface,directory,'after')
            if legacy.saved_queue_signature(directory,'after')!=signature:raise RuntimeError('final queue changed')
            receiver_snmp_after=legacy.checked(stations[0],['cat','/proc/net/snmp'])
            (directory/'after-sta1-snmp.txt').write_text(receiver_snmp_after)
            (directory/'udp-error-deltas.json').write_text(json.dumps(audit_udp_errors(receiver_snmp_before,receiver_snmp_after,
                                                  allow_noports=spec['workload']=='static')))
            if spec['mode']=='fq_codel':audit_final_fq(json.loads((directory/'after-srv-qdisc.json').read_text()))
            if spec['mode']=='qos' and not all(legacy.class_bytes(directory,'after').get(f'1:{x}',0)>0 for x in (10,20)):
                if not spec.get('no_tcp'):raise RuntimeError('class traffic evidence missing')
            if spec['workload']=='dynamic':
                metrics=dynamic_metrics(directory,config)
            else:
                metrics={'udp':legacy.interval_metrics(json.loads((directory/'udp-receiver.json').read_text()),
                            config['warmup'],spec['seconds'],udp=True)}
                if tcp:
                    tcp_data=json.loads((directory/'tcp-receiver.json').read_text())
                    metrics['tcp']=tcp_window(tcp_data,config['tcp_start_lower_ns'],config['tcp_start_upper_ns'],
                                             config['udp_start_lower_ns'],config['warmup'],spec['seconds'])
            rtts=[];ping_sequences=[]
            for line in (directory/'ping.txt').read_text().splitlines():
                match=re.search(r'^\[(\d+\.\d+)\].*icmp_seq=(\d+).*time[=<]([\d.]+) ms',line)
                if not match:continue
                mono=config['ping_start_mono_ns']+(float(match[1])*1e9-config['ping_start_wall_ns'])
                t=(mono-(config.get('udp_t0_ns',config['udp_start_lower_ns'])))/1e9
                if config['warmup']<=t<spec['seconds']:
                    rtts.append(float(match[3]));ping_sequences.append(int(match[2]))
            if not rtts:raise ValueError('no valid RTT samples')
            metrics['rtt']={'mean_ms':statistics.mean(rtts),'p95_ms':sorted(rtts)[math.ceil(.95*len(rtts))-1],
                            'successful_samples':len(rtts),'interior_sequence_gaps':max(ping_sequences)-min(ping_sequences)+1-len(set(ping_sequences))}
            (directory/'metrics.json').write_text(json.dumps(metrics,indent=2)+'\n')
            for node in [server,*aps,*stations]:legacy.node_snapshot(node,directory,'after')
            for node in [server,stations[0]]:
                (directory/f'after-{node.name}-snmp.txt').write_text(legacy.checked(node,['cat','/proc/net/snmp']))
        finally:
            legacy.stop_processes(processes)
            for handle in handles:handle.close()


def run_spec(spec,root,kind='formal'):
    root=Path(root);directory=root/'runs'/spec['id']
    directory.mkdir(parents=True,exist_ok=False);directory.chmod(0o2750)
    config=spec|{'kind':kind,'protocol_version':'1.1','warmup':spec.get('warmup',10),
                 'started_utc':datetime.now(timezone.utc).isoformat(),'source_hashes':freeze_hashes()}
    (directory/'config.json').write_text(json.dumps(config,indent=2))
    (directory/'status.txt').write_text('RUNNING\n')
    saved=[os.dup(1),os.dup(2)];previous=Path.cwd()
    try:
        with (directory/'run.log').open('w',buffering=1) as log:
            os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
            try:
                with tempfile.TemporaryDirectory(prefix='wifi-expc-v11-') as work:
                    os.chdir(work)
                    execute(spec,directory,config)
            except BaseException:
                (directory/'status.txt').write_text('INVALID\n');traceback.print_exc();raise
            else:(directory/'status.txt').write_text('PASS\n')
            finally:os.chdir(previous)
    finally:
        for fd,saved_fd in enumerate(saved,1):os.dup2(saved_fd,fd);os.close(saved_fd)
    return str(directory)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--kind',default='pilot')
    parser.add_argument('--lock-fd',type=int)
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('root required for isolated network experiment')
    def stop(signum,frame):raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,stop)
    if args.lock_fd is not None:
        actual=os.fstat(args.lock_fd);expected=os.stat('/var/lib/wifi-lab/run.lock')
        if (actual.st_dev,actual.st_ino)!=(expected.st_dev,expected.st_ino):raise ValueError('invalid inherited lock')
        fcntl.flock(args.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        print(run_spec(json.loads(args.spec.read_text()),args.root,args.kind),flush=True)
        return
    with open('/var/lib/wifi-lab/run.lock','r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        print(run_spec(json.loads(args.spec.read_text()),args.root,args.kind),flush=True)


if __name__=='__main__':main()
