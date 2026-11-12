#!/usr/bin/env python3
"""校验合并JSONL并恢复原始日志；使用Python标准库，无压缩或解压步骤。"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def restore(source, target):
    source, target = Path(source), Path(target)
    if target.exists():
        raise FileExistsError(f'目标已存在，不覆盖：{target}')
    files = sorted(source.glob('*.jsonl'))
    if not files:
        raise ValueError('未找到合并日志')
    index_file = source/'index.json'
    index = json.loads(index_file.read_text()) if index_file.exists() else None
    expected = {r['log_file']: r for r in index['runs']} if index else None
    if index and len(expected)!=len(index['runs']):
        raise ValueError('索引中存在重复日志文件名')
    if expected is not None and set(expected) != {f.name for f in files}:
        raise ValueError('索引与合并日志文件不一致')
    records = {}
    for file in files:
        raw = file.read_bytes()
        if expected is not None and hashlib.sha256(raw).hexdigest() != expected[file.name]['sha256']:
            raise ValueError(f'合并文件校验失败：{file.name}')
        count = 0
        for line in raw.decode('utf-8').splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            path = PurePosixPath(record['path'])
            if path.is_absolute() or '..' in path.parts or len(path.parts) < 2 or '\\' in record['path']:
                raise ValueError('无效日志路径')
            if path.parts[0] != file.stem or path in records:
                raise ValueError('日志路径归属不符或重复')
            content = record['content'].encode('utf-8')
            if hashlib.sha256(content).hexdigest() != record['sha256']:
                raise ValueError(f'原文件校验失败：{path}')
            records[path] = content
            count += 1
        if expected is not None and count != expected[file.name]['files']:
            raise ValueError('日志条目数量不符')
    # 所有内容、路径和校验都通过后才创建目标目录。
    target.mkdir(parents=True)
    for path, content in records.items():
        destination = target/Path(*path.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return len(records)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?', default='merged_logs')
    parser.add_argument('target', nargs='?', default='logs')
    args = parser.parse_args()
    print(f'已校验并恢复 {restore(args.source, args.target)} 份原始日志。')
