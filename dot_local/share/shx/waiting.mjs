// shx-waiting entry: wires the real adapters into the core and prints the waiting threads. Contract and layout: README.md.
// The wrapper (bin/executable_shx-waiting) loads this file and turns any failure to load or run it into exit 3: exit 1 means
// "something waits".
import { randomBytes } from 'node:crypto';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { createFsStore } from './adapters/fs_store.mjs';
import { api } from './adapters/shartifacts_http.mjs';
import { runWaiting } from './core/waiting.mjs';

const env = process.env;
// The server the skill documents; SHARTIFACTS_URL or a URL argument overrides it.
const DEFAULT_BASE = 'https://shartifacts.internal.cartwmic.com';
const store = createFsStore(join(env.XDG_STATE_HOME || join(homedir(), '.local', 'state'), 'shx'), 'waiting.log');
const { stdout, stderr, exitCode } = await runWaiting(process.argv.slice(2), {
  api,
  files: store.files,
  log: store.log,
  clock: { now: () => Date.now() },
  random: { hex: () => randomBytes(3).toString('hex') },
  warn: (line) => process.stderr.write(line + '\n'),
}, { base: env.SHARTIFACTS_URL || DEFAULT_BASE });
if (stdout) process.stdout.write(stdout + '\n');
if (stderr) process.stderr.write(stderr + '\n');
process.exitCode = exitCode;
