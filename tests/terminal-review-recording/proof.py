"""Outside-in CLI proof. Set PATH to real pinned dependencies; outputs stay private."""
import argparse, hashlib, json, os, pathlib, pty, struct, subprocess, sys, termios, fcntl
ROOT=pathlib.Path(__file__).resolve().parents[2]
CLI=ROOT/'dot_local/bin/executable_terminal-review-record'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();base=pathlib.Path(a.output);base.mkdir(mode=0o700)
 def call(name,args,code=0,env=None):
  r=subprocess.run([str(CLI),'--output-dir',str(base/name),*args],capture_output=True,text=True,env=env,timeout=90)
  (base/(name+'.log')).write_text(r.stdout+r.stderr);assert r.returncode==code,(name,r.returncode,r.stderr);return base/name
 assert subprocess.run([str(CLI),'--help'],capture_output=True).returncode==0
 marker=base/'INJECTION'
 fixture=base/'fixture.py';fixture.write_text("import sys,time\nprint(repr(sys.argv[1:]),flush=True)\nprint('\\x1b[31mRED\\x1b[0m      GAP\\n界  X\\né  Y\\n<script></script>',flush=True)\ntime.sleep(1)\nprint('\\x1b[?1049hALTERNATE',flush=True)\ntime.sleep(1)\nprint('\\x1b[?1049lRESTORED',flush=True)\ntime.sleep(2)\n")
 out=call('fixture',['--',sys.executable,str(fixture),'space arg','; touch '+str(marker)]);assert not marker.exists()
 events=[json.loads(x) for x in (out/'record.cast').read_text().splitlines()];assert events[0]['version']==3 and not any(x[1]=='i' for x in events[1:])
 m=json.loads((out/'metadata.json').read_text());assert m['exit']==0 and abs(m['cast_duration']-m['movie_duration'])<.2
 for name,entry in m['files'].items():assert digest(out/name)==entry['sha256']
 call('exit7',['--','sh','-c','printf FAILED; sleep 2; exit 7'],7)
 call('empty',['--','sh','-c','exit 0'],1)
 for version in (1,2):
  d=base/('v'+str(version));d.mkdir();c=d/'record.cast';c.write_text(json.dumps({'version':version,'width':48,'height':32})+'\n[1,"o","x"]\n');h=digest(c)
  call(d.name,['--export-only'],1);assert digest(c)==h and not (d/'phone.mp4').exists()
 call('invalid',['--size','0x2','--','true'],2);assert not (base/'invalid').exists()
 # Real outer PTY and a recorder found on PATH whose exec fails after resize.
 bins=base/'broken-bin';bins.mkdir();rec=bins/'asciinema';rec.write_text('#!/nonexistent/interpreter\n');rec.chmod(0o700)
 env={**os.environ,'PATH':str(bins)+os.pathsep+os.environ['PATH']}
 master,slave=pty.openpty();fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,80,0,0))
 r=subprocess.run([str(CLI),'--output-dir',str(base/'startup-failure'),'--','true'],stdin=slave,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=10)
 assert r.returncode!=0 and struct.unpack('HHHH',fcntl.ioctl(slave,termios.TIOCGWINSZ,b'\0'*8))[:2]==(24,80)
 os.close(master);os.close(slave)
 # Non-executable recorder cannot be selected or hang.
 rec.chmod(0o600)
 env['PATH']=str(bins)+os.pathsep+os.path.dirname(sys.executable)+':/usr/bin:/bin'
 r=subprocess.run([str(CLI),'--output-dir',str(base/'missing'),'--','true'],env=env,capture_output=True,timeout=10);assert r.returncode!=0
 (base/'receipt.json').write_text(json.dumps({'status':'PASS','fixture':str(out),'metadata':m},indent=2));print('PASS: actual capture/export, argv, hashes/timing, exit7, empty failure, v1/v2 rejection, startup geometry')
if __name__=='__main__':main()
