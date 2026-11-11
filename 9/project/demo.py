"""Member 09 integration CLI. Python 3.10+, paramiko for remote actions."""
import argparse, datetime, getpass, hashlib, html, json, pathlib, re, sys, time
ROOT=pathlib.Path(__file__).resolve().parent

def manifest():
 return {str(p.relative_to(ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.parent.rglob('*') if p.is_file() and p.name not in ('manifest.json',) and '__pycache__' not in p.parts and 'build' not in p.parts and p.suffix!='.zip'}

def verify():
 expected=json.loads((ROOT/'manifest.json').read_text(encoding='utf8'));bad=[]
 for n,h in expected.items():
  p=ROOT.parent/n
  if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:bad.append(n)
 print(json.dumps({'checked':len(expected),'failures':bad},ensure_ascii=False));return bool(bad)

def browse():
 files=sorted(p for folder in ('evidence','media') for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.json','.txt','.png','.mp4'))
 body='<h1>9号：系统集成与演示</h1><p>按运行记录查看环境配置、AP关联、连通性探测和TCP接收统计；视频与关键截图展示完整操作顺序。</p>'
 for p in files:
  body+='<p><a href="'+html.escape(p.relative_to(ROOT).as_posix(),quote=True)+'">'+html.escape(p.relative_to(ROOT).as_posix())+'</a></p>'
 video=ROOT/'media'/'系统集成演示_4分钟_20261111.mp4'
 if video.is_file():body+='<h2>四分钟演示</h2><video controls width="960" src="media/'+html.escape(video.name,quote=True)+'"></video>'
 (ROOT/'index.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:18px system-ui;max-width:1100px;margin:40px auto;background:#eef3f6;color:#142a40}a{color:#126b95}</style>'+body,encoding='utf8')
 print(ROOT/'index.html');return 0

def remote(args):
 import paramiko
 cfg=json.loads(pathlib.Path(args.config).read_text(encoding='utf8'))
 t=paramiko.Transport((cfg['host'],cfg.get('port',22)))
 t.start_client(timeout=15)
 fingerprint=hashlib.sha256(t.get_remote_server_key().asbytes()).hexdigest()
 if fingerprint!=cfg['host_key_sha256_hex']:t.close();raise RuntimeError('Host key mismatch; contact platform owner')
 try:
  t.auth_password(cfg['user'],getpass.getpass('SSH password (not stored): '))
  outdir=ROOT/'sessions'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');outdir.mkdir(parents=True)
  cmd='id; sudo -n -l; cat /opt/wifi-lab/source-versions.txt; ls -lt /var/lib/wifi-lab/runs | head -12' if args.action=='check' else 'sudo -n /usr/local/sbin/wifi-lab 2 1,6'
  if args.action=='collect':
   if not re.fullmatch(r'[A-Za-z0-9_.-]+',args.run or ''):raise ValueError('Use a run directory basename')
   collect(t,args.run,outdir);return 0
  ch=t.open_session();ch.settimeout(220);ch.exec_command(cmd)
  output=ch.makefile().read().decode('utf8','replace');error=ch.makefile_stderr().read().decode('utf8','replace');code=ch.recv_exit_status()
  record={'command':cmd,'utc':outdir.name,'stdout':output,'stderr':error,'exit_code':code,'status':'BUSY' if code==75 else 'PASS' if code==0 else 'FAIL'}
  (outdir/'session.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8');print(output,error)
  if code==75:print('Platform busy. Use offline evidence/video. Do not clean other runs.')
  if args.action=='run':
   m=re.search(r'/var/lib/wifi-lab/runs/([\w.-]+)',output)
   if m:collect(t,m[1],outdir)
  return code
 finally:t.close()

def collect(t,name,outdir):
 s=__import__('paramiko').SFTPClient.from_transport(t);src='/var/lib/wifi-lab/runs/'+name;dst=outdir/name;dst.mkdir()
 for entry in s.listdir_attr(src):
  import stat
  if stat.S_ISREG(entry.st_mode):s.get(src+'/'+entry.filename,str(dst/entry.filename))
 s.close();print('Evidence:',dst)

def main():
 a=argparse.ArgumentParser();a.add_argument('action',choices=['check','run','collect','browse','verify']);a.add_argument('--config',default=str(ROOT/'config.example.json'));a.add_argument('--run');args=a.parse_args()
 try:return verify() if args.action=='verify' else browse() if args.action=='browse' else remote(args)
 except Exception as e:print(type(e).__name__+': '+str(e),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
