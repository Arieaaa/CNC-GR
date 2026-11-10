"""运行一轮 B。启动者须先取得公共 run.lock。"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
import traceback
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from collect import collect

sys.path.insert(0, '/opt/wifi-lab')
from topology import campus_topology, ap_radio, wait_association, SERVER_IP, RUNS
import mn_wifi.mobility as mobility


def run(policy, repeat, phase):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = Path(tempfile.mkdtemp(prefix=f'expB_{phase}_{policy}_{repeat}_{stamp}_', dir=RUNS))
    print(out, flush=True)
    positions = ['15,25,0', '14,24,0', '15,26,0', '16,24,0']
    config = dict(policy=policy, repeat=repeat, phase=phase, utc=stamp, stations=4,
                  positions=positions, channels=[1, 6], background_kbps_each=256,
                  udp_payload_bytes=512, direction='sta2-4 to srv', ports=[5202,5203,5204],
                  duration_s=75, probe_period_s=0.2, probe_timeout_s=1,
                  route='sta1: x=15+min(max(t-10,0),55), y=25, z=0', operator='wifi05')
    for name in ['run_b.py', 'collect.py']:
        src = Path(__file__).with_name(name)
        config[name+'_sha256'] = hashlib.sha256(src.read_bytes()).hexdigest()
        shutil.copyfile(src, out/name)
    (out/'config.json').write_text(json.dumps(config, indent=2))
    shutil.copyfile('/opt/wifi-lab/source-versions.txt', out/'source-versions.txt')
    status = out/'status.txt'
    status.write_text('RUNNING\n')
    try:
        with campus_topology(4, (1,6)) as (net, aps, stations, srv), ExitStack() as stack:
            original = mobility.AssCtrl
            decisions = stack.enter_context((out/'decisions.jsonl').open('w', buffering=1))
            def trace(intf, ap, ac):
                before = getattr(intf.associatedTo, 'name', None)
                result = original(intf, ap, ac)
                decisions.write(json.dumps(dict(t=time.monotonic(), sta=intf.name,
                    current=before, candidate=ap.name, policy=ac, change=result.changeAP))+'\n')
                return result
            mobility.AssCtrl = trace
            stack.callback(setattr, mobility, 'AssCtrl', original)
            net.start()
            for sta, pos in zip(stations, positions):
                sta.setPosition(pos)
            radios = [ap_radio(ap, ch, out) for ap,ch in zip(aps,(1,6))]
            for sta in stations:
                wait_association(sta, radios[0], out)
            # Keep selection in Mininet-WiFi. Execute its chosen association
            # synchronously and check kernel results on the moving interface.
            mobile = stations[0].wintfs[0]
            def connect_chosen(ap):
                i = aps.index(ap.node)
                freq = ('2412', '2437')[i]
                sta = stations[0]
                radio = sta.params['wlan'][0]
                link = sta.pexec(['iw','dev',radio,'link'])[0].lower()
                if f'connected to {radios[i]}' not in link:
                    if 'connected to ' in link:
                        sta.pexec(['iw','dev',radio,'disconnect'])
                    cmd = ['timeout','5','iw','dev',radio,'connect','-w',
                           ap.ssid,freq,radios[i]]
                    stdout, stderr, rc = sta.pexec(cmd)
                    with (out/'kernel-connect.jsonl').open('a') as f:
                        f.write(json.dumps(dict(t=time.monotonic(),args=cmd,
                            stdout=stdout,stderr=stderr,rc=rc))+'\n')
                    if rc:
                        raise RuntimeError(f'kernel association failed: {stderr}')
                mobile.setConnected(ap)
            mobile.iw_connect = connect_chosen
            mobility.Mobility.ac = policy
            def spawn(node, args, filename):
                log = stack.enter_context((out/filename).open('w'))
                proc = node.popen(args, stdout=log, stderr=-2)
                def stop():
                    if proc.poll() is None:
                        proc.kill()
                    proc.wait()
                stack.callback(stop)
                return proc
            for port in config['ports']:
                spawn(srv, ['iperf3','-s','-1','-B',SERVER_IP,'-p',str(port),'-J'], f'srv-{port}.json')
            time.sleep(0.5)
            clients = []
            for sta, port in zip(stations[1:],config['ports']):
                clients.append(spawn(sta,['iperf3','-c',SERVER_IP,'-p',str(port),'-u',
                    '-b','256K','-l','512','-t','85','-J'], f'{sta.name}.json'))
            time.sleep(2)
            if any(p.poll() is not None for p in clients):
                raise RuntimeError('背景流启动失败')
            collect(stations[0], aps, out/'observations')
            for proc, sta in zip(clients, stations[1:]):
                if proc.wait(timeout=20) or not json.loads((out/f'{sta.name}.json').read_text())['end']['sum_received']['bytes']:
                    raise RuntimeError('背景流无接收数据')
        status.write_text('COLLECTED\n')
    except BaseException:
        (out/'error.txt').write_text(traceback.format_exc())
        status.write_text('FAIL\n')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('policy', choices=['ssf','llf'])
    parser.add_argument('repeat', type=int)
    parser.add_argument('phase', choices=['pilot','formal'])
    args = parser.parse_args()
    run(args.policy, args.repeat, args.phase)
