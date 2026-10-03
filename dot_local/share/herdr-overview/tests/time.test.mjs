import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { displayTime, recapTimeZone } from '../src/time.mjs';
import { normalizeSnapshot } from '../src/model.mjs';
import { createJourney } from '../src/navigation.mjs';
import { mapLines } from '../src/presenters/map.mjs';
import { snapshot } from './popup-fixture.mjs';

test('recap CLI time_zone config is honored, local file wins, default local', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'overview-tz-')), dir = path.join(root, 'session-recap');
  assert.equal(recapTimeZone({ XDG_CONFIG_HOME: root }), 'local');
  mkdirSync(dir); writeFileSync(path.join(dir, 'config.toml'), 'auto_publish = false\ntime_zone = "UTC"\n');
  assert.equal(recapTimeZone({ XDG_CONFIG_HOME: root }), 'UTC');
  writeFileSync(path.join(dir, 'config.local.toml'), 'time_zone = "Asia/Tokyo"\n');
  assert.equal(recapTimeZone({ XDG_CONFIG_HOME: root }), 'Asia/Tokyo');
});

test('display converts UTC records, including DST, and leaves odd values alone', () => {
  assert.equal(displayTime('2026-01-15T12:00:00Z', 'America/New_York'), '2026-01-15 07:00:00 GMT−5 [America/New_York]');
  assert.equal(displayTime('2026-07-15T12:00:00.123456Z', 'America/New_York'), '2026-07-15 08:00:00 GMT−4 [America/New_York]');
  assert.equal(displayTime('2026-07-15T12:00:00', 'UTC'), '2026-07-15T12:00:00');
  assert.equal(displayTime('not a date', 'UTC'), 'not a date');
  assert.equal(displayTime('2026-07-15T12:00:00Z', 'Not/AZone'), '2026-07-15T12:00:00Z');
});

test('cards and reading show the converted time, not raw Z', () => {
  const model = normalizeSnapshot(snapshot());
  model.panes.p1.recap = { latest: { record_id: 'r', status: 'published', published_at: '2026-07-15T12:00:00Z', summary: 'Synthetic recap.' } };
  const journey = createJourney(model), plain = s => s.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '');
  const card = plain(mapLines({ model, journey, timeZone: 'Asia/Tokyo' }, 120).body.join('\n'));
  assert.match(card, /Recap 2026-07-15 21:00 GMT\+9 /); assert.doesNotMatch(card, /T12:00:00Z|\[Asia/);
  const reading = plain(mapLines({ model, journey: { ...journey, level: 'pane' }, timeZone: 'Asia/Tokyo' }, 120).body.join('\n'));
  assert.match(reading, /Latest good recap · 2026-07-15 21:00:00 GMT\+9 \[Asia\/Tokyo\]/); assert.doesNotMatch(reading, /T12:00:00Z/);
});
