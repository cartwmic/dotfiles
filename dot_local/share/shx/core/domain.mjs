// Domain: arguments, the stroke contract, placing a stroke on a page, the crop, and the log record.
// Pure logic. It imports nothing from node: or outside core/ (tests/shx/test_boundaries.py).

export const USAGE = `usage:
  shx-note-image <base-url> <artifact-id> <comment-id> [--version N] [--out file.png] [--pad 24]
  shx-note-image check <base-url> <artifact-id>
  <base-url> may be left out when SHARTIFACTS_URL is set.`;

export const EXIT_CODES = new Map([['bad_input', 2], ['render_failed', 3], ['missing_dependency', 4], ['request_failed', 5]]);
export const DEFAULT_PAD = 24;
// The size of the phone screen that `check` renders at. Whether a quote or an element is present does not depend on it.
export const CHECK_VIEWPORT = { w: 390, h: 844 };

export class ShxError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

const badInput = (message) => new ShxError('bad_input', message);
const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);

/** The base URL without trailing slashes, or a bad_input error when it is not http(s). */
export function normalizeBase(base) {
  if (!/^https?:\/\/[^/\s]+/i.test(base)) throw badInput(`base URL must start with http:// or https://, got ${base}`);
  return base.replace(/\/+$/, '');
}

/** The scheme and host of a URL, for the log: no path, no credentials, no query. */
export function originOf(base) {
  const m = /^(https?:\/\/)(?:[^/@]*@)?([^/?#]+)/i.exec(base);
  return m ? m[1].toLowerCase() + m[2] : '';
}

function parseFlags(args, names) {
  const flags = new Map();
  const positional = [];
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith('--') && a.length > 2) {
      const name = a.slice(2);
      if (!names.includes(name)) throw badInput(`unknown option ${a}\n${USAGE}`);
      const value = args[++i];
      if (value === undefined) throw badInput(`${a} needs a value\n${USAGE}`);
      flags.set(name, value);
    } else {
      positional.push(a);
    }
  }
  return { flags, positional };
}

// The base URL is the first positional when it looks like a URL; otherwise it comes from the default (SHARTIFACTS_URL).
function takeBase(positional, defaultBase, count) {
  const hasBase = positional.length > 0 && /^https?:\/\//i.test(positional[0]);
  const rest = hasBase ? positional.slice(1) : positional;
  const base = hasBase ? positional[0] : defaultBase;
  if (!base) throw badInput(`no base URL: pass one or set SHARTIFACTS_URL\n${USAGE}`);
  if (rest.length !== count) throw badInput(`expected ${count} argument${count === 1 ? '' : 's'} after the base URL, got ${rest.length}\n${USAGE}`);
  return { base: normalizeBase(base), rest };
}

function nonNegativeNumber(name, value) {
  const n = Number(value);
  if (value.trim() === '' || !Number.isFinite(n) || n < 0) throw badInput(`${name} must be a number of 0 or more, got ${value}`);
  return n;
}

/** argv -> { command: 'note' | 'check', base, artifact, comment?, version?, out?, pad? }. Throws ShxError bad_input. */
export function parseArgs(argv, defaultBase) {
  if (argv[0] === 'check') {
    const { positional } = parseFlags(argv.slice(1), []);
    const { base, rest } = takeBase(positional, defaultBase, 1);
    return { command: 'check', base, artifact: rest[0] };
  }
  const { flags, positional } = parseFlags(argv, ['version', 'out', 'pad']);
  const { base, rest } = takeBase(positional, defaultBase, 2);
  const parsed = { command: 'note', base, artifact: rest[0], comment: rest[1], pad: DEFAULT_PAD };
  if (flags.has('version')) {
    const v = flags.get('version');
    if (!/^[1-9][0-9]*$/.test(v)) throw badInput(`--version must be a whole number of 1 or more, got ${v}`);
    parsed.version = Number(v);
  }
  if (flags.has('out')) parsed.out = flags.get('out');
  if (flags.has('pad')) parsed.pad = nonNegativeNumber('--pad', flags.get('pad'));
  return parsed;
}

/**
 * The stroke of one root comment, checked and with defaults filled in (shape: DESIGN.md "Comment.stroke").
 * Throws bad_input when the comment is missing, is a reply, has no stroke, or the stroke is unusable.
 */
export function readStroke(comments, commentId) {
  const c = Array.isArray(comments) ? comments.find((x) => x && x.id === commentId) : null;
  if (!c) throw badInput(`no comment ${commentId} on this artifact`);
  if (c.parent) throw badInput(`comment ${commentId} is a reply; pass the id of the thread's first comment`);
  const s = c.stroke;
  if (!s || typeof s !== 'object') throw badInput(`comment ${commentId} has no stroke (only drawings have a picture)`);
  const { viewport, box, points } = s;
  if (!viewport || !isNumber(viewport.w) || !isNumber(viewport.h) || viewport.w <= 0 || viewport.h <= 0) throw badInput('the stroke has no usable viewport');
  if (!box || !isNumber(box.x) || !isNumber(box.y)) throw badInput('the stroke has no usable box');
  if (!Array.isArray(points) || points.length === 0 || !points.every((p) => Array.isArray(p) && isNumber(p[0]) && isNumber(p[1]))) {
    throw badInput('the stroke has no usable points');
  }
  if (!Number.isInteger(s.version) || s.version < 1) throw badInput('the stroke has no usable version');
  return {
    version: s.version,
    viewport: { w: viewport.w, h: viewport.h },
    anchor: typeof s.anchor === 'string' ? s.anchor : '',
    box: { x: box.x, y: box.y, w: isNumber(box.w) ? box.w : 0, h: isNumber(box.h) ? box.h : 0 },
    points: points.map((p) => [p[0], p[1], isNumber(p[2]) ? p[2] : 0.5]),
    color: typeof s.color === 'string' && s.color ? s.color : '#d33',
    width: isNumber(s.width) && s.width > 0 ? s.width : 4,
  };
}

/** Points in document coordinates: the stroke's offsets added to where its anchor element is now. */
export function placePoints(stroke, origin) {
  return stroke.points.map(([dx, dy, pressure]) => [origin.x + dx, origin.y + dy, pressure]);
}

/**
 * The part of the document to photograph, in whole CSS px: the stroke's bounding box plus `pad`, joined with the
 * anchor element's box when that fits on the screen the stroke was drawn on, and cut to the document.
 */
export function cropRect({ points, width, element, viewport, pad, doc }) {
  const half = width / 2;
  let left = Math.min(...points.map((p) => p[0])) - half;
  let top = Math.min(...points.map((p) => p[1])) - half;
  let right = Math.max(...points.map((p) => p[0])) + half;
  let bottom = Math.max(...points.map((p) => p[1])) + half;
  if (element && element.w > 0 && element.h > 0 && element.w <= viewport.w && element.h <= viewport.h) {
    left = Math.min(left, element.x);
    top = Math.min(top, element.y);
    right = Math.max(right, element.x + element.w);
    bottom = Math.max(bottom, element.y + element.h);
  }
  left = Math.max(0, Math.floor(left - pad));
  top = Math.max(0, Math.floor(top - pad));
  right = Math.min(doc.w, Math.ceil(right + pad));
  bottom = Math.min(doc.h, Math.ceil(bottom + pad));
  // A stroke wholly outside the document leaves nothing to cut out: show the top of the page instead.
  if (right <= left || bottom <= top) return { x: 0, y: 0, w: Math.max(1, Math.min(doc.w, viewport.w)), h: Math.max(1, Math.min(doc.h, viewport.h)) };
  return { x: left, y: top, w: right - left, h: bottom - top };
}

/**
 * What `check` looks for, one item per open root comment that points at something. A comment with a quote is looked
 * up by its text; a drawing or a plain pin by its anchor selector. A comment with neither has nothing to lose.
 */
export function checkItems(comments) {
  const items = [];
  for (const c of Array.isArray(comments) ? comments : []) {
    if (!c || c.parent || c.resolved || typeof c.id !== 'string') continue;
    const quote = typeof c.quote === 'string' ? c.quote : '';
    const anchor = (typeof c.anchor === 'string' && c.anchor) || (c.stroke && typeof c.stroke.anchor === 'string' ? c.stroke.anchor : '');
    if (!quote && !anchor) continue;
    const item = { id: c.id, quote, anchor };
    // A drawing also says what its anchor was when it was drawn, so a path that now finds another element is not found.
    // One on an element with no text (anchor_text is "") cannot be told from its neighbour: it is not checked, and its
    // status stays unchecked on a later version.
    if (!quote && c.stroke && c.stroke.anchor_text === '') continue;
    if (!quote && c.stroke) {
      if (typeof c.stroke.anchor_tag === 'string' && c.stroke.anchor_tag) item.tag = c.stroke.anchor_tag;
      if (typeof c.stroke.anchor_text === 'string') item.text = c.stroke.anchor_text;
    }
    items.push(item);
  }
  return items;
}

/** The version number from GET /api/artifacts/<id>: how many revisions it has. */
export function latestVersion(artifact) {
  const n = artifact && Array.isArray(artifact.revisions) ? artifact.revisions.length : 0;
  if (n < 1) throw new ShxError('request_failed', 'the artifact has no versions');
  return n;
}

/** One line for the action log. `error` is null on success. */
export function logRecord({ id, startedAt, durationMs, request, artifact, version, viewport, out, error }) {
  return {
    id,
    ts: new Date(startedAt).toISOString(),
    command: request.command,
    base: request.base ? originOf(request.base) : null,
    artifact: artifact ?? null,
    comment: request.comment ?? null,
    version: version ?? null,
    pad: request.pad ?? null,
    viewport: viewport ?? null,
    out: out ?? null,
    duration_ms: durationMs,
    error: error ? { code: error.code, message: error.message } : null,
  };
}
