import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, statSync, chmodSync, existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import extension from './index.ts';
import { readPrompt } from './prompt-store.ts';
import { runSessionRecap, writePiMetadata, retirePiMetadata } from './helpers.ts';
import { readPiSessionFields, piSessionFile } from '../../../../dot_local/share/herdr-overview/src/pi-session-store.mjs';

const dir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(dir, '../../../..');
const delay = (ms: number) => new Promise(r => setTimeout(r, ms));
async function wait(predicate: () => boolean, label = 'consumer to complete') {
  for (let i = 0; i < 500; i++) { if (predicate()) return; await delay(20); }
  throw new Error(`Timed out waiting for ${label}`);
}
const readJson = (file: string) => JSON.parse(readFileSync(file, 'utf8'));

async function world() {
  const root = mkdtempSync(path.join(os.tmpdir(), 'overview-consumer-'));
  const saved = { ...process.env };
  const calls: any[] = [];
  let pane: any = { pane_id: 'pane-original', workspace_id: 'workspace-original', terminal_id: 'terminal-exact' };
  const snapshot: any = { protocol: 22, panes: [
    { pane_id: 'pane-original', terminal_id: 'terminal-exact' },
    { pane_id: 'focused-pane', terminal_id: 'terminal-focused' },
  ] };
  let failWake = false, limitFailures = 0;
  const socketPath = path.join(root, 'h.sock');
  const server = net.createServer(socket => {
    let buffer = '';
    socket.on('data', chunk => {
      buffer += chunk;
      const n = buffer.indexOf('\n');
      if (n < 0) return;
      const request = JSON.parse(buffer.slice(0, n));
      calls.push(request);
      socket.end(JSON.stringify({ id: request.id, ...(request.method === 'pane.current'
        ? { result: { type: 'pane_current', pane } }
        : request.method === 'session.snapshot' ? { result: { snapshot } }
        : failWake ? { error: { message: 'scripted missed wake-up' } }
        : limitFailures > 0 && limitFailures-- ? { error: { code: 'plugin_command_limit_reached', message: 'maximum concurrent plugin commands reached (32)' } }
        : { result: {} }) }) + '\n');
    });
  });
  await new Promise<void>(resolve => server.listen(socketPath, resolve));
  const cli = path.join(root, 'cli');
  writeFileSync(cli, `#!/bin/sh\nprintf '%s\\n' "$*" >> '${root}/cli.log'\nexec ${JSON.stringify(process.env.PYTHON ?? 'python3')} '${repo}/dot_local/share/session-recap/session_recap.py' "$@"\n`);
  chmodSync(cli, 0o700);
  const env: Record<string, string> = {
    PATH: process.env.PATH!, HOME: path.join(root, 'home'), TMPDIR: root,
    XDG_DATA_HOME: path.join(root, 'data'), XDG_CONFIG_HOME: path.join(root, 'config'),
    XDG_STATE_HOME: path.join(root, 'state'), SESSION_RECAP_BIN: cli,
    HERDR_SOCKET_PATH: socketPath, HERDR_PANE_ID: 'inherited-caller',
    PI_CODING_AGENT_DIR: path.join(root, 'agent'), PI_OFFLINE: '1', PI_TELEMETRY: '0',
    SESSION_RECAP_PYTHON: process.env.PYTHON ?? 'python3',
  };
  for (const key of ['HOME', 'PI_CODING_AGENT_DIR']) mkdirSync(env[key], { recursive: true });
  writeFileSync(path.join(env.PI_CODING_AGENT_DIR, 'settings.json'), JSON.stringify({ cacheWarming: 'off', enableInstallTelemetry: false }));
  // In-process helper tests must use the same private roots as spawned Pi.
  for (const key of ['HERDR_OVERVIEW_PI_SESSIONS_DIR', 'SESSION_RECAP_IMPLEMENTATION']) delete process.env[key];
  Object.assign(process.env, env);
  const recordsDir = path.join(root, 'data/session-recap/records/2026-10-01');
  mkdirSync(recordsDir, { recursive: true });
  const hooks = new Map<string, any[]>();
  const listeners = new Map<string, any>();
  extension({ on(name: string, handler: any) { hooks.set(name, [...(hooks.get(name) ?? []), handler]); }, events: { on(name: string, handler: any) { listeners.set(name, handler); return () => listeners.delete(name); } } } as any);
  const ctx = (id = 'native-session', pending = false) => ({ mode: 'rpc', isIdle: () => false, hasPendingMessages: () => pending, sessionManager: { getSessionId: () => id } });
  const fire = async (name: string, event: any = {}, context: any = ctx()) => { for (const fn of hooks.get(name) ?? []) await fn(event, context); };
  const put = (id: string, owner = 'native-session') => {
    const record = { schema_version: 2, record_id: id, source_kind: 'pi', source_id: 'independent-history', kind: 'single', status: 'published', created_at: '2026-10-01T00:00:00Z', summary: 'Saved only once by Pi', metadata: { pi: { sessionId: owner, historyId: 'independent-history', coverage: { anchor: 'original-anchor' } } }, annotations: {} };
    writeFileSync(path.join(recordsDir, `${id}.json`), JSON.stringify(record));
    return record;
  };
  return { root, env, cli, calls, snapshot, ctx, fire, put, listeners,
    setPane(value: any) { pane = value; }, failWake(value: boolean) { failWake = value; }, limit(count: number) { limitFailures = count; },
    record(id: string) { return readJson(path.join(recordsDir, `${id}.json`)); },
    async close() {
      await fire('session_shutdown');
      await new Promise<void>(resolve => server.close(() => resolve()));
      for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
      Object.assign(process.env, saved);
      rmSync(root, { recursive: true, force: true });
    },
  };
}

test('real CLI consumer: prompt/rekey/settle, saved event, missed wake-up and return; no generation or policy import', async () => {
  const w = await world();
  try {
    await w.fire('session_start');
    await w.fire('input', { source: 'rpc', text: 'Real user request' });
    await w.fire('input', { source: 'extension', text: 'Ignore generated continuation' });
    assert.equal(readPrompt('native-session').text, 'Real user request');
    assert.equal(readPrompt('native-session').working, true);
    assert.equal(statSync(path.join(w.root, 'data/herdr-overview/prompts/native-session.json')).mode & 0o777, 0o600);
    w.setPane({ pane_id: 'pane-rekeyed', workspace_id: 'workspace-destination' });
    await w.fire('agent_settled', {}, w.ctx('native-session', true));
    assert.equal(readPrompt('native-session').working, true, 'queued user input must not settle a prompt');
    await w.fire('agent_settled');
    assert.equal(readPrompt('native-session').pane_id, 'pane-rekeyed');
    assert.equal(readPrompt('native-session').working, false);
    const original = w.put('a'.repeat(32));
    w.failWake(true);
    w.listeners.get('recap:saved')({ recordId: original.record_id, sessionId: 'native-session' });
    await wait(() => w.calls.some(c => c.method === 'plugin.action.invoke'));
    const record = w.record(original.record_id);
    assert.deepEqual(record.metadata, original.metadata);
    assert.equal(record.summary, original.summary);
    assert.equal(record.source_id, 'independent-history');
    assert.deepEqual(record.annotations.herdr, { pane_id: 'pane-rekeyed', workspace_id: 'workspace-destination' });
    w.failWake(false);
    w.setPane({ pane_id: 'pane-later', workspace_id: 'workspace-later' });
    await w.fire('session_shutdown');
    await w.fire('session_start');
    assert.equal(w.record(original.record_id).annotations.herdr.workspace_id, 'workspace-destination');
    assert.equal(readPrompt('native-session').pane_id, 'pane-later');
    assert.equal(w.calls.filter(c => c.method === 'plugin.action.invoke').length, 2);
    assert.ok(w.calls.filter(c => c.method === 'pane.current').every(c => c.params.caller_pane_id === 'inherited-caller'));
    const commands = readFileSync(path.join(w.root, 'cli.log'), 'utf8').split('\n');
    assert.ok(commands.every(c => !/^(prepare|publish|prompt|create|config)\b/.test(c)));
  } finally { await w.close(); }
});

test('startup discovers detached saves for native identity; absent Herdr stays session-only', async () => {
  const w = await world();
  try {
    delete process.env.HERDR_SOCKET_PATH;
    const own = w.put('b'.repeat(32));
    const other = w.put('c'.repeat(32), 'other-session');
    await w.fire('session_start');
    assert.deepEqual(w.record(own.record_id).annotations.herdr, {});
    assert.deepEqual(w.record(other.record_id).annotations, {});
    await w.fire('input', { source: 'rpc', text: 'No socket prompt' });
    await w.fire('agent_settled');
    assert.equal(readPrompt('native-session').pane_id, undefined);
    assert.equal(readPrompt('native-session').working, false);
    assert.deepEqual(w.calls, []);
    await w.fire('session_shutdown');
    await w.fire('session_start', {}, w.ctx('other-session'));
    assert.deepEqual(w.record(other.record_id).annotations.herdr, {});
  } finally { await w.close(); }
});

async function scriptedProvider(w: Awaited<ReturnType<typeof world>>) {
  let count = 0;
  const server = http.createServer((request, response) => {
    request.resume(); request.on('end', () => {
      count++;
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      const common = { id: 'script', object: 'chat.completion.chunk', created: 1, model: 'script' };
      response.write('data: ' + JSON.stringify({ ...common, choices: [{ index: 0, delta: { role: 'assistant', content: 'Scripted completed work.' }, finish_reason: null }] }) + '\n\n');
      response.write('data: ' + JSON.stringify({ ...common, choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] }) + '\n\n');
      response.end('data: [DONE]\n\n');
    });
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address() as net.AddressInfo;
  const file = path.join(w.root, 'provider.mjs');
  writeFileSync(file, `export default function(pi) { pi.registerProvider('scripted-overview', { api:'openai-completions',apiKey:'test-only',baseUrl:'http://127.0.0.1:${address.port}/v1', models:[{id:'script',name:'Script',reasoning:false,input:['text'],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:4096,maxTokens:128}] }); }`);
  return { file, count: () => count, close: () => new Promise<void>(resolve => server.close(() => resolve())) };
}
function startPi(w: Awaited<ReturnType<typeof world>>, provider: string, args: string[]) {
  const child = spawn('pi', [...args, '--session-dir', path.join(w.root, 'sessions'), '--provider', 'scripted-overview', '--model', 'script', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files', '--no-tools', '--offline', '--extension', dir, '--extension', provider], { cwd: w.root, env: w.env, stdio: ['pipe', 'pipe', 'pipe'] });
  const records: any[] = [];
  let stdout = '', stderr = '', buffer = '';
  child.stdout.on('data', (x: Buffer) => {
    stdout += x; buffer += x;
    let n;
    while ((n = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, n); buffer = buffer.slice(n + 1);
      try { records.push(JSON.parse(line)); } catch {}
    }
  });
  child.stderr.on('data', (x: Buffer) => { stderr += x; });
  let number = 0;
  return { child, records, stdout: () => stdout, stderr: () => stderr,
    async request(type: string, fields = {}) {
      const id = `${type}-${++number}`;
      child.stdin.write(JSON.stringify({ id, type, ...fields }) + '\n');
      await wait(() => records.some(record => record.id === id) || child.exitCode !== null, type);
      const response = records.find(record => record.id === id);
      assert.equal(response?.success, true, JSON.stringify(response) + stderr);
    },
    async close() {
      if (child.exitCode !== null || child.signalCode !== null) return;
      child.stdin.end();
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => { child.kill('SIGTERM'); reject(new Error('Pi RPC did not exit: ' + stderr)); }, 10000);
        child.once('close', () => { clearTimeout(timer); resolve(); });
      });
    },
  };
}

test('scripted real Pi RPC input completes with private prompt and no duplicate Pi generation', async () => {
  const w = await world();
  const provider = await scriptedProvider(w);
  const rpc = startPi(w, provider.file, ['--mode', 'rpc', '--session-id', 'rpc-proof']);
  try {
    await rpc.request('prompt', { message: 'Real RPC user prompt' });
    await wait(() => rpc.stdout().includes('"type":"agent_settled"'));
    try { await wait(() => readPrompt('rpc-proof')?.working === false, 'private prompt settlement'); }
    catch (error) { throw new Error(`${error}\nRPC: ${rpc.stdout()}\nstderr: ${rpc.stderr()}\nprompt: ${JSON.stringify(readPrompt('rpc-proof'))}`); }
    assert.equal(readPrompt('rpc-proof').text, 'Real RPC user prompt');
    assert.equal(provider.count(), 1, rpc.stderr());
    assert.ok(!rpc.stdout().includes('extension_error'), rpc.stderr());
    assert.deepEqual(JSON.parse(await runSessionRecap(['list', '--json'])).records, []);
  } finally { await rpc.close(); await provider.close(); await w.close(); }
});

test('private bridge rejects duplicates, conflicts and invalid digests; retirement is compare-owned', async () => {
  const w = await world();
  try {
    const sessionId = '11111111-1111-4111-8111-111111111111';
    const record = { schemaVersion: 1, socketPath: w.env.HERDR_SOCKET_PATH, terminalId: 'terminal-exact', paneId: 'old-pane', sessionId, sessionName: 'Full stable synthetic name', publisherPid: process.pid, generation: 'new-owner' };
    const file = writePiMetadata(record);
    const snapshot: any = { protocol: 22, panes: [{ pane_id: 'new-pane', terminal_id: 'terminal-exact' }] };
    const read = () => readPiSessionFields(snapshot, { socketPath: record.socketPath, env: w.env }).piSessionsByPaneId;
    assert.equal(read()['new-pane'].digest.reason, 'missing');
    const digestDir = path.join(w.env.HOME, '.pi/session-search/digests'); mkdirSync(digestDir, { recursive: true });
    writeFileSync(path.join(digestDir, sessionId + '.json'), JSON.stringify({ schemaVersion: 1, body: 'POSITIVE NEW DIGEST', generatedAt: '2026-01-01T00:00:00Z' }));
    assert.equal(read()['new-pane'].digest.body, 'POSITIVE NEW DIGEST');
    retirePiMetadata(file, 'old-owner'); assert.ok(existsSync(file));
    writeFileSync(path.join(path.dirname(file), 'duplicate.json'), JSON.stringify(record)); assert.deepEqual(read(), {}); rmSync(path.join(path.dirname(file), 'duplicate.json'));
    snapshot.panes[0].agent_session = '22222222-2222-4222-8222-222222222222'; assert.deepEqual(read(), {}); delete snapshot.panes[0].agent_session;
    writeFileSync(path.join(digestDir, sessionId + '.json'), JSON.stringify({ schemaVersion: 1, body: 'NEGATIVE INVALID', generatedAt: 'bad' })); assert.equal(read()['new-pane'].digest.body, null);
    writePiMetadata({ ...record, publisherPid: 2147483647 }); assert.deepEqual(read(), {});
    writePiMetadata(record); retirePiMetadata(file, 'new-owner'); assert.equal(existsSync(file), false);
  } finally { await w.close(); }
});

test('disposable Pi replacement and reload publish only the current caller-bound UUID', async () => {
  const w = await world();
  const provider = await scriptedProvider(w);
  writeFileSync(provider.file, readFileSync(provider.file, 'utf8').replace('export default function(pi) {', 'export default function(pi) { pi.registerCommand("fixture-clear-name", { description: "Clear name fixture", handler: async () => { pi.setSessionName(""); } }); pi.registerCommand("fixture-reload", { description: "Reload fixture", handler: async (_args, ctx) => { await ctx.reload(); } }); pi.on("session_start", () => pi.setSessionName("Synthetic full stable lifecycle name"));'));
  const firstId = '11111111-1111-4111-8111-111111111111';
  const rpc = startPi(w, provider.file, ['--mode', 'rpc', '--session-id', firstId]);
  const file = piSessionFile(w.env.HERDR_SOCKET_PATH, 'terminal-exact', w.env);
  try {
    await wait(() => existsSync(file), 'initial bridge');
    assert.equal(readJson(file).sessionId, firstId);
    assert.equal(statSync(file).mode & 0o777, 0o600);
    for (const name of ['Real RPC stable name', 'Replacement RPC stable name']) {
      await rpc.request('set_session_name', { name });
      await wait(() => readJson(file).sessionName === name, 'public name event bridge refresh');
    }
    await wait(() => w.calls.filter(c => c.params?.action_id === 'overview.refresh_names').length >= 2, 'passive name wake-up');
    await rpc.request('prompt', { message: '/fixture-clear-name' });
    await wait(() => readJson(file).sessionName === null, 'public cleared name');
    assert.equal(readJson(file).sessionId, firstId);
    assert.equal(provider.count(), 0);
    assert.ok(!existsSync(path.join(w.root, 'cli.log')) || readFileSync(path.join(w.root, 'cli.log'), 'utf8').trim().split('\n').every(c => c === 'list --json --source-kind pi --status published'));
    const digestDir = path.join(w.env.HOME, '.pi/session-search/digests'); mkdirSync(digestDir, { recursive: true });
    writeFileSync(path.join(digestDir, firstId + '.json'), JSON.stringify({ schemaVersion: 1, body: 'NEGATIVE OLD SESSION', generatedAt: '2026-01-01T00:00:00Z' }));
    await rpc.request('new_session');
    await wait(() => existsSync(file) && readJson(file).sessionId !== firstId, 'replacement bridge');
    const newId = readJson(file).sessionId;
    const read = () => readPiSessionFields(w.snapshot, { socketPath: w.env.HERDR_SOCKET_PATH, env: w.env }).piSessionsByPaneId;
    assert.equal(read()['pane-original'].digest.body, null);
    writeFileSync(path.join(digestDir, newId + '.json'), JSON.stringify({ schemaVersion: 1, body: 'POSITIVE NEW SESSION', generatedAt: '2026-01-02T00:00:00Z' }));
    assert.equal(read()['pane-original'].digest.body, 'POSITIVE NEW SESSION');
    assert.equal(read()['focused-pane'], undefined);
    const oldGeneration = readJson(file).generation;
    await rpc.request('prompt', { message: '/fixture-reload' });
    await wait(() => existsSync(file) && readJson(file).generation !== oldGeneration && readJson(file).sessionId === newId, 'reload bridge');
    assert.equal(readJson(file).sessionName, 'Synthetic full stable lifecycle name');
    assert.equal(provider.count(), 0);
    assert.ok(!rpc.stdout().includes('extension_error'), rpc.stderr());
    await rpc.close(); await wait(() => !existsSync(file), 'owned retirement');
  } finally { await rpc.close(); await provider.close(); await w.close(); }
});

test('real print and JSON children with inherited Herdr env never contact or claim the parent binding', async () => {
  const w = await world();
  const provider = await scriptedProvider(w);
  const record = { schemaVersion: 1, socketPath: w.env.HERDR_SOCKET_PATH, terminalId: 'terminal-exact', paneId: 'pane-original', sessionId: '11111111-1111-4111-8111-111111111111', sessionName: 'Owner interactive name', publisherPid: process.pid, generation: 'owner' };
  const file = writePiMetadata(record);
  try {
    for (const mode of ['text', 'json']) {
      const rpc = startPi(w, provider.file, ['--print', '--mode', mode, '--no-session', 'Synthetic child reply']);
      rpc.child.stdin.end();
      const code = await new Promise<number | null>((resolve, reject) => { rpc.child.once('error', reject); rpc.child.once('exit', resolve); });
      assert.equal(code, 0, rpc.stderr());
      assert.deepEqual(w.calls, []);
      assert.deepEqual(readJson(file), record);
      assert.equal(existsSync(path.join(w.root, 'cli.log')), false);
      assert.deepEqual(readPrompt('native-session'), undefined);
    }
  } finally { retirePiMetadata(file, 'owner'); await provider.close(); await w.close(); }
});

test('actual public wait edges pair one native contribution and clear only owned reason across lifecycle', async () => {
  const { registerQuestionWait } = await import('./question-wait.ts');
  const { EventEmitter } = await import('node:events');
  const w = await world();
  try {
    process.env.HERDR_ENV = '1';
    w.setPane({ pane_id: 'pane-original', workspace_id: 'workspace-original', terminal_id: 'terminal-exact' });
    const handlers = new Map<string, any>(), bus = new EventEmitter(), edges: any[] = [];
    bus.on('herdr:blocked', data => edges.push(data));
    registerQuestionWait({ events: { on: (name: string, fn: any) => bus.on(name, fn), emit: (name: string, data: any) => bus.emit(name, data) }, on: (name: string, fn: any) => handlers.set(name, fn) } as any);
    const ctx = { mode: 'tui', hasUI: true, sessionManager: { getSessionId: () => 'question-session' } } as any;
    await handlers.get('session_start')({}, ctx);
    bus.emit('rpiv:ask-user:blocked', { active: true }); bus.emit('rpiv:ask-user:blocked', { active: true });
    await wait(() => w.calls.some(c => c.method === 'pane.report_metadata' && c.params.state_labels?.blocked === 'Awaiting answer'), 'owned question label');
    bus.emit('rpiv:ask-user:blocked', { active: false }); bus.emit('rpiv:ask-user:blocked', { active: false });
    await handlers.get('session_shutdown')({ reason: 'reload' }, ctx);
    assert.deepEqual(edges, [{ active: true, label: 'Awaiting answer' }, { active: false, label: 'Awaiting answer' }]);
    const reports = w.calls.filter(c => c.method === 'pane.report_metadata');
    assert.ok(reports.length >= 3);
    assert.ok(reports.every(c => c.params.source === 'herdr:overview-question' && c.params.applies_to_source === 'herdr:pi'));
    assert.equal(reports.at(-1).params.clear_state_labels, true);
    assert.ok(reports.every((c, i) => !i || c.params.seq > reports[i - 1].params.seq));
    assert.ok(!w.calls.some(c => c.method === 'pane.report_agent' || c.method === 'pane.clear_agent_authority'));
    bus.emit('rpiv:ask-user:blocked', { active: true }); assert.equal(edges.length, 2);
  } finally { delete process.env.HERDR_ENV; await w.close(); }
});

test('reload with many saved recaps wakes overview once and rides out a full plugin command table', async () => {
  const w = await world();
  const warnings: string[] = []; const original = console.warn; console.warn = (...args: any[]) => { warnings.push(args.join(' ')); };
  try {
    for (const id of ['d', 'e', 'f', '1', '2', '3']) w.put(id.repeat(32));
    w.limit(2);
    await w.fire('session_start');
    const invokes = w.calls.filter(c => c.method === 'plugin.action.invoke' && c.params?.action_id === 'overview.reconcile');
    assert.equal(invokes.length, 3, 'one wake-up for six records, retried twice past the command limit');
    assert.deepEqual(warnings, [], 'a full command table is not reported as a failure');
  } finally { console.warn = original; await w.close(); }
});
