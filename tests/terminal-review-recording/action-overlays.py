#!/usr/bin/env python3
"""Actual CLI/controlling-PTY action overlay proof; synthetic input, private outputs."""
import argparse,pathlib,subprocess,os,pty,fcntl,termios,struct,json,time,select,hashlib
REPO=pathlib.Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();root=pathlib.Path(a.output);root.mkdir(mode=0o700)
fixture=root/'fixture.py';fixture.write_text("import time,json,pathlib,sys\npathlib.Path(sys.argv[1]).write_text(json.dumps({'start':time.monotonic()}))\nprint('RESPONSE STAYS VISIBLE',flush=True)\nvalue=input('PROMPT> ')\nreceipt=pathlib.Path(sys.argv[2]);tmp=receipt.with_suffix('.tmp');tmp.write_text(json.dumps({'received':value}));tmp.replace(receipt)\nprint('ACTUAL INPUT: '+value,flush=True)\ntime.sleep(3)\n")
clock=root/'clock.json';received=root/'received.json';actions=root/'actions.json';actions.write_text('[]')
master,slave=pty.openpty();fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',16,60,0,0))
def controlling():os.setsid();fcntl.ioctl(slave,termios.TIOCSCTTY,0)
proc=subprocess.Popen([str(REPO/'dot_local/bin/executable_terminal-review-record'),'--output-dir',str(root/'capture'),'--actions',str(actions),'--size','60x16','--','python3',str(fixture),str(clock),str(received)],cwd=root,stdin=slave,stdout=slave,stderr=slave,preexec_fn=controlling);os.close(slave);out=bytearray()
def wait(pred,label):
 end=time.monotonic()+90
 while time.monotonic()<end:
  if select.select([master],[],[],.05)[0]:
   try:out.extend(os.read(master,65536))
   except OSError:pass
  if pred():return
  if proc.poll() is not None:
   if pred():return
   raise RuntimeError('CLI exited before '+label+' (status '+str(proc.returncode)+')')
 raise RuntimeError('Timeout '+label)
try:
 wait(lambda:b'PROMPT> ' in out and clock.exists(),'actual input prompt')
 start=json.loads(clock.read_text())['start']
 typed="SAFE prompt: spaces {braces} \\N 100% <script>"
 at=time.monotonic()-start
 # Retain exactly the explicit writes, not raw terminal input capture.
 os.write(master,typed.encode());first={'time':at,'kind':'text','value':typed}
 time.sleep(.4);at=time.monotonic()-start;os.write(master,b'\r')
 actions.write_text(json.dumps([first,{'time':at,'kind':'key','value':'Enter'}]))
 wait(lambda:received.exists(),'application received actual input')
 assert json.loads(received.read_text())['received']==typed
 wait(lambda:proc.poll() is not None,'CLI normal exit/export')
 assert proc.returncode==0
finally:
 (root/'cli.ansi').write_bytes(out);os.close(master)
 if proc.poll() is None:
  proc.terminate()
  try:proc.wait(timeout=5)
  except subprocess.TimeoutExpired:proc.kill();proc.wait()
capture=root/'capture';metadata=json.loads((capture/'metadata.json').read_text());assert metadata['exit']==0 and metadata['actions']['enabled']
assert json.loads((capture/'actions.json').read_text())==json.loads(actions.read_text())
cast=capture/'record.cast';digest=hashlib.sha256(cast.read_bytes()).hexdigest()
events=[json.loads(x) for x in cast.read_text().splitlines()];assert events[0]['version']==3 and not any(x[1]=='i' for x in events[1:])
assert metadata['actions']['overlay_height']>0
# Export-only keeps explicit actions without requiring a second --actions argument.
z=subprocess.run([str(REPO/'dot_local/bin/executable_terminal-review-record'),'--output-dir',str(capture),'--export-only'],cwd=root,capture_output=True,text=True,timeout=90)
(root/'reexport.log').write_text(z.stdout+z.stderr);assert z.returncode==0 and hashlib.sha256(cast.read_bytes()).hexdigest()==digest
for name,bad in [('out-of-range',[{'time':metadata['cast_duration']+1,'kind':'key','value':'Escape'}]),('nonfinite',[{'time':float('nan'),'kind':'text','value':'safe'}]),('controls',[{'time':0,'kind':'text','value':'safe\x1b'}]),('unordered',[{'time':2,'kind':'key','value':'End'},{'time':1,'kind':'key','value':'Home'}]),('unknown',[{'time':0,'kind':'key','value':'j','capture_all':True}])]:
 f=root/(name+'.json');f.write_text(json.dumps(bad));z=subprocess.run([str(REPO/'dot_local/bin/executable_terminal-review-record'),'--output-dir',str(capture),'--export-only','--actions',str(f)],cwd=root,capture_output=True,text=True,timeout=20)
 (root/(name+'.log')).write_text(z.stdout+z.stderr);assert z.returncode!=0 and hashlib.sha256(cast.read_bytes()).hexdigest()==digest
(root/'receipt.json').write_text(json.dumps({'status':'passed','actual_typed_input':typed,'application_received':json.loads(received.read_text()),'no_input_events':True,'cast_preserved':True,'actions':str(actions),'capture':str(capture)},indent=2)+"\n")
print('PASS: actual typed input/key overlay export, reexport persistence, invalid action refusal, no input events, unchanged original cast')
