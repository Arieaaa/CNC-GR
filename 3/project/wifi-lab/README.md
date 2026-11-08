# 校园 Wi-Fi 共享实验平台

3 号维护一台专用 Ubuntu 虚拟机。其他成员通过各自的 SSH 公钥登录。基础验收入口一次只运行一组，每次生成独立日志目录。

## 选实验机

| 路线 | 做法 |
| --- | --- |
| 学校或实验室虚拟机 | 优先问老师能否提供带 sudo 的专用 Ubuntu 虚拟机。请同学从宿舍网试一次 SSH，校外可走学校提供的 VPN。 |
| Mac 本地虚拟机 | Apple 芯片选 UTM 的 **Virtualize → Linux**，装 Ubuntu Server 24.04 LTS **ARM64**，网卡选共享网络。Mac 开机且虚拟机运行时可用。 |
| 国内免费试用 | 先查腾讯云轻量的 2 核 4 GB 一个月试用，或阿里云 ECS 的个人试用。选 Ubuntu 24.04，确认领用资格、到期时间和实际费用，导出日志后再释放。 |

可从 2–4 vCPU、4 GB 内存和约 40 GB 磁盘起步。正式采集前，用 12 终端的目标负载看 CPU、内存和丢包，确认实验机有余量。

Mac 下载入口见 [UTM 官网](https://getutm.app/) 和 [Ubuntu 24.04 ARM64 ISO](https://download.cdimage.ubuntu.com/ubuntu/releases/24.04/release/)。云试用见 [腾讯云免费试用](https://cloud.tencent.com/act/pro/free) 和 [阿里云 ECS 试用规则](https://help.aliyun.com/zh/ecs/user-guide/ecs-free-trial)。

## 先检查 Linux 内核

以下命令在专用 Ubuntu 虚拟机里执行。若 `modinfo` 找不到模块，尝试安装与当前内核同版本的 extra 包，再检查。若云镜像缺少对应包，先更换可用的 Ubuntu 通用内核或镜像。

~~~bash
sudo apt update
sudo apt install -y git openssh-server openvswitch-switch iperf3 iputils-ping kmod python3-setuptools

modinfo mac80211_hwsim
# 仅在 modinfo 找不到模块且软件源有对应包时执行
# sudo apt install "linux-modules-extra-$(uname -r)"
sudo modprobe mac80211_hwsim radios=0
sudo modprobe -r mac80211_hwsim
findmnt /sys/kernel/debug
# 如果没有输出，在专用虚拟机中挂载后重试
# sudo mount -t debugfs debugfs /sys/kernel/debug
~~~

## 安装平台并生成第一份日志

在新虚拟机上用 Mininet-WiFi 的源码安装流程。这里先用 apt 安装 OVS，再安装无线依赖、wmediumd 和 Mininet-WiFi；基础拓扑采用 OVS 独立转发。已安装且可用的机器可直接部署目录里的脚本。上游安装流程见 [Mininet-WiFi Get Started](https://mininet-wifi.github.io/get-started/) 和 [安装脚本](https://github.com/intrig-unicamp/mininet-wifi/blob/master/util/install.sh)。

~~~bash
sudo git clone https://github.com/intrig-unicamp/mininet-wifi.git /opt/mininet-wifi
cd /opt/mininet-wifi
sudo env PYTHON=python3 ./util/install.sh -Wln
sudo systemctl enable --now openvswitch-switch
~~~

把这个 `wifi-lab` 目录复制到 Ubuntu，例如从 Mac 在本项目目录运行 `scp -r wifi-lab 管理员账号@实验机地址:~/`。管理员进入 Ubuntu 上的 `wifi-lab` 目录，执行下面的安装和验收命令。

~~~bash
sudo bash deploy.sh
{
  printf 'Mininet-WiFi: '; sudo git -C /opt/mininet-wifi rev-parse HEAD
  printf 'Mininet: '; sudo git -C /opt/mininet-wifi/mininet rev-parse HEAD
  printf 'wmediumd: '; sudo git -C /opt/wmediumd rev-parse HEAD
  sudo git -C /opt/mininet-wifi submodule status
  iperf3 --version
  ovs-vsctl --version
} | sudo tee /opt/wifi-lab/source-versions.txt

sudo /usr/local/sbin/wifi-lab 2 1,6
~~~

基础数据路径为 `sta → ap1 或 ap2 → s1 → srv`。两个 AP 接同一个虚拟交换机，终端和服务器用 `10.44.0.0/24`。两侧各放一个起始终端，逐个 ping 服务器，再各跑一次 3 秒 TCP iperf3。无线参数和实际 AP 信道及关联状态都写入日志。

终端静态地址按编号分配：`staN = 10.44.0.N/24`，因此 `sta1 = 10.44.0.1/24`、`sta2 = 10.44.0.2/24`；当前最多 12 台终端，地址至 `10.44.0.12/24`。业务服务器 `srv = 10.44.0.100/24`。该规则来自 `topology.py` 的 `campus_topology()`；`10.44.0.1` 已分配给 `sta1`，后续实验配置应沿用此规则。

命令打印形如 `/var/lib/wifi-lab/runs/smoke_…` 的日志目录。验收看 `status.txt` 是否为 `PASS`，核对两个 `ap*-iw-info.txt`、各终端的 `*-iw-link.txt` 和 `*-ping.txt`，并保留两份 `*-iperf3.json`。这些记录用于验收公共平台，正式数据由 4–6 号按各组对照设计采集。

## 给组员开账号

每人用已有 SSH 公钥，或用 `ssh-keygen -t ed25519` 生成一对密钥。请组员把 `.pub` 文件发给管理员。以下给 4 号开通，假设你已把其公钥保存为当前目录的 `wifi04.pub`。

~~~bash
sudo adduser --disabled-password --gecos '' wifi04
sudo usermod -aG wifi-lab,wifi-run wifi04
sudo install -d -m 0700 -o wifi04 -g wifi04 /home/wifi04/.ssh
sudo install -m 0600 -o wifi04 -g wifi04 wifi04.pub /home/wifi04/.ssh/authorized_keys
~~~

所有组员账号（`wifi01`、`wifi02`、`wifi04` 至 `wifi10`）都加入 `wifi-lab` 和 `wifi-run` 两组，可以读取和下载日志，也可以用 `sudo` 启动基础验收。`sudo` 授权仅限 `/usr/local/sbin/wifi-lab`，运行时无需输入 `sudo` 密码。每人使用自己的账号，分组后重新连接 SSH。

如果使用 Mac 虚拟机且同学不在同一局域网，可以在 Ubuntu 虚拟机和另外九名同学的电脑上装 ZeroTier，建立私有网络，逐一授权后，把 Ubuntu 虚拟机的 Managed IP 发给组员。免费个人方案支持 10 台设备，虚拟机占 1 台，其他九名同学各 1 台。你可以在 UTM 控制台管理虚拟机。先找一位同学从不同网络完成一次 SSH 登录，再扩到全组。 [ZeroTier 定价](https://www.zerotier.com/pricing/) · [ZeroTier 组网步骤](https://docs.zerotier.com/quickstart/)

学校机器使用学校批准的入口。云主机使用可达的管理地址，并在安全组限制 SSH 来源或使用私有组网。可以在实例控制台查看 SSH 主机指纹 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`，把它和主机地址一起给组员核验。 [Ubuntu OpenSSH 文档](https://ubuntu.com/server/docs/how-to/security/openssh-server/)

组员可以用以下命令登录、运行和下载日志。

~~~bash
# 组员自己的电脑
ssh wifi04@实验机地址

# SSH 登录后
sudo /usr/local/sbin/wifi-lab 2 1,6
sudo /usr/local/sbin/wifi-lab 12 1,1
ls -lt /var/lib/wifi-lab/runs
exit

# 回到组员自己的电脑，替换成命令输出的实际目录名
scp -r wifi04@实验机地址:/var/lib/wifi-lab/runs/实际运行目录 .
~~~

## 接入正式实验

- **4 号**复用 `topology.py` 里的 `campus_topology()`，配置 4、8、12 台终端和 1/1、1/6 信道。并发 iperf3 为各流分配独立服务进程和端口。
- **5 号**在 `net.start()` 前配置移动路线和关联策略，并记录移动终端的实际 BSSID、连续探测时间戳和探测间隔。
- **6 号**在 `srv` 的仿真接口上做队列配置，比较相同聚合限速下的默认队列和 HTB。将队列计数与业务日志一起保存。 [Linux tc 手册](https://www.man7.org/linux/man-pages/man8/tc.8.html)
- **3 号**先审核并发布正式脚本，初期可以由你代运行。所有正式入口和手工清理共用 `/var/lib/wifi-lab/run.lock`，例如 `sudo flock -n /var/lib/wifi-lab/run.lock /usr/bin/python3 /opt/wifi-lab/已审核的脚本.py`。把正式输出放进独立、组内可读的运行目录。确认实验机空闲后，可用 `sudo flock -n /var/lib/wifi-lab/run.lock mn -c` 清理失败运行的残留，再跑基础验收。

首次联调让一位同学登录并启动基础验收，再让第二位同时尝试启动，确认第二条命令提示实验机忙。让 7 或 8 号用自己的 SSH 账号下载日志，并让一位同学在同一环境跑一次 12 终端启动检查。正式采集期间，组员把统计绘图等计算任务放到自己的电脑上执行。
