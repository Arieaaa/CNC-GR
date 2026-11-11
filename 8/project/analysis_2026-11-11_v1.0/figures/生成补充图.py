"""Draw formal A/B/C figures and separate C diagnostic figures."""
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent
FORMAL = ROOT.parent / 'inputs' / 'formal_run_metrics.csv'
DIAG = ROOT.parent / 'inputs' / 'C交错复测_20261111.csv'
FONT = Path('C:/Windows/Fonts/msyh.ttc')
font_manager.fontManager.addfont(str(FONT))
plt.rcParams.update({'font.family': font_manager.FontProperties(fname=str(FONT)).get_name(),
                     'axes.unicode_minus':False, 'font.size':15, 'savefig.facecolor':'white'})
NAVY='#16324a'; BLUE='#436b96'; TEAL='#087f79'; GREY='#5a7084'
CONFIGS=['A_n04_ch1-6','A_n08_ch1-6','A_n12_ch1-6','A_n12_ch1-1']
XLABS=['4 台\n1/6','8 台\n1/6','12 台\n1/6','12 台\n1/1']

with FORMAL.open(encoding='utf-8-sig', newline='') as f: FORMAL_ROWS=list(csv.DictReader(f))
with DIAG.open(encoding='utf-8-sig', newline='') as f: DIAG_ROWS=list(csv.DictReader(f))
assert len(DIAG_ROWS)==6
for row in DIAG_ROWS:
    assert math.isclose(float(row['udp_loss_pct']),100*int(row['udp_lost'])/int(row['udp_packets']),abs_tol=1e-12)

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def configure(ax, title, ylabel, labs):
    ax.set_title(title, loc='left',fontsize=18,fontweight='bold',color=NAVY,pad=15)
    ax.set_ylabel(ylabel,fontsize=15,color=GREY)
    ax.set_xticks(range(len(labs)),labs,fontsize=14,color=NAVY)
    ax.grid(axis='y',color='#dbe7ee',linewidth=.8)
    ax.set_axisbelow(True)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(axis='both',length=0,pad=8,labelcolor=GREY)

def points(ax, groups, labs, title, unit, fmt):
    configure(ax,title,unit,labs)
    maxval=max(max(v) for v in groups)
    top=max(max(v)+statistics.stdev(v) for v in groups)
    scale=top or 1.0
    ax.set_ylim(-scale*.08, scale*1.38)
    for i,vals in enumerate(groups):
        assert len(vals)==3
        color=BLUE if i%2==0 else TEAL
        mu,sd=statistics.mean(vals),statistics.stdev(vals)
        ax.scatter([i-.16,i,i+.16],vals,s=54,c=color,alpha=.55,zorder=3)
        ax.errorbar(i,mu,yerr=sd,fmt='D',markersize=8,elinewidth=2,
                    capsize=5,color=color,zorder=4)
        ax.text(i,mu+sd+scale*.055,format(mu,fmt),ha='center',fontsize=12,
                fontweight='bold',color=NAVY)
    ax.margins(x=.15)

def formal(metric):
    grouped=[]
    for config in CONFIGS:
        rows=[x for x in FORMAL_ROWS if x['experiment']=='A' and x['config_id']==config and x['metric_id']==metric]
        assert len(rows)==3 and {x['repeat'] for x in rows}=={'1','2','3'}, (config,metric)
        grouped.append([float(x['value']) for x in sorted(rows,key=lambda y:y['repeat'])])
    return grouped

def a_figure(filename,title,panels):
    fig,axes=plt.subplots(1,3,figsize=(16,9))
    fig.subplots_adjust(left=.075,right=.975,top=.76,bottom=.25,wspace=.45)
    fig.text(.065,.93,title,fontsize=29,fontweight='bold',color=NAVY)
    fig.text(.065,.875,'正式样本：每配置 3 轮（n=3）',fontsize=17,color=GREY)
    for ax,(key,caption,unit,fmt) in zip(axes,panels):
        points(ax,formal(key),XLABS,caption,unit,fmt)
    fig.text(.065,.16,'圆点：每轮数据   菱形及误差线：均值 ± 样本标准差',fontsize=14,color=GREY)
    fig.text(.065,.115,'TCP/UDP 各预热 10 秒后统计 60 秒；ping 约 60 秒且不剔除预热。',fontsize=13,color=GREY)
    fig.text(.065,.075,'TCP+ping 与 UDP 分轮；TCP 为各终端接收吞吐之和，各流窗口未严格对齐。来源：4 号正式汇总。',fontsize=13,color=GREY)
    fig.savefig(ROOT/filename,dpi=180);plt.close(fig)

a_figure('A_正式_TCP与RTT.png','A  正式实验：并发与信道',[
    ('tcp_total','各终端 TCP 接收吞吐之和','Mbit/s','.3f'),
    ('tcp_station_avg','单终端平均 TCP 吞吐','Mbit/s','.3f'),
    ('rtt_p95_station_max','各终端 P95 RTT 的最大值','ms','.2f')])
a_figure('A_正式_UDP丢包与抖动.png','A  正式实验：UDP 丢包与抖动',[
    ('udp_loss_station_mean','各终端 UDP 丢包率的平均值','%','.3f'),
    ('udp_loss_station_max','各终端 UDP 丢包率的最大值','%','.3f'),
    ('udp_jitter_station_max','各终端 UDP 抖动的最大值','ms','.3f')])

def diagvals(mode,key):
    rows=[x for x in DIAG_ROWS if x['mode']==mode]
    assert len(rows)==3 and {x['repeat_diagnostic'] for x in rows}=={'91','92','93'}
    return [float(r[key]) for r in sorted(rows,key=lambda r:r['repeat_diagnostic'])]

fig,axes=plt.subplots(1,2,figsize=(16,9))
fig.subplots_adjust(left=.09,right=.96,top=.75,bottom=.28,wspace=.37)
fig.text(.065,.93,'C  额外交错诊断：实时 UDP 与全业务队列',fontsize=27,fontweight='bold',color=NAVY)
fig.text(.065,.875,'2 Mbit/s 出口，300 kbit/s UDP 与后台 TCP；每方案 3 轮（n=3）',fontsize=17,color=GREY)
labs=['共享 FIFO','分类 QoS']
points(axes[0],[diagvals('baseline','udp_loss_pct'),diagvals('qos','udp_loss_pct')],labs,'实时 UDP 丢包率','%', '.3f')
points(axes[1],[diagvals('baseline','queue_drops_all_traffic'),diagvals('qos','queue_drops_all_traffic')],labs,'队列累计丢包（全部业务）','包', '.1f')
fig.text(.065,.19,'圆点：每轮数据   菱形及误差线：均值 ± 样本标准差',fontsize=14,color=GREY)
fig.text(.065,.145,'UDP 使用接收端后 50 秒；队列计数覆盖整轮、所有业务，不能与 UDP 丢包数直接相加或等同。',fontsize=13,color=GREY)
fig.text(.065,.10,'这 6 轮是额外诊断，不并入 24 轮正式统计。来源：7 号 C 交错复测。',fontsize=13,color=GREY)
fig.savefig(ROOT/'C_交错诊断_实时UDP与队列.png',dpi=180);plt.close(fig)

def formal_other(experiment, configs, metric, scale=1):
    result=[]
    for config in configs:
        rows=[x for x in FORMAL_ROWS if x['experiment']==experiment and x['config_id']==config and x['metric_id']==metric]
        assert len(rows)==3 and {x['repeat'] for x in rows}=={'1','2','3'}, (config,metric)
        result.append([float(x['value'])*scale for x in sorted(rows,key=lambda y:y['repeat'])])
    return result

def quad(filename,title,subtitle,experiment,configs,labs,panels,foot1,foot2):
    fig,axes=plt.subplots(2,2,figsize=(16,9))
    fig.subplots_adjust(left=.075,right=.97,top=.76,bottom=.23,hspace=.65,wspace=.3)
    fig.text(.065,.94,title,fontsize=27,fontweight='bold',color=NAVY)
    fig.text(.065,.885,subtitle,fontsize=15,color=GREY)
    for ax,(key,caption,unit,fmt,scale) in zip(axes.flat,panels):
        points(ax,formal_other(experiment,configs,key,scale),labs,caption,unit,fmt)
    fig.text(.065,.14,'每配置 n=3；圆点为每轮数据，菱形及误差线为均值 ± 样本标准差。',fontsize=13,color=GREY)
    fig.text(.065,.10,foot1,fontsize=12,color=GREY)
    fig.text(.065,.06,foot2,fontsize=12,color=GREY)
    fig.savefig(ROOT/filename,dpi=180);plt.close(fig)

quad('B_移动与关联.png','B  正式实验：移动过程与关联',
     '路线 15 至 70 m、1 m/s；信道 1/6；3 条 256 kbit/s UDP 背景流',
     'B',['B_ssf','B_llf'],['SSF','LLF'],[
     ('ap2_first_x','首次观测 AP2 的 X 坐标','m','.2f',1),
     ('event_reply_gap','切换附近最大相邻成功回包间隔','s','.2f',.001),
     ('rtt_p95','全轮成功应答 P95 RTT','ms','.3f',1),
     ('ping_loss','全轮探测丢失率','%','.3f',1)],
     '回包间隔包含正常探测周期，并非协议层切换耗时；P95 仅含成功应答。',
     '原路线存在信号正值异常；偏移路线试跑另列。数据：5 号正式汇总。')
quad('C_混合业务与QoS.png','C  正式实验：实时 UDP 与后台 TCP',
     '服务器出口 2 Mbit/s；300 kbit/s UDP + 后台 TCP；每轮 60 秒取后 50 秒',
     'C',['C_baseline','C_qos'],['共享 FIFO','分类 HTB'],[
     ('udp_loss','实时 UDP 丢包率','%','.3f',1),
     ('udp_jitter','UDP 逐秒抖动的时间均值','ms','.3f',1),
     ('rtt_p95','成功应答 P95 RTT','ms','.3f',1),
     ('tcp_received','后台 TCP 接收吞吐','Mbit/s','.4f',1)],
     'P95 仅含成功应答；UDP 业务丢包和 ping 探测缺失分开记录。',
     '样本来自服务器出口队列与合成业务；数据：6 号正式汇总。')

meta={'formal_table_sha256':digest(FORMAL),'diagnostic_input_sha256':digest(DIAG),
      'diagnostic_source_git_blob_sha1':'bd094cc04fe9d4c00813670d83bd9fa991392289',
      'diagnostic_source':'https://github.com/Arieaaa/CNC-GR/blob/65e4e94f447a485de9c8217b094fe414d74cab06/7/project/诊断试验/C交错复测_20261111.csv',
      'formal_plot_source':'../inputs/formal_run_metrics.csv',
      'note':'使用正式逐轮指标与 7 号诊断输入；图中 A 窗口按 12 个 config 核对。'}
(ROOT/'图表来源校验.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
print('PASS: 5 figures, 4 A configurations x 3 repeats, 6 diagnostic runs.')
