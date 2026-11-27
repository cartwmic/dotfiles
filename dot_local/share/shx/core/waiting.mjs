// shx-waiting: lists the comment threads whose latest message is the owner's, so none stays unanswered.
// Pure logic and one use case; the outside is reached only through ports (waiting.mjs wires the real ones).
// It imports nothing from node: or outside core/ (tests/shx/test_boundaries.py).
//
// The server's comment list is flat: a thread's first comment has no `parent`, every reply carries the first
// comment's id as `parent`. Each has `author` (`you` for the owner, `agent` for an agent) and `created_at`.
//   api    { pages(base) -> [{ id, title }], comments(base, page) -> [comment], artifact(base, page) -> { title } }
//   files  { read(path) -> text }
//   log    { append(record) }
//   clock  { now() -> epoch ms }
//   random { hex() -> short random hex string }
import { EXIT_CODES, ShxError, normalizeBase, originOf } from './domain.mjs';

export const WAITING_USAGE = `usage:
  shx-waiting [<base-url>] [--file F]... [<page-id>...]
  With no page ids and no --file it reads every page the server has, archived ones too. --file F holds page ids, any text:
  each 24-character hex word in it is one id (a plain list, or rows with the id in one column).
  exit 0: nothing waits; 1: at least one thread waits; 2: bad usage; 3: unexpected failure; 4: no node; 5: could not read.
  <base-url> may be left out: SHARTIFACTS_URL, else the server the using-shartifacts skill names.`;

const OWNER = 'you';
// How many pages are read at once. The server answers each in about a tenth of a second.
const CONCURRENCY = 12;
const QUOTE_SHOWN = 160;

const badInput = (message) => new ShxError('bad_input', message);
const requestFailed = (message) => new ShxError('request_failed', message);

/** argv -> { base, pages: string[] | null, files: string[] }. `pages` null means every page the server has. */
export function parseWaitingArgs(argv, defaultBase) {
  const files = [];
  const ids = [];
  let base = defaultBase;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--file') {
      if (argv[i + 1] === undefined) throw badInput(`--file needs a value\n${WAITING_USAGE}`);
      files.push(argv[++i]);
    } else if (a.startsWith('--')) {
      throw badInput(`unknown option ${a}\n${WAITING_USAGE}`);
    } else if (/^https?:\/\//i.test(a)) {
      base = a;
    } else {
      ids.push(a);
    }
  }
  if (!base) throw badInput(`no base URL: pass one or set SHARTIFACTS_URL\n${WAITING_USAGE}`);
  return { base: normalizeBase(base), ids, files };
}

/** Every 24-character hex word in the text, in order, once each. */
export function pageIdsIn(text) {
  return [...new Set(text.match(/(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])/g) ?? [])];
}

// created_at has fractional seconds of varying length, so it is padded to a fixed width before it is compared.
function timeKey(comment) {
  const m = /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z$/.exec(comment.created_at);
  if (!m) throw requestFailed(`comment ${comment.id} has no usable created_at (${JSON.stringify(comment.created_at)})`);
  return `${m[1]}.${(m[2] ?? '').padEnd(9, '0')}`;
}

/**
 * The threads of one page that wait for an agent: not resolved, and the latest message (by time, then list order)
 * is the owner's. Oldest first. Each has the first comment, the owner's unanswered messages (all his messages after
 * the last message that is not his) and the time of the first of them. Throws request_failed on a list that is not
 * comments. A reply whose first comment is not in the list is left out.
 */
export function waitingThreads(comments) {
  if (!Array.isArray(comments)) throw requestFailed('the comment list was not a list');
  for (const c of comments) {
    if (!c || typeof c !== 'object' || typeof c.id !== 'string' || typeof c.author !== 'string') throw requestFailed('a comment has no id or author');
  }
  const byId = new Map(comments.map((c) => [c.id, c]));
  const threads = new Map();
  comments.forEach((c, index) => {
    // A reply names the first comment; follow `parent` up in case one names a reply instead.
    let root = c;
    for (const seen = new Set([c.id]); root.parent; ) {
      root = byId.get(root.parent);
      if (!root || seen.has(root.id)) return;
      seen.add(root.id);
    }
    threads.set(root.id, [...(threads.get(root.id) ?? []), { c, index, key: timeKey(c) }]);
  });
  const waiting = [];
  for (const [rootId, entries] of threads) {
    const root = byId.get(rootId);
    if (root.resolved) continue;
    entries.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : a.index - b.index));
    let from = entries.length;
    while (from > 0 && entries[from - 1].c.author === OWNER) from--;
    if (from === entries.length) continue;
    const unanswered = entries.slice(from);
    waiting.push({ root, messages: unanswered.map((e) => e.c), since: unanswered[0].c.created_at, key: unanswered[0].key });
  }
  return waiting.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
}

const oneLine = (text) => String(text ?? '').replace(/\s+/g, ' ').trim();

function pointedAt(root) {
  const quote = oneLine(root.quote);
  if (quote) return quote.length > QUOTE_SHOWN ? `${quote.slice(0, QUOTE_SHOWN)}...` : quote;
  return root.stroke ? '(a drawing)' : '(no text selected)';
}

/** The text for stdout: one block per waiting thread, longest waiting first across all pages, then the count line with what was read. */
export function renderWaiting(base, found, pagesRead, scope) {
  const all = found.flatMap(({ page, title, waiting }) => waiting.map((t) => ({ page, title, t })));
  all.sort((a, b) => (a.t.key < b.t.key ? -1 : a.t.key > b.t.key ? 1 : 0));
  const lines = [];
  for (const { page, title, t } of all) {
    lines.push(`page ${page}${title ? ` (${title})` : ''}`);
    lines.push(`  link   ${base}/view/${page}`);
    lines.push(`  thread ${t.root.id}  waiting since ${t.since}`);
    lines.push(`  on     ${pointedAt(t.root)}`);
    for (const m of t.messages) lines.push(`  he wrote: ${oneLine(m.body)}`);
    lines.push('');
  }
  const pages = found.length;
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  // The count line says what was selected: a run over every page says that archived pages are in it.
  const read = `${plural(pagesRead, 'page')} read${scope === 'all' ? ', archived pages included' : ''}`;
  lines.push(all.length === 0 ? `none waiting (${read})` : `${plural(all.length, 'thread')} waiting on ${plural(pages, 'page')} (${read})`);
  return lines.join('\n');
}

/** Runs `work` on each item, at most `limit` at a time, results in item order. The first failure stops new starts and is thrown. */
async function mapLimit(items, limit, work) {
  const results = new Array(items.length);
  let next = 0;
  let failure = null;
  async function worker() {
    while (failure === null && next < items.length) {
      const i = next++;
      try {
        results[i] = await work(items[i]);
      } catch (e) {
        failure ??= e;
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  if (failure !== null) throw failure;
  return results;
}

async function listPages(request, ports) {
  const ids = [...request.ids];
  for (const file of request.files) ids.push(...pageIdsIn(await ports.files.read(file)));
  if (request.ids.length + request.files.length === 0) {
    const pages = await ports.api.pages(request.base);
    if (!Array.isArray(pages)) throw requestFailed('the page list was not a list');
    return { pages: pages.map((p) => ({ id: p.id, title: p.title })), scope: 'all' };
  }
  const unique = [...new Set(ids)];
  if (unique.length === 0) throw badInput('no page id found in the --file given');
  return { pages: unique.map((id) => ({ id, title: undefined })), scope: 'ids' };
}

async function scan(request, ports, ctx) {
  const { pages, scope } = await listPages(request, ports);
  ctx.scope = scope;
  ctx.pages = pages.length;
  // A run over pages the caller named records which; a run over every page records only how many.
  if (scope === 'ids') ctx.pageIds = pages.map((p) => p.id);
  const found = (await mapLimit(pages, CONCURRENCY, async (p) => {
    try {
      return { page: p.id, title: p.title, waiting: waitingThreads(await ports.api.comments(request.base, p.id)) };
    } catch (e) {
      if (e instanceof ShxError) throw new ShxError(e.code, `page ${p.id}: ${e.message}`);
      throw e;
    }
  })).filter((f) => f.waiting.length > 0);
  // A page given by id has no title yet; only the pages that print a block need one.
  for (const f of found) if (f.title === undefined) f.title = oneLine((await ports.api.artifact(request.base, f.page)).title);
  ctx.waiting = found.reduce((n, f) => n + f.waiting.length, 0);
  ctx.threads = found.flatMap((f) => f.waiting.map((t) => ({ page: f.page, thread: t.root.id })));
  return { text: renderWaiting(request.base, found, pages.length, scope), waiting: ctx.waiting };
}

/** One line for the action log. `error` is null on success. */
export function waitingLogRecord({ id, startedAt, durationMs, request, scope, pageIds, pages, waiting, threads, error }) {
  return {
    id,
    ts: new Date(startedAt).toISOString(),
    command: 'waiting',
    base: request ? originOf(request.base) : null,
    scope: scope ?? null,
    page_ids: pageIds ?? null,
    pages: pages ?? null,
    waiting: waiting ?? null,
    threads: threads ?? null,
    duration_ms: durationMs,
    error: error ? { code: error.code, message: error.message } : null,
  };
}

/**
 * Runs one command line. Returns { stdout, stderr, exitCode } (strings, no trailing newline) and leaves one log record.
 * The exit code is 0 for nothing waiting, 1 for something waiting, and a contract code (never 1) for any failure.
 */
export async function runWaiting(argv, ports, defaults = {}) {
  const startedAt = ports.clock.now();
  const ctx = {};
  let request = null;
  let error = null;
  let result = null;
  try {
    request = parseWaitingArgs(argv, defaults.base);
    result = await scan(request, ports, ctx);
  } catch (e) {
    error = e instanceof ShxError ? e : new ShxError('render_failed', `unexpected error: ${e && e.stack ? e.stack : e}`);
  }
  try {
    await ports.log.append(waitingLogRecord({
      id: `${startedAt.toString(36)}-${ports.random.hex()}`, startedAt, durationMs: ports.clock.now() - startedAt, request, error, ...ctx,
    }));
  } catch (e) {
    ports.warn?.(`[shx-waiting] WARN: cannot append the log record: ${e.message}`);
  }
  if (error) return { stdout: '', stderr: `[shx-waiting] ERROR: ${error.message}`, exitCode: EXIT_CODES.get(error.code) };
  return { stdout: result.text, stderr: '', exitCode: result.waiting > 0 ? 1 : 0 };
}
