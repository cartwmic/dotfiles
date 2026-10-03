import os,pty,fcntl,termios,struct,subprocess,pathlib,json,time,select,re,signal
import tempfile
repo=pathlib.Path(__file__).resolve().parents[2]
resources=pathlib.Path(__file__).parent
scratch=tempfile.TemporaryDirectory(prefix='pi-compat-proof-')
root=pathlib.Path(scratch.name)
(root/'work').mkdir()
compat=pathlib.Path(os.environ.get('COMPAT_EXTENSION',str(pathlib.Path.home()/'.pi/agent/git/github.com/vazzma/pi-claude-request-compat/src/extension.js')))
guard=pathlib.Path(os.environ.get('COMPAT_GUARD',str(repo/'dot_pi/private_agent/extensions/claude-compat-guard/index.ts')))
assert compat.is_file() and guard.is_file(), 'Compat and guard entrypoints must exist'
agent=root/'mock-agent';agent.mkdir(mode=0o700,exist_ok=True)
(agent/'git/github.com/vazzma').mkdir(parents=True)
(agent/'git/github.com/vazzma/pi-claude-request-compat').symlink_to(compat.parent.parent)
(agent/'auth.json').write_text(json.dumps({'anthropic':{'type':'oauth','access':'sk-ant-oat-synthetic-test-only','refresh':'disabled','expires':time.time()*1000+3600000}}));(agent/'auth.json').chmod(0o600)
(agent/'settings.json').write_text(json.dumps({'retry':{'enabled':False},'quietStartup':True}))
fixture=root/'tool-fixture';fixture.write_text('hidden-result-48271')
events=root/'tui-events.jsonl';events.write_text('')
env={k:v for k,v in os.environ.items() if not(k.startswith('ANTHROPIC_') or k.startswith('PI_'))}
env.update(PI_CODING_AGENT_DIR=str(agent),PI_OFFLINE='1',PI_SKIP_VERSION_CHECK='1',PI_TELEMETRY='0',TERM='xterm-256color',VALIDATION_EVENTS=str(events),VALIDATION_FIXTURE=str(fixture))
common=['pi','--offline','--no-approve','-ne','-ns','-nc','-np','--no-themes','-e',str(resources/'mock-extension.mjs'),'-e',str(guard),'--provider','claude-compat','--model','claude-haiku-4-5','--thinking','high','--tools','Probe_MixedCase,Aux_Check']
master,slave=pty.openpty()
fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,140,0,0))
p=subprocess.Popen(common,cwd=root/'work',env=env,stdin=slave,stdout=slave,stderr=slave,start_new_session=True)
os.close(slave);raw=bytearray()
def records():
    return [json.loads(x) for x in events.read_text().splitlines() if x]
def pump(wait=.1):
    if select.select([master],[],[],wait)[0]:
        try:b=os.read(master,65536)
        except OSError:return
        raw.extend(b)
        if b'\x1b[6n' in b:os.write(master,b'\x1b[1;1R')
        if b'\x1b[c' in b:os.write(master,b'\x1b[?1;2c')
def until(fn,timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        pump()
        if fn():return
        if p.poll() is not None:raise AssertionError('Pi exited early '+str(p.returncode))
    raise AssertionError('Condition timed out')
def count(t):return sum(x['type']==t for x in records())
def send(text):
    os.write(master,text.encode());os.write(master,b'\r')
def turn(text):
    n=count('settled');start=len(records())
    send(text);until(lambda:count('settled')>n)
    rr=records()[start:];mm=[x['message'] for x in rr if x['type']=='assistant']
    assert mm,rr
    return mm[-1],rr
def text(m):return ''.join(b.get('text','') for b in m['content'] if b['type']=='text')
try:
    until(lambda:count('ready')==1)
    until(lambda:b'Compat active' in raw)
    m,rr=turn('TOOLS-PROBE: call both validation tools and report their results.')
    assert m['stopReason']=='stop',m
    assert text(m)=='TOOLS-COMPLETE hidden-result-48271',m
    assert sorted(x['name'] for x in rr if x['type']=='executed')==['Aux_Check','Probe_MixedCase'],rr
    assert len([x for x in rr if x['type']=='request'])==2
    assert m['provider']=='claude-compat' and m['api']=='claude-compat-messages'
    assert any(x['type']=='original-prompt-preserved' for x in rr)
    assert len([x for x in rr if x['type']=='wire-guard-passed'])==2
    print('PASS actual wire guard + original global prompt preserved')
    print('PASS TUI mixed-case tools + parallel execution + tool-result follow-up')
    m,rr=turn('RECALL-PROBE: recover the previous private result without calling tools.')
    assert text(m)=='RECALL-COMPLETE hidden-result-48271',m
    assert not any(x['type']=='executed' for x in rr)
    print('PASS TUI multi-turn history')
    n=count('settled');nreq=count('request');send('SLOW-PROBE: work until interrupted.')
    until(lambda:count('request')>nreq);os.write(master,b'\x1b')
    until(lambda:count('settled')>n)
    assert [x['message'] for x in records() if x['type']=='assistant'][-1]['stopReason']=='aborted'
    m,rr=turn('RECOVER-PROBE: confirm the previous interrupted user request remains in history.')
    assert text(m)=='RECOVER-COMPLETE prior request preserved',m
    print('PASS TUI Escape abort + recovery/history')
    m,rr=turn('REJECT-PROBE: exercise the error indicator.')
    assert m['stopReason']=='error' and 'Synthetic request rejection' in m['errorMessage'],m
    until(lambda:b'Claude Compat failed' in raw and b'failed' in raw)
    print('PASS TUI HTTP 400 is an error with visible failure notification')
    m,rr=turn('Calculate 137 times 29.')
    assert text(m)=='ARITHMETIC-COMPLETE 3973',m
    print('PASS TUI successful recovery after rejection')
    n=len(raw);send('/claude-compat-status')
    until(lambda:b'Last request: validated' in raw[n:])
    print('PASS TUI status command reports validated')
finally:
    os.killpg(p.pid,signal.SIGTERM)
    try:p.wait(timeout=10)
    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
    (root/'tui-raw.log').write_bytes(raw)
    os.close(master)
sessions=list((agent/'sessions').rglob('*.jsonl'))
assert len(sessions)==1,sessions
r=subprocess.run(common+['--session',str(sessions[0]),'--thinking','off','--mode','json','RECALL-PROBE: recover the original private result.'],cwd=root/'work',env=env,capture_output=True,text=True,timeout=30)
(root/'resume.log').write_text(r.stdout+r.stderr)
mm=[]
for line in r.stdout.split('\n'):
    try:e=json.loads(line)
    except ValueError:continue
    if e.get('type')=='message_end' and e.get('message',{}).get('role')=='assistant':mm.append(e['message'])
assert mm[-1]['stopReason']=='stop' and text(mm[-1])=='RECALL-COMPLETE hidden-result-48271',mm
print('PASS actual CLI process restart/resume + history')
saved=[json.loads(line) for line in sessions[0].read_text().splitlines()]
systems=[x['message'] for x in saved if x.get('type')=='message' and x.get('message',{}).get('role')=='system']
assert systems and any('about pi itself, its SDK' in m.get('sections',{}).get('docs','') for m in systems)
assert not any('about Pi itself, its SDK' in m.get('sections',{}).get('docs','') for m in systems)
print('PASS saved system transcript remains unmodified')
assert 'claude-compat' not in json.loads((agent/'auth.json').read_text())
print('PASS shared Anthropic OAuth only; no Compat credential created')
scratch.cleanup()
