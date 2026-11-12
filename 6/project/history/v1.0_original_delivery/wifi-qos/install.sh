#!/bin/bash
# 由服务器管理员审阅 scripts/expc.py、scripts/wifi-expc 后执行。
set -euo pipefail
if (( EUID != 0 )); then
    printf '仅供管理员执行：sudo bash install.sh\n' >&2
    exit 1
fi
package_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test -f /opt/wifi-lab/topology.py
test -f /var/lib/wifi-lab/run.lock
id wifi06 >/dev/null
/usr/bin/python3 -m py_compile "$package_dir/scripts/expc.py"
/bin/bash -n "$package_dir/scripts/wifi-expc"
if [[ -e /opt/wifi-lab/expc.py || -e /usr/local/sbin/wifi-expc || -e /etc/sudoers.d/wifi-expc ]]; then
    printf '已有实验C部署文件；请管理员核对版本后手动更新，本安装器不覆盖。\n' >&2
    exit 1
fi
sudoers_file=$(mktemp)
trap 'rm -f "$sudoers_file"' EXIT
printf 'wifi06 ALL=(root) NOPASSWD: /usr/local/sbin/wifi-expc\n' > "$sudoers_file"
/usr/sbin/visudo -cf "$sudoers_file"
/usr/bin/install -o root -g root -m 0644 "$package_dir/scripts/expc.py" /opt/wifi-lab/expc.py
/usr/bin/install -o root -g root -m 0755 "$package_dir/scripts/wifi-expc" /usr/local/sbin/wifi-expc
/usr/bin/install -o root -g root -m 0440 "$sudoers_file" /etc/sudoers.d/wifi-expc
/usr/sbin/visudo -cf /etc/sudoers.d/wifi-expc
printf '已部署固定入口，wifi06可运行实验C；未启动实验。\n'
