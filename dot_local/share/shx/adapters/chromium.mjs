// Browser port: drive Chromium over the DevTools Protocol on --remote-debugging-pipe (fd 3: we write, fd 4: Chromium
// writes; messages are NUL-terminated JSON). No npm packages and no debugging port.
//
// The pipe plumbing is copied from viz (../../viz/adapters/chromium.mjs) and cut down, not imported: the viz one
// only exposes a single "screenshot a file" call, and importing another component's adapter would break the rule
// that components never import each other.
import { spawn } from 'node:child_process';
import { accessSync, constants, mkdtempSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join } from 'node:path';
import { ShxError } from '../core/domain.mjs';

const SCALE = 2; // device pixel ratio of the picture: sharp enough to read on a phone
const FRAME_WAIT_MS = 15000;

const renderFailed = (message) => new ShxError('render_failed', message);

function isExecutable(p) {
  try { accessSync(p, constants.X_OK); return statSync(p).isFile(); } catch { return false; }
}

/** $SHX_CHROMIUM, else chromium on PATH. */
export function locateChromium(env) {
  if (env.SHX_CHROMIUM) {
    if (!isExecutable(env.SHX_CHROMIUM)) throw new ShxError('missing_dependency', `SHX_CHROMIUM=${env.SHX_CHROMIUM} is not an executable file`);
    return env.SHX_CHROMIUM;
  }
  for (const dir of (env.PATH || '').split(delimiter)) {
    if (dir && isExecutable(join(dir, 'chromium'))) return join(dir, 'chromium');
  }
  throw new ShxError('missing_dependency', 'no chromium on PATH; set SHX_CHROMIUM to a Chromium or Chrome binary');
}

// ---- code that runs inside the page ---------------------------------------------------------------------------------

// Resolves to the frame's address once /view has set it. /view loads the artifact into an iframe after it has asked
// the server which version to show, so the address is not there at load time.
const FRAME_SRC = `new Promise((resolve) => {
  const frame = document.getElementById('preview');
  const done = () => frame && frame.getAttribute('src') ? resolve(frame.src) : null;
  if (!frame || done()) return;
  new MutationObserver((_, o) => { if (done()) o.disconnect(); }).observe(frame, { attributes: true, attributeFilter: ['src'] });
})`;

// Once fonts are in and two frames have painted, the layout is the one a person sees. Resolves to the document size.
const SETTLE = `(async () => {
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const doc = document.documentElement;
  return { w: Math.max(innerWidth, doc.scrollWidth), h: Math.max(innerHeight, doc.scrollHeight) };
})()`;

// The box of the first element a selector matches, in document coordinates, or null.
const ANCHOR_BOX = `((selector) => {
  let el = null;
  try { el = document.querySelector(selector); } catch {}
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height };
})`;

// Lays the stroke over the whole document, above the page's own content. The path comes in as data and is set as an
// attribute, so nothing in it is read as markup.
const DRAW = `((d, color, w, h) => {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', w);
  svg.setAttribute('height', h);
  svg.style.cssText = 'position:absolute;left:0;top:0;pointer-events:none;z-index:2147483647';
  const path = document.createElementNS(NS, 'path');
  path.setAttribute('d', d);
  path.setAttribute('fill', color);
  svg.append(path);
  document.documentElement.append(svg);
})`;

// Whether each comment still finds its place, by the same rule as the frame (web/runtime.js locate): a comment with a
// quote needs the quote's words on the page, with whitespace matched loosely, in its anchor element or anywhere; one
// without needs its anchor selector to match an element, and for a drawing that element must be the one drawn on (the
// same tag, and the same identity: its first 120 characters of text, cut at whole characters, or for an element with
// no text its attributes except style), because a path such as p:nth-of-type(4) names a slot that an edit fills with
// something else.
const FIND = `((items) => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  const textOf = (el) => norm(el.textContent) || norm(el.getAttribute('aria-label') || el.getAttribute('alt') || el.getAttribute('title'));
  const clip = (s, n = 120) => Array.from(s).slice(0, n).join('');
  const identityOf = (el) => clip(textOf(el) || Array.from(el.attributes).filter((a) => a.name !== 'style').map((a) => a.name + '=' + norm(a.value)).join(' '));
  let all = '';
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = walk.nextNode()); ) {
    if (!(n.parentElement && n.parentElement.closest('script, style, template'))) all += n.data;
  }
  all = norm(all);
  return items.map(({ id, quote, anchor, tag, text }) => {
    let el = null;
    try { el = anchor ? document.querySelector(anchor) : null; } catch {}
    const q = norm(quote);
    if (q) return { id, found: Boolean((el && textOf(el).includes(q)) || all.includes(q)) };
    const holds = el !== null && (!tag || el.tagName.toLowerCase() === tag) && (text == null || identityOf(el) === text);
    return { id, found: holds };
  });
})`;

const call = (fn, ...args) => `${fn}(${args.map((a) => JSON.stringify(a)).join(', ')})`;

/**
 * Starts Chromium, opens the /view page for an artifact version at the given screen size, and then loads the frame's
 * own address in the same tab at that size. The frame is what a person draws on, and its size is the size the stroke
 * recorded; loading it alone gives the page that exact viewport, without the bar /view puts above it.
 */
export async function open({ chromium, url, width, height, timeoutMs = 60000 }) {
  const profile = mkdtempSync(join(tmpdir(), 'shx-chromium-'));
  const child = spawn(chromium, [
    '--headless', '--remote-debugging-pipe', `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--mute-audio',
    '--use-mock-keychain', '--password-store=basic', 'about:blank',
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
  child.on('exit', (code, signal) => fail(renderFailed(`Chromium exited early (${signal || code}): ${stderrTail.trim().slice(-500)}`)));
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

  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(renderFailed(`timed out after ${timeoutMs / 1000}s rendering ${url}`)), timeoutMs);
  });
  timeout.catch(() => {});
  const guard = (p) => Promise.race([p, failed, timeout]);

  let sessionId;
  const send = (method, params = {}) => guard(new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject, method });
    child.stdio[3].write(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }) + '\0');
  }));
  const loaded = () => new Promise((resolve) => {
    const l = (msg) => {
      if (msg.method === 'Page.loadEventFired' && msg.sessionId === sessionId) { listeners.delete(l); resolve(); }
    };
    listeners.add(l);
  });
  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) {
      throw renderFailed(`the page script failed: ${(r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text}`);
    }
    return r.result.value;
  };
  const navigate = async (to) => {
    const done = loaded();
    const nav = await send('Page.navigate', { url: to });
    if (nav.errorText) throw renderFailed(`cannot load ${to}: ${nav.errorText}`);
    await guard(done);
  };

  const close = async () => {
    clearTimeout(timer);
    child.removeAllListeners('exit');
    const exited = child.exitCode !== null || child.signalCode !== null ? Promise.resolve() : new Promise((r) => child.once('exit', r));
    // unref'd, so a timer that lost its race does not keep the process alive after the answer is printed.
    const delay = (ms) => new Promise((r) => setTimeout(r, ms).unref());
    try { await Promise.race([Promise.race([send('Browser.close'), failed]), delay(2000)]); } catch { /* already gone */ }
    await Promise.race([exited, delay(2000)]);
    child.kill('SIGKILL');
    await Promise.race([exited, delay(1000)]);
    rmSync(profile, { recursive: true, force: true });
  };

  try {
    const { targetId } = await send('Target.createTarget', { url: 'about:blank' });
    ({ sessionId } = await send('Target.attachToTarget', { targetId, flatten: true }));
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: SCALE, mobile: false });
    await navigate(url);
    const frameSrc = await guard(Promise.race([
      evaluate(FRAME_SRC),
      new Promise((_, reject) => setTimeout(() => reject(renderFailed(`${url} did not load an artifact into its frame (wrong id or version?)`)), FRAME_WAIT_MS).unref()),
    ]));
    await navigate(frameSrc);
    const doc = await evaluate(SETTLE);

    return {
      doc,
      anchorBox: (selector) => evaluate(call(ANCHOR_BOX, selector)),
      find: (items) => evaluate(call(FIND, items)),
      async shoot({ d, color, clip }) {
        await evaluate(call(DRAW, d, color, doc.w, doc.h));
        const shot = await send('Page.captureScreenshot', {
          format: 'png', clip: { x: clip.x, y: clip.y, width: clip.w, height: clip.h, scale: 1 }, captureBeyondViewport: true, fromSurface: true,
        });
        const png = Buffer.from(shot.data, 'base64');
        return { png, width: png.readUInt32BE(16), height: png.readUInt32BE(20) };
      },
      close,
    };
  } catch (e) {
    await close();
    throw e;
  }
}
