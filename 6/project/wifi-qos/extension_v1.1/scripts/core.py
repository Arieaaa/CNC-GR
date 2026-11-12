"""Frozen experiment definitions and offline packet accounting. Standard library only."""
import math
import random
import re
import statistics
import struct

HEADER = struct.Struct('!4sBBHQQQ')


def queue_commands(interface, mode, rt_kbit, buffer_bytes, station_ip):
    if not re.fullmatch(r'srv-eth\d+', interface):
        raise ValueError('only simulated server interfaces are allowed')
    if mode not in ('baseline','qos','fq_codel') or not 0 < rt_kbit < 2000:
        raise ValueError('invalid mode or guarantee')
    if buffer_bytes not in (16384,32768,65536):
        raise ValueError('invalid buffer level')
    commands = [
        ['tc','qdisc','replace','dev',interface,'root','handle','1:','htb','default','20'],
        ['tc','class','add','dev',interface,'parent','1:','classid','1:1','htb',
         'rate','2000kbit','ceil','2000kbit','burst','4096','cburst','4096']]
    def leaf(minor, rate, size, fq=False):
        commands.append(['tc','class','add','dev',interface,'parent','1:1','classid',f'1:{minor}',
                         'htb','rate',f'{rate}kbit','ceil','2000kbit','burst','4096','cburst','4096',
                         'prio','0','quantum','1514'])
        command=['tc','qdisc','add','dev',interface,'parent',f'1:{minor}','handle',f'{minor}:']
        if fq:
            command+=['fq_codel','limit',str({16384:11,32768:22,65536:44}[size]),
                      'flows','1024','quantum','1514','target','10ms','interval','100ms',
                      'noecn','memory_limit','1048576']
        else:
            command+=['bfifo','limit',str(size)]
        commands.append(command)
    if mode=='qos':
        leaf(10,rt_kbit,buffer_bytes//4)
        leaf(20,2000-rt_kbit,buffer_bytes*3//4)
        base=['tc','filter','add','dev',interface,'protocol','ip','parent','1:','prio']
        commands.append(base+['1','u32','match','ip','protocol','17','0xff','match','ip','sport','5202','0xffff',
                              'match','ip','dst',station_ip+'/32','flowid','1:10'])
        commands.append(base+['2','u32','match','ip','protocol','1','0xff',
                              'match','ip','dst',station_ip+'/32','flowid','1:10'])
    else:
        leaf(20,2000,buffer_bytes,mode=='fq_codel')
    return commands


def encode_packet(nonce, phase, seq, send_ns):
    return HEADER.pack(b'WQ11',1,phase,0,nonce,seq,send_ns)+bytes(160-HEADER.size)


def decode_packet(data, nonce):
    if len(data)!=160:
        raise ValueError('invalid packet size')
    magic,version,phase,reserved,actual,seq,stamp=HEADER.unpack(data[:HEADER.size])
    if magic!=b'WQ11' or version!=1 or reserved or actual!=nonce or phase>2:
        raise ValueError('invalid packet header or run nonce')
    return phase,seq,stamp


def phase_at(seconds, durations):
    end=0
    for i,duration in enumerate(durations):
        end+=duration
        if seconds<end:
            return i
    return None


def percentile(values, q):
    return sorted(values)[max(0,math.ceil(q*len(values))-1)] if values else None


def packet_metrics(sent, received, start, end, t0_ns, deadline_ms=50):
    selected=[x for x in sent if start <= (x['send_ns']-t0_ns)/1e9 < end]
    tx={x['seq']:x for x in selected if x['ok']}
    if len(tx)!=sum(x['ok'] for x in selected):
        raise ValueError('duplicate transmit sequence')
    rx={}; duplicates=0; reordered=0; highest=-1
    for x in received:
        seq=x['seq']
        if seq not in tx:
            continue
        if seq in rx:
            duplicates+=1
            continue
        if seq<highest:
            reordered+=1
        highest=max(highest,seq)
        rx[seq]=x
    delays=[(rx[k]['recv_ns']-v['send_ns'])/1e6 for k,v in tx.items() if k in rx]
    if any(x<0 for x in delays):
        raise ValueError('negative latency: clock not trustworthy')
    count=len(tx)
    return {'start':start,'end':end,'sent_packets':count,'received_packets':len(rx),
            'send_errors':sum(not x['ok'] for x in selected), 'duplicates':duplicates,'reordered':reordered,
            'loss_percent':100*(count-len(rx))/count if count else None,
            'on_time_percent':100*sum(x<=deadline_ms for x in delays)/count if count else None,
            'received_mbps':len(rx)*160*8/(end-start)/1e6,
            'sent_mbps':count*160*8/(end-start)/1e6,
            'delay_p50_ms':percentile(delays,.5),'delay_p95_ms':percentile(delays,.95),
            'delay_max_ms':max(delays) if delays else None,
            'delay_mean_ms':statistics.mean(delays) if delays else None}


def build_manifest(seed=20261111):
    rng=random.Random(seed); runs=[]
    def add(exp, mode, rt, buf, workload, repeat):
        runs.append(dict(id=f'{exp}_{mode}_r{rt}_b{buf}_{workload}_n{repeat}',
                         experiment=exp,mode=mode,rt_kbit=rt,buffer_bytes=buf,workload=workload,
                         repeat=repeat,seconds=90 if workload=='dynamic' else 60))
    for repeat,order in enumerate([['baseline','qos','fq_codel'],['qos','fq_codel','baseline'],
                                   ['fq_codel','baseline','qos']],1):
        for mode in order: add('E1',mode,600,32768,'static',repeat)
    for repeat in range(1,4):
        rates=[200,400,1000];rng.shuffle(rates)
        for rt in rates:add('E2','qos',rt,32768,'static',repeat)
    for repeat in range(1,4):
        configs=[('baseline',600),('qos',600),('qos',1200),('fq_codel',600)];rng.shuffle(configs)
        for mode,rt in configs:add('E3',mode,rt,32768,'dynamic',repeat)
    for repeat in range(1,4):
        configs=[(mode,buf) for mode in ['baseline','qos','fq_codel'] for buf in [16384,65536]]
        rng.shuffle(configs)
        for mode,buf in configs:add('E4',mode,600,buf,'static',repeat)
    return runs
