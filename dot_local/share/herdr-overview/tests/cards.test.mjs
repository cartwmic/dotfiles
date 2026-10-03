import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeSnapshot } from '../src/model.mjs';
import { createJourney } from '../src/navigation.mjs';
import { mapLines, renderMap, cellWidth } from '../src/presenters/map.mjs';
import { snapshot } from './popup-fixture.mjs';
import { resolvePalette } from '../src/theme.mjs';
test('padded outlined cards and in-place full-width reading replace debug rows', () => {
 const model = normalizeSnapshot(snapshot()); const journey = createJourney(model);
 for (const width of [32,40,48,120]) {
  const lines = mapLines({model,journey},width).body;
  assert.ok(lines.some(l=>l.includes('┌') && l.includes('┐')));
  assert.ok(lines.every(l=>cellWidth(l)<=width));
  assert.ok(lines.some(l=>/│ [› ] Tab/.test(l.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,''))));
  const detail = mapLines({model,journey:{...journey,level:'pane'}},width).body.join('\n');
  // The blocked multi-pane group bubbles above the expanded working Tab 1.
  assert.ok(detail.indexOf('Tab 3') < detail.indexOf('Latest good recap'));
  assert.doesNotMatch(detail,/Process |cwd |\[p1\]/);
 }
 const frame=renderMap({model,journey,theme:resolvePalette({name:'tokyo-night'})},40,40);
 assert.match(frame,/\x1b\[48;2;/);
 assert.match(frame,/needs input/);
});

test('grapheme/cell geometry, typed ANSI roles and prose whitespace remain distinct', async () => {
 const {wrap,paint}=await import('../src/presenters/map.mjs');
 assert.equal(cellWidth('©'),1); assert.equal(cellWidth('©️'),2);
 assert.equal(cellWidth('部署 e\u0301 😀 👩‍💻'),12);
 assert.deepEqual(wrap('alpha beta gamma',10),['alpha ','beta gamma']);
 assert.equal(wrap('  indented\n\nnext',20).join('\n'),'  indented\n\nnext');
 assert.equal(wrap('👩‍💻👩‍💻👩‍💻',4).join(''),'👩‍💻👩‍💻👩‍💻');
 assert.equal(paint({kind:'reset'},true),'\x1b[49m');
 assert.equal(paint({kind:'ansi',name:'darkgray'},true),'\x1b[100m');
 assert.equal(paint({kind:'ansi',name:'lightcyan'}),'\x1b[96m');
 const model=normalizeSnapshot(snapshot());model.tabs.t1.fullTitle='部署 é 😀 long subject';model.tabs.t2.displayNameOwnership={mode:'manual'};
 for(const width of [32,40,48,120,180]) {
  const lines=mapLines({model,journey:createJourney(model),theme:resolvePalette({name:'terminal'})},width).body;
  assert.ok(lines.every(line=>cellWidth(line)<=width));
  assert.match(lines.join('\n'),/Tab 2 M/);
  assert.match(lines.join('\n'),/Subject 3/);assert.match(lines.join('\n'),/Subject 4/);
  assert.match(lines.join('\n'),/\x1b\[100m/);
 }
});

test('late reading anchors, middle passage resize/refresh, digest end and back preserve selected content', async () => {
 const {movePane,scrollDetail,backJourneyLevel}=await import('../src/navigation.mjs');
 const native=snapshot();native.workspaces.push({workspace_id:'late',label:'Late workspace with a long readable name',number:2});
 native.tabs.push({tab_id:'late-tab',workspace_id:'late',label:'Late subject',number:9});
 native.panes.push({pane_id:'late-pane',tab_id:'late-tab',workspace_id:'late',terminal_id:'late-terminal',label:'Late subject',agent:'pi',agent_status:'blocked'});
 const model=normalizeSnapshot(native), pane=model.panes['late-pane'];
 pane.recap={latest:{status:'published',published_at:'2026-10-01',summary:Array.from({length:80},(_,n)=>`Passage ${n} meaningful synthetic text with natural word wrapping`).join('\n')+'\nRECAP-LAST'}};
 pane.digest={status:'available',generatedAt:'2026-10-02',body:'digest line\n'.repeat(80)+'DIGEST-END'};
 let journey={...movePane(createJourney(model),model,2),level:'pane'}; // p3,p4,p1,p2,late
 assert.match(renderMap({model,journey},40,24),/Late subject/);
 journey=scrollDetail(journey,39);renderMap({model,journey},40,24);const position={...journey.readingPosition};
 assert.ok(position.cell>0,'middle wrapped passage exercises a nonzero cell offset');
 for(const width of [120,32,48,40]) { renderMap({model,journey},width,24); assert.deepEqual(journey.readingPosition,position); }
 const before=renderMap({model,journey},40,24);
 journey={...journey,returnReading:{detailScroll:journey.detailScroll,readingPosition:journey.readingPosition},level:'digest',detailScroll:0,readingPosition:null};
 assert.match(renderMap({model,journey},40,24),/Session digest/);
 journey=scrollDetail(journey,9999);assert.match(renderMap({model,journey},40,24),/DIGEST-END/);
 journey=backJourneyLevel(journey);assert.equal(renderMap({model,journey},40,24),before);
});

test('collapsed two-row titles signal omitted rows without truncating expanded titles', () => {
 const model=normalizeSnapshot(snapshot()), journey=createJourney(model);
 model.panes.p3.agent.status='working'; // keep native order so Tab 1 is the first card
 for (const title of ['alpha beta', 'alpha beta gamma delta epsilon zeta eta theta', '部署確認 é 😀 検証作業完了後に安全な公開を確認する']) {
  model.tabs.t1.fullTitle=title;
  for (const width of [32,40,48,120,180]) {
   const inner=Math.floor((width-2)/2)-4;
   const collapsed=mapLines({model,journey},width).body;
   const first=collapsed.slice(0,collapsed.findIndex(line=>line.includes('└'))+1).join('\n').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'');
   assert.ok(collapsed.every(line=>cellWidth(line)<=width));
   // First card contains no omitted-title cue when the complete title fits.
   if(cellWidth(title)<=inner) assert.ok(!first.includes('…'));
   else if(cellWidth(title)>inner*2) assert.ok(first.includes('…'));
   const expanded=mapLines({model,journey:{...journey,level:'pane'}},width).body.join('\n').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/[│\s]/g,'');
   assert.ok(expanded.includes(title.replace(/\s/g,'')));
  }
 }
});
