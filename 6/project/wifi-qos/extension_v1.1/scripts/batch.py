#!/usr/bin/env python3
"""Serialize a frozen manifest and retain invalid attempts for audit."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
from core import build_manifest
from runner import run_spec,freeze_hashes


def prepare_batch(root,manifest,hashes):
    root.mkdir(parents=True,exist_ok=False);root.chmod(0o2750)
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (root/'source-hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--manifest',type=Path);parser.add_argument('--kind',default='formal')
    a=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('root required')
    manifest=json.loads(a.manifest.read_text()) if a.manifest else build_manifest()
    hashes=freeze_hashes()
    status={'state':'RUNNING','completed':0,'total':len(manifest),'invalid_attempts':0,'started_ns':time.time_ns()}
    def checkpoint():
        tmp=a.root/'progress.tmp';tmp.write_text(json.dumps(status,indent=2)+'\n');tmp.replace(a.root/'progress.json')
    def stop(signum,frame):raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM,stop)
    with open('/var/lib/wifi-lab/run.lock','r+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        prepare_batch(a.root,manifest,hashes)
        try:
            for spec in manifest:
                for attempt in (1,2):
                    if freeze_hashes()!=hashes:raise RuntimeError('source changed after freeze')
                    current=spec|{'id':spec['id']+(f'_attempt{attempt}' if attempt>1 else ''),
                                  'planned_id':spec['id'],'attempt':attempt}
                    status['current']=current['id'];checkpoint()
                    error=None
                    try:
                        specs=a.root/'specs';specs.mkdir(exist_ok=True)
                        spec_file=specs/(current['id']+'.json');spec_file.write_text(json.dumps(current))
                        proc=subprocess.run([sys.executable,'-u',str(Path(__file__).with_name('runner.py')),
                            '--spec',str(spec_file),'--root',str(a.root),'--kind',a.kind,'--lock-fd',str(lock.fileno())],
                            pass_fds=(lock.fileno(),),stdin=subprocess.DEVNULL)
                        directory=str(a.root/'runs'/current['id'])
                        if proc.returncode:raise RuntimeError(f'isolated runner exit {proc.returncode}')
                    except Exception as exc:
                        error=f'{type(exc).__name__}: {exc}';directory=str(a.root/'runs'/current['id'])
                        status['invalid_attempts']+=1;traceback.print_exc()
                    row=current|{'directory':directory,'status':'INVALID' if error else 'PASS','error':error}
                    with (a.root/'index.jsonl').open('a') as out:out.write(json.dumps(row)+'\n')
                    if not error:break
                    if attempt==2:raise RuntimeError('two invalid attempts; fix acquisition before continuing')
                status['completed']+=1;checkpoint()
                print(json.dumps({'completed':status['completed'],'total':len(manifest),'id':current['id']}),flush=True)
            status['state']='COMPLETE';status['finished_ns']=time.time_ns();checkpoint()
        except BaseException as exc:
            status['state']='STOPPED';status['error']=f'{type(exc).__name__}: {exc}';checkpoint();raise


if __name__=='__main__':main()
