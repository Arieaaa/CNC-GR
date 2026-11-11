#!/usr/bin/env python3
"""先校验归档与所有文件，再将指定运行还原至新的原始日志目录。"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id', help='原始归档/index.json 中的运行 ID')
    parser.add_argument('--dest', type=Path, default=ROOT/'原始日志')
    args = parser.parse_args()
    index = json.loads((ROOT/'原始归档/index.json').read_text(encoding='utf-8'))
    matches = [x for x in index if x['run_id'] == args.run_id]
    if len(matches) != 1:
        parser.error('运行 ID 不在索引内或存在重复')
    record = matches[0]
    archive = ROOT/'原始归档'/record['archive']
    content = archive.read_bytes()
    if hashlib.sha256(content).hexdigest() != record['archive_sha256']:
        raise ValueError('归档 SHA-256 不一致')
    entries = []
    seen = set()
    for line in content.splitlines():
        row = json.loads(line)
        path = row['path']
        parts = PurePosixPath(path).parts
        if (not parts or path.startswith('/') or '\\' in path or ':' in path
                or any(p in ('.', '..') for p in parts) or path in seen):
            raise ValueError('不安全或重复的相对路径: ' + path)
        seen.add(path)
        payload = base64.b64decode(row['base64'], validate=True)
        if hashlib.sha256(payload).hexdigest() != row['sha256']:
            raise ValueError('文件 SHA-256 不一致: ' + path)
        entries.append((parts, payload))
    if len(entries) != record['files']:
        raise ValueError('归档记录数与索引不一致')
    args.dest.mkdir(parents=True, exist_ok=True)
    target = args.dest/args.run_id
    if target.exists():
        parser.error('目标目录已存在，不覆盖: ' + str(target))
    with tempfile.TemporaryDirectory(prefix='.还原中-', dir=args.dest) as tmp:
        stage = Path(tmp)/args.run_id
        stage.mkdir()
        for parts, payload in entries:
            file = stage.joinpath(*parts)
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(payload)
        os.rename(stage, target)
    print('还原成功:', target, '文件数:', len(entries))


if __name__ == '__main__':
    main()
