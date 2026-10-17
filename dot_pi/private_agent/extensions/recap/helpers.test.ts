import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { restoreState, resolveSettings, setOverride, project, capture, uncovered, version, seedSettings, capturedSettings, displayTime, validTimeZone, compatibleRecord, priorRecord, sessionListArgs, argumentCompletions, commandCatalog, commandHelp, projectContext, failureNotice, hardBreaks } from './helpers.ts';

test('native completions replace the whole argument prefix and match parser contexts', () => {
  assert.deepEqual(argumentCompletions('').map(c => c.value), commandCatalog.map(c => c.value));
  assert.ok(argumentCompletions('').every(c => c.description));
  assert.deepEqual(argumentCompletions('he').map(c => c.value), ['help']);
  assert.deepEqual(argumentCompletions('settings d').map(c => c.value), ['settings defaults']);
  assert.deepEqual(argumentCompletions('history all a').map(c => c.value), ['history all attempts']);
  assert.deepEqual(argumentCompletions('history attempts l').map(c => c.value), ['history attempts legacy']);
  assert.deepEqual(argumentCompletions('history legacy ').map(c => c.value), ['history legacy all', 'history legacy attempts']);
  for (const prefix of ['view ', 'full ', 'cancel ', 'help ', 'settings defaults ', 'history invalid ', 'unknown ']) assert.deepEqual(argumentCompletions(prefix), []);
  assert.ok(argumentCompletions('history all attempts legacy ').length === 0);
});
test('read-only help states commands and unchanged generation/settings/cancel semantics', () => {
  for (const c of commandCatalog) assert.ok(commandHelp.includes(`/recap ${c.value}`));
  for (const phrase of ['incremental', 'reused without generation', 'Filters combine', 'Clear override', 'not Pi’s agent', 'default on', 'follows current Pi', 'display-only', 'do not generate']) assert.ok(commandHelp.includes(phrase), phrase);
});
test('production automation defaults remain independent of accelerated PTY settings', () => {
  assert.equal(seedSettings.completed, true);
  assert.equal(seedSettings.periodic, true);
  assert.equal(seedSettings.beforeCompaction, true);
  assert.equal(seedSettings.model, null);
  assert.equal(seedSettings.mode, 'incremental');
  assert.equal(seedSettings.cadence, 1);
  assert.equal(seedSettings.intervalMinutes, 15);
  assert.equal(seedSettings.timeoutSeconds, 180);
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

test('current projection uses source provenance and summaries never cover originals', () => {
  const projection = { entries: [
    { sourceEntry: { id: 'compact', type: 'compaction' }, messages: [{ role: 'compactionSummary', summary: 'same public text' }] },
    { sourceEntry: { id: 'kept', type: 'message' }, messages: [{ role: 'user', content: 'edited public text' }] },
    { sourceEntry: { id: 'output', type: 'custom_message' }, messages: [{ role: 'custom', content: 'recap excluded' }] },
  ] };
  const units = projectContext(projection);
  assert.deepEqual(units.map(u => u.id), ['compact:compactionSummary', 'kept']);
  assert.equal(units[1].text, 'user: edited public text');
  const state = restoreState('a', []), snapshot = capture(units, ['compact', 'kept'], state, seedSettings, 'incremental', 'manual');
  assert.equal(snapshot.metadata.pi.scope, 'current-context');
  const row = { status: 'published', created_at: '2026', record_id: 'r', metadata: snapshot.metadata };
  assert.equal(compatibleRecord([row], state, ['kept'], 'raw-branch'), undefined);
  assert.equal(resolveSettings({ inputBudget: 1 }, { inputBudget: 2 }).inputBudget, undefined);
  assert.match(failureNotice({ reason: 'context_limit', message: 'PRIVATE' }), /routed model context window/);
  assert.equal(failureNotice({ message: 'PRIVATE' }), 'Recap failed; coverage unchanged.');
});

test('widget excerpt keeps single newlines as hard breaks outside code fences', () => {
  assert.equal(hardBreaks('# Title\nline one\nline two\n\nnext'), '# Title  \nline one  \nline two\n\nnext');
  assert.equal(hardBreaks('a\n```\ncode\nmore\n```\nb'), 'a\n```\ncode\nmore\n```\nb');
  assert.equal(hardBreaks(''), '');
});

// cartwmic/dotfiles#12: per-session reads must reach the real CLI as a scoped list.
test('sessionListArgs lists only one Pi session through the real CLI', () => {
  const root = mkdtempSync(join(tmpdir(), 'recap-scope-'));
  try {
    const day = join(root, 'data', 'session-recap', 'records', '2026-10-10');
    mkdirSync(day, { recursive: true });
    for (const [id, sid, status] of [['r1', 'sess-a', 'published'], ['r2', 'sess-b', 'published'], ['r3', 'sess-a', 'failed']]) {
      writeFileSync(join(day, id + '.json'), JSON.stringify({ schema_version: 2, record_id: id, source_kind: 'pi', source_id: sid, kind: 'single', status, summary: 's', created_at: '2026-10-10T00:00:0' + id[1] + '+00:00', metadata: { pi: { nativeSessionId: sid } }, annotations: {} }));
    }
    const cli = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', 'dot_local', 'bin', 'executable_session-recap');
    const env: Record<string, string | undefined> = { ...process.env, SESSION_RECAP_IMPLEMENTATION: undefined, XDG_DATA_HOME: join(root, 'data'), XDG_CONFIG_HOME: join(root, 'config') };
    const run = (args: string[]) => JSON.parse(spawnSync(cli, args, { env, encoding: 'utf8' }).stdout).records.map((r: any) => r.record_id);
    assert.deepEqual(sessionListArgs('sess-a'), ['list', '--json', '--source-kind', 'pi', '--source-id', 'sess-a', '--omit-coverage-units']);
    assert.deepEqual(run(sessionListArgs('sess-a')), ['r1', 'r3']);
    assert.deepEqual(run(sessionListArgs('sess-b')), ['r2']);
    assert.deepEqual(run(sessionListArgs('absent')), []);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

// Selection must not change when coverage units are omitted from the listing (cartwmic/dotfiles#12 follow-up).
test('compatibleRecord picks the same record from the units-omitted listing, and read supplies the units', () => {
  const root = mkdtempSync(join(tmpdir(), 'recap-lite-'));
  try {
    const day = join(root, 'data', 'session-recap', 'records', '2026-10-10');
    mkdirSync(day, { recursive: true });
    const mk = (id: string, at: string, anchor: string | null, extra: any = {}) => writeFileSync(join(day, id + '.json'), JSON.stringify({ schema_version: 2, record_id: id, source_kind: 'pi', source_id: 'S', kind: 'single', status: 'published', summary: 's', created_at: at, metadata: { pi: { nativeSessionId: 'S', historyId: 'H', scope: 'current-context', coverage: { anchor, units: [{ id: 'u1', v: id }] }, ...extra } }, annotations: {} }));
    mk('r1', '2026-10-10T00:00:01+00:00', 'a1'); mk('r2', '2026-10-10T00:00:02+00:00', 'a2'); mk('r3', '2026-10-10T00:00:03+00:00', 'gone'); mk('r4', '2026-10-10T00:00:04+00:00', null, { scope: 'other' });
    const cli = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', 'dot_local', 'bin', 'executable_session-recap');
    const env: Record<string, string | undefined> = { ...process.env, SESSION_RECAP_IMPLEMENTATION: undefined, XDG_DATA_HOME: join(root, 'data'), XDG_CONFIG_HOME: join(root, 'config') };
    const list = (args: string[]) => JSON.parse(spawnSync(cli, args, { env, encoding: 'utf8' }).stdout).records;
    const state: any = { nativeSessionId: 'S', historyId: 'H', overrides: {} };
    for (const ids of [['a1', 'a2'], ['a1'], ['zzz'], ['a1', 'a2', 'gone']]) {
      const full = compatibleRecord(list(['list', '--json', '--source-kind', 'pi', '--source-id', 'S']), state, ids, 'current-context');
      const lite = compatibleRecord(list(sessionListArgs('S')), state, ids, 'current-context');
      assert.equal(lite?.record_id, full?.record_id, 'branch ' + ids.join(','));
      if (lite) {
        assert.equal(lite.metadata.pi.coverage.units, undefined);
        assert.equal(lite.metadata.pi.coverage.unitsOmitted, 1);
        const whole = JSON.parse(spawnSync(cli, ['read', lite.record_id, '--json'], { env, encoding: 'utf8' }).stdout).record;
        assert.deepEqual(whole.metadata.pi.coverage.units, full.metadata.pi.coverage.units);
      }
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test('priorRecord reads the ONE chosen record in full (the listing omits coverage units), and reads nothing when no recap is compatible', async () => {
  const state: any = { nativeSessionId: 'S', historyId: 'H', overrides: {} };
  const row = (id: string, anchor: string | null) => ({ record_id: id, source_kind: 'pi', source_id: 'S', status: 'published', created_at: '2026-10-10T00:00:0' + id.slice(1) + '+00:00', metadata: { pi: { nativeSessionId: 'S', historyId: 'H', scope: 'current-context', coverage: { anchor, unitsOmitted: 3 } } } });
  const full = (id: string) => ({ record_id: id, metadata: { pi: { coverage: { anchor: 'a2', units: [{ id: 'u1' }, { id: 'u2' }, { id: 'u3' }] } } } });
  const reads: string[] = [];
  const read = async (id: string) => { reads.push(id); return full(id); };
  const got = await priorRecord([row('r1', 'a1'), row('r2', 'a2')], state, ['a1', 'a2'], 'current-context', read);
  assert.deepEqual(reads, ['r2'], 'exactly one full read, of the record selected from the listing');
  assert.equal(got.metadata.pi.coverage.units.length, 3, 'the caller gets the FULL record with units, not the units-less listing row');
  reads.length = 0;
  assert.equal(await priorRecord([row('r1', 'gone')], state, ['a1'], 'current-context', read), undefined);
  assert.equal(await priorRecord([], state, ['a1'], 'current-context', read), undefined);
  assert.deepEqual(reads, [], 'no compatible recap means no read');
});

test('recap/index.ts wires the prior through priorRecord with a real "read" call, not the listing row', () => {
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'index.ts'), 'utf8');
  const uses = src.split('\n').filter((line) => line.includes('priorRecord(') && !line.includes('import '));
  assert.equal(uses.length, 1, 'one call site');
  assert.ok(uses[0].includes("call('read', recordId, '--json')).record"), 'the reader is the CLI read subcommand');
  assert.ok(!src.includes('const prior = priorLite'), 'the units-less listing row is never used as the prior');
  assert.ok(!src.includes('compatibleRecord(await recordsFor(own.nativeSessionId)'), 'no direct use of the listing row for the prior');
});
