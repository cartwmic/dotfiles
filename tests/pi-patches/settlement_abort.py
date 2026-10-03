#!/usr/bin/env python3
"""Private real-Pi RPC/TUI settlement abort proof; no credentials or paid calls."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import pty
import select
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / 'dot_local/share/pi-patches/settlement-abort/patch.mjs'
SOURCE = Path(os.environ.get('PI_SETTLEMENT_SOURCE_PACKAGE', '/Users/cartwmic/.local/share/mise/installs/node/24.18.1/lib/node_modules/@earendil-works/pi-coding-agent'))

EXTENSION = r'''
import fs from 'node:fs';
export default function(pi) {
 let count=0, previous;
 pi.on('session_start',async()=>fs.appendFileSync(process.env.PROBE_TRACE, JSON.stringify({kind:'ready'})+'\n'));
 const log=x=>fs.appendFileSync(process.env.PROBE_TRACE, JSON.stringify(x)+'\n');
 pi.registerCommand('signal-idle',{description:'Inspect signal after completed operation',handler:async(args,ctx)=>log({kind:'idle',signal:!!ctx.signal,idle:ctx.isIdle()})});
 pi.on('agent_before_settle',async(event,ctx)=>{
  count++;
  const signal=ctx.signal;
  log({kind:'boundary',count,signal:!!signal,aborted:signal?.aborted,fresh:signal!==previous});
  previous=signal;
  signal?.addEventListener('abort',()=>log({kind:'abort',count}),{once:true});
  if(count===1 && process.env.PROBE_PHASE!=='settled'){
   while(!fs.existsSync(process.env.PROBE_RELEASE)) await new Promise(r=>setTimeout(r,20));
   log({kind:'late',aborted:signal?.aborted});
   if(!signal?.aborted) { log({kind:'notification'}); ctx.ui.notify('ABANDONED-GUIDANCE-NOTIFICATION','info'); }
   return {entries:[{type:'custom_message',customType:'settlement-proof',content:'ABANDONED-GUIDANCE',display:true}],continue:true};
  }
 });
 pi.on('agent_settled',async(event,ctx)=>{
  const signal=ctx.signal;
  log({kind:'settled-start',count,signal:!!signal,aborted:signal?.aborted,same:signal===previous,idle:ctx.isIdle()});
  if(count===1 && process.env.PROBE_PHASE==='settled') {
   signal?.addEventListener('abort',()=>log({kind:'settled-abort',count}),{once:true});
   if(process.env.PROBE_DEFERRED==='yes') pi.sendUserMessage('DEFERRED-TURN');
   if(process.env.PROBE_CUSTOM==='trigger') pi.sendMessage({customType:'proof',content:'CUSTOM-TURN',display:true},{triggerTurn:true});
   if(process.env.PROBE_CUSTOM==='notify') pi.sendMessage({customType:'proof',content:'CUSTOM-NOTIFY',display:true},{triggerTurn:false});
   while(!fs.existsSync(process.env.PROBE_RELEASE)) await new Promise(r=>setTimeout(r,20));
   log({kind:'settled-late',aborted:signal?.aborted});
   if(!signal?.aborted && ctx.isIdle()===true) { log({kind:'settled-notification'}); ctx.ui.notify('SETTLED-NOTIFICATION','info'); }
  }
  log({kind:'settled',count});
  if(count===1 && process.env.PROBE_THROW==='yes') throw new Error('SETTLED-FIXTURE-EXCEPTION');
 });
}
'''

def require(value, message):
    if not value: raise RuntimeError(message)

def wait(predicate, label, timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate(): return
        time.sleep(.03)
    raise RuntimeError('watchdog timeout (FAIL): '+label)

def trace(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

class Backend(http.server.ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self):
        self.requests=[]
        backend=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                backend.requests.append(body)
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                for delta,finish in [({'role':'assistant'},None),({'content':'SCRIPTED-ANSWER'},None),({},'stop')]:
                    payload={'id':'proof','object':'chat.completion.chunk','created':1,'model':'proof','choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
                    self.wfile.write(('data: '+json.dumps(payload)+'\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
        super().__init__(('127.0.0.1',0),Handler)
        threading.Thread(target=self.serve_forever,daemon=True).start()

def fingerprint(package):
    paths=[package/'dist/core/agent-session.js',package/'dist/core/extensions/types.d.ts']
    paths += [p for p in (package/'dist/bundle/chunks').glob('*.js') if 'async _runAgentPrompt(messages){' in p.read_text()]
    return {str(p.relative_to(package)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def patch(package,profile='personal',check=False,success=True):
    env={**os.environ,'PI_SETTLEMENT_ABORT_PACKAGE':str(package),'PI_CHEZMOI_PROFILE':profile}
    result=subprocess.run(['node',str(PATCH)]+(['--check'] if check else []),env=env,cwd=ROOT,text=True,capture_output=True)
    require((result.returncode==0)==success, result.stdout+result.stderr)
    return result

def journey(package, directory, module=False, tui=False, abort=True, patched=True, settled=False, deferred=False, throws=False, custom=None, legacy=False, stock=False):
    deferred = deferred or custom=='trigger'
    directory.mkdir();agent=directory/'agent';agent.mkdir();project=directory/'project';project.mkdir()
    backend=Backend();extension=directory/'probe.mjs';extension.write_text(EXTENSION)
    tracepath=directory/'trace';release=directory/'release'
    (agent/'models.json').write_text(json.dumps({'providers':{'proof':{'baseUrl':f'http://127.0.0.1:{backend.server_port}/v1','api':'openai-completions','apiKey':'dummy-local','models':[{'id':'proof','name':'Proof','reasoning':False,'input':['text'],'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0},'contextWindow':8192,'maxTokens':256}]}}}))
    (agent/'settings.json').write_text(json.dumps({'compaction':{'enabled':False},'retry':{'enabled':False}}))
    env={k:v for k,v in os.environ.items() if not any(x in k for x in ['API_KEY','TOKEN','PI_','HERDR_'])}
    env.update(HOME=str(directory),PI_CODING_AGENT_DIR=str(agent),PROBE_TRACE=str(tracepath),PROBE_RELEASE=str(release),PROBE_PHASE='settled' if settled else 'before',PROBE_DEFERRED='yes' if deferred and not custom else 'no',PROBE_THROW='yes' if throws else 'no',PROBE_CUSTOM=custom or '',TERM='xterm-256color',NO_COLOR='1')
    cli=package/('dist/cli.js' if module else 'dist/bundle/cli.js')
    args=['node',str(cli),'--provider','proof','--model','proof','--no-skills','--no-prompt-templates','--no-extensions','--extension',str(extension)]
    ipc=None;ipc_temp=None;reports=[]
    if stock:
        require(tui and settled and not abort, 'stock diagnostic requires TUI settled control')
        stock_source=Path('/Users/cartwmic/.pi/agent/extensions/herdr-agent-state.ts')
        stock_copy=directory/'stock-herdr.ts';shutil.copyfile(stock_source,stock_copy)
        print('STOCK:', hashlib.sha256(stock_copy.read_bytes()).hexdigest(), flush=True)
        ipc_temp=tempfile.TemporaryDirectory(prefix='pi-ipc-',dir='/tmp')
        socket_path=str(Path(ipc_temp.name)/'s')
        class IPCHandler(socketserver.StreamRequestHandler):
            def handle(self):
                reports.append(json.loads(self.rfile.readline()))
                self.wfile.write(b'{"ok":true}\n');self.wfile.flush()
        ipc=socketserver.ThreadingUnixStreamServer(socket_path,IPCHandler)
        ipc.daemon_threads=True
        threading.Thread(target=ipc.serve_forever,daemon=True).start()
        env.update(HERDR_ENV='1',HERDR_SOCKET_PATH=socket_path,HERDR_PANE_ID='private-proof')
        args = args[:-2]+['--extension',str(stock_copy),'--extension',str(extension)]
    outputs=[];master=None
    if tui:
        master,slave=pty.openpty()
        import fcntl,termios,struct
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,140,0,0))
        process=subprocess.Popen(args,stdin=slave,stdout=slave,stderr=slave,env=env,cwd=project);os.close(slave)
        def reader():
            while True:
                try:
                    data=os.read(master,65536)
                    if not data: break
                    outputs.append(data.decode(errors='replace'))
                except OSError: break
        threading.Thread(target=reader,daemon=True).start()
        wait(lambda:any(x['kind']=='ready' for x in trace(tracepath)), 'TUI session ready');os.write(master,b'FIRST-TURN\r')
    else:
        process=subprocess.Popen(args+['--mode','rpc'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,cwd=project,text=True)
        def reader():
            for line in process.stdout: outputs.append(line)
        threading.Thread(target=reader,daemon=True).start()
        def send(command): process.stdin.write(json.dumps(command)+'\n');process.stdin.flush()
        send({'type':'prompt','message':'FIRST-TURN'})
    try:
        wait(lambda:any(x['kind']==('settled-start' if settled else 'boundary') for x in trace(tracepath)),'first delayed boundary')
        if settled and patched and not tui:
            send({'type':'get_state','id':'pending-state'})
            wait(lambda:any('"pending-state"' in x for x in outputs), 'pending state response')
            state=next(json.loads(x) for x in outputs if '"pending-state"' in x)
            require(state['success'] and state['data']['isStreaming'], 'awaited settled must remain streaming')
        if stock:
            wait(lambda:any(x.get('params',{}).get('state')=='working' for x in reports),'stock working report')
            def native_ready():
                states=[x['params']['state'] for x in reports if x['method']=='pane.report_agent']
                return 'working' in states and 'idle' in states[states.index('working')+1:]
            if legacy:
                time.sleep(.3);require(not native_ready(),'legacy unexpectedly published native READY')
            else: wait(native_ready,'stock native READY publication through private IPC')
            print('PASS: unmodified stock Herdr private IPC', 'legacy READY suppressed' if legacy else 'READY published during awaited settlement', flush=True)
        if abort:
            if tui: os.write(master,b'\x1b')
            else: send({'type':'abort','id':'abort-proof'})
            if patched: wait(lambda:any(x['kind']==('settled-abort' if settled else 'abort') for x in trace(tracepath)),'prompt abort signal')
            else: time.sleep(.3)
            if patched and not tui:
                require(not any('"abort-proof"' in x for x in outputs), 'abort returned before delayed handler completed')
        release.touch()
        wait(lambda:sum(x['kind']=='settled' for x in trace(tracepath))>=(2 if deferred else 1),'completed settlement/deferred control')
        if abort and patched and not tui:
            wait(lambda:any('"abort-proof"' in x for x in outputs), 'abort completion response')
            require(next(json.loads(x) for x in outputs if '"abort-proof"' in x)['success'], 'abort did not complete successfully')
        first=list(trace(tracepath));first_requests=len(backend.requests)
        if custom=='notify':
            wait(lambda:'CUSTOM-NOTIFY' in '\n'.join(p.read_text() for p in agent.rglob('*.jsonl')), 'custom notification persisted before next turn')
            wait(lambda:'CUSTOM-NOTIFY' in ''.join(outputs), 'custom notification displayed before next turn')
        if tui: os.write(master,b'SECOND-TURN\r')
        else: send({'type':'prompt','message':'SECOND-TURN'})
        wait(lambda:sum(x['kind']=='settled' for x in trace(tracepath))>=(3 if deferred else 2),'follow-up completes')
        if patched:
            if tui: os.write(master,b'/signal-idle\r')
            else: send({'type':'prompt','message':'/signal-idle'})
            wait(lambda:any(x['kind']=='idle' for x in trace(tracepath)), 'idle signal inspection')
            idle=next(x for x in trace(tracepath) if x['kind']=='idle')
            require(idle['idle'] and not idle['signal'], 'operation controller leaked after settlement')
        events=trace(tracepath)
        if throws:
            wait(lambda:'SETTLED-FIXTURE-EXCEPTION' in ''.join(outputs), 'settled handler exception surfaced')
        boundary=[x for x in events if x['kind']=='boundary']
        sessions='\n'.join(p.read_text() for p in agent.rglob('*.jsonl'))
        require('FIRST-TURN' in sessions and 'SECOND-TURN' in sessions, 'saved session missing user turns')
        requests=json.dumps(backend.requests)
        require(len(backend.requests)==first_requests+1, 'follow-up must issue exactly one NEW backend request')
        latest=json.dumps(backend.requests[-1])
        require('SECOND-TURN' in latest, 'new request missing SECOND-TURN')
        if patched and abort: require('ABANDONED-GUIDANCE' not in latest, 'follow-up request leaked abandoned guidance')
        entries=[json.loads(line) for p in agent.rglob('*.jsonl') for line in p.read_text().splitlines()]
        messages=[e.get('message',{}) if e.get('type')=='message' else {**e,'role':'custom'} for e in entries if e.get('type') in ['message','custom_message']]
        def answered(turn):
            indexes=[i for i,m in enumerate(messages) if turn in json.dumps(m) and m.get('role') in ['user','custom']]
            require(indexes, 'missing persisted turn '+turn)
            require(any(m.get('role')=='assistant' and m.get('stopReason')=='stop' and 'SCRIPTED-ANSWER' in json.dumps(m) for m in messages[indexes[-1]+1:]), 'missing successful corresponding answer '+turn)
        answered('SECOND-TURN')
        if deferred and patched:
            turn='CUSTOM-TURN' if custom else 'DEFERRED-TURN'
            require(turn in json.dumps(backend.requests[first_requests-1]), 'deferred request missing turn')
            answered(turn)
        notification=any(x['kind']=='notification' for x in events) or 'ABANDONED-GUIDANCE-NOTIFICATION' in ''.join(outputs)
        if settled:
            notifications=any(x['kind']=='settled-notification' for x in first)
            if patched:
                require(all(x['signal'] and x['same'] for x in events if x['kind']=='settled-start'), 'settled lost current operation signal')
                require(all(x['fresh'] and not x['aborted'] for x in boundary), 'settled/deferred next operation did not receive fresh signal')
                require(first_requests==(2 if deferred else 1), 'unexpected settled model continuation')
                require(all(x['idle']==(not legacy) for x in events if x['kind']=='settled-start'), 'main-agent idle guard mismatch')
                require(notifications == (not abort and not legacy), 'settled idle-guarded notification cancellation/control failed')
                require(any(x['kind']=='settled-late' and x['aborted']==abort for x in first), 'late settled signal outcome incorrect')
                require('ABANDONED-GUIDANCE' not in sessions and 'ABANDONED-GUIDANCE' not in requests, 'settled leaked abandoned guidance')
                if deferred: require(('CUSTOM-TURN' if custom else 'DEFERRED-TURN') in sessions, 'deferred prompt did not persist')
            else:
                require(abort and notifications, 'unpatched settled notification regression missing')
        elif abort:
            defect='ABANDONED-GUIDANCE' in sessions or 'ABANDONED-GUIDANCE' in requests or notification
            require(defect != patched,'expected unpatched regression / patched suppression')
            if patched:
                require(first_requests==1,'abort made extra model step')
                require(boundary[0]['signal'] and all(x['fresh'] and not x['aborted'] for x in boundary),'operation signal not fresh')
                require(any(x['kind']=='late' and x['aborted'] for x in first),'late result did not see cancellation')
        else:
            require(first_requests==2,'normal continuation missing')
            require('ABANDONED-GUIDANCE' in requests and 'ABANDONED-GUIDANCE' in sessions,'normal proposal not committed')
            require(all(x['signal'] and not x['aborted'] for x in boundary),'control signal invalid')
            require(boundary[0]['fresh'] and not boundary[1]['fresh'] and boundary[2]['fresh'], 'continuation must retain signal; next operation must replace it')
        print('PASS:', 'module' if module else 'bundle',('TUI Escape' if abort else 'TUI') if tui else 'RPC', 'agent_settled' if settled else 'agent_before_settle', 'deferred' if deferred else 'handler-exception' if throws else '', 'abort' if abort else 'control', 'patched' if patched else 'unpatched regression demonstrated',flush=True)
    finally:
        artifacts=os.environ.get('PI_SETTLEMENT_PROOF_ARTIFACTS')
        if artifacts:
            destination=Path(artifacts)/directory.name;destination.mkdir(parents=True,exist_ok=True)
            (destination/'trace.json').write_text(json.dumps(trace(tracepath),indent=2))
            (destination/'backend-requests.json').write_text(json.dumps(backend.requests,indent=2))
            (destination/'native-ipc.json').write_text(json.dumps(reports,indent=2))
            (destination/'output.txt').write_text(''.join(outputs))
        if process.poll() is None:
            if tui:
                os.write(master,b'\x03');time.sleep(.2);os.write(master,b'\x03')
            else: process.stdin.close()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()
                raise RuntimeError('watchdog kill is failure, not completion')
        if master is not None: os.close(master)
        backend.shutdown();backend.server_close()
        if ipc: ipc.shutdown();ipc.server_close()
        if ipc_temp: ipc_temp.cleanup()

def main():
    trigger=(ROOT/'run_onchange_after_30_apply_pi_patches.sh.tmpl').read_text()
    require(trigger.count('include "dot_local/share/pi-patches/settlement-abort/patch.mjs" | sha256sum')==1, 'expected one source hash trigger')
    version=json.loads((SOURCE/'package.json').read_text())['version']
    require(version in ('0.99.2','1.0.0'),'requires tested Pi 0.99.2 or 1.0.0')
    original=fingerprint(SOURCE)
    print('IDENTITY:', SOURCE, 'Pi', version, json.dumps(original), flush=True)
    print('PAYLOAD:', hashlib.sha256(PATCH.read_bytes()).hexdigest(), flush=True)
    with tempfile.TemporaryDirectory(prefix='pi-settlement-proof-') as temp:
        root=Path(temp);package=root/'package';shutil.copytree(SOURCE,package,symlinks=True)
        if 'chezmoi-pi-patch:settlement-abort v1' in (package/'dist/core/agent-session.js').read_text():
            for module in [False, True]:
                journey(package,root/f'legacy-idle-{module}',module=module,settled=True,abort=False,legacy=True)
            journey(package,root/'legacy-stock',tui=True,settled=True,abort=False,legacy=True,stock=True)
            patch(package,check=True,success=False)
            legacy_fingerprint=fingerprint(package)
            legacy_files={relative:(package/relative).read_bytes() for relative in legacy_fingerprint}
            target=package/'dist/core/agent-session.js';saved=target.read_text()
            for malformed in [saved.replace('chezmoi-pi-patch:settlement-abort v1','chezmoi-pi-patch:settlement-abort v2'), saved.replace('chezmoi-pi-patch:settlement-abort v1','chezmoi-pi-patch:settlement-abort v3'), saved.replace('return !this.isStreaming && !this.isCompacting;', 'return !this._isAgentRunActive && !this.isCompacting;')]:
                target.write_text(malformed);before=fingerprint(package)
                patch(package,success=False);require(fingerprint(package)==before,'mixed/partial legacy refusal wrote targets')
            target.write_text(saved)
            patch(package);patch(package,check=True)
            require(fingerprint(package)!=legacy_fingerprint,'legacy v1 not upgraded')
            upgraded=fingerprint(package)
            patch(package,'termux');disabled=fingerprint(package)
            for relative,content in legacy_files.items(): (package/relative).write_bytes(content)
            patch(package,'termux');patch(package,'termux',check=True)
            require(fingerprint(package)==disabled,'disabled legacy reversal differs from v2 reversal')
            patch(package);require(fingerprint(package)==upgraded,'legacy disabled/reapply changed siblings')
            print('PASS: legacy v1 guard failure, exact upgrade, mixed/partial refusal',flush=True)
        for name, override in [('headless-extension-drain','PI_HEADLESS_PATCH_PACKAGE'), ('standing-reminder-origin','PI_STANDING_REMINDER_ORIGIN_PACKAGE')]:
            subprocess.run(['node',str(ROOT/f'dot_local/share/pi-patches/{name}/patch.mjs')],env={**os.environ,override:str(package),'PI_CHEZMOI_PROFILE':'personal'},cwd=ROOT,check=True,capture_output=True)
        patch(package,'termux');baseline=fingerprint(package)
        require('chezmoi-pi-patch:headless-extension-drain' in (package/'dist/core/agent-session.js').read_text(), 'headless sibling not installed')
        require('chezmoi-pi-patch:standing-reminder-origin' in (package/'dist/core/agent-session.js').read_text(), 'origin sibling not installed')
        journey(package,root/'unpatched',patched=False)
        journey(package,root/'unpatched-settled',patched=False,settled=True)
        patch(package,check=True,success=False)
        patch(package);after=fingerprint(package);patch(package);require(fingerprint(package)==after,'not idempotent')
        patches=root/'patches';patches.mkdir()
        for name in ['headless-extension-drain','standing-reminder-origin','settlement-abort']:
            shutil.copytree(ROOT/f'dot_local/share/pi-patches/{name}',patches/name)
        helper_env={**os.environ,'HOME':str(root/'helper-home'),'PI_PATCHES_ROOT':str(patches),'PI_CHEZMOI_PROFILE':'personal','PI_HEADLESS_PATCH_PACKAGE':str(package),'PI_STANDING_REMINDER_ORIGIN_PACKAGE':str(package),'PI_SETTLEMENT_ABORT_PACKAGE':str(package)}
        for repeat in range(2):
            for name in ['headless-extension-drain','standing-reminder-origin']:
                subprocess.run(['node',str(patches/name/'patch.mjs'),'--check'],env=helper_env,cwd=ROOT,check=True,capture_output=True)
            subprocess.run(['sh',str(ROOT/'dot_local/user_scripts/executable_apply_pi_patches.sh')],env=helper_env,cwd=ROOT,check=True,capture_output=True)
            patch(package,check=True)
            require(fingerprint(package)==after,'helper reapply changed combined patches')
        require(not (root/'helper-home/.local/state/chezmoi-pi-patches').exists(),'private helper wrote receipts')
        patch(package,check=True);patch(package,'axon-work-computer',check=True)
        for module in [False,True]:
            journey(package,root/f'rpc-{module}',module=module)
            journey(package,root/f'control-{module}',module=module,abort=False)
            journey(package,root/f'settled-{module}',module=module,settled=True)
            journey(package,root/f'settled-control-{module}',module=module,settled=True,abort=False)
            journey(package,root/f'deferred-control-{module}',module=module,settled=True,deferred=True,abort=False)
            journey(package,root/f'deferred-abort-{module}',module=module,settled=True,deferred=True)
            for custom in ['trigger','notify']:
                journey(package,root/f'custom-{custom}-{module}',module=module,settled=True,custom=custom,abort=False)
            journey(package,root/f'settled-exception-{module}',module=module,settled=True,throws=True,abort=False)
        journey(package,root/'stock-ready',tui=True,settled=True,abort=False,stock=True)
        print('PATCHED IDENTITY:', json.dumps(after), flush=True)
        journey(package,root/'tui',tui=True)
        journey(package,root/'tui-settled',tui=True,settled=True)
        journey(package,root/'module-tui',module=True,tui=True)
        journey(package,root/'module-tui-settled',module=True,tui=True,settled=True)
        journey(package,root/'module-stock-ready',module=True,tui=True,settled=True,abort=False,stock=True)
        target=package/'dist/core/agent-session.js';saved=target.read_text()
        for malformed in [saved.replace('chezmoi-pi-patch:settlement-abort v2','chezmoi-pi-patch:settlement-abort v3'), saved.replace('this._operationAbortController?.abort();','/* missing abort */')]:
            target.write_text(malformed);before=fingerprint(package)
            patch(package,success=False);require(fingerprint(package)==before,'unknown/partial v2 refusal wrote targets')
        target.write_text(saved)
        patch(package,'termux');patch(package,'termux',check=True);require(fingerprint(package)==baseline,'reversal changed sibling patches')
        for kind in ['missing','ambiguous']:
            p=package/'dist/core/extensions/types.d.ts';saved=p.read_text()
            anchor='    /** The current abort signal, or undefined when the agent is not streaming. */'
            p.write_text(saved.replace(anchor,'/* missing */' if kind=='missing' else anchor+'\n'+anchor))
            before=fingerprint(package);patch(package,success=False);require(fingerprint(package)==before,'anchor refusal wrote targets');p.write_text(saved)
        patch(package,'axon-work-computer');patch(package,'axon-work-computer',check=True)
        patch(package,'unknown');require(fingerprint(package)==baseline,'unknown profile reversal changed siblings')
        print('PASS: check/idempotence, anchor refusal without writes, disabled profile exact reversal/sibling preservation')
    require(fingerprint(SOURCE)==original,'installed package changed')
    print('PASS: installed runtime unchanged')

if __name__=='__main__': main()
