#!/usr/bin/env node
// Owner adapter only: the installed package owns all patch payload and checks.
import { existsSync } from 'node:fs';
import { delimiter, join } from 'node:path';
import { homedir } from 'node:os';
import { execFileSync, spawnSync } from 'node:child_process';

const profile = process.env.PI_CHEZMOI_PROFILE;
if (!['personal', 'axon-work-computer'].includes(profile)) {
  console.log('[response-visibility] skipped: desktop profile required');
  process.exit(0);
}
const actions = { '--check': 'check', '--rollback': 'rollback', check: 'check', apply: 'apply', rollback: 'rollback' };
const args = process.argv.slice(2);
if (args.length > 1 || (args.length && !actions[args[0]])) {
  console.error('Usage: patch.mjs [--check|--rollback|check|apply|rollback]');
  process.exit(1);
}
// Prefer an explicit helper, then a package bin, then Pi's installed Git package.
// This is discovery/delegation only: never download or duplicate the patch payload.
const helper = process.env.PI_RESPONSE_VISIBILITY_HELPER || (process.env.PATH || '')
  .split(delimiter).map(dir => join(dir, 'pi-response-visibility-core')).find(existsSync)
  || join(process.env.PI_CODING_AGENT_DIR || join(homedir(), '.pi', 'agent'), 'git', 'github.com', 'cartwmic', 'pi-response-visibility', 'bin', 'core.mjs');
if (!helper || !existsSync(helper)) {
  console.error('[response-visibility] missing canonical helper; install the Pi Git package, expose its package bin on PATH, or set PI_RESPONSE_VISIBILITY_HELPER to its bin/core.mjs');
  process.exit(1);
}
const forwarded = [helper, actions[args[0]] || 'apply'];
let root = process.env.PI_ROOT;
if (!root) {
  try { root = join(execFileSync('npm', ['root', '-g'], { encoding: 'utf8' }).trim(), '@earendil-works', 'pi-coding-agent'); }
  catch { console.error('[response-visibility] cannot resolve global Pi root; set PI_ROOT explicitly'); process.exit(1); }
}
forwarded.push('--pi-root', root);
const result = spawnSync(process.execPath, forwarded, { stdio: 'inherit' });
if (result.error) console.error(result.error.message);
process.exit(result.status ?? 1);
