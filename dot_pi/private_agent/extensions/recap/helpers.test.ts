import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { restoreState, resolveSettings, setOverride, project, capture, uncovered, version, seedSettings, capturedSettings, displayTime, validTimeZone, compatibleRecord } from './helpers.ts';

test('production automation defaults remain independent of accelerated PTY settings', () => {
  assert.equal(seedSettings.completed, true);
  assert.equal(seedSettings.periodic, true);
  assert.equal(seedSettings.beforeCompaction, true);
  assert.equal(seedSettings.model, null);
  assert.equal(seedSettings.mode, 'incremental');
  assert.equal(seedSettings.cadence, 1);
  assert.equal(seedSettings.intervalMinutes, 15);
  assert.equal(seedSettings.timeoutSeconds, 60);
  assert.deepEqual(JSON.parse(readFileSync(new URL('./create_config.json', import.meta.url), 'utf8')), seedSettings);
});
test('independent fork/clone history and sparse session-wide inheritance', () => {
  const a = restoreState('a', []);
  const changed = setOverride(a, 'cadence', 3);
  assert.equal(restoreState('a', [changed]).historyId, a.historyId);
  assert.notEqual(restoreState('b', [changed]).historyId, a.historyId);
  assert.equal(resolveSettings({ intervalMinutes: 20 }, changed.overrides).intervalMinutes, 20);
  assert.equal(resolveSettings({}, setOverride(changed, 'cadence', undefined).overrides).cadence, 1);
});
test('public projection deduplicates final/live and excludes thinking and custom output', () => {
  const entries = [{ type: 'message', id: 'final', message: { role: 'assistant', content: [{ type: 'thinking', thinking: 'SECRET' }, { type: 'text', text: 'done' }] } }, { type: 'message', id: 'recap', message: { role: 'custom', content: 'excluded' } }];
  const units = project(entries, [{ id: 'live', text: 'partial', status: 'ongoing/partial', verifiable: false }], { live: 'final' });
  assert.equal(units.length, 1);
  assert.equal(units[0].text, 'assistant: done');
});
test('branch, prefix, final, changed and unverifiable observations', () => {
  const u = { id: 'm', text: 'abc', status: 'ongoing/partial', verifiable: true };
  const baseline = { anchor: 'leaf', units: [version(u)] };
  assert.equal(uncovered([u], baseline, ['leaf']).length, 0);
  assert.equal(uncovered([u], baseline, ['other']).length, 1);
  assert.match(uncovered([{ ...u, text: 'abcdef' }], baseline, ['leaf'])[0].text, /def/);
  for (const update of [{ ...u, status: 'completed' }, { ...u, text: 'xyz' }, { ...u, verifiable: false }]) assert.equal(uncovered([update], baseline, ['leaf']).length, 1);
});
test('full fingerprint and safe metadata include effective options', () => {
  const state = restoreState('a', []), u = { id: 'm', text: 'abc', status: 'completed', verifiable: true };
  const a = capture([u], ['m'], state, seedSettings, 'full', 'manual');
  const b = capture([u], ['m'], state, { ...seedSettings, options: { maxTokens: 2 } }, 'full', 'manual');
  assert.notEqual(a.fingerprint, b.fingerprint);
  assert.equal(a.metadata.pi.historyId, state.historyId);
  assert.equal(a.metadata.pi.coverage.units[0].hash.length, 64);
});

test('false automation overrides and current model capture remain independent', () => {
  assert.equal(resolveSettings({ completed: false }, {}).completed, false);
  assert.equal(resolveSettings({}, { periodic: false, beforeCompaction: false }).periodic, false);
  const a = { provider: 'fixture', id: 'a' }, b = { provider: 'fixture', id: 'b' };
  const old = capturedSettings(seedSettings, a);
  a.id = 'changed';
  assert.equal(old.model.id, 'a');
  assert.equal(capturedSettings(seedSettings, b).model.id, 'b');
  assert.equal(capturedSettings({ ...seedSettings, model: old.model }, b).model.id, 'a');
});
test('timezone is presentation-only, validated, and observes DST', () => {
  assert.equal(validTimeZone('Not/AZone'), false);
  assert.equal(validTimeZone('local'), true);
  assert.match(displayTime('2026-01-15T12:00:00Z', 'America/New_York'), /07:00:00 GMT[−-]5/);
  assert.match(displayTime('2026-07-15T12:00:00Z', 'America/New_York'), /08:00:00 GMT[−-]4/);
  const state = restoreState('a', []), u = { id: 'm', text: 'abc', status: 'completed', verifiable: true };
  assert.equal(capture([u], ['m'], state, seedSettings, 'full', 'manual').fingerprint,
    capture([u], ['m'], state, { ...seedSettings, timeZone: 'UTC' }, 'full', 'manual').fingerprint);
  const row = { status: 'published', created_at: '2026-01-15', record_id: 'r', metadata: { pi: { nativeSessionId: 'a', historyId: state.historyId, coverage: { anchor: 'm' } } } };
  assert.equal(compatibleRecord([row], state, ['m']), row);
  assert.equal(compatibleRecord([row], state, ['other']), undefined);
  assert.equal(compatibleRecord([row], restoreState('b', []), ['m']), undefined);
});
