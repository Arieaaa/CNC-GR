"""为每个实测轮次输出可直接查看的 SVG。"""
import csv
import json
import re
import sys
from pathlib import Path


def plot(run):
    obs=run/'observations'
    rows=list(csv.DictReader((obs/'samples.csv').open()))
    cfg=json.loads((run/'config.json').read_text())
    t0=json.loads((obs/'clock.json').read_text())['epoch']
    points=[(float(t)-t0,float(rtt)) for t,rtt in re.findall(
        r'^\[([\d.]+)\] \d+ bytes from .*?time=([\d.]+) ms',(obs/'ping.txt').read_text(),re.M)]
    bssids=[re.search(r'\baddr ([\da-f:]+)',(run/f'ap{i}-iw-info.txt').read_text())[1] for i in (1,2)]
    def x(t): return 90+10*t
    ceiling=max(1,max(rtt for _,rtt in points))
    svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 920 315" font-family="sans-serif" font-size="14">',
         '<rect width="920" height="315" fill="white"/>',
         f'<text x="40" y="30" font-size="21">实验 B · {cfg["policy"].upper()} · {cfg["phase"]} {cfg["repeat"]}</text>']
    for t in range(0,76,5):
        svg.append(f'<path d="M{x(t)} 50V260" stroke="#eee"/><text x="{x(t)-5}" y="282">{t}</text>')
    for i,label in enumerate(['AP1','AP2','无关联']):
        y=65+25*i
        svg.append(f'<text x="20" y="{y+4}">{label}</text>')
    for row in rows:
        idx=bssids.index(row['bssid']) if row['bssid'] in bssids else 2
        svg.append(f'<circle cx="{x(float(row["start_s"])):.2f}" cy="{65+25*idx}" r="1.5" fill="#18697d"/>')
    for t,rtt in points:
        svg.append(f'<circle cx="{x(t):.2f}" cy="{255-90*rtt/ceiling:.2f}" r="1.7" fill="#ab4f22"/>')
    svg.extend([f'<text x="12" y="160">{ceiling:.1f} ms</text>', '<text x="20" y="258">0 ms</text>',
                '<text x="90" y="145">成功回包 RTT</text><text x="390" y="305">采集开始后的时间（秒）</text></svg>'])
    (run/'timeline.svg').write_text('\n'.join(svg))


if __name__=='__main__':
    for run in Path(sys.argv[1]).glob('expB_*'):
        if (run/'status.txt').read_text().strip()=='COLLECTED':
            plot(run)
