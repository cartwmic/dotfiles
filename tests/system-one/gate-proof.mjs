import assert from 'node:assert/strict';
import { mkdtempSync, cpSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const sourceRoot = fileURLToPath(new URL('../../', import.meta.url));

const profile = process.argv[process.argv.indexOf('--profile') + 1];
assert.ok(['personal', 'axon-work-computer'].includes(profile), 'explicit supported profile required');
const piRoot = process.env.PI_ROOT ?? '/Users/cartwmic/.local/share/mise/installs/node/24.18.1/lib/node_modules/@earendil-works/pi-coding-agent';
const plusRoot = process.env.PI_OPENROUTER_PLUS_ROOT ?? '/Users/cartwmic/.pi/agent/git/github.com/olixis/pi-openrouter-plus';
const load = p => import(pathToFileURL(join(piRoot, p)).href);
const sandbox = mkdtempSync(join(tmpdir(), 'gate-proof-'));
const oldHome = process.env.HOME;
const oldKey = process.env.OPENROUTER_API_KEY;
const oldFetch = globalThis.fetch;
const traffic = [];
const unexpected = [];
try {
  process.env.HOME = sandbox;
  delete process.env.OPENROUTER_API_KEY;
  const { ModelRuntime } = await load('dist/core/model-runtime.js');
  const { ModelRegistry } = await load('dist/core/model-registry.js');
  const { loadExtensions, createExtensionRuntime } = await load('dist/core/extensions/loader.js');
  const { getBuiltinClassifierModels } = await load('node_modules/@earendil-works/pi-ai/dist/providers/all.js');
  const nativeId = getBuiltinClassifierModels('openrouter')[0]?.id;
  assert.ok(nativeId, 'real builtin native classifier must exist');
  const chatId = 'z-ai/glm-5.3-flash';
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input instanceof Request ? input.url : input);
    const body = init.body ? JSON.parse(init.body) : undefined;
    traffic.push({ url, body, headers: Object.fromEntries(new Headers(init.headers)) });
    if (url === 'https://openrouter.ai/api/v1/models') return Response.json({ data: [chatId, nativeId].map(id => ({ id, name: id, context_length: 8192, architecture: { input_modalities: ['text'] }, pricing: { prompt: '0.000001', completion: '0.000002' }, top_provider: { max_completion_tokens: 512 } })) });
    if (['https://openrouter.ai/api/v1/systemone', 'https://openrouter.ai/api/v1/chat/completions'].includes(url) && new Headers(init.headers).get('authorization') !== 'Bearer fixture-only') return Response.json({ error: { message: 'Invalid API key', code: 401 } }, { status: 401 });
    if (url === 'https://openrouter.ai/api/v1/systemone') return Response.json({ answers: { ready: { type: 'noul', noul: 0.95 } }, usage: { input_tokens: 2, output_tokens: 1 } });
    if (url === 'https://openrouter.ai/api/v1/chat/completions') {
      const chunk = { id: 'scripted', object: 'chat.completion.chunk', created: 1, model: chatId, choices: [{ index: 0, delta: { role: 'assistant', content: 'completed scripted chat' }, finish_reason: null }] };
      const done = { ...chunk, choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] };
      return new Response(`data: ${JSON.stringify(chunk)}\n\ndata: ${JSON.stringify(done)}\n\ndata: [DONE]\n\n`, { headers: { 'content-type': 'text/event-stream' } });
    }
    unexpected.push(url);
    throw new Error(`Unexpected network denied: ${url}`);
  };
  mkdirSync(join(sandbox, '.pi/agent'), { recursive: true });
  const authPath = join(sandbox, '.pi/agent/auth.json');
  writeFileSync(authPath, JSON.stringify(profile === 'personal' ? { 'openrouter-stashed': { type: 'api_key', key: 'fixture-only' } } : {}));
  const runtime = await ModelRuntime.create({ authPath, modelsPath: null, modelsStorePath: join(sandbox, 'models-cache.json'), refreshOnCreate: false });
  const registry = new ModelRegistry(runtime);
  const extensionRuntime = createExtensionRuntime();
  extensionRuntime.registerProvider = (id, config) => registry.registerProvider(id, config);
  const paths = [];
  if (profile === 'personal') {
    const gate = join(sandbox, 'gate');
    cpSync(resolve(sourceRoot, 'dot_pi/private_agent/extensions/openrouter-gate'), gate, { recursive: true });
    writeFileSync(join(gate, 'config.json'), JSON.stringify({ enabled: true, allowedModels: [nativeId, chatId] }));
    paths.push(join(gate, 'index.ts'), join(plusRoot, 'extensions/openrouter-routing/index.ts'));
  } else {
    await runtime.setRuntimeApiKey('openrouter', 'fixture-only', { allowNetwork: false });
  }
  const loaded = await loadExtensions(paths, sandbox, undefined, extensionRuntime);
  assert.deepEqual(loaded.errors, []);
  for (const registration of extensionRuntime.pendingProviderRegistrations) registry.registerProvider(registration.name, registration.config);
  const ctx = { modelRegistry: registry, hasUI: false, ui: { notify() {}, setStatus() {} } };
  const emit = async name => { for (const extension of loaded.extensions) for (const handler of extension.handlers.get(name) ?? []) await handler({ type: name }, ctx); };
  const command = async (name, args) => {
    const owner = loaded.extensions.find(e => e.commands.has(name));
    assert.ok(owner, `missing command ${name}`);
    await owner.commands.get(name).handler(args, ctx);
  };
  await emit('session_start');
  if (profile === 'personal') {
    await command('openrouter-sync', '');
    assert.equal(registry.getModelOfType('classifier', 'openrouter', nativeId), undefined, 'actual plus chat overlay erases native before gate hook');
  }
  await emit('resources_discover');
  await emit('before_agent_start');
  await emit('model_select');
  const native = registry.getModelOfType('classifier', 'openrouter', nativeId);
  assert.equal(native?.type, 'classifier');
  assert.ok((await registry.getAvailableOfType('classifier', 'openrouter')).some(m => m.id === nativeId));
  const result = await registry.classify(native, { state: { ready: true }, questions: { ready: { type: 'bool', instructions: 'Is the explicit ready flag true?', criteria: { true: 'ready is true', false: 'ready is false' } } } }, { maxRetries: 0 });
  assert.equal(result.stopReason, 'stop', JSON.stringify(result));
  assert.equal(result.answers.ready.probability, 0.95);
  const chat = registry.find('openrouter', chatId);
  const completed = await registry.streamSimple(chat, { messages: [{ role: 'user', content: 'fixture chat', timestamp: 1 }] }, { maxRetries: 0 }).result();
  assert.equal(completed.stopReason, 'stop', JSON.stringify(completed));
  assert.equal(completed.content[0].text, 'completed scripted chat');
  for (const request of traffic.filter(t => /\/(systemone|chat\/completions)$/.test(t.url))) assert.equal(request.headers.authorization, 'Bearer fixture-only');
  assert.equal(Object.hasOwn(native, 'apiKey'), false);
  if (profile === 'personal') {
    const request = traffic.find(t => t.url.endsWith('/chat/completions'));
    assert.equal(request.body.model, chatId);
    assert.equal(request.headers['http-referer'], 'https://github.com/olixis/pi-openrouter-plus');
    assert.equal(request.headers['x-title'], 'pi-openrouter-realtime');
    await command('openrouter', 'off');
    await command('openrouter-sync', '');
    await emit('resources_discover');
    assert.equal(registry.getModelOfType('classifier', 'openrouter', nativeId), undefined);
    assert.equal((await registry.getAvailableOfType('classifier', 'openrouter')).length, 0);
    assert.equal(process.env.OPENROUTER_API_KEY, undefined);
    assert.equal(await registry.getApiKeyForProvider('openrouter'), undefined);
    assert.equal(registry.getRegisteredProviderConfig('openrouter').apiKey, '$OPENROUTER_API_KEY');
    const before = traffic.filter(t => t.url.endsWith('/systemone')).length;
    const refused = await registry.classify(native, { state: { ready: true }, questions: { ready: { type: 'bool', instructions: 'Is the explicit ready flag true?', criteria: { true: 'ready is true', false: 'ready is false' } } } }, { maxRetries: 0 });
    console.log(JSON.stringify({ profile, nativeId, allowedNativeSuccess: result.stopReason, completedChat: completed.content[0].text, offDiscoveryHidden: true, offAvailabilityEmpty: true, staleNativeAfterOff: refused.stopReason, nativeCalls: traffic.filter(t => t.url.endsWith('/systemone')).length, unexpected }));
    assert.equal(refused.stopReason, 'error', 'off must refuse even a previously discovered native model');
    assert.equal(traffic.filter(t => t.url.endsWith('/systemone')).length, before);
    await command('openrouter', 'on');
    writeFileSync(join(sandbox, 'gate/config.json'), JSON.stringify({ enabled: true, allowedModels: [chatId] }));
    await command('openrouter', 'reload');
    await command('openrouter-sync', '');
    await emit('before_agent_start');
    assert.equal(registry.getModelOfType('classifier', 'openrouter', nativeId), undefined);
    assert.equal((await registry.getAvailableOfType('classifier', 'openrouter')).length, 0);
    writeFileSync(join(sandbox, 'gate/config.json'), JSON.stringify({ enabled: true, allowedModels: [nativeId, chatId] }));
    await command('openrouter', 'reload');
    await command('openrouter-sync', '');
    await emit('resources_discover');
    assert.equal(registry.getModelOfType('classifier', 'openrouter', nativeId)?.type, 'classifier');
    assert.ok((await registry.getAvailableOfType('classifier', 'openrouter')).some(m => m.id === nativeId));
    assert.equal(await registry.getApiKeyForProvider('openrouter'), 'fixture-only');
  } else assert.equal(loaded.extensions.length, 0);
  assert.deepEqual(unexpected, []);
  assert.equal(traffic.filter(t => t.url.endsWith('/systemone')).length, 1);
  console.log(JSON.stringify({ profile, nativeId, nativeCalls: 1, completedChat: completed.content[0].text, traffic: traffic.map(t => ({ url: t.url, authorization: t.headers.authorization ?? null })), unexpected, personalComposition: profile === 'personal' }));
} finally {
  globalThis.fetch = oldFetch;
  if (oldHome === undefined) delete process.env.HOME; else process.env.HOME = oldHome;
  if (oldKey === undefined) delete process.env.OPENROUTER_API_KEY; else process.env.OPENROUTER_API_KEY = oldKey;
  rmSync(sandbox, { recursive: true, force: true });
}
