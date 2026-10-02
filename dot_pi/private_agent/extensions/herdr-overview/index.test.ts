import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, statSync, chmodSync } from 'node:fs';
import { spawn } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import extension from './index.ts';
import { readPrompt } from './prompt-store.ts';
import { runSessionRecap } from './helpers.ts';

const dir = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(dir, '../../../..');
const delay = (ms: number) => new Promise(r => setTimeout(r, ms));
async function wait(predicate: () => boolean) {
  for (let i = 0; i < 250; i++) { if (predicate()) return; await delay(20); }
  throw new Error('consumer did not complete');
}
async function world() {
  const root = mkdtempSync(path.join(os.tmpdir(), 'overview-consumer-'));
  const saved = { ...process.env };
  const calls: any[] = [];
  let pane: any = { pane_id: 'pane-original', workspace_id: 'workspace-original' };
  let failWake = false;
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
        : failWake ? { error: { message: 'scripted missed wake-up' } } : { result: {} }) }) + '\n');
    });
  });
  await new Promise<void>(resolve => server.listen(socketPath, resolve));
  const cli = path.join(root, 'cli');
  writeFileSync(cli, `#!/bin/sh\nprintf '%s\\n' "$*" >> '${root}/cli.log'\nexec python3 '${repo}/dot_local/share/session-recap/session_recap.py' "$@"\n`);
  chmodSync(cli, 0o700);
  Object.assign(process.env, { XDG_DATA_HOME: path.join(root, 'data'), XDG_CONFIG_HOME: path.join(root, 'config'), SESSION_RECAP_BIN: cli, HERDR_SOCKET_PATH: socketPath, HERDR_PANE_ID: 'inherited-caller' });
  const recordsDir = path.join(root, 'data/session-recap/records/2026-10-01');
  mkdirSync(recordsDir, { recursive: true });
  const hooks = new Map<string, any[]>();
  const listeners = new Map<string, any>();
  extension({ on(name: string, handler: any) { hooks.set(name, [...(hooks.get(name) ?? []), handler]); }, events: { on(name: string, handler: any) { listeners.set(name, handler); return () => listeners.delete(name); } } } as any);
  const ctx = (id = 'native-session', idle = true) => ({ mode: 'rpc', isIdle: () => idle, sessionManager: { getSessionId: () => id } });
  const fire = async (name: string, event: any = {}, context: any = ctx()) => { for (const fn of hooks.get(name) ?? []) await fn(event, context); };
  const put = (id: string, owner = 'native-session') => {
    const record = { schema_version: 2, record_id: id, source_kind: 'pi', source_id: 'independent-history', kind: 'single', status: 'published', created_at: '2026-10-01T00:00:00Z', summary: 'Saved only once by Pi', metadata: { pi: { sessionId: owner, historyId: 'independent-history', coverage: { anchor: 'original-anchor' } } }, annotations: {} };
    writeFileSync(path.join(recordsDir, `${id}.json`), JSON.stringify(record));
    return record;
  };
  return { root, cli, calls, ctx, fire, put, listeners,
    setPane(value: any) { pane = value; }, failWake(value: boolean) { failWake = value; },
    record(id: string) { return JSON.parse(readFileSync(path.join(recordsDir, `${id}.json`), 'utf8')); },
    async close() { await new Promise<void>(resolve => server.close(() => resolve())); for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key]; Object.assign(process.env, saved); rmSync(root, { recursive: true, force: true }); },
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

test('scripted real Pi RPC input completes with private prompt and no duplicate Pi generation', async () => {
  const w = await world();
  let child: any;
  try {
    const agentDir = path.join(w.root, 'agent');
    mkdirSync(agentDir);
    writeFileSync(path.join(agentDir, 'settings.json'), JSON.stringify({ cacheWarming: 'off', enableInstallTelemetry: false }));
    const provider = path.join(w.root, 'provider.mjs');
    // No credentials, owner server, or paid model; drive the public Pi RPC path.
    const http = await import('node:http');
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
    writeFileSync(provider, `export default function(pi) { pi.registerProvider('scripted-overview', { api:'openai-completions',apiKey:'test-only',baseUrl:'http://127.0.0.1:${address.port}/v1', models:[{id:'script',name:'Script',reasoning:false,input:['text'],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:4096,maxTokens:128}] }); }`);
    try {
      child = spawn('pi', ['--mode', 'rpc', '--session-id', 'rpc-proof', '--session-dir', path.join(w.root, 'sessions'), '--provider', 'scripted-overview', '--model', 'script', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files', '--no-tools', '--offline', '--extension', dir, '--extension', provider], { cwd: w.root, env: { ...process.env, PI_CODING_AGENT_DIR: agentDir, PI_OFFLINE: '1', PI_TELEMETRY: '0' }, stdio: ['pipe', 'pipe', 'pipe'] });
      let stdout = '', stderr = '';
      child.stdout.on('data', (x: Buffer) => { stdout += x; });
      child.stderr.on('data', (x: Buffer) => { stderr += x; });
      child.stdin.write(JSON.stringify({ id: 'proof', type: 'prompt', message: 'Real RPC user prompt' }) + '\n');
      await wait(() => stdout.includes('"type":"agent_settled"'));
      await wait(() => readPrompt('rpc-proof')?.working === false);
      assert.equal(readPrompt('rpc-proof').text, 'Real RPC user prompt');
      assert.equal(count, 1, stderr);
      assert.ok(!stdout.includes('extension_error'), stderr);
      const listed = JSON.parse(await runSessionRecap(['list', '--json']));
      assert.deepEqual(listed.records, []);
      child.stdin.end();
      await new Promise<void>(resolve => child.once('close', resolve));
      child = undefined;
    } finally { child?.kill('SIGTERM'); await new Promise<void>(resolve => server.close(() => resolve())); }
  } finally { await w.close(); }
});
