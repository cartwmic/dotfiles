// Mermaid port: the installed mmdc, with its puppeteer pointed at Playwright's
// chrome-headless-shell.
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';
import { VizError } from '../core/domain.mjs';
import { isExecutable, which } from './executables.mjs';

// Newest chromium_headless_shell-<rev> under the Playwright cache.
function findHeadlessShell(env) {
  const roots = env.PLAYWRIGHT_BROWSERS_PATH ? [env.PLAYWRIGHT_BROWSERS_PATH]
    : [join(homedir(), 'Library', 'Caches', 'ms-playwright'), join(homedir(), '.cache', 'ms-playwright')];
  const candidates = [];
  for (const root of roots) {
    let revisions = [];
    try { revisions = readdirSync(root).filter((e) => /^chromium_headless_shell-\d+$/.test(e)); } catch { continue; }
    for (const rev of revisions) {
      let platforms = [];
      try { platforms = readdirSync(join(root, rev)).filter((p) => p.startsWith('chrome-headless-shell-')); } catch { continue; }
      for (const plat of platforms) {
        const bin = join(root, rev, plat, 'chrome-headless-shell');
        if (isExecutable(bin)) candidates.push({ rev: Number(rev.split('-')[1]), bin });
      }
    }
  }
  candidates.sort((a, b) => b.rev - a.rev);
  if (!candidates.length) {
    throw new VizError('missing_dependency', `no Playwright chrome-headless-shell under ${roots.join(' or ')} (needed by mmdc)`);
  }
  return candidates[0].bin;
}

// Keep the parser's own words ("Parse error on line ...") and drop the stack.
function parserMessage(stderr) {
  const lines = stderr.split('\n');
  const start = lines.findIndex((l) => /error/i.test(l));
  if (start === -1) return stderr.trim().slice(-2000) || 'mmdc failed with no message';
  const kept = [];
  for (const l of lines.slice(start)) {
    if (/^\s+at\s/.test(l) || /\((https?|file):\/\//.test(l)) break;
    kept.push(l);
  }
  return kept.join('\n').replace(/^Error:\s*/, '').trim();
}

export function createMermaid(env) {
  return {
    locate() {
      const mmdc = which('mmdc', env.PATH || '');
      if (!mmdc) throw new VizError('missing_dependency', 'no mmdc on PATH (mise task install-mermaid-cli installs @mermaid-js/mermaid-cli)');
      return { mmdc, browser: findHeadlessShell(env) };
    },

    toSvg(source, { mmdc, browser }) {
      const work = mkdtempSync(join(tmpdir(), 'viz-mmdc-'));
      try {
        const config = join(work, 'puppeteer.json');
        const input = join(work, 'diagram.mmd');
        const output = join(work, 'diagram.svg');
        writeFileSync(config, JSON.stringify({ executablePath: browser }));
        writeFileSync(input, source);
        const r = spawnSync(mmdc, ['-q', '-i', input, '-o', output, '-p', config], { encoding: 'utf8', timeout: 60000 });
        if (r.error) throw new VizError('render_failed', `mmdc did not run: ${r.error.message}`);
        if (r.status !== 0 || !existsSync(output)) {
          throw new VizError('render_failed', parserMessage(`${r.stderr || ''}\n${r.stdout || ''}`));
        }
        return readFileSync(output, 'utf8');
      } finally {
        rmSync(work, { recursive: true, force: true });
      }
    },

    version({ mmdc }) {
      const v = spawnSync(mmdc, ['--version'], { encoding: 'utf8', timeout: 30000 });
      return v.status === 0 ? v.stdout.trim() : null;
    },
  };
}
