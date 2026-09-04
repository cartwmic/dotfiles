import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const patch = fileURLToPath(new URL('./patch.mjs', import.meta.url));
const id = 'gpt-6-astra';
const group = 'openai-codex-responses';
const marker = `chezmoi-pi-patch:openai-codex-gpt-6-astra`;
const entry = readFileSync(patch, 'utf8').match(/const BUNDLE_ENTRY = `(.*)`;/)[1]
  .replaceAll('${MODEL_ID}', id);
const v2 = `,/*${marker} v2*/${entry.replace('contextWindow:872e3', 'contextWindow:272e3')}`;

function fixture(t, variant) {
  const dir = mkdtempSync(join(tmpdir(), 'astra-patch-test-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const root = join(dir, 'global');
  const pkg = join(root, '@earendil-works/pi-coding-agent');
  const json = join(pkg, 'node_modules/@earendil-works/pi-ai/dist/providers/data/openai-codex.json');
  const bundle = join(pkg, 'dist/bundle/chunks/chunk-test.js');
  const bin = join(dir, 'bin');
  for (const p of [bin, join(pkg, 'dist/bundle/chunks'), join(json, '..')]) mkdirSync(p, { recursive: true });
  writeFileSync(join(pkg, 'package.json'), '{"version":"0.85.0"}');
  writeFileSync(join(bin, 'npm'), `#!/bin/sh\nprintf '%s\\n' '${root}'\n`, { mode: 0o755 });
  const base = `var openai_codex_default={"${group}":{"gpt-5.5":{id:"gpt-5.5",contextWindow:272000}}};`;
  const suffix = 'var OPENAI_CODEX_MODELS=flattenModelCatalog("openai-codex",openai_codex_default);\n' +
    'function flattenModelCatalog(p,c){return Object.values(c).flatMap(Object.values)}\n' +
    `console.log(JSON.stringify(OPENAI_CODEX_MODELS.find(m=>m.id==="${id}")));`;
  const vanilla = base + suffix;
  const vanillaJson = JSON.stringify({ [group]: { 'gpt-5.5': { id: 'gpt-5.5', contextWindow: 272000 } } });
  writeFileSync(bundle, vanilla);
  writeFileSync(json, vanillaJson);
  if (variant !== 'fresh') {
    const insert = variant === 'v2' ? v2 : `,"${id}":{id:"${id}",contextWindow:900000}`;
    writeFileSync(bundle, base.slice(0, -3) + insert + base.slice(-3) + suffix);
    const data = JSON.parse(vanillaJson);
    data[group][id] = { id, contextWindow: variant === 'v2' ? 272000 : 900000 };
    writeFileSync(json, JSON.stringify(data));
    if (variant === 'v2') {
      writeFileSync(bundle + '.orig.chezmoi-pi-patch', vanilla);
      writeFileSync(json + '.orig.chezmoi-pi-patch', vanillaJson);
    }
  }
  // Simulate another patch sharing the chunk: upgrading must preserve it.
  writeFileSync(bundle, readFileSync(bundle, 'utf8') + '\n// unrelated edit\n');
  const run = (profile = 'personal', args = []) => spawnSync(process.execPath, [patch, ...args], {
    env: { ...process.env, HOME: dir, NODE_PATH: '', PATH: `${bin}:${process.env.PATH}`, PI_CHEZMOI_PROFILE: profile },
    encoding: 'utf8', timeout: 15000,
  });
  return { run, bundle, json };
}

for (const variant of ['fresh', 'v2']) {
  test(`${variant}: CLI apply yields 872K, is idempotent, and restores on work profile`, t => {
    const f = fixture(t, variant);
    assert.notEqual(f.run('personal', ['--check']).status, 0);
    const apply = f.run();
    assert.equal(apply.status, 0, apply.stderr);
    assert.equal(f.run('personal', ['--check']).status, 0);
    assert.equal(JSON.parse(readFileSync(f.json, 'utf8'))[group][id].contextWindow, 872000);
    const cli = spawnSync(process.execPath, [f.bundle], { encoding: 'utf8' });
    assert.equal(cli.status, 0, cli.stderr);
    assert.equal(JSON.parse(cli.stdout).contextWindow, 872000);
    const first = readFileSync(f.bundle, 'utf8');
    assert.ok(first.includes('// unrelated edit'));
    assert.ok(first.includes(`${marker} v3`));
    assert.equal(f.run().status, 0);
    assert.equal(readFileSync(f.bundle, 'utf8'), first);
    assert.equal(f.run('axon-work-computer').status, 0);
    assert.equal(f.run('axon-work-computer', ['--check']).status, 0);
    assert.ok(!readFileSync(f.bundle, 'utf8').includes(marker));
    assert.ok(!JSON.parse(readFileSync(f.json, 'utf8'))[group][id]);
  });
}

test('native upstream entry stays byte-identical on either profile', t => {
  const f = fixture(t, 'upstream');
  const before = [readFileSync(f.bundle, 'utf8'), readFileSync(f.json, 'utf8')];
  const result = f.run();
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /upstream caught up/);
  assert.equal(f.run('personal', ['--check']).status, 0);
  assert.equal(f.run('axon-work-computer').status, 0);
  assert.deepEqual([readFileSync(f.bundle, 'utf8'), readFileSync(f.json, 'utf8')], before);
});
