#!/bin/bash
set -euo pipefail

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ $(uname -s) != Linux || $EUID != 0 ]]; then
    printf '请在已装好 Mininet-WiFi 的专用 Ubuntu 虚拟机上运行 sudo bash deploy.sh。\n' >&2
    exit 1
fi

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
for program in systemd-run flock visudo ovs-vsctl hostapd iw wmediumd hwsim_mgmt mnexec ping iperf3; do
    command -v "$program" >/dev/null || { printf '缺少 %s\n' "$program" >&2; exit 1; }
done
modinfo mac80211_hwsim >/dev/null
findmnt -n -t debugfs /sys/kernel/debug >/dev/null || { printf '请先挂载 debugfs。\n' >&2; exit 1; }
ovs-vsctl --timeout=5 show >/dev/null
MPLBACKEND=Agg /usr/bin/python3 -I -c 'from mn_wifi.net import Mininet_wifi'

getent group wifi-lab >/dev/null || groupadd --system wifi-lab
getent group wifi-run >/dev/null || groupadd --system wifi-run
install -d -o root -g root -m 0755 /opt/wifi-lab /var/lib/wifi-lab
install -d -o root -g wifi-lab -m 2750 /var/lib/wifi-lab/runs

# Use the same lock for platform updates and all runs.
umask 027
exec 9>>/var/lib/wifi-lab/run.lock
flock -n 9 || { printf '实验正在运行，请结束后再更新平台。\n' >&2; exit 75; }

install -o root -g root -m 0644 "$source_dir/topology.py" /opt/wifi-lab/topology.py
install -o root -g root -m 0755 "$source_dir/wifi-lab" /usr/local/sbin/wifi-lab

rule=$(mktemp)
trap 'rm -f -- "$rule"' EXIT
cat > "$rule" <<'EOF'
%wifi-run ALL=(root) NOPASSWD: /usr/local/sbin/wifi-lab
EOF
visudo -cf "$rule"
install -o root -g root -m 0440 "$rule" /etc/sudoers.d/wifi-lab
printf '平台入口已安装。运行 sudo /usr/local/sbin/wifi-lab 2 1,6 进行基础验收。\n'
