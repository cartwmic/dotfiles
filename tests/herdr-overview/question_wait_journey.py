#!/usr/bin/env python3
"""Real installed questionnaire, native status writer and Overview; no live model."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import proof
from map_journey import Client
from map_frames import wait_frame
from native_visual import capture


def run(receipts):
 receipts.mkdir(mode=0o700,parents=True,exist_ok=False)
 result={'status':'FAIL','outcomes':{}};base=Path(tempfile.mkdtemp(prefix='oq-',dir='/tmp'));run_id=proof.make_run_id();server=client=http=None
 try:
  package=Path.home()/'.pi/agent/npm/node_modules/@juicesharp/rpiv-ask-user-question/index.ts'
  stock=Path.home()/'.pi/agent/extensions/herdr-agent-state.ts'
  if not package.exists() or not stock.exists():raise proof.ProofBlocked('installed public question package/native state writer unavailable')
  root,state,env=proof.setup_herdr_run(run_id,base)
  real_pi=shutil.which('pi')
  proof.json_dump(receipts/'execution-target.json', {
   'executable':real_pi,'sha256':hashlib.sha256(Path(real_pi).read_bytes()).hexdigest(),
   'PATH':os.environ['PATH'],
   'runtime_manifest':json.loads(Path(os.environ['QUESTION_RUNTIME_MANIFEST']).read_text()) if os.environ.get('QUESTION_RUNTIME_MANIFEST') else None,
  })
  # Real installed packages are read-only evidence; private fixtures select them explicitly.
  config=Path(env['HERDR_CONFIG_PATH']);config.write_text(config.read_text().replace('[ui]','[ui]\nstatus_indicators = "symbols"'))
  (root/'config/session-recap/config.toml').write_text('auto_publish = false\n')
  request_log=[]
  (root/'release-question').touch()
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));request_log.append(body);proof.json_dump(receipts/'provider-requests.json',request_log)
    messages=body['messages'];last=messages[-1];followup=last.get('role')=='tool' or '/proof-' in str(last.get('content'))
    if followup:
     proof.wait_for(lambda:(root/'release-response').exists(),'scripted follow-up release',timeout=90)
     delta={'role':'assistant','content':'Scripted completed questionnaire turn.'};finish='stop'
    else:
     proof.wait_for(lambda:(root/'release-question').exists(),'scripted question release',timeout=90)
     args={'questions':[{'question':'Choose the synthetic delivery path','header':'Delivery','options':[{'label':'Proceed','description':'Scripted safe choice'},{'label':'Adjust','description':'Scripted alternative'}]}]}
     if 'invalid' in str(last.get('content')):args['questions'][0]['options']=[]
     delta={'role':'assistant','tool_calls':[{'index':0,'id':'question-'+str(len(request_log)),'type':'function','function':{'name':'ask_user_question','arguments':json.dumps(args)}}]};finish='tool_calls'
    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
    common={'id':'scripted-question','object':'chat.completion.chunk','created':1,'model':'scripted-model'}
    for value in ({**common,'choices':[{'index':0,'delta':delta,'finish_reason':None}]},{**common,'choices':[{'index':0,'delta':{},'finish_reason':finish}]}):self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode())
    self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
  http=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=http.serve_forever,daemon=True).start()
  extension=root/'provider.mjs';proof.make_pi_provider_extension(extension)
  extension.write_text(extension.read_text().replace('export default function (pi) {', """
import {appendFileSync} from 'node:fs';
export default function (pi) {
 const log = d => appendFileSync(process.env.QUESTION_EVENTS, JSON.stringify(d)+'\\n');
 pi.events.on('rpiv:ask-user:blocked', d=>log({channel:'rpiv:ask-user:blocked',...d}));
 pi.on('session_start',(e,ctx)=>log({channel:'session_start',reason:e.reason,mode:ctx.mode,session:ctx.sessionManager.getSessionId(),file:ctx.sessionManager.getSessionFile()}));
 pi.on('agent_settled',(_e,ctx)=>log({channel:'agent_settled',idle:ctx.isIdle(),session:ctx.sessionManager.getSessionId()}));
 pi.on('session_shutdown',(e,ctx)=>log({channel:'session_shutdown',reason:e.reason,idle:ctx.isIdle(),session:ctx.sessionManager.getSessionId()}));
 pi.on('tool_result',e=>log({channel:'tool_result',name:e.toolName,isError:e.isError,content:e.content}));
 pi.registerCommand('proof-reload',{description:'Public reload fixture',handler:async(_a,ctx)=>{log({channel:'command',name:'reload'});try {await ctx.reload();} catch(error) {log({channel:'command-error',name:'reload',message:String(error)});}}});
 pi.registerCommand('proof-new',{description:'Public new-session fixture',handler:async(_a,ctx)=>{log({channel:'command',name:'new'});try {const result=await ctx.newSession();log({channel:'command-result',name:'new',result});} catch(error) {log({channel:'command-error',name:'new',message:String(error)});}}});
 pi.registerCommand('proof-switch',{description:'Public session-switch fixture',handler:async(a,ctx)=>{log({channel:'command',name:'switch'});await ctx.switchSession(a.trim());}});
 pi.registerCommand('proof-quit',{description:'Public orderly shutdown fixture',handler:async(_a,ctx)=>ctx.shutdown()});
 let foreign=false;
 pi.on('before_agent_start',(e)=>{if(e.prompt.includes('overlap')){foreign=true;pi.events.emit('herdr:blocked',{active:true,label:'Foreign fixture'});}});
 pi.on('agent_settled',()=>{if(foreign){foreign=false;pi.events.emit('herdr:blocked',{active:false});}});
"""))
  # Real read-only package registration/execution. Only the public custom-UI
  # completion boundary is faulted, after the real dialog has rendered and closed.
  boundary=root/'question-boundary.mjs'
  boundary.write_text("""
import register from """+json.dumps(str(package))+""";
import {existsSync, appendFileSync} from 'node:fs';
export default function(pi) {
 register(new Proxy(pi,{get(target,key){
  if(key !== 'registerTool') return Reflect.get(target,key);
  return tool => pi.registerTool({...tool,async execute(id,params,signal,update,ctx){
   const ui={...ctx.ui,custom:async (...args)=>{
    const result=await ctx.ui.custom(...args);
    if(existsSync(process.env.QUESTION_UI_FAULT)) {
     appendFileSync(process.env.QUESTION_EVENTS,JSON.stringify({channel:'controlled-ui-error',boundary:'custom completion after real user dismissal'})+'\\n');
     throw new Error('Controlled public custom UI completion fault');
    }
    return result;
   }};
   return tool.execute(id,params,signal,update,{...ctx,ui});
  }});
 }}));
}
""")
  env['QUESTION_UI_FAULT']=str(root/'ui-fault')
  env['HERDR_OVERVIEW_TEST_PROVIDER_URL']=f'http://127.0.0.1:{http.server_address[1]}/v1';env['QUESTION_EVENTS']=str(root/'question-events.jsonl')
  real_pi=shutil.which('pi');proof.write_exec(root/'bin/pi','#!/bin/sh\nset -eu\nexec '+shlex.quote(real_pi)+' "$@"\n')
  server=subprocess.Popen([state['herdr_bin'],'server'],env=env,cwd=root,stdout=(receipts/'server.log').open('wb'),stderr=subprocess.STDOUT)
  proof.wait_for(lambda:Path(state['socket_path']).exists() and proof.server_status(state,env).get('running'),'owned native server')
  work=root/'work';work.mkdir();proof.herdr_cmd(state,env,'workspace','create','--cwd',str(work),'--label','Question fixture')
  pane=proof.snapshot(state)['panes'][0];pid=pane['pane_id']
  proof.herdr_cmd(state,env,'agent','start','question-fixture','--kind','pi','--pane',pid,'--timeout','120000','--','--provider','herdr-proof-scripted','--model','scripted-model','--extension',str(stock),'--extension',str(boundary),'--extension',str(proof.ROOT/'dot_pi/private_agent/extensions/herdr-overview/index.ts'),'--extension',str(extension),'--no-skills','--no-prompt-templates','--no-themes','--no-context-files','--offline','--approve','--session-dir',str(root/'pi-sessions'),timeout=130)
  client=Client(state,env,120,max_drain=.5);client.drain(3)
  def wait_ui(marker):
   def visible():
    client.drain(.2);return marker in '\n'.join(client.screen.display)
   return proof.wait_for(visible,'real Pi UI '+marker)
  def type_command(text):
   client.key(b'\x1b[200~'+text.encode()+b'\x1b[201~');client.key(b'\r')
  def native():return next(p for p in proof.snapshot(state)['panes'] if p['pane_id']==pid)
  def status(value):return proof.wait_for(lambda:native() if native()['agent_status']==value else None,'native '+value)
  def save(name):
   proof.json_dump(receipts/(name+'-snapshot.json'),proof.snapshot(state));(receipts/(name+'-frame.txt')).write_text(client.frame())
   proof.json_dump(receipts/(name+'-cells.json'),[[dict(text=client.screen.buffer[y][x].data,fg=client.screen.buffer[y][x].fg,bg=client.screen.buffer[y][x].bg) for x in range(client.screen.columns)] for y in range(client.screen.lines)])
   records=[json.loads(p.read_text()) for p in (Path(env['XDG_STATE_HOME'])/'herdr-overview/pi-sessions').glob('*.json')]
   proof.json_dump(receipts/(name+'-publishers.json'),records)
  def overview(name):
   proof.api_request(state,'plugin.action.invoke',dict(action_id='overview.open'));wait_frame(client,'Awaiting answer');value=capture(client,receipts,name);assert any(c['text']=='×' and c['fg']=='f7768e' for row in value['cells'] for c in row);client.key(b'q')
  for action in ('answer','cancel','overlap','error'):
   (root/'release-response').unlink(missing_ok=True)
   (root/'release-question').unlink(missing_ok=True)
   proof.herdr_cmd(state,env,'agent','prompt','question-fixture','Synthetic '+action,timeout=30)
   if action=='answer':status('working')
   save(action+'-before-ui')
   (root/'release-question').touch()
   wait_ui('Choose the synthetic delivery path');status('blocked');save(action+'-wait')
   assert native()['state_labels'].get('blocked')=='Awaiting answer'
   client.key(b'\x1d');status('blocked');save(action+'-collapsed')
   assert any(c['text']=='×' and c['fg']=='f7768e' for row in json.loads((receipts/(action+'-collapsed-cells.json')).read_text()) for c in row)
   overview(action+'-overview')
   client.key(b'\x1d');wait_ui('Choose the synthetic delivery path')
   if action=='error':(root/'ui-fault').touch()
   client.key(b'\r' if action in ('answer','error') else b'\x1b');status('blocked' if action=='overlap' else 'working');save(action+'-working')
   assert native().get('state_labels',{}).get('blocked')!='Awaiting answer'
   (root/'ui-fault').unlink(missing_ok=True)
   (root/'release-response').touch();status('idle');client.drain(.5);save(action+'-settled');
   result['outcomes'][action]={'actual_wait_collapse_clear':True,'foreign_blocker_preserved':action=='overlap','ready':native()['agent_status']=='idle'}
   if native()['agent_status']!='idle':result.setdefault('blockers',[]).append(action+': installed stock writer retains working after completed scripted turn')
  # Invalid UI invocation and noninteractive/absent-package paths must not emit wait.
  before=(root/'question-events.jsonl').read_text().count('"active":true')
  proof.herdr_cmd(state,env,'agent','prompt','question-fixture','Synthetic invalid',timeout=30)
  client.drain(2);save('invalid');assert (root/'question-events.jsonl').read_text().count('"active":true')==before
  result['outcomes']['invalid-no-wait']=True
  (root/'release-response').touch()
  for package_present in (True,False):
   private_env={**env,'HERDR_ENV':'0'};private_env.pop('HERDR_PANE_ID',None)
   argv=[real_pi,'--print','--no-session','--offline','--approve','--provider','herdr-proof-scripted','--model','scripted-model','--extension',str(extension),'--no-skills','--no-prompt-templates','--no-themes','--no-context-files']
   if package_present:argv.extend(['--extension',str(package)])
   argv.append('Synthetic no UI')
   completed=subprocess.run(argv,env=private_env,cwd=root,capture_output=True,text=True,timeout=45)
   name='no-ui' if package_present else 'absent-package';(receipts/(name+'.stdout')).write_text(completed.stdout);(receipts/(name+'.stderr')).write_text(completed.stderr);proof.json_dump(receipts/(name+'-command.json'),dict(argv=argv,exit=completed.returncode))
   assert completed.returncode==0 and (root/'question-events.jsonl').read_text().count('"active":true')==before
   result['outcomes'][name]=True
  def events():return [json.loads(line) for line in (root/'question-events.jsonl').read_text().splitlines()]
  def starts():return [e for e in events() if e['channel']=='session_start' and e.get('mode')=='tui']
  def no_question():assert native().get('state_labels',{}).get('blocked')!='Awaiting answer'
  initial=starts()[-1];original_session=initial['session'];original_file=initial['file']
  for control in ('reload','new'):
   (root/'release-response').unlink(missing_ok=True)
   proof.herdr_cmd(state,env,'agent','prompt','question-fixture','Synthetic active '+control,timeout=30)
   wait_ui('Choose the synthetic delivery path');status('blocked');client.key(b'\x1d');save('active-before-'+control)
   count=len(starts());commands=len([e for e in events() if e['channel']=='command'])
   type_command('/proof-'+control);client.drain(1);save('active-'+control+'-requested')
   assert len(starts())==count
   assert native()['agent_status']=='blocked' and native()['state_labels'].get('blocked')=='Awaiting answer'
   result['outcomes']['active-'+control+'-request']={'completed':False,'interpretation':'public command submitted while hidden dialog waits; no session transition completed', 'events':events()[-3:]}
   client.key(b'\x1d');wait_ui('Choose the synthetic delivery path');client.key(b'\x1b')
   proof.wait_for(lambda:native()['agent_status']=='working' or len(starts())>count,'wait ended or lifecycle transition')
   no_question();save(control+'-after-wait')
   (root/'release-response').touch();status('idle');no_question();save(control+'-after-wait-ready')
   # Reload refuses while busy; new waits for UI then replaces/aborts the turn.
   # Retry only when the original public request did not complete after settling.
   client.drain(1)
   if len(starts())==count:
    client.key(b'\x15');type_command('/proof-'+control)
   proof.wait_for(lambda:len(starts())>count,'actual '+control+' session_start')
   marker=starts()[-1];assert marker['reason']==control
   if control=='reload':assert marker['session']==original_session
   else:assert marker['session']!=original_session
   client.drain(1);no_question();save(control+'-completed')
   result['outcomes'][control+'-completed']={'marker':marker,'native_status':native()['agent_status'],'no_question_badge':True}
  count=len(starts());type_command('/proof-switch '+original_file)
  proof.wait_for(lambda:len(starts())>count,'actual session switch')
  marker=starts()[-1];assert marker['reason']=='resume' and marker['session']==original_session
  client.drain(1);no_question();save('switch-completed')
  result['outcomes']['switch-completed']={'marker':marker,'no_question_badge':True}
  assert any(e['channel']=='controlled-ui-error' for e in events())
  assert any(e['channel']=='tool_result' and e.get('isError') and 'Controlled public custom UI completion fault' in str(e) for e in events())
  # Ordinary public shutdown, not a kill pretending to be a lifecycle event.
  shutdown_offset=len(events())
  type_command('/proof-quit')
  proof.wait_for(lambda:any(e['channel']=='session_shutdown' and e['reason']=='quit' and e['session']==original_session for e in events()[shutdown_offset:]),'orderly public quit')
  client.drain(1);no_question();save('shutdown')
  result['outcomes']['ordinary-shutdown']={'native_status':native()['agent_status'],'no_question_badge':True}
  result['status']='PASS' if not result.get('blockers') else 'BLOCKED'
 except Exception as exc:
  (receipts/'failure-traceback.txt').write_text(traceback.format_exc());result['reason']=repr(exc)
 finally:
  if client:(receipts/'host-output.bin').write_bytes(client.output);client.close()
  if 'root' in locals() and (root/'question-events.jsonl').exists():(receipts/'question-events.jsonl').write_bytes((root/'question-events.jsonl').read_bytes())
  if 'root' in locals():
   try:proof.json_dump(receipts/'final-native.json',proof.snapshot(state))
   except Exception:pass
   (root/'release-response').touch();(root/'release-question').touch()
  if http:
   http.shutdown();http.server_close();result['local_http_provider_stopped']=True
  if server:
   try:result['cleanup']=proof.scenario_cleanup(run_id,base)
   except Exception as exc:result['cleanup_error']=repr(exc)
   try:server.wait(timeout=8)
   except subprocess.TimeoutExpired:server.terminate();server.wait(timeout=8)
  proof.json_dump(receipts/'result.json',result)
 return result

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--receipts',type=Path,required=True);args=parser.parse_args();value=run(args.receipts.resolve());print(json.dumps(value));raise SystemExit(0 if value['status']=='PASS' else 1)
