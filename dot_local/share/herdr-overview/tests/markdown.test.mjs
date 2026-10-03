import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeSnapshot } from '../src/model.mjs';
import { createJourney } from '../src/navigation.mjs';
import { mapLines, mapFrame, cellWidth } from '../src/presenters/map.mjs';
import { markdownLines, plainMarkdown } from '../src/markdown.mjs';
import { resolvePalette } from '../src/theme.mjs';
import { snapshot } from './popup-fixture.mjs';

const plain = s => s.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '');
const SAMPLE = '## Synthetic status\n**Complete:** merged at `abc1234`; snake_case_name stays literal.\n- first item with a long continuation that must wrap under its bullet text\n> quoted note\n```\nconst x = 1;\n```';

test('markdown subset parses headings, emphasis, code, lists, quotes and fences', () => {
  const lines = markdownLines(SAMPLE);
  assert.deepEqual(lines[0].spans, [{ role: 'accent', bold: true, text: 'Synthetic status' }]);
  assert.deepEqual(lines[1].spans.slice(0, 4), [{ bold: true, text: 'Complete:' }, { text: ' merged at ' }, { role: 'peach', text: 'abc1234' }, { text: '; snake_case_name stays literal.' }]);
  assert.equal(lines[2].prefix.map(s => s.text).join(''), '• ');
  assert.ok(lines[3].spans[0].italic);
  assert.ok(lines[4].skip && lines[6].skip);
  assert.equal(lines[5].spans[0].text, 'const x = 1;');
  assert.equal(plainMarkdown(SAMPLE).split('\n')[1], 'Complete: merged at abc1234; snake_case_name stays literal.');
});

test('expanded recap renders markdown styling; collapsed preview drops markers', () => {
  const model = normalizeSnapshot(snapshot());
  model.panes.p1.recap = { latest: { record_id: 'r1', status: 'published', published_at: '2026-01-01T00:00:00Z', summary: SAMPLE } };
  const journey = createJourney(model);
  for (const width of [32, 48, 120]) {
    const collapsed = mapLines({ model, journey }, width).body;
    assert.ok(collapsed.every(l => cellWidth(l) <= width));
    assert.doesNotMatch(plain(collapsed.join('\n')), /\*\*|##|`/);
    const expanded = mapLines({ model, journey: { ...journey, level: 'pane' }, theme: resolvePalette({ name: 'tokyo-night' }) }, width).body;
    assert.ok(expanded.every(l => cellWidth(l) <= width));
    const text = plain(expanded.join('\n'));
    assert.doesNotMatch(text, /\*\*Complete|## Synthetic|`abc1234`|```/);
    assert.match(text, /Synthetic status/); assert.match(text, /│ quoted note/); assert.match(text, /const x = 1;/);
    assert.match(expanded.join('\n'), /\x1b\[1m\x1b\[[0-9;]*m\x1b\[[0-9;]*mComplete:/);
  }
  const rows = plain(mapLines({ model, journey: { ...journey, level: 'pane' } }, 48).body.join('\n')).split('\n');
  const first = rows.findIndex(r => r.includes('• first item')), next = rows[first + 1];
  assert.match(next, /│ {3}\S/, 'continuation hangs under bullet text');
});

test('markdown reading keeps source-line scroll position across reflow', () => {
  const model = normalizeSnapshot(snapshot());
  model.panes.p1.recap = { latest: { record_id: 'r1', status: 'published', summary: Array.from({ length: 40 }, (_, i) => `- **item ${i}** with enough words to wrap at narrow widths`).join('\n') } };
  const journey = { ...createJourney(model), level: 'pane' };
  mapFrame({ model, journey }, 120, 12);
  journey.scrollDelta = 25;
  const wide = plain(mapFrame({ model, journey }, 120, 12).text).split('\n');
  const item = wide.slice(2).join('\n').match(/item \d+/)[0];
  assert.ok(Number(item.slice(5)) > 10, item);
  const narrow = plain(mapFrame({ model, journey }, 40, 12).text);
  assert.match(narrow, new RegExp(item + '\\b'));
});

test('collapsed cards give otherwise blank rows to the recap without growing', () => {
  const words = n => Array.from({ length: n }, (_, i) => `word${i}`).join(' ');
  const recap = summary => ({ latest: { record_id: 'r', status: 'published', published_at: '2026-01-01T00:00:00Z', summary } });
  const model = normalizeSnapshot(snapshot());
  model.panes.p1.recap = recap(words(80));
  model.panes.p2.recap = { ...recap(words(80)), lastAttempt: { record_id: 'f', status: 'failed' } };
  model.tabs.t2.fullTitle = 'A much longer second title that wraps onto two lines';
  model.panes.p3.agent.status = 'working'; // keep the singleton pair first
  const journey = createJourney(model);
  for (const width of [40, 120]) {
    const rows = plain(mapLines({ model, journey }, width).body.join('\n')).split('\n');
    const top = rows.findIndex(r => r.includes('┌')), bottom = rows.findIndex(r => r.includes('└'));
    const split = rows[top].lastIndexOf('┌');
    const left = rows.slice(top, bottom + 1).map(s => s.slice(0, split)), other = rows.slice(top, bottom + 1).map(s => s.slice(split));
    const count = card => card.filter(r => /word\d/.test(r)).length;
    // Right: the newer-attempt warning keeps the two-line minimum.
    assert.equal(count(other), 2, width);
    assert.match(other.join(' '), /Newer attempt/);
    // Left: no warning, and a taller partner at narrow width; spare rows go to the recap.
    assert.equal(count(left), width === 40 ? 4 : 3, width);
    // Only border padding and the fixed second title row may stay blank.
    assert.ok(left.filter(r => /│\s*│/.test(r)).length <= 3);
    assert.match(left.findLast(r => /word\d/.test(r)), /…/);
  }
  model.panes.p1.recap = recap('Short recap.');
  const short = plain(mapLines({ model, journey }, 40).body.join('\n'));
  assert.match(short, /Short recap\./); assert.doesNotMatch(short, /Short recap\.…/);
});
