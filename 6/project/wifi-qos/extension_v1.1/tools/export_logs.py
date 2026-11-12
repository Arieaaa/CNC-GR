#!/usr/bin/env python3
"""Lossless UTF-8 run logs, one JSONL per completed attempt; no archive."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def export(root,output):
    root,output=Path(root),Path(output)
    records=[]
    folders=[]
    for runs in root.glob('*/runs'):
        folders.extend(x for x in runs.iterdir() if x.is_dir())
    names=Counter(x.name for x in folders)
    if any(count>1 for count in names.values()):raise ValueError('run names collide across batches; refusing overwrite')
    output.mkdir(parents=True,exist_ok=True)
    for directory in sorted(folders):
        status_file=directory/'status.txt'
        if not status_file.exists() or status_file.read_text().strip()=='RUNNING':continue
        destination=output/(directory.name+'.jsonl')
        temp=destination.with_suffix('.tmp');count=0
        with temp.open('w',encoding='utf-8',newline='\n') as out:
            for path in sorted(directory.rglob('*')):
                if not path.is_file():continue
                if path.is_symlink():raise ValueError('refusing symlink')
                data=path.read_bytes();content=data.decode('utf-8')
                record={'path':str(Path(directory.name)/path.relative_to(directory)),
                        'sha256':hashlib.sha256(data).hexdigest(),'content':content}
                out.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n');count+=1
        temp.replace(destination)
        records.append(dict(log_file=destination.name,sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                            files=count,bytes=destination.stat().st_size,batch=directory.parent.parent.name,
                            status=status_file.read_text().strip(),status_mtime_ns=status_file.stat().st_mtime_ns))
    index={'format':'path-sha256-content-jsonl-v1','runs':records,'total_files':sum(x['files'] for x in records)}
    tmp=output/'index.tmp';tmp.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n');tmp.replace(output/'index.json')
    return index


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('output');a=p.parse_args()
    result=export(a.root,a.output);print(json.dumps({'runs':len(result['runs']),'files':result['total_files']}))
