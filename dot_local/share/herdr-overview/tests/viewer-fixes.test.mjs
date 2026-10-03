import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { PassThrough } from 'node:stream';
import { nativePiSessionId, readPiSessionFields, piSessionFile } from '../src/pi-session-store.mjs';
import { normalizeSnapshot } from '../src/model.mjs';
import { createJourney } from '../src/navigation.mjs';
import { mapFrame } from '../src/presenters/map.mjs';
import { runOverviewPane } from '../src/pane.mjs';
import { snapshot } from './popup-fixture.mjs';

const sid = '01a101ec-1006-747c-95d9-63674f7ba4df';
const plain = s => s.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '');

test('a Pi session reported by file path yields its exact UUID; other shapes do not', () => {
  assert.equal(nativePiSessionId({ agent: 'pi', kind: 'id', value: sid }), sid);
  assert.equal(nativePiSessionId({ agent: 'pi', kind: 'path', value: `/x/sessions/--cwd--/2026-10-03T13-20-10-247Z_${sid}.jsonl` }), sid);
  for (const bad of [{ agent: 'pi', kind: 'path', value: sid }, { agent: 'pi', kind: 'path', value: `/x/${sid}.json` },
    { agent: 'codex', kind: 'path', value: `/x/a_${sid}.jsonl` }, null, { agent: 'pi', kind: 'other', value: sid }])
    assert.equal(nativePiSessionId(bad), null);
});

test('digest joins a live pane whose native session is a path (real Herdr shape)', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'overview-path-')), env = { HOME: root, HERDR_OVERVIEW_PI_SESSIONS_DIR: path.join(root, 's'), PI_SESSION_SEARCH_DIGEST_DIR: path.join(root, 'd') };
  mkdirSync(env.HERDR_OVERVIEW_PI_SESSIONS_DIR); mkdirSync(env.PI_SESSION_SEARCH_DIGEST_DIR);
  writeFileSync(piSessionFile('/sock', 'term1', env), JSON.stringify({ schemaVersion: 1, socketPath: '/sock', terminalId: 'term1', paneId: 'p1', sessionId: sid, sessionName: null, publisherPid: process.pid, generation: 'g' }));
  writeFileSync(path.join(env.PI_SESSION_SEARCH_DIGEST_DIR, sid + '.json'), JSON.stringify({ schemaVersion: 1, generatedAt: '2026-10-03T00:00:00Z', body: 'DIGEST' }));
  const session = { source: 'herdr:pi', agent: 'pi', kind: 'path', value: `/x/2026_${sid}.jsonl` };
  const snap = { protocol: 22, panes: [{ pane_id: 'p1', terminal_id: 'term1', agent_session: session }], agents: [{ pane_id: 'p1', agent_session: session }] };
  assert.equal(readPiSessionFields(snap, { socketPath: '/sock', env }).piSessionsByPaneId.p1?.digest.status, 'available');
});

test('a short expanded digest stays at the top of the viewport, not clamped to the map end', () => {
  const model = normalizeSnapshot(snapshot());
  const journey = { ...createJourney(model), level: 'digest' };
  const lines = plain(mapFrame({ model, journey }, 60, 40).text).split('\n');
  assert.match(lines[2], /^┌/); assert.match(lines[3], /Single 1/); assert.match(lines.join('\n'), /Session digest · date unavailable/);
});

test('the viewer redraws in place inside a synchronized update, never clearing the screen', async () => {
  const input = new PassThrough(), output = new PassThrough(); let text = '';
  Object.assign(input, { isTTY: true, isRaw: false, setRawMode() {} }); Object.assign(output, { isTTY: true, columns: 60, rows: 20 });
  output.on('data', d => { text += d; });
  const model = normalizeSnapshot(snapshot()), dir = mkdtempSync(path.join(tmpdir(), 'overview-draw-'));
  writeFileSync(path.join(dir, 'overview.json'), JSON.stringify({ model }));
  const api = { snapshot: async () => snapshot(), socketPath: '/none' };
  const done = runOverviewPane({ api, stateDir: dir, dataRoot: dir, configPath: path.join(dir, 'none.toml'), input, output, env: { HOME: dir } });
  await new Promise(r => setTimeout(r, 200)); input.write('\x1b[<65;5;5M'); await new Promise(r => setTimeout(r, 100)); input.write('q'); await done;
  assert.ok(text.includes('\x1b[?2026h\x1b[H') && text.includes('\x1b[J\x1b[?2026l')); assert.ok(!text.includes('\x1b[2J'));
});

test('paired cards keep equal heights and full borders when recaps contain blank lines', () => {
  const model = normalizeSnapshot(snapshot());
  const recap = summary => ({ latest: { record_id: 'r', status: 'published', published_at: '2026-10-03T17:00:00Z', summary } });
  model.panes.p1.recap = recap('Recap for reorientation and resumption\n\nWhere things stand\n\nMore text here');
  model.panes.p2.recap = recap('Recap: viewer fixes are committed, merged, applied and pushed\n\nWhere things stand');
  model.tabs.t1.fullTitle = 'Pi lifecycle classifiers and Jev integration'; model.panes.p3.agent.status = 'working';
  for (const width of [40, 46, 92, 160]) {
    const rows = plain(mapFrame({ model, journey: createJourney(model) }, width, 60).text).split('\n');
    const top = rows.findIndex(r => r.includes('┌')), bottom = rows.findIndex((r, i) => i > top && r.includes('└'));
    assert.equal((rows[top].match(/┌/g) || []).length, 2, width);
    assert.equal((rows[bottom].match(/└/g) || []).length, 2, `both bottom borders on one row at ${width}`);
    for (const row of rows.slice(top + 1, bottom)) assert.equal((row.match(/│/g) || []).length, 4, width);
    assert.ok(!rows[top].includes('┐  ┌'), `one-column gap between paired cards at ${width}`);
  }
});
