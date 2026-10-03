import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeSnapshot } from '../src/model.mjs';
import { createJourney, reconcileJourney, getCurrentPaneId } from '../src/navigation.mjs';
import { renderMap, mapLines, cellWidth } from '../src/presenters/map.mjs';
import { snapshot } from './popup-fixture.mjs';
test('one map has two-column narrow singles and explicit selectable native multi-pane groups', () => {
  const model = normalizeSnapshot(snapshot()); const journey = createJourney(model);
  for (const width of [32,40,64,100,160]) {
    const frame = renderMap({ model, journey: { ...journey } }, width, 30);
    assert.ok(frame.split('\n').every(line => cellWidth(line) <= width));
    assert.match(frame, /Tab 3/);
    assert.match(mapLines({model,journey},width).body.join('\n'), /BLOCKED/); // Previews push later groups below the first viewport.
    assert.ok(frame.split('\n').some(line => line.includes('Single 1') && line.includes('Single 2')));
    assert.doesNotMatch(frame, /Recent output|preview|Mosaic|Board/);
  }
});
test('full detail and digest lines are bounded only by viewport and reach final markers', () => {
  const model = normalizeSnapshot(snapshot()); const journey = { ...createJourney(model), level: 'pane' };
  model.tabs.t1.fullTitle = 'Complete title '.repeat(10) + 'TITLE-END';
  model.panes.p1.recap = { latest: { status: 'published', record_id: 'good', published_at: '2026-10-01T00:00:00Z', summary: 'recap line\n'.repeat(100) + 'RECAP-END' }, lastAttempt: { status: 'failed', record_id: 'bad', created_at: '2026-10-01T01:00:00Z', failure: { message: 'synthetic failure' } } };
  model.panes.p1.digest = { status: 'available', generatedAt: '2026-10-01T02:00:00Z', body: 'digest line\n'.repeat(100) + 'DIGEST-END' };
  assert.match(mapLines({ model, journey }, 40).body.join('\n'), /TITLE-END|RECAP-END/);
  const detail = mapLines({ model, journey }, 40).body;
  assert.match(detail.join('\n'), /synthetic failure/);
  let seen = '';
  for (let offset = 0; offset < detail.length; offset++) seen += renderMap({ model, journey: { ...journey, detailScroll: offset } }, 40, 10);
  assert.match(seen, /RECAP-END/);
  const digestJourney = { ...journey, level: 'digest', detailScroll: 9999 };
  assert.match(renderMap({ model, journey: digestJourney }, 40, 10), /DIGEST-END/);
  assert.ok(digestJourney.detailScroll < 9999);
});
test('selection follows only a unique terminal rekey and never falls back after loss/conflict', () => {
  const model = normalizeSnapshot(snapshot()), journey = createJourney(model);
  const moved = structuredClone(model); moved.panes.new = { ...moved.panes.p1, id: 'new' }; delete moved.panes.p1;
  assert.equal(reconcileJourney(journey, moved).paneId, 'new');
  delete moved.panes.new;
  assert.equal(getCurrentPaneId(journey, moved), null);
  moved.panes.copy = { ...model.panes.p1, id: 'copy' }; moved.panes.other = { ...model.panes.p1, id: 'other' };
  assert.equal(getCurrentPaneId(journey, moved), null);
});
test('workspace rows wrap in native order and selected anchors/details survive column changes', () => {
  const native = snapshot();
  for (let n = 2; n <= 5; n++) {
    native.workspaces.push({ workspace_id: `w${n}`, label: `Workspace ${n}`, number: n });
    native.tabs.push({ tab_id: `extra${n}`, workspace_id: `w${n}`, label: `Tab ${n}`, number: n });
    native.panes.push({ pane_id: `extra${n}`, tab_id: `extra${n}`, workspace_id: `w${n}`, terminal_id: `terminal-extra${n}`, label: `Subject ${n}` });
  }
  const model = normalizeSnapshot(native);
  const journey = { ...createJourney(model), paneId: 'extra5', terminalId: 'terminal-extra5', workspaceId: 'w5', tabId: 'extra5' };
  for (const width of [32, 40, 82, 120, 160]) {
    const map = mapLines({ model, journey }, width);
    assert.ok(map.body.every(line => cellWidth(line) <= width));
    assert.match(map.body[map.anchor + 2], /› Tab 5/);
    const frame = renderMap({ model, journey: { ...journey } }, width, 12);
    assert.match(frame, /› Tab 5/);
    const detail = mapLines({ model, journey: { ...journey, level: 'pane' } }, width).body.join('\n');
    assert.match(detail, /Manual · NO AGENT/);
    if (width >= 120) {
      assert.ok(map.body.some(line => line.includes('Synthetic workspace') && line.includes('Workspace 2')));
      assert.ok(map.body.findIndex(line => line.includes('Workspace 5')) > map.body.findIndex(line => line.includes('Workspace 2')));
    } else assert.ok(!map.body.some(line => line.includes('Synthetic workspace') && line.includes('Workspace 2')));
  }
});
test('collapsed card status is bold and recap date is dimmer than recap text', async () => {
  const { resolvePalette } = await import('../src/theme.mjs');
  const theme = resolvePalette({ name: 'catppuccin' }), palette = theme.palette;
  const model = normalizeSnapshot(snapshot()); const journey = createJourney(model);
  model.panes.p1.agent = { ...model.panes.p1.agent, recognized: true, status: 'idle' };
  model.panes.p1.recap = { latest: { status: 'published', record_id: 'good', published_at: '2026-10-01T00:00:00Z', summary: 'short' } };
  const frame = renderMap({ model, journey, theme }, 100, 40);
  const color = token => token?.kind === 'rgb' ? token.hex.slice(1).match(/../g).map(h => parseInt(h, 16)).join(';') : null;
  const ready = frame.split('\n').find(line => line.includes('READY'));
  const dated = frame.split('\n').find(line => line.includes('Latest good recap · 2026-10-01T00:00:00Z'));
  assert.match(ready, new RegExp('\\x1b\\[1m\\x1b\\[38;2;' + color(palette.blue) + 'm(\\x1b\\[[0-9;]*m)*READY'));
  // The foreground set immediately before each text (borders carry their own colors).
  const fg = (line, text) => line.slice(0, line.indexOf(text)).match(/\x1b\[38;2;([0-9;]+)m(?:\x1b\[48;2;[0-9;]+m)?$/)?.[1];
  assert.equal(fg(dated, 'Latest good recap'), color(palette.overlay1));
  const excerpt = frame.split('\n').find(line => line.includes('short'));
  assert.equal(fg(excerpt, 'short'), color(palette.text));
  assert.notEqual(color(palette.overlay1), color(palette.text));
});
