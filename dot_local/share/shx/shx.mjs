// shx-note-image entry: wires the real adapters into the core and prints the one JSON object for stdout.
// Contract and layout: README.md.
import { randomBytes } from 'node:crypto';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { locateChromium, open } from './adapters/chromium.mjs';
import { outline } from './adapters/freehand.mjs';
import { createFsStore } from './adapters/fs_store.mjs';
import { api } from './adapters/shartifacts_http.mjs';
import { run } from './core/use_cases.mjs';

const env = process.env;
const store = createFsStore(join(env.XDG_STATE_HOME || join(homedir(), '.local', 'state'), 'shx'));

const { output, exitCode } = await run(process.argv.slice(2), {
  api,
  browser: { locate: () => locateChromium(env), open },
  outline,
  files: store.files,
  log: store.log,
  clock: { now: () => Date.now() },
  random: { hex: () => randomBytes(3).toString('hex') },
  warn: (line) => process.stderr.write(line + '\n'),
}, { base: env.SHARTIFACTS_URL });
process.stdout.write(JSON.stringify(output) + '\n');
process.exitCode = exitCode;
