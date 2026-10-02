#!/usr/bin/env python3
"""Owned attached-client Overview input and whole-frame/reference proof."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import shlex
import tempfile
import traceback
import time
import proof
from map_journey import Client, log_digest, require_busy
from map_frames import canvas, selected_in_frame, wait_frame
from native_visual import capture

BROWSER = r'''
import json,sys,base64,re
from pathlib import Path
from playwright.sync_api import sync_playwright
reference,output,datafile=sys.argv[1:]
data=json.loads(Path(datafile).read_text())
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 page=browser.new_page()
 page.goto(Path(reference).resolve().as_uri())
 for width in (40,48,120,180):
  page.set_viewport_size({'width':width*9,'height':32*18})
  page.evaluate(''' + "'''" + r'''data=>{workspaces.splice(0,workspaces.length,...data);selected=data[0].tabs[0].panes[0].id;expanded=null;render();updateWidth();const panes=data.flatMap(w=>w.tabs.flatMap(t=>t.panes));const counts=document.querySelector('.counts').children;counts[0].textContent='!'+panes.filter(p=>p.status==='blocked').length+' needs input';counts[1].textContent='W'+panes.filter(p=>p.status==='working').length+' working';counts[2].textContent='R'+panes.filter(p=>p.status==='idle').length+' ready';counts[3].textContent=data.length+' workspaces · '+data.reduce((n,w)=>n+w.tabs.length,0)+' tabs';document.querySelectorAll('.review').forEach(e=>e.style.display='none');document.querySelectorAll('[data-pane]').forEach(e=>{const p=data.flatMap(w=>w.tabs.flatMap(t=>t.panes)).find(p=>p.id===e.dataset.pane);const time=e.querySelector('time');if(time)time.textContent=p.date;if(p.status==='blocked')e.querySelector('.status').textContent='× '+(p.question?'Awaiting answer':'BLOCKED');});}''' + "'''" + r''',data)
  (Path(output)/f'reference-header-{width}.json').write_text(json.dumps(page.locator('.counts').inner_text()))
  page.screenshot(path=str(Path(output)/f'reference-{width}.png'),full_page=True)
 for svg in Path(output).glob('native-*.svg'):
  size=re.search(r'width="(\d+)" height="(\d+)"',svg.read_text());page.set_viewport_size({'width':int(size[1]),'height':int(size[2])});page.set_content('<body style="margin:0"><img src="data:image/svg+xml;base64,'+base64.b64encode(svg.read_bytes()).decode()+'"></body>');page.locator('img').screenshot(path=str(svg.with_suffix('.png')),timeout=60000)
 browser.close()
'''


def run(receipts, reference, browser_python):
 receipts.mkdir(mode=0o700, parents=True, exist_ok=False)
 run_id=proof.make_run_id();base=Path(tempfile.mkdtemp(prefix='oi-',dir='/tmp'));server=client=None
 result={'status':'FAIL','outcomes':{},'reference_sha256':hashlib.sha256(reference.read_bytes()).hexdigest()}
 try:
  root,state,env=proof.setup_herdr_run(run_id,base)
  config=Path(env['HERDR_CONFIG_PATH']);config.write_text(config.read_text().replace('[ui]','[ui]\nmouse_capture = true\nstatus_indicators = "symbols"'))
  server=subprocess.Popen([state['herdr_bin'],'server'],env=env,cwd=root,stdout=(receipts/'server.log').open('wb'),stderr=subprocess.STDOUT)
  proof.wait_for(lambda:Path(state['socket_path']).exists() and proof.server_status(state,env).get('running'),'owned server')
  work=root/'work';work.mkdir()
  reference_data=[];sources=[];blocked_panes=[];records=root/'data/session-recap/records/2026-10-02';records.mkdir(parents=True)
  def rename(kind,id,label):proof.api_request(state,kind+'.rename',{kind+'_id':id,'label':label})
  for w in range(2):
   proof.herdr_cmd(state,env,'workspace','create','--cwd',str(work),'--label',f'Synthetic workspace {w+1}')
   snap=proof.snapshot(state);ws=snap['workspaces'][-1];wsid=ws['workspace_id'];tabs=[]
   for t in range(3):
    if t:proof.herdr_cmd(state,env,'tab','create','--workspace',wsid,'--cwd',str(work),'--label',f'Work {w+1}.{t+1}','--no-focus')
    snap=proof.snapshot(state);tab=[tab for tab in snap['tabs'] if tab['workspace_id']==wsid][-1]
    label=['Deployment readiness','Policy review','部署 😀 rollback pair'][t]+f' {w+1}';rename('tab',tab['tab_id'],label)
    pane=next(p for p in snap['panes'] if p['tab_id']==tab['tab_id'])
    if t==2:proof.herdr_cmd(state,env,'pane','split',pane['pane_id'],'--direction','right','--cwd',str(work),'--no-focus')
    panes=[]
    for n,pane in enumerate(p for p in proof.snapshot(state)['panes'] if p['tab_id']==tab['tab_id']):
     name=label if t<2 else ['部署 😀 rollback verification','Peer review notes'][n]+f' {w+1}';rename('pane',pane['pane_id'],name)
     summary='' if t==1 else 'Short verified recap.' if n==1 else 'The release candidate passed the configuration checks. Preserve the rollback artifact and wait for owner approval. '*4
     date='Producer Oct 2 · 11:05 UTC' if w==0 else 'Producer fallback · 20:05 +09'
     rid=f'good-{w}-{t}-{n}';failure=t==0
     if summary:
      value=dict(schema_version=1,record_id=rid,status='published',source_kind='manual',source_id=pane['pane_id'],pane_id=pane['pane_id'],summary=summary,**({'published_at':date} if w==0 else {'created_at':date}))
      proof.json_dump(records/(rid+'.json'),value)
      item=dict(source_kind='manual',source_id=pane['pane_id'],latest_success_id=rid,last_attempt_id=rid)
      if failure:
       failed=dict(schema_version=1,record_id=rid+'-failed',status='failed',source_kind='manual',source_id=pane['pane_id'],pane_id=pane['pane_id'],created_at='Producer newer attempt',failure=dict(message='Scripted failure; previous good retained'))
       proof.json_dump(records/(failed['record_id']+'.json'),failed);item['last_attempt_id']=failed['record_id']
      sources.append(item)
     status='blocked' if t==2 and n==0 else 'none'
     if status=='blocked':
      blocked_panes.append((pane,w==0))
     panes.append(dict(id=pane['pane_id'],name=name,status=status,question=status=='blocked' and w==0,agent='Pi' if status=='blocked' else 'Manual',recap=summary,date=date,failure='Newer attempt failed' if failure else ''))
    tabs.append(dict(number=t+1,name=label,manual=True,panes=panes))
   reference_data.append(dict(name=f'Synthetic workspace {w+1}',tabs=tabs))
  proof.json_dump(root/'data/session-recap/latest.json',dict(sources=sources))
  provider=proof.ensure_scripted_provider(root,state,env);extension=root/'scripted-provider.mjs';proof.make_pi_provider_extension(extension)
  real_pi=shutil.which('pi');stock=Path.home()/'.pi/agent/extensions/herdr-agent-state.ts'
  if not real_pi or not stock.exists():raise proof.ProofBlocked('real Pi/native writer unavailable for synthetic status fixture')
  proof.write_exec(root/'bin/pi','#!/bin/sh\nset -eu\nIFS= read -r HERDR_OVERVIEW_TEST_PROVIDER_URL < "$HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE"\nexport HERDR_OVERVIEW_TEST_PROVIDER_URL\nexec '+shlex.quote(real_pi)+' "$@"\n')
  Path(env['HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE']).write_text(provider['url']+'\n')
  (root/'config/session-recap/config.toml').write_text('auto_publish = false\n')
  for number,(pane,question) in enumerate(blocked_panes):
   proof.herdr_cmd(state,env,'agent','start',f'visual-{number}','--kind','pi','--pane',pane['pane_id'],'--timeout','120000','--','--provider','herdr-proof-scripted','--model','scripted-model','--extension',str(stock),'--extension',str(extension),'--extension',str(proof.ROOT/'dot_pi/private_agent/extensions/herdr-overview/index.ts'),'--no-tools','--no-skills','--no-prompt-templates','--no-themes','--no-context-files','--offline','--approve','--session-dir',str(root/'pi-sessions'),timeout=130)
   session=proof.wait_for(lambda:next((p.get('agent_session') for p in proof.snapshot(state)['panes'] if p['pane_id']==pane['pane_id'] and p.get('agent_session',{}).get('agent')=='pi'),None),'real native Pi session reference')
   field='agent_session_path' if session['kind']=='path' else 'agent_session_id'
   proof.api_request(state,'pane.report_agent',dict(pane_id=pane['pane_id'],source='herdr:pi',agent='pi',state='blocked',**{field:session['value']},seq=time.time_ns()//1000))
   if question:proof.api_request(state,'pane.report_metadata',dict(pane_id=pane['pane_id'],source='herdr:overview-question',agent='pi',applies_to_source='herdr:pi',state_labels={'blocked':'Awaiting answer'},seq=time.time_ns()//1000))
  native=proof.snapshot(state);first=native['panes'][0];proof.api_request(state,'pane.focus',dict(pane_id=first['pane_id']))
  proof.api_request(state,'plugin.action.invoke',dict(action_id='overview.refresh_names'))
  baseline=log_digest(root);proof.json_dump(receipts/'native-fixture.json',proof.snapshot(state));proof.json_dump(receipts/'reference-data.json',reference_data)
  def open_map():
   proof.api_request(state,'plugin.action.invoke',dict(action_id='overview.open'));wait_frame(client,'Esc/q');require_busy(state,receipts,f'busy-{time.time_ns()}')
  def click_visible(label):
   rows=client.frame().splitlines();oy=next(y for y,row in enumerate(rows) if 'Herdr Overview' in row and row[row.index('Herdr Overview')-1]!='┌');ox=rows[oy].index('Herdr Overview');target=next((y,row.index(label)) for y,row in enumerate(canvas(client.frame())) if label in row)
   host(f'\x1b[<0;{ox+target[1]+max(2,len(label)//2)};{oy+target[0]+2}M');host(f'\x1b[<0;{ox+target[1]+max(2,len(label)//2)};{oy+target[0]+2}m')
  def selected(id):
   if not selected_in_frame(client.frame(),id,proof.snapshot(state)):raise proof.ProofFailure(f'expected selected native pane {id}')
  def host(packet):
   with (receipts/'host-input.jsonl').open('a') as f:f.write(json.dumps(packet)+'\n')
   client.key(packet.encode())
  for width in (40,48,120,180):
   if client:client.close()
   client=Client(state,env,width);client.drain(2);open_map();selected(first['pane_id'])
   capture(client,receipts,f'native-{width}-collapsed')
   rows=client.frame().splitlines();oy=next(y for y,row in enumerate(rows) if 'Herdr Overview' in row and row[row.index('Herdr Overview')-1]!='┌');ox=rows[oy].index('Herdr Overview')
   frame=canvas(client.frame());target=next((y,row.index('Tab 2')) for y,row in enumerate(frame) if 'Tab 2' in row)
   focus_before=proof.snapshot(state)['focused_pane_id']
   host(f'\x1b[<0;{ox+target[1]+2};{oy+target[0]+1}M');host(f'\x1b[<0;{ox+target[1]+2};{oy+target[0]+1}m')
   second=reference_data[0]['tabs'][1]['panes'][0]['id'];selected(second)
   assert proof.snapshot(state)['focused_pane_id']==focus_before
   host(f'\x1b[<0;{ox+4};{oy+1}M');host(f'\x1b[<0;{ox+4};{oy+1}m');selected(second);host('h');selected(first['pane_id']);host('\x1b[C');selected(second);host('k');selected(second)
   grouped=reference_data[0]['tabs'][2]['panes']
   host('j');selected(grouped[0]['id']);capture(client,receipts,f'native-{width}-question-wait')
   host('j');selected(grouped[1]['id']);capture(client,receipts,f'native-{width}-short-recap')
   host('k');selected(grouped[0]['id']);host('k')
   for _ in range(len(native['panes'])):
    if selected_in_frame(client.frame(),second,proof.snapshot(state)):break
    host(']')
   selected(second)
   if width==180:
    host('l');selected(reference_data[1]['tabs'][0]['panes'][0]['id']);host('h');selected(second)

   # A wheel moves only the viewport; f must still focus the prior selected ID.
   before=canvas(client.frame());host(f'\x1b[<65;{ox+4};{oy+5}M');after=canvas(client.frame());assert before!=after
   capture(client,receipts,f'native-{width}-wheel')
   host('r');refreshed=canvas(client.frame());proof.json_dump(receipts/f'refresh-{width}.json',dict(before=after,after=refreshed));assert refreshed==after
   click_visible('Deployment');selected(first['pane_id']);assert proof.snapshot(state)['focused_pane_id']==focus_before
   capture(client,receipts,f'native-{width}-click-after-wheel')
   host('h');selected(first['pane_id'])
   for pane in native['panes'][1:]:
    host(']');selected(pane['pane_id'])
    if pane['pane_id']==reference_data[1]['tabs'][2]['panes'][0]['id']:capture(client,receipts,f'native-{width}-generic-blocker')
   host(']');selected(first['pane_id'])
   host('\r');wait_frame(client,'Latest good recap');host(f'\x1b[<65;{ox+4};{oy+5}M');capture(client,receipts,f'native-{width}-reading-wheel')
   host('\x1b');selected(first['pane_id'])
   client.resize(180 if width<100 else 40);selected(first['pane_id']);click_visible('Tab 2');selected(second);assert proof.snapshot(state)['focused_pane_id']==focus_before;client.resize(width);selected(second);host('h');selected(first['pane_id'])
   host('q');open_map();selected(first['pane_id']);capture(client,receipts,f'native-{width}-reopened')
   click_visible('Tab 2');selected(second);assert proof.snapshot(state)['focused_pane_id']==focus_before;host('f');proof.wait_for(lambda:proof.snapshot(state)['focused_pane_id']==second,'explicit exact focus')
   proof.api_request(state,'pane.focus',dict(pane_id=first['pane_id']))
   result['outcomes'][str(width)]=dict(click_select_only=True,wheel_independent=True,native_order_reachable=True,directional_edges=True,reading_wheel=True,resize_reopen=True,exact_focus=True)
  assert baseline==log_digest(root),'viewer invoked generation'
  proof.json_dump(receipts/'backend-before-after.json',dict(before=baseline,after=log_digest(root)))
  (receipts/'browser-render.py').write_text(BROWSER)
  command=[str(browser_python),str(receipts/'browser-render.py'),str(reference),str(receipts),str(receipts/'reference-data.json')]
  rendered=subprocess.run(command,capture_output=True,text=True);(receipts/'browser.log').write_text(rendered.stdout+rendered.stderr);proof.json_dump(receipts/'browser-command.json',dict(argv=command,exit=rendered.returncode));assert rendered.returncode==0
  result['status']='PASS';result['independent_visual_review']='pending; inspect full cells/SVG/PNG against reference, not a self-certified visual pass'
 except Exception as exc:
  (receipts/'failure-traceback.txt').write_text(traceback.format_exc());result['reason']=repr(exc)
 finally:
  if client:(receipts/'host-output.bin').write_bytes(client.output);client.close()
  if server:
   try:result['cleanup']=proof.scenario_cleanup(run_id,base)
   except Exception as exc:result['cleanup_error']=repr(exc)
   try:server.wait(timeout=8)
   except subprocess.TimeoutExpired:server.terminate();server.wait(timeout=8)
  proof.json_dump(receipts/'result.json',result)
 return result

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--receipts',type=Path,required=True);parser.add_argument('--reference',type=Path,required=True);parser.add_argument('--browser-python',type=Path,required=True);args=parser.parse_args()
 result=run(args.receipts.resolve(),args.reference.resolve(),args.browser_python.absolute());print(json.dumps(result));raise SystemExit(0 if result['status']=='PASS' else 1)
