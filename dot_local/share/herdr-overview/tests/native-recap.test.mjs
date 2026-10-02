import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { readRecapFields, readLatestRecapRecords, readCurrentPiPrompts } from '../src/recap-store.mjs';
import { reconcileRecapCoordinator } from '../src/recap-coordinator.mjs';

test('native history joins via Pi session metadata; annotation does not mutate narrative/coverage; delayed consumption and legacy coexist', async t => {
  const base = await mkdtemp(path.join(os.tmpdir(), 'overview-native-'));
  t.after(() => rm(base, { recursive: true, force: true }));
  const root = path.join(base, 'session-recap');
  const directory = path.join(root, 'records/2026-10-01');
  await mkdir(directory, { recursive: true });
  const native = { schema_version: 2, record_id: 'a'.repeat(32), status: 'published', source_kind: 'pi', source_id: 'different-history-key', created_at: '2026-10-01T00:00:00Z', published_at: '2026-10-01T00:00:00Z', summary: 'Native saved recap', metadata: { pi: { sessionId: 'native-session', historyId: 'different-history-key', coverage: { anchor: 'coverage-preserved' } } }, annotations: {} };
  const filename = path.join(directory, `${native.record_id}.json`);
  await writeFile(filename, JSON.stringify(native));
  const legacy = { schema_version: 1, record_id: 'b'.repeat(32), status: 'published', source_kind: 'pi-session', source_id: 'legacy-session', pane_id: 'legacy-pane', workspace_id: 'workspace', published_at: '2026-09-30T00:00:00Z', summary: 'Legacy saved recap' };
  await writeFile(path.join(directory, `${legacy.record_id}.json`), JSON.stringify(legacy));
  const snapshot = { panes: [{ pane_id: 'native-pane', workspace_id: 'workspace', terminal_id: 'terminal' }], workspaces: [{ workspace_id: 'workspace' }] };
  let { state } = await reconcileRecapCoordinator({ dataRoot: root, snapshot, now: Date.parse(native.published_at), runRecap: async () => 'disabled' });
  assert.ok(!state.processedRecordIds.includes(native.record_id), 'do not consume before annotation exists');
  native.annotations.herdr = { pane_id: 'native-pane', workspace_id: 'workspace' };
  await writeFile(filename, JSON.stringify(native));
  const recovered = await reconcileRecapCoordinator({ state, dataRoot: root, snapshot, now: Date.parse(native.published_at) + 10_000, runRecap: async args => { assert.deepEqual(args, ['config', 'auto-publish']); return 'enabled'; } });
  state = recovered.state;
  assert.equal(state.workspaceDeadlines.workspace, '2026-10-01T00:00:30.000Z');
  assert.equal(recovered.wakeups[0].deadline, '2026-10-01T00:00:30.000Z');
  assert.equal(state.piTerminalIdsBySessionId['native-session'], 'terminal');
  const fields = await readRecapFields(snapshot, root);
  assert.equal(fields.piRecapsBySessionId['native-session'].latest.record_id, native.record_id);
  assert.equal(fields.piRecapsByPaneId['native-pane'].latest.summary, native.summary);
  assert.equal(fields.piRecapsBySessionId['legacy-session'].latest.summary, legacy.summary);
  assert.deepEqual(JSON.parse(await readFile(filename, 'utf8')), native);
  assert.equal((await readLatestRecapRecords(root, 'pi-session')).length, 2, 'dated records work without latest index');
  const moved = { ...snapshot, panes: [{ pane_id: 'moved-pane', workspace_id: 'other-workspace', terminal_id: 'terminal' }] };
  const afterMove = await readRecapFields(moved, root, state.piTerminalIdsBySessionId);
  assert.equal(afterMove.recapsByPaneId['moved-pane'].latest.record_id, native.record_id);
  assert.equal(afterMove.recapsByPaneId['moved-pane'].latest.workspace_id, 'workspace', 'publication attribution remains fixed');
});

test('legacy index breaks only validated history ties; stale/missing indices and native history remain passive', async t => {
  const base = await mkdtemp(path.join(os.tmpdir(), 'overview-legacy-tie-'));
  t.after(() => rm(base, { recursive: true, force: true }));
  const directory = path.join(base, 'records/2026-10-01');
  await mkdir(directory, { recursive: true });
  const good = { record_id: 'z-good', source_kind: 'pi-session', source_id: 'legacy', status: 'published', created_at: '2026-10-01T00:00:00Z', summary: 'Latest good legacy recap' };
  const failed = { ...good, record_id: 'a-failed', status: 'failed', summary: undefined };
  const other = { ...failed, record_id: 'other-source', source_id: 'other' };
  const save = record => writeFile(path.join(directory, record.record_id + '.json'), JSON.stringify(record));
  for (const record of [good, failed, other]) await save(record);
  const index = (success, attempt) => writeFile(path.join(base, 'latest.json'), JSON.stringify({ sources: [{ source_kind: 'pi-session', source_id: 'legacy', latest_success_id: success, last_attempt_id: attempt }] }));
  const read = async () => (await readRecapFields({ panes: [] }, base)).piRecapsBySessionId.legacy;
  await index(good.record_id, failed.record_id);
  assert.equal((await read()).lastAttempt.record_id, failed.record_id);
  assert.equal((await read()).latest.record_id, good.record_id);
  for (const invalid of ['absent-record', other.record_id]) {
    await index(failed.record_id, invalid);
    const fields = await read();
    assert.equal(fields.latest.record_id, good.record_id, 'failed index target cannot supply latest success');
    assert.equal(fields.lastAttempt.record_id, good.record_id, 'nonmatching pointer uses deterministic history');
  }
  await rm(path.join(base, 'latest.json'));
  assert.equal((await read()).lastAttempt.record_id, good.record_id);
  const newer = { ...failed, record_id: '0-newer', created_at: '2026-10-01T00:01:00Z' };
  await save(newer); await index(good.record_id, failed.record_id);
  assert.equal((await read()).lastAttempt.record_id, newer.record_id, 'convenience pointer cannot override newer history');
  const native = { ...good, source_kind: 'pi', source_id: 'history', record_id: 'native-good', metadata: { pi: { sessionId: 'native' } }, annotations: { herdr: {} } };
  const nativeFailure = { ...native, status: 'failed', record_id: 'native-failed', summary: undefined };
  await save(native); await save(nativeFailure);
  await writeFile(path.join(base, 'latest.json'), JSON.stringify({ sources: [{ source_kind: 'pi-session', source_id: 'native', latest_success_id: native.record_id, last_attempt_id: nativeFailure.record_id }] }));
  assert.equal((await readRecapFields({ panes: [] }, base)).piRecapsBySessionId.native.lastAttempt.record_id, native.record_id, 'generic native records ignore legacy tie hints');
});

test('adapter-owned private prompts override legacy files without removing them', async t => {
  const base = await mkdtemp(path.join(os.tmpdir(), 'overview-prompts-'));
  t.after(() => rm(base, { recursive: true, force: true }));
  const root = path.join(base, 'session-recap');
  const oldDir = path.join(root, 'prompts');
  const newDir = path.join(base, 'herdr-overview/prompts');
  await mkdir(oldDir, { recursive: true }); await mkdir(newDir, { recursive: true });
  const legacy = { schema_version: 1, session_id: 'session', text: 'Old prompt', working: true };
  const current = { ...legacy, text: 'New real user prompt', working: false, pane_id: 'new-pane' };
  await writeFile(path.join(oldDir, 'session.json'), JSON.stringify(legacy));
  await writeFile(path.join(newDir, 'session.json'), JSON.stringify(current), { mode: 0o600 });
  assert.deepEqual(await readCurrentPiPrompts(root), [current]);
  assert.deepEqual(JSON.parse(await readFile(path.join(oldDir, 'session.json'), 'utf8')), legacy);
});
