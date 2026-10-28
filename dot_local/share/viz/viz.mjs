// viz CLI entry: wires the real adapters into the core and prints the one JSON
// object for stdout. Contract and layout: README.md.
import { randomBytes } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { locateChromium, screenshot } from './adapters/chromium.mjs';
import { createFsStore } from './adapters/fs_store.mjs';
import { createSite } from './adapters/http_site.mjs';
import { createMermaid } from './adapters/mmdc.mjs';
import { VizError } from './core/domain.mjs';
import { runAction } from './core/use_cases.mjs';

const env = process.env;

const input = {
  read(file) {
    if (file === '-') {
      const bytes = readFileSync(0);
      return { bytes, text: bytes.toString('utf8'), path: '-', baseHref: null };
    }
    const path = resolve(file);
    let st;
    try { st = statSync(path); } catch { throw new VizError('bad_input', `no such file: ${file}`); }
    if (!st.isFile()) throw new VizError('bad_input', `not a regular file: ${file}`);
    const bytes = readFileSync(path);
    return { bytes, text: bytes.toString('utf8'), path, baseHref: pathToFileURL(dirname(path) + '/').href };
  },
};

const { output, exitCode } = await runAction(process.argv.slice(2), {
  store: createFsStore(resolve(env.VIZ_STATE_DIR || join(homedir(), '.local', 'state', 'viz'))),
  input,
  browser: { locate: () => locateChromium(env), screenshot },
  mermaid: createMermaid(env),
  site: createSite(env),
  clock: { now: () => Date.now() },
  random: { hex: () => randomBytes(3).toString('hex') },
  runtime: { node: process.execPath, nodeVersion: process.version },
  warn: (line) => process.stderr.write(line + '\n'),
});
process.stdout.write(JSON.stringify(output) + '\n');
process.exitCode = exitCode;
