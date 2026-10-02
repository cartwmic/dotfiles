import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
const estimateTokens = message => Math.ceil((typeof message.content === 'string' ? message.content : message.content[0].text).length / 4);

import { generate, budgets, LimitFailure } from './backend.mjs';

test('direct exact virtual selection, explicit options, host resources and disposal', async () => {
  const calls = [];
  const runtime = {
    getModel(p, id) { calls.push(['select', p, id]); return id === 'virtual' ? { id, provider: 'extension', api: 'pi-virtual' } : undefined; },
    async resolveModel(model, messages, options) { assert.equal(model.id, 'virtual'); assert.equal(options.reason, 'direct'); return { model: { id: 'physical', provider: 'physical-provider', contextWindow: 32768, maxTokens: 4096 }, thinkingLevel: options.thinkingLevel }; },
    async completeSimple(model, context, options) { calls.push(['complete', model, context, options]); return { content: [{ type: 'text', text: 'nondefault recap' }], stopReason: 'stop' }; }
  };
  const sdk = {
    estimateTokens,
    ModelRuntime: { async create(options) { calls.push(['auth', options]); return runtime; } },
    SettingsManager: { create() { return {}; } },
    DefaultResourceLoader: class { async reload() { calls.push(['resources']); } },
    SessionManager: { inMemory() { return {}; } },
    async createAgentSession(options) { assert.deepEqual(options.tools, []); assert.equal(options.noTools, true); return { session: { dispose() { calls.push(['dispose']); }, prompt() { throw Error('forbidden'); }, bindExtensions() { throw Error('forbidden'); } } }; }
  };
  const selection = { model: { provider: 'extension', id: 'virtual' }, instructions: 'EXPLICIT', options: { thinkingLevel: 'low', maxTokens: 123 } };
  const derived = await generate(sdk, '/host', '/workspace', selection, 'public source', true);
  assert.equal(derived.maxTokens, 123);
  assert.ok(derived.inputBudget > 24000);
  assert.ok(!calls.some(c => c[0] === 'complete'), 'budget query generated');
  assert.equal(await generate(sdk, '/host', '/workspace', selection, 'public source'), 'nondefault recap');
  assert.deepEqual(calls.find(c => c[0] === 'select'), ['select', 'extension', 'virtual']);
  assert.equal(calls.find(c => c[0] === 'complete')[2].systemPrompt, 'EXPLICIT');
  assert.deepEqual(calls.find(c => c[0] === 'complete')[3], { maxTokens: 123, reasoning: 'low' });
  await generate(sdk, '/host', '/workspace', { ...selection, options: { ...selection.options, apiKey: 'virtual-only-dummy', headers: { Authorization: 'virtual-only-dummy' }, env: { TOKEN: 'virtual-only-dummy' } } }, 'input');
  assert.deepEqual(calls.filter(c => c[0] === 'complete').at(-1)[3], { maxTokens: 123, reasoning: 'low' }, 'virtual caller auth forwarded to another provider');
  for (const budgetOnly of [true, false]) {
    await assert.rejects(generate(sdk, '/host', '/workspace', { ...selection, model: { provider: 'extension', id: 'missing' } }, 'input', budgetOnly),
      error => error instanceof LimitFailure && error.reason === 'model_limits' && error.message === 'Selected recap model unavailable');
  }
  for (const stopReason of ['length', 'error', 'aborted', 'toolUse', undefined]) {
    runtime.completeSimple = async () => ({ content: [{ type: 'text', text: 'partial' }], stopReason });
    await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'input'), /did not finish/);
  }
  await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'x'.repeat(150000)), /exceeds routed/);
  const resolve = runtime.resolveModel;
  runtime.resolveModel = async () => ({ model: { id: 'changed-route', contextWindow: 2048, maxTokens: 512 }, thinkingLevel: 'off' });
  const count = calls.filter(c => c[0] === 'complete').length;
  await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'x'.repeat(10000)), /exceeds routed/);
  assert.equal(calls.filter(c => c[0] === 'complete').length, count, 'smaller actual route generated oversized input');
  runtime.resolveModel = resolve;
  runtime.completeSimple = async () => ({ stopReason: 'error', errorMessage: 'Your input exceeds the context window of this model PRIVATE', content: [] });
  await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'input'), error => error.reason === 'context_limit' && !error.message.includes('PRIVATE'));
  runtime.completeSimple = async () => ({ stopReason: 'error', errorMessage: 'Throttling: too many tokens PRIVATE', content: [] });
  await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'input'), error => !error.reason && !error.message.includes('PRIVATE'));
  runtime.completeSimple = async () => { throw Error('auth unavailable'); };
  await assert.rejects(generate(sdk, '/host', '/workspace', selection, 'input'), /auth unavailable/);
});

test('installed SDK estimate preserves quarter-window output for default and explicit small-model requests', async () => {
  const sdkPath = execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim() + '/@earendil-works/pi-coding-agent/dist/index.js';
  const { estimateTokens } = await import(pathToFileURL(sdkPath).href);
  const physical = { provider: 'physical', id: 'small', contextWindow: 4096, maxTokens: 4096 };
  const virtual = { provider: 'router', id: 'auto', api: 'pi-virtual' };
  const fact = 'FACT_result=checks-passed';
  const calls = [];
  const runtime = {
    getModel(provider) { return provider === 'router' ? virtual : physical; },
    async resolveModel() { return { model: physical, thinkingLevel: 'off' }; },
    async completeSimple(model, context, options) {
      assert.equal(model, physical);
      assert.equal(context.messages[0].content[0].text, fact);
      calls.push(options);
      return { content: [{ type: 'text', text: 'checks-passed' }], stopReason: 'stop' };
    }
  };
  const sdk = {
    estimateTokens, ModelRuntime: { async create() { return runtime; } },
    SettingsManager: { create() { return {}; } },
    DefaultResourceLoader: class { async reload() {} },
    SessionManager: { inMemory() { return {}; } },
    async createAgentSession() { return { session: { dispose() {} } }; }
  };
  for (const model of [physical, virtual]) {
    for (const options of [{}, { maxTokens: 4096 }]) {
      const selection = { model, instructions: 'Recap', options };
      const derived = await generate(sdk, '/unused', '/unused', selection, fact, true);
      assert.equal(derived.maxTokens, 1024);
      assert.ok(derived.inputBudget >= Buffer.byteLength(fact));
      assert.equal(await generate(sdk, '/unused', '/unused', selection, fact), 'checks-passed');
      assert.equal(calls.at(-1).maxTokens, 1024);
    }
  }
  assert.equal(calls.length, 4, 'preflight must not generate');
});

test('model-derived estimated budgets retire byte caps and reserve output/framing', () => {
  const model = { contextWindow: 4096, maxTokens: 512 };
  const selection = { instructions: 'brief', inputBudget: 1, options: { maxTokens: 4096 } };
  const derive = (s = selection, thinking = 'off', input = 'x'.repeat(4000)) => budgets(model, s, thinking, estimateTokens, input);
  const result = derive();
  assert.equal(result.maxTokens, 512);
  assert.equal(result.estimatedInputTokens, 1000);
  assert.ok(result.inputBudget > 10000);
  assert.deepEqual(derive({ ...selection, inputBudget: 24000 }), result);
  assert.ok(derive({ ...selection, options: { maxTokens: 128 } }).inputBudget > result.inputBudget);
  assert.equal(derive({ ...selection, options: { maxTokens: 128 } }, 'high').inputBudget, result.inputBudget);
  assert.ok(derive(selection, 'off', '観'.repeat(4000)).inputBudget > result.inputBudget, 'bytes are not mislabeled as tokens');
  for (const bad of [{ contextWindow: 0, maxTokens: 512 }, { contextWindow: 4096, maxTokens: 0 }]) assert.throws(() => budgets(bad, selection, 'off', estimateTokens, 'source'));
  assert.throws(() => derive({ ...selection, instructions: 'x'.repeat(20000) }));
});
