# 9号成员｜系统集成与演示

此目录包含演示运行工具、手工实验手册、实机记录、关键截图和离线演示视频。最终PPT与逐页讲稿位于同级 `../ppt/`。

## 快速开始

Windows PowerShell，Python 3.10+

```powershell
cd 9/project
python -m pip install -r requirements.txt
python demo.py verify
python demo.py browse
python demo.py check
python demo.py run
```

`check`读取账号权限、实验平台版本和最近运行目录；`run`调用已授权的双终端、信道1/6固定入口；`collect --run <目录名>`下载指定运行日志；`browse`生成离线证据浏览页；`verify`按SHA256清单校验交付文件。SSH密码仅在终端提示时输入，不写入配置或记录。主机指纹变化时先向平台负责人核对。

详细手工步骤和预期输出见[实验全流程手册](手工实验全流程手册_v1.0_20261111.md)。四分钟录屏和六张关键帧见 `media/`；实机逐轮日志见 `evidence/`。

## 实测记录

wifi09账号已在实验机完成双AP基础验收，运行记录分别位于：

- `evidence/smoke_20261111T043303Z_gt1112v7/`
- `evidence/smoke_20261111T062720Z_3e2b4ph6/`

两轮运行均保存配置、版本、关联、ping与iperf3原始记录。基础验收使用两个终端、信道1和6；iperf3对每个终端顺序运行约3秒。A/B/C正式实验的脚本与统计记录由对应成员维护，本目录中的上游镜像仅供检索，不纳入本次交付。

## 汇报播放

在PowerPoint打开 `../ppt/校园无线网络_系统集成与演示.pptx`，选择“幻灯片放映 → 使用演示者视图”；可按 `Alt+F5` 在当前窗口预览演讲者视图。逐页讲稿同时放在 `../ppt/逐页讲稿_11分钟.md`，PPT每页备注含相同讲稿与建议时长。

## 项目文件

- `demo.py`：统一运行与证据管理入口。
- `config.example.json`：实验机地址、用户和主机指纹，不含密码。
- `手工实验全流程手册_v1.0_20261111.md`：命令、预期输出与故障处理。
- `操作稿与彩排.md`：4分钟演示节奏及11分钟讲述安排。
- `evidence/`：实机原始日志与源版本信息。
- `media/`：实际录屏、关键截图和媒体校验记录。
- `index.html`：离线证据目录页面，可由`python demo.py browse`重新生成。
- `manifest.json`：交付文件SHA256完整性清单。

