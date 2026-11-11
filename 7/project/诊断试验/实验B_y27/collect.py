"""03 号在已启动的公共拓扑内调用 collect(sta1, [ap1, ap2], out)。"""
import csv
import json
import math
import re
import subprocess
import time
from contextlib import ExitStack
from pathlib import Path


def route(t):
    return (15 + min(max(t - 10, 0), 55), 27, 0)


def collect(sta, aps, out):
    """调用前启动背景流量、启用策略。out 为本轮新建的采集子目录。"""
    out = Path(out)
    out.mkdir(exist_ok=False)
    origin = time.monotonic()
    epoch = time.time()
    (out / 'clock.json').write_text(json.dumps(dict(monotonic=origin, epoch=epoch)))
    with ExitStack() as stack:
        def file(name):
            return stack.enter_context((out / name).open('w', buffering=1))
        raw = file('iw.jsonl')
        rows = csv.writer(file('samples.csv'))
        rows.writerow(['start_s', 'end_s', 'x_m', 'y_m', 'bssid', 'signal_dBm',
                       'ap1_count', 'ap2_count'])
        def iw(node, *args):
            p = node.popen(['iw', 'dev', *args], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
            data = p.communicate(timeout=3)[0].decode(errors='replace')
            raw.write(json.dumps(dict(t=time.monotonic()-origin, node=node.name,
                                      args=args, rc=p.returncode, output=data))+'\n')
            if p.returncode:
                raise RuntimeError(f'iw failed on {node.name}, see iw.jsonl')
            return data
        for ap in aps:
            iw(ap, ap.params['wlan'][0], 'info')
        ping = sta.popen(['env', 'LC_ALL=C', 'ping', '-n', '-D', '-O', '-i', '0.2',
                          '-W', '1', '-c', '375', '10.44.0.100'],
                         stdout=file('ping.txt'), stderr=subprocess.STDOUT)
        try:
            tick = 0
            while tick < 375:
                t = time.monotonic()-origin
                x, y, z = route(t)
                sta.setPosition(f'{x},{y},{z}')
                link = iw(sta, sta.params['wlan'][0], 'link')
                bssid = re.search(r'Connected to ([\da-f:]+)', link, re.I)
                signal = re.search(r'signal:\s*([-\d.]+)', link)
                counts = [len(re.findall(r'^Station ', iw(ap, ap.params['wlan'][0],
                          'station', 'dump'), re.M)) for ap in aps]
                rows.writerow([t, time.monotonic()-origin, x, y,
                               bssid[1] if bssid else '', signal[1] if signal else '', *counts])
                tick = max(tick+1, math.ceil((time.monotonic()-origin)*5))
                time.sleep(max(0, origin+tick/5-time.monotonic()))
            if ping.wait(timeout=4) != 0:
                raise RuntimeError('探测失败，检查 ping.txt')
        finally:
            if ping.poll() is None:
                ping.kill()
                ping.wait()


if __name__ == '__main__':
    # 仅验证给定覆盖半径下的路线几何，不启动无线网络。
    samples = [(i/5, route(i/5)[0]) for i in range(375)]
    overlap = [t for t, x in samples if abs(x-15)<=36 and abs(x-70)<=36]
    assert samples[0][1] == 15 and samples[-1][1] == 70
    assert overlap[0] == 29 and overlap[-1] == 46
    print(f'路线预检通过：{len(samples)} 个计划采样点，理论重叠区 {overlap[0]}–{overlap[-1]} s')
