import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generate, budgets } from './backend.mjs';

test('direct exact virtual selection, explicit options, host resources and disposal', async () => {
  const calls = [];
  const runtime = {
    getModel(p, id) { calls.push(['select', p, id]); return id === 'virtual' ? { id, provider: 'extension', api: 'pi-virtual' } : undefined; },
    async resolveModel(model, messages, options) { assert.equal(model.id, 'virtual'); assert.equal(options.reason, 'direct'); return { model: { id: 'physical', provider: 'physical-provider', contextWindow: 32768, maxTokens: 4096 }, thinkingLevel: options.thinkingLevel }; },
    async completeSimple(model, context, options) { calls.push(['complete', model, context, options]); return { content: [{ type: 'text', text: 'nondefault recap' }], stopReason: 'stop' }; }
  };
  const sdk = {
    ModelRuntime: { async create(options) { calls.push(['auth', options]); return runtime; } },
    SettingsManager: { create() { return {}; } },
    DefaultResourceLoader: class { async reload() { calls.push(['resources']); } },
    SessionManager: { inMemory() { return {}; } },
    async createAgentSession(options) { assert.deepEqual(options.tools, []); assert.equal(options.noTools, true); return { session: { dispose() { calls.push(['dispose']); }, prompt() { throw Error('forbidden'); }, bindExtensions() { throw Error('forbidden'); } } }; }
  };
  const selection = { model: { provider: 'extension', id: 'virtual' }, instructions: 'EXPLICIT', options: { thinkingLevel: 'low', maxTokens: 123 } };
  assert.deepEqual(await generate(sdk, '/host', '/workspace', selection, 'public source', true), { inputBudget: 24000, maxTokens: 123 });
  assert.ok(!calls.some(c => c[0] === 'complete'), 'budget query generated');
  assert.equal(await generate(sdk, '/host', '/workspace', selection, 'public source'), 'nondefault recap');
  assert.deepEqual(calls.find(c => c[0] === 'select'), ['select', 'extension', 'virtual']);
  assert.equal(calls.find(c => c[0] === 'complete')[2].systemPrompt, 'EXPLICIT');
  assert.deepEqual(calls.find(c => c[0] === 'complete')[3], { maxTokens: 123, reasoning: 'low' });
  await generate(sdk, '/host', '/workspace', { ...selection, options: { ...selection.options, apiKey: 'virtual-only-dummy', headers: { Authorization: 'virtual-only-dummy' }, env: { TOKEN: 'virtual-only-dummy' } } }, 'input');
  assert.deepEqual(calls.filter(c => c[0] === 'complete').at(-1)[3], { maxTokens: 123, reasoning: 'low' }, 'virtual caller auth forwarded to another provider');
  await assert.rejects(generate(sdk, '/host', '/workspace', { ...selection, model: { provider: 'extension', id: 'missing' } }, 'input'), /unavailable/);
  for (const stopReason of ['length', 'error', 'aborted', 'toolUse', undefined]) {
    runtime.completeSimple = async () => ({ content: [{ type: 'text', text: 'partial' }], stopReason });
    await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'input'), /did not finish/);
  }
  await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'x'.repeat(40000)), /exceeds routed/);
  const resolve = runtime.resolveModel;
  runtime.resolveModel = async () => ({ model: { id: 'changed-route', contextWindow: 2048, maxTokens: 512 }, thinkingLevel: 'off' });
  const count = calls.filter(c => c[0] === 'complete').length;
  await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'x'.repeat(1500)), /exceeds routed/);
  assert.equal(calls.filter(c => c[0] === 'complete').length, count, 'smaller actual route generated oversized input');
  runtime.resolveModel = resolve;
  runtime.completeSimple = async () => { throw Error('auth unavailable'); };
  await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'input'), /auth unavailable/);
});

test('physical conservative budgets respect user ceilings, framing, instructions and reasoning', () => {
  const model = { contextWindow: 4096, maxTokens: 512 };
  const selection = { instructions: 'brief', inputBudget: 24000, options: { maxTokens: 4096 } };
  assert.deepEqual(budgets(model, selection), { inputBudget: 2555, maxTokens: 512 });
  assert.deepEqual(budgets(model, { ...selection, inputBudget: 700, options: { maxTokens: 128 } }), { inputBudget: 700, maxTokens: 128 });
  assert.equal(budgets(model, { ...selection, options: { maxTokens: 128 } }, 'high').inputBudget, 2555);
  for (const bad of [{ contextWindow: 0, maxTokens: 512 }, { contextWindow: 4096, maxTokens: 0 }, { contextWindow: 512, maxTokens: 128 }]) assert.throws(() => budgets(bad, selection));
  assert.throws(() => budgets(model, { ...selection, instructions: 'x'.repeat(4096) }));
});
