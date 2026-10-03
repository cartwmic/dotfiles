import test from 'node:test';
import assert from 'node:assert/strict';
import {InputDecoder,hitPane} from '../src/input.mjs';
import {mapFrame,mapLines} from '../src/presenters/map.mjs';
import {createJourney,moveDirection,scrollOverview} from '../src/navigation.mjs';
import {normalizeSnapshot} from '../src/model.mjs';
import {snapshot} from './popup-fixture.mjs';
test('streaming mouse/arrow packets and bounded standalone escape never leak commands',()=>{
  for(const packet of ['\x1b[A','\x1b[B','\x1b[C','\x1b[D','\x1b[<0;6;8M','\x1b[<65;6;8M']) {
    const whole=new InputDecoder().push(Buffer.from(packet));
    for(let i=1;i<packet.length;i++){ const restart=new InputDecoder();restart.push(Buffer.from('\x1b[<0;'));assert.deepEqual(restart.push(Buffer.from('\x1b')),[]);assert.deepEqual(restart.flush(),['escape']);
  const malformed=new InputDecoder();assert.deepEqual(malformed.push(Buffer.from('\x1b[<garbagef;qM')),[]);
  const d=new InputDecoder(); assert.deepEqual(d.push(Buffer.from(packet.slice(0,i))),[]);assert.deepEqual(d.push(Buffer.from(packet.slice(i))),whole); }
  }
  const d=new InputDecoder(); assert.deepEqual(d.push(Buffer.from('\x1b')),[]);assert.deepEqual(d.flush(),['escape']);
  assert.deepEqual(d.push(Buffer.from('\x1b[<0;6;8m\x1b[<32;6;8M\x1b[99~')),[]);
});
test('renderer rectangles drive movement, click projection and independent bounded viewport',()=>{
  const model=normalizeSnapshot(snapshot());let journey=createJourney(model);
  let state={model,journey};let frame=mapFrame(state,100,24);
  assert.equal(moveDirection(journey,model,frame.rectangles,'l').paneId,'p2');
  assert.equal(moveDirection(journey,model,frame.rectangles,'h').paneId,'p1');
  const r=frame.rectangles.find(r=>r.paneId==='p2');assert.equal(hitPane(frame,r.x+2,r.y-frame.viewport.offset+frame.viewport.y+2),'p2');
  assert.equal(hitPane(frame,r.x-1,r.y+frame.viewport.y),null);
  journey=scrollOverview(journey,999);frame=mapFrame({model,journey},100,24);assert.equal(journey.paneId,'p1');assert.equal(frame.viewport.offset,frame.viewport.max);
  journey.ensureVisible=true;frame=mapFrame({model,journey},40,24);assert.equal(journey.paneId,'p1');assert.ok(frame.viewport.offset<=frame.rectangles.find(r=>r.paneId==='p1').y);
});
test('all cards show published producer metadata, short text is honest and failed attempt stays separate',()=>{
 const model=normalizeSnapshot(snapshot());model.panes.p1.recap={latest:{status:'published',record_id:'good',published_at:'Producer local 02:30 +09',summary:'Short recap.'},lastAttempt:{status:'failed',record_id:'bad'}};
 model.panes.p2.recap={latest:{status:'published',created_at:'Producer fallback',summary:'Long recap '.repeat(30)}};
 const body=mapLines({model,journey:createJourney(model)},120).body.join('\n').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'');
 assert.match(body,/Producer local 02:30 \+09/);assert.match(body,/Short recap\./);assert.doesNotMatch(body,/Short recap\.\s*…/);assert.match(body,/Newer attempt failed/);assert.match(body,/Producer fallback/);assert.match(body,/…/);
});
