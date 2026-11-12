#!/usr/bin/env python3
"""Single five-tuple, timestamped UDP phase sender/receiver."""
import argparse
import json
import os
from pathlib import Path
import socket
import struct
import time

from core import decode_packet, encode_packet, percentile


def environment():
    return {'pid':os.getpid(),'time_namespace':os.readlink('/proc/self/ns/time') if Path('/proc/self/ns/time').exists() else None,
            'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip() if Path('/proc/sys/kernel/random/boot_id').exists() else None}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('role',choices=['send','receive'])
    p.add_argument('--bind',required=True);p.add_argument('--destination')
    p.add_argument('--port',type=int,default=5202);p.add_argument('--source-port',type=int,default=5202)
    p.add_argument('--nonce',type=int,required=True);p.add_argument('--t0-ns',type=int,required=True)
    p.add_argument('--durations',default='30,30,30');p.add_argument('--rates',default='300,900,300')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();durations=[float(x) for x in a.durations.split(',')];rates=[float(x) for x in a.rates.split(',')]
    if len(durations)!=3 or len(rates)!=3 or min(durations+rates)<=0:raise ValueError('invalid phase schedule')
    output={'role':a.role,'nonce':a.nonce,'t0_ns':a.t0_ns,'durations':durations,'rates_kbit':rates,
            'payload_bytes':160,'environment':environment(),'events':[]}
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        if a.role=='send':
            sock.bind((a.bind,a.source_port));sock.setblocking(False)
            phase_start=a.t0_ns;seq=0
            for phase,(duration,rate) in enumerate(zip(durations,rates)):
                spacing=160*8*1e6/rate
                count=0;phase_end=phase_start+round(duration*1e9)
                while True:
                    due=phase_start+round(count*spacing)
                    if due>=phase_end:break
                    delay=(due-time.monotonic_ns())/1e9
                    if delay>0:time.sleep(delay)
                    now=time.monotonic_ns();error=None;ok=False
                    if now-due>spacing:
                        error='schedule_miss'
                    else:
                        try:
                            sock.sendto(encode_packet(a.nonce,phase,seq,now),(a.destination,a.port));ok=True
                        except OSError as exc:
                            error=f'{exc.errno}:{exc.strerror}'
                    output['events'].append(dict(seq=seq,phase=phase,send_ns=now,scheduled_ns=due,
                                                 lateness_ns=now-due,spacing_ns=spacing,ok=ok,error=error))
                    seq+=1;count+=1
                phase_start=phase_end
            output['pacing']={'p99_lateness_ms':percentile([x['lateness_ns']/1e6 for x in output['events']],.99),
                              'missed_or_errors':sum(not x['ok'] for x in output['events'])}
        else:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,1024*1024)
            if hasattr(socket,'MSG_CTRUNC') and os.name=='posix' and Path('/proc').exists():
                sock.setsockopt(socket.SOL_SOCKET,40,1)  # Linux SO_RXQ_OVFL
            sock.bind((a.bind,a.port));sock.settimeout(.2)
            output.update(malformed=0,socket_drops=0,rcvbuf=sock.getsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF))
            end=a.t0_ns+round((sum(durations)+2)*1e9)
            while time.monotonic_ns()<end:
                try:
                    data,ancillary,flags,source=sock.recvmsg(2048,128)
                except socket.timeout:continue
                now=time.monotonic_ns()
                for level,kind,value in ancillary:
                    if level==socket.SOL_SOCKET and kind==40:
                        output['socket_drops']=max(output['socket_drops'],struct.unpack('I',value[:4])[0])
                try:
                    phase,seq,stamp=decode_packet(data,a.nonce)
                except ValueError:
                    output['malformed']+=1;continue
                output['events'].append(dict(seq=seq,phase=phase,send_ns=stamp,recv_ns=now,
                                             source=f'{source[0]}:{source[1]}'))
    a.output.write_text(json.dumps(output,separators=(',',':'))+'\n')


if __name__=='__main__':main()
