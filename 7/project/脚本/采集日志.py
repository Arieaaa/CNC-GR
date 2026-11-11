#!/usr/bin/env python3
"""Download a closed run via OpenSSH and verify its SHA-256 manifest."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def local_manifest(root):
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('不支持符号链接: ' + str(path))
        if path.is_file():
            result['./' + path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def remote_manifest(user_host, remote, options):
    cmd = 'cd ' + remote + ' && find . -type f -exec sha256sum -z -- {} +'
    data = subprocess.run(['ssh', *options, user_host, cmd], stdout=subprocess.PIPE, check=True).stdout
    result = {}
    for entry in data.split(b'\0'):
        if entry:
            digest, name = entry.split(b'  ', 1)
            result[name.decode('utf-8')] = digest.decode('ascii')
    return result


def main():
    parser = argparse.ArgumentParser(description='下载服务器指定运行目录；前后核对 SHA-256，不覆盖原始数据。')
    parser.add_argument('run_id', help='服务器 runs 目录下的单个目录名')
    parser.add_argument('--dest', type=Path, default=Path(__file__).resolve().parent.parent / '原始日志')
    parser.add_argument('--host', required=True, help='经组内确认的实验机地址')
    parser.add_argument('--user', default='wifi07')
    parser.add_argument('--known-hosts', type=Path, required=True, help='含已通过可信渠道核对公钥的本地 known_hosts 文件')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', args.run_id):
        parser.error('运行目录名仅能包含英文字母、数字、下划线、连字符和点，且不能以点或连字符开头')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.user) or not re.fullmatch(r'[A-Za-z0-9_.:-]+', args.host):
        parser.error('用户名或主机地址格式无效')
    if not args.known_hosts.is_file():
        parser.error('没有找到已核对的主机密钥文件')
    args.dest.mkdir(parents=True, exist_ok=True)
    target = args.dest / args.run_id
    if target.exists():
        parser.error('目标目录已存在，不会覆盖: ' + str(target))
    options = ['-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(args.known_hosts.resolve()),
               '-o', 'GlobalKnownHostsFile=none', '-o', 'ConnectTimeout=15']
    user_host = args.user + '@' + args.host
    remote = '/var/lib/wifi-lab/runs/' + args.run_id
    stage = Path(tempfile.mkdtemp(prefix='.采集中-', dir=str(args.dest)))
    try:
        before = remote_manifest(user_host, remote, options)
        if not before:
            raise ValueError('远程目录为空，或找不到普通文件')
        subprocess.run(['scp', *options, '-r', user_host + ':' + remote, str(stage)], check=True)
        downloaded = stage / args.run_id
        after = remote_manifest(user_host, remote, options)
        local = local_manifest(downloaded)
        if before != after or after != local:
            print('远程文件在采集期间变化或本地校验不一致。', file=sys.stderr)
            print('远程前后变化:', sorted(set(before) ^ set(after) | {k for k in before.keys() & after.keys() if before[k] != after[k]}), file=sys.stderr)
            print('本地差异:', sorted(set(local) ^ set(after) | {k for k in local.keys() & after.keys() if local[k] != after[k]}), file=sys.stderr)
            raise ValueError('SHA-256 校验失败')
        # Do not replace a directory that appeared while downloading.
        os.rename(downloaded, target)
        stage.rmdir()
        print('采集完成:', target)
        print('文件数:', len(local), '；远程采集前后与本地 SHA-256 一致')
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print('采集失败:', exc, file=sys.stderr)
        print('暂存目录保留以供检查:', stage, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
