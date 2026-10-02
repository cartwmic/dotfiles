import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdir, mkdtemp, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { normalizeSnapshot } from '../src/model.mjs';
import { runOverviewPane, renderOverview } from '../src/pane.mjs';
import { snapshot } from './popup-fixture.mjs';
const wait = async predicate => { for (let n=0;n<200;n++) { if (predicate()) return; await new Promise(r=>setTimeout(r,5)); } throw Error('view timeout'); };
test('theme uses validated typed tokens', () => {
  const text = renderOverview({ model: normalizeSnapshot(snapshot()), theme: { palette: { accent: { kind:'rgb', hex:'#010203' } } } },100,30);
  assert.match(text, /\x1b\[38;2;1;2;3mHerdr Overview/);
});
test('real pane loop serializes keys, refreshes saved native changes, exact rekey focus exits, closes input/watchers', async t => {
  const root=await mkdtemp(path.join(os.tmpdir(),'overview-pane-')); t.after(()=>rm(root,{recursive:true,force:true}));
  const stateDir=path.join(root,'state'); await mkdir(stateDir);
  const configPath=path.join(root,'config.toml'); await writeFile(configPath,'[theme]\nname="terminal"\n');
  let native=snapshot(); await writeFile(path.join(stateDir,'overview.json'),JSON.stringify({model:normalizeSnapshot(native)}));
  const input=new EventEmitter(); Object.assign(input,{isTTY:true,isRaw:false,setRawMode(value){this.isRaw=value;},resume(){},pause(){}});
  const output=new EventEmitter(); const frames=[]; Object.assign(output,{columns:40,rows:24,isTTY:false,write(text){frames.push(text);}});
  const calls=[]; let fail=true;
  const api={async snapshot(){calls.push('snapshot'); return native;},async focusPane(id){calls.push(`focus:${id}`); if(fail)throw Error('synthetic focus failure');}};
  const running=runOverviewPane({api,stateDir,configPath,dataRoot:path.join(root,'recaps'),input,output});
  t.after(async()=>{input.emit('data',Buffer.from('q')); await running;});
  await wait(()=>input.listenerCount('data')>0);
  input.emit('data',Buffer.from(']f')); await wait(()=>frames.some(frame=>frame.includes('Could not focus')));
  assert.deepEqual(calls.filter(call=>call.startsWith('focus:')),['focus:p2']); assert.equal(input.listenerCount('data'),1);
  native.panes[1].pane_id='moved';
  await writeFile(path.join(stateDir,'overview.json'),JSON.stringify({model:normalizeSnapshot(native)}));
  await wait(()=>frames.at(-1).includes('› Tab 2'));
  output.columns=100; output.emit('resize'); assert.match(frames.at(-1),/› Tab 2/);
  input.emit('data',Buffer.from('d')); await wait(()=>frames.at(-1).includes('Unavailable'));
  input.emit('data',Buffer.from('\x1b')); await wait(()=>frames.at(-1).includes('Supplied prompt'));
  fail=false; input.emit('data',Buffer.from('f')); await running;
  assert.equal(calls.at(-1),'focus:moved'); assert.equal(input.isRaw,false); assert.equal(input.listenerCount('data'),0);
  assert.ok(calls.every(call=>call==='snapshot'||call.startsWith('focus:')),'no output reads or generation');
});
test('failed snapshot and vanished selection cannot focus cached or unrelated native pane', async t => {
  const root=await mkdtemp(path.join(os.tmpdir(),'overview-fail-')); t.after(()=>rm(root,{recursive:true,force:true}));
  await writeFile(path.join(root,'overview.json'),JSON.stringify({model:normalizeSnapshot(snapshot())}));
  const input=new EventEmitter(); Object.assign(input,{isTTY:true,setRawMode(v){this.isRaw=v;},resume(){},pause(){}});
  const frames=[]; const output={columns:60,rows:24,write(text){frames.push(text);}}; let focuses=0;
  const api={async snapshot(){throw Error('offline');},async focusPane(){focuses++;}};
  const run=runOverviewPane({api,stateDir:root,configPath:path.join(root,'missing'),input,output});
  await wait(()=>input.listenerCount('data'));
  input.emit('data',Buffer.from('f')); await new Promise(r=>setTimeout(r,30));
  assert.equal(focuses,0); assert.match(frames.at(-1),/offline/);
  input.emit('data',Buffer.from('q')); await run;
});

test('EOF and input/output errors restore owned mouse modes and prior raw state',async t=>{
 const root=await mkdtemp(path.join(os.tmpdir(),'overview-cleanup-'));t.after(()=>rm(root,{recursive:true,force:true}));
 await writeFile(path.join(root,'overview.json'),JSON.stringify({model:normalizeSnapshot(snapshot())}));
 for(const event of ['end','input-error','output-error']) {
  const input=new EventEmitter(),output=new EventEmitter(),writes=[];
  Object.assign(input,{isTTY:true,isRaw:false,setRawMode(v){this.isRaw=v},resume(){},pause(){}});Object.assign(output,{columns:100,rows:24,write(text){writes.push(text)}});
  const running=runOverviewPane({api:{async snapshot(){return snapshot()}},stateDir:root,configPath:path.join(root,'missing'),dataRoot:path.join(root,'recaps'),input,output});
  const completed=event==='end'?running:assert.rejects(running,/synthetic/);
  await wait(()=>input.listenerCount('data'));input.emit('data',Buffer.from('\x1b[<0;'));
  if(event==='end')input.emit('end');else (event==='input-error'?input:output).emit('error',Error('synthetic'));
  await completed;assert.equal(input.isRaw,false);assert.ok(writes.join('').includes('\x1b[?1000h'));assert.ok(writes.join('').includes('\x1b[?1006l\x1b[?1000l'));assert.equal(input.listenerCount('data'),0);
 }
});
