// Domain: formats, options, ids, pages and PNG facts. Pure logic; imports
// nothing from node: or outside core/ (tests/viz/test_boundaries.py).

export const USAGE = `usage:
  viz render <file|-> [--as mermaid|svg|html] [--width 1200] [--scale 2]
  viz publish <file|id> [--as mermaid|svg|html] [--width 1200] [--scale 2] [--workstream NAME] [--ask NUMBER]
  viz list [--limit N]
  viz doctor`;

export const EXIT_CODES = new Map([['bad_input', 2], ['render_failed', 3], ['missing_dependency', 4], ['publish_failed', 5], ['unlinked_publish', 6]]);
export const SOURCE_EXT = new Map([['mermaid', 'mmd'], ['svg', 'svg'], ['html', 'html']]);
const FORMAT_BY_EXT = new Map([['.mmd', 'mermaid'], ['.svg', 'svg'], ['.html', 'html']]);
export const PAD = 16; // CSS px of white margin around an SVG or Mermaid drawing

export class VizError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

const badInput = (message) => new VizError('bad_input', message);

export function parseOptions(args, names) {
  const opts = new Map();
  const positional = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith('--') && a.length > 2) {
      const eq = a.indexOf('=');
      const name = eq === -1 ? a.slice(2) : a.slice(2, eq);
      if (!names.includes(name)) throw badInput(`unknown option --${name}\n${USAGE}`);
      const value = eq === -1 ? args[++i] : a.slice(eq + 1);
      if (value === undefined) throw badInput(`--${name} needs a value\n${USAGE}`);
      opts.set(name, value);
    } else {
      positional.push(a);
    }
  }
  return { opts, positional };
}

export function parsePositiveInteger(name, value) {
  if (!/^\d+$/.test(value) || Number(value) < 1) {
    throw badInput(`--${name} must be a positive integer, got ${JSON.stringify(value)}`);
  }
  return Number(value);
}

function parsePositiveNumber(name, value) {
  const n = value.trim() === '' ? NaN : Number(value);
  if (!Number.isFinite(n) || n <= 0) throw badInput(`--${name} must be a positive number, got ${JSON.stringify(value)}`);
  return n;
}

function formatOfPath(file) {
  const base = file.slice(file.lastIndexOf('/') + 1);
  const dot = base.lastIndexOf('.');
  return dot > 0 ? FORMAT_BY_EXT.get(base.slice(dot).toLowerCase()) : undefined;
}

/** Validate `render` arguments into { file, as, width, scale }. */
export function parseRenderRequest(args) {
  const { opts, positional } = parseOptions(args, ['as', 'width', 'scale']);
  if (positional.length !== 1) throw badInput(`render takes exactly one <file|->\n${USAGE}`);
  const file = positional[0];
  let as = opts.get('as');
  if (as === undefined) {
    if (file === '-') throw badInput('reading stdin (-) needs --as mermaid|svg|html');
    as = formatOfPath(file);
    if (!as) throw badInput(`cannot tell the format of ${file}; use .mmd, .svg or .html, or pass --as mermaid|svg|html`);
  } else if (!SOURCE_EXT.has(as)) {
    throw badInput(`--as must be mermaid, svg or html, got ${JSON.stringify(as)}`);
  }
  const width = opts.has('width') ? parsePositiveInteger('width', opts.get('width')) : 1200;
  const scale = opts.has('scale') ? parsePositiveNumber('scale', opts.get('scale')) : 2;
  return { file, as, width, scale };
}

/**
 * Validate `publish` arguments: a render id, or a file (or -) to render first with the render options.
 * --workstream NAME and --ask NUMBER are for the tag (tagFor), not for rendering, so they are not in renderArgs.
 */
export function parsePublishRequest(args) {
  const { opts, positional } = parseOptions(args, ['as', 'width', 'scale', 'workstream', 'ask']);
  if (positional.length !== 1) throw badInput(`publish takes exactly one <file|id>\n${USAGE}`);
  const target = positional[0];
  const workstream = opts.has('workstream') ? opts.get('workstream').trim() : null;
  if (workstream === '') throw badInput(`--workstream needs a name\n${USAGE}`);
  const ask = opts.has('ask') ? parsePositiveInteger('ask', opts.get('ask')) : null;
  const link = { workstream, ask };
  if (!isRenderId(target)) {
    const renderArgs = [];
    for (let i = 0; i < args.length; i++) {
      const name = args[i].startsWith('--') ? args[i].slice(2).split('=')[0] : null;
      if (name === 'workstream' || name === 'ask') { if (!args[i].includes('=')) i++; } else renderArgs.push(args[i]);
    }
    return { id: null, renderArgs, ...link };
  }
  if ([...opts.keys()].some((k) => k !== 'workstream' && k !== 'ask')) {
    throw badInput(`${target} is a render id; --as, --width and --scale apply only when publishing a file`);
  }
  return { id: target, renderArgs: null, ...link };
}

function decodeEntities(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (m, e) => {
    const named = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }[e.toLowerCase()];
    if (named) return named;
    const code = e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : Number(e.slice(1));
    return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : m;
  });
}

function textOfElement(html, tag) {
  const m = new RegExp(`<${tag}(?:\\s[^>]*)?>([\\s\\S]*?)</${tag}\\s*>`, 'i').exec(html);
  if (!m) return null;
  const text = decodeEntities(m[1].replace(/<[^>]*>/g, '')).replace(/\s+/g, ' ').trim();
  return text || null;
}

/**
 * The tag file for one published page (README, "page.json"). The title is the page's <title>, else its first h1, else
 * the source file's name, else null (a page read from stdin has no file).
 */
export function tagFor({ id, pageHtml, input, machine, thread, workstream, ask, publishedAt }) {
  const source = input && input !== '-' ? input : null;
  const title = textOfElement(pageHtml, 'title') ?? textOfElement(pageHtml, 'h1') ?? (source ? source.slice(source.lastIndexOf('/') + 1) : null);
  return { v: 1, id, title, machine, thread: thread || null, workstream: workstream ?? null, ask: ask ?? null, source, published_at: publishedAt };
}

/** Where a published render is: the page at <base>/<id>/, the PNG beside it. */
export function publishedUrls(base, id) {
  const root = `${base.replace(/\/+$/, '')}/${id}/`;
  return { url: root, png_url: `${root}image.png` };
}

const ID_PATTERN = /^\d{8}-\d{6}-\d{3}-[0-9a-f]+$/;

/** True for the shape newId makes; anything else is treated as a file. */
export function isRenderId(s) { return ID_PATTERN.test(s); }

/** Sortable, unique-enough id: UTC time to the millisecond plus random hex. */
export function newId(nowMs, randomHex) {
  const t = new Date(nowMs).toISOString().replace(/[-:]/g, '').replace('T', '-').replace('.', '-').replace('Z', '');
  return `${t}-${randomHex}`;
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/**
 * The page viz writes around one SVG drawing (SVG input or mmdc's output). viz
 * owns this document, so it can put the source directory's <base> in its head.
 */
export function wrapperPage(svg, baseHref) {
  const base = baseHref ? `<base href="${escapeHtml(baseHref)}">` : '';
  return `<!doctype html>
<html><head><meta charset="utf-8">${base}
<style>html,body{margin:0;background:#fff}#viz-root{padding:${PAD}px}#viz-root>svg{display:block}</style>
</head><body><div id="viz-root">
${svg}
</div></body></html>
`;
}

/** Pixel size from a PNG's IHDR chunk. */
export function pngSize(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes.byteLength < 24 || view.getUint32(0) !== 0x89504e47) throw new VizError('render_failed', 'the renderer did not return a PNG');
  return { width: view.getUint32(16), height: view.getUint32(20) };
}

/** Sort comparator for render metadata: newest first. */
export function newestFirst(a, b) {
  return String(b.created).localeCompare(String(a.created)) || String(b.id).localeCompare(String(a.id));
}
