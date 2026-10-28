// Browser port: drive Chromium over the DevTools Protocol on
// --remote-debugging-pipe (fd 3: we write, fd 4: Chromium writes; messages are
// NUL-terminated JSON). No npm packages and no debugging port.
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { VizError } from '../core/domain.mjs';
import { isExecutable, which } from './executables.mjs';

const INITIAL_VIEWPORT_HEIGHT = 800;

// Runs in the page. `clipTo` is a CSS selector to crop to (plus padding), or
// null to take the whole document at the viewport width.
const MEASURE = `(async (clipTo, pad) => {
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const doc = document.documentElement;
  if (clipTo) {
    const el = document.querySelector(clipTo);
    if (!el) return { error: 'no element matches ' + clipTo };
    const r = el.getBoundingClientRect();
    const x = Math.max(0, r.left + scrollX - pad), y = Math.max(0, r.top + scrollY - pad);
    return { x, y, width: r.right + scrollX + pad - x, height: r.bottom + scrollY + pad - y };
  }
  let bottom = doc.getBoundingClientRect().height;
  for (const el of document.body ? document.body.querySelectorAll('*') : []) {
    const r = el.getBoundingClientRect();
    if (r.width && r.height) bottom = Math.max(bottom, r.bottom + scrollY);
  }
  return { x: 0, y: 0, width: Math.max(innerWidth, doc.scrollWidth), height: bottom };
})`;

const renderFailed = (message) => new VizError('render_failed', message);

/** $VIZ_CHROMIUM, else chromium on PATH. */
export function locateChromium(env) {
  if (env.VIZ_CHROMIUM) {
    if (!isExecutable(env.VIZ_CHROMIUM)) {
      throw new VizError('missing_dependency', `VIZ_CHROMIUM=${env.VIZ_CHROMIUM} is not an executable file`);
    }
    return env.VIZ_CHROMIUM;
  }
  const found = which('chromium', env.PATH || '');
  if (!found) throw new VizError('missing_dependency', 'no chromium on PATH; set VIZ_CHROMIUM to a Chromium or Chrome binary');
  return found;
}

/**
 * Load `pagePath` in headless Chromium at `width` CSS px and `scale` device
 * pixel ratio, and return a PNG Buffer sized to the content.
 */
export async function screenshot({ chromium, pagePath, width, scale, clipTo = null, pad = 0, timeoutMs = 60000 }) {
  const profile = mkdtempSync(join(tmpdir(), 'viz-chromium-'));
  const child = spawn(chromium, [
    '--headless', '--remote-debugging-pipe', `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--mute-audio',
    '--use-mock-keychain', '--password-store=basic', '--allow-file-access-from-files',
    'about:blank',
  ], { stdio: ['ignore', 'ignore', 'pipe', 'pipe', 'pipe'] });
  let stderrTail = '';
  child.stderr.on('data', (d) => { stderrTail = (stderrTail + d).slice(-2000); });

  const pending = new Map();
  const listeners = new Set();
  let nextId = 1;
  let buffered = '';
  let fail;
  const failed = new Promise((_, reject) => { fail = reject; });
  failed.catch(() => {});
  child.on('error', (e) => fail(renderFailed(`cannot start Chromium ${chromium}: ${e.message}`)));
  child.on('exit', (code, signal) => fail(renderFailed(
    `Chromium exited early (${signal || code}): ${stderrTail.trim().slice(-500)}`)));
  child.stdio[4].on('data', (chunk) => {
    buffered += chunk.toString('utf8');
    let end;
    while ((end = buffered.indexOf('\0')) !== -1) {
      const msg = JSON.parse(buffered.slice(0, end));
      buffered = buffered.slice(end + 1);
      if (msg.id && pending.has(msg.id)) {
        const { resolve, reject, method } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) reject(renderFailed(`${method}: ${msg.error.message}`));
        else resolve(msg.result);
      } else if (msg.method) {
        for (const l of listeners) l(msg);
      }
    }
  });
  child.stdio[3].on('error', () => {});

  const send = (method, params = {}, sessionId) => Promise.race([failed, new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject, method });
    child.stdio[3].write(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }) + '\0');
  })]);
  const waitFor = (method, sessionId) => Promise.race([failed, new Promise((resolve) => {
    const l = (msg) => {
      if (msg.method === method && msg.sessionId === sessionId) { listeners.delete(l); resolve(msg.params); }
    };
    listeners.add(l);
  })]);

  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(renderFailed(`timed out after ${timeoutMs / 1000}s rendering ${pagePath}`)), timeoutMs);
  });
  const pageErrors = [];
  listeners.add((msg) => {
    if (msg.method === 'Runtime.exceptionThrown') {
      const d = msg.params.exceptionDetails;
      pageErrors.push((d.exception && d.exception.description) || d.text);
    }
  });

  const run = async () => {
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true });
    await send('Page.enable', {}, sessionId);
    await send('Runtime.enable', {}, sessionId);
    await send('Emulation.setDeviceMetricsOverride',
      { width, height: INITIAL_VIEWPORT_HEIGHT, deviceScaleFactor: scale, mobile: false }, sessionId);
    const loaded = waitFor('Page.loadEventFired', sessionId);
    const nav = await send('Page.navigate', { url: pathToFileURL(pagePath).href }, sessionId);
    if (nav.errorText) throw renderFailed(`cannot load ${pagePath}: ${nav.errorText}`);
    await loaded;
    const evaluated = await send('Runtime.evaluate', {
      expression: `${MEASURE}(${JSON.stringify(clipTo)}, ${Number(pad)})`,
      awaitPromise: true, returnByValue: true,
    }, sessionId);
    if (evaluated.exceptionDetails) throw renderFailed(`measuring the page failed: ${evaluated.exceptionDetails.text}`);
    const box = evaluated.result.value;
    if (box.error) throw renderFailed(box.error);
    // Whole CSS px, so the PNG is exactly (box * scale) device px.
    const clip = {
      x: Math.floor(box.x), y: Math.floor(box.y),
      width: Math.max(1, Math.ceil(box.width)), height: Math.max(1, Math.ceil(box.height)), scale: 1,
    };
    const shot = await send('Page.captureScreenshot',
      { format: 'png', clip, captureBeyondViewport: true, fromSurface: true }, sessionId);
    return Buffer.from(shot.data, 'base64');
  };

  try {
    const png = await Promise.race([run(), timeout, failed]);
    return { png, pageErrors };
  } finally {
    clearTimeout(timer);
    child.removeAllListeners('exit');
    const exited = child.exitCode !== null || child.signalCode !== null
      ? Promise.resolve() : new Promise((r) => child.once('exit', r));
    const delay = (ms) => new Promise((r) => setTimeout(r, ms));
    try { await Promise.race([send('Browser.close'), delay(2000)]); } catch { /* already gone */ }
    await Promise.race([exited, delay(2000)]);
    child.kill('SIGKILL');
    await Promise.race([exited, delay(1000)]);
    rmSync(profile, { recursive: true, force: true });
  }
}
