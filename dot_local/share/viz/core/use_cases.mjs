// Use cases: render, publish, list, doctor, and the action record every call leaves.
// The outside is reached only through these ports (viz.mjs wires the real ones):
//   store   { root, isTaken(id), stage(files) -> { path(name) }, add(staging, name, data),
//             finalPaths(id, names) -> { name: path }, commit(staging, id), discard(staging),
//             readRenders() -> [meta], readRender(id) -> meta|null, readFile(id, name) -> bytes,
//             appendAction(record) }
//   input   { read(file) -> { bytes, text, path, baseHref } }   file '-' means stdin (path '-', no baseHref)
//   browser { locate() -> path, screenshot({ chromium, pagePath, width, scale, clipTo, pad }) -> { png, pageErrors } }
//   mermaid { locate() -> { mmdc, browser }, toSvg(source, located) -> svg, version(located) -> string|null }
//   site    { locate() -> base URL, put(path, bytes, contentType) -> HTTP status }   path is '<id>/<name>'
//   clock   { now() -> epoch ms }
//   random  { hex() -> short random hex string }
//   runtime { node, nodeVersion }
//   warn(line)   diagnostics for stderr
// Adapters signal failures by throwing VizError with a contract code.
import {
  EXIT_CODES, PAD, SOURCE_EXT, USAGE, VizError, newId, newestFirst, parseOptions,
  parsePositiveInteger, parsePublishRequest, parseRenderRequest, pngSize, publishedUrls, wrapperPage,
} from './domain.mjs';

async function render(args, ports, ctx) {
  const req = parseRenderRequest(args);
  ctx.step({ step: 'request', input: req.file, as: req.as, width: req.width, scale: req.scale });
  const input = await ports.input.read(req.file);
  ctx.step({ step: 'input', path: input.path, bytes: input.bytes.byteLength });
  if (!input.text.trim()) throw new VizError('bad_input', `${req.file === '-' ? 'stdin' : req.file} is empty`);
  if (req.as === 'svg' && !/<svg[\s>]/i.test(input.text)) throw new VizError('bad_input', `${req.file} has no <svg> element`);

  const chromium = ports.browser.locate();
  ctx.step({ step: 'chromium', path: chromium });
  let page;
  let clipTo = null;
  let renderFrom = null; // null: the staged page.html
  if (req.as === 'mermaid') {
    const located = ports.mermaid.locate();
    try {
      page = wrapperPage(await ports.mermaid.toSvg(input.text, located), null);
    } catch (e) {
      ctx.step({ step: 'mmdc', ok: false, mmdc: located.mmdc, message: e.message });
      throw e;
    }
    ctx.step({ step: 'mmdc', ok: true, mmdc: located.mmdc });
    clipTo = '#viz-root > svg';
  } else if (req.as === 'svg') {
    page = wrapperPage(input.text, input.baseHref);
    clipTo = '#viz-root svg';
  } else {
    // page.html is a byte-exact copy. A file is rendered from its own location so
    // relative URLs resolve as the author wrote them; stdin has no location.
    page = input.bytes;
    if (input.path !== '-') renderFrom = input.path;
  }

  const sourceName = `source.${SOURCE_EXT.get(req.as)}`;
  const staging = await ports.store.stage({ [sourceName]: input.bytes, 'page.html': page });
  let committed = false;
  try {
    const pagePath = renderFrom ?? staging.path('page.html');
    const shot = await ports.browser.screenshot({
      chromium, pagePath, width: req.width, scale: req.scale, clipTo, pad: PAD,
    });
    const { width, height } = pngSize(shot.png);
    ctx.step({ step: 'screenshot', page: renderFrom ?? 'page.html', width, height, bytes: shot.png.byteLength, page_errors: shot.pageErrors });
    for (const err of shot.pageErrors) ports.warn(`viz: page error: ${err}`);
    await ports.store.add(staging, 'image.png', shot.png);
    const paths = ports.store.finalPaths(ctx.id, ['image.png', 'page.html', sourceName]);
    const result = {
      ok: true, id: ctx.id, png: paths['image.png'], html: paths['page.html'], source: paths[sourceName],
      width, height, bytes: shot.png.byteLength,
    };
    const meta = {
      id: ctx.id, created: new Date(ctx.started).toISOString(), as: req.as, input: input.path,
      css_width: req.width, scale: req.scale, png: result.png, html: result.html, source: result.source,
      width, height, bytes: result.bytes, chromium, page_errors: shot.pageErrors,
    };
    await ports.store.add(staging, 'meta.json', JSON.stringify(meta, null, 2) + '\n');
    await ports.store.commit(staging, ctx.id);
    committed = true;
    return result;
  } finally {
    if (!committed) await ports.store.discard(staging);
  }
}

// The files a published render needs, and the names they get on the site.
const UPLOADS = [
  { name: 'image.png', remote: 'image.png', type: 'image/png' },
  { name: 'page.html', remote: 'index.html', type: 'text/html; charset=utf-8' },
];

async function publish(args, ports, ctx) {
  const req = parsePublishRequest(args);
  const base = ports.site.locate(); // before rendering: a missing site config fails fast
  ctx.step({ step: 'site', base });
  let rendered;
  if (req.renderArgs) {
    rendered = await render(req.renderArgs, ports, ctx);
  } else {
    const meta = await ports.store.readRender(req.id);
    if (!meta) throw new VizError('bad_input', `no render with id ${req.id}; see viz list`);
    ctx.step({ step: 'render', id: meta.id });
    rendered = {
      ok: true, id: meta.id, png: meta.png, html: meta.html, source: meta.source,
      width: meta.width, height: meta.height, bytes: meta.bytes,
    };
  }
  for (const u of UPLOADS) {
    const bytes = await ports.store.readFile(rendered.id, u.name);
    const path = `${rendered.id}/${u.remote}`;
    let status;
    try {
      status = await ports.site.put(path, bytes, u.type);
    } catch (e) {
      ctx.step({ step: 'upload', path, bytes: bytes.byteLength, ok: false, message: e.message });
      if (e instanceof VizError) e.message += `; render ${rendered.id} is kept, retry with: viz publish ${rendered.id}`;
      throw e;
    }
    ctx.step({ step: 'upload', path, bytes: bytes.byteLength, status });
  }
  return { ...rendered, ...publishedUrls(base, rendered.id) };
}

async function list(args, ports, ctx) {
  const { opts, positional } = parseOptions(args, ['limit']);
  if (positional.length) throw new VizError('bad_input', `list takes no arguments\n${USAGE}`);
  const limit = opts.has('limit') ? parsePositiveInteger('limit', opts.get('limit')) : Infinity;
  const renders = (await ports.store.readRenders()).sort(newestFirst).slice(0, limit).map((m) => ({
    id: m.id, created: m.created, as: m.as, input: m.input, png: m.png, html: m.html, source: m.source,
    width: m.width, height: m.height, bytes: m.bytes,
  }));
  ctx.step({ step: 'list', limit: opts.get('limit') ?? null, count: renders.length });
  return { ok: true, state_dir: ports.store.root, renders };
}

function doctor(args, ports, ctx) {
  if (args.length) throw new VizError('bad_input', `doctor takes no arguments\n${USAGE}`);
  const report = { state_dir: ports.store.root, node: ports.runtime.node, node_version: ports.runtime.nodeVersion };
  const missing = [];
  const probe = (key, locate) => {
    try { return locate(); } catch (e) {
      if (!(e instanceof VizError)) throw e;
      missing.push(e.message);
      report[key] = null;
      return null;
    }
  };
  report.chromium = probe('chromium', () => ports.browser.locate());
  const located = probe('mmdc', () => ports.mermaid.locate());
  if (located) {
    report.mmdc = located.mmdc;
    report.mermaid_chromium = located.browser;
    report.mmdc_version = ports.mermaid.version(located);
  }
  ctx.step({ step: 'doctor', missing });
  if (missing.length) return { ok: false, code: 'missing_dependency', message: missing.join('; '), ...report };
  return { ok: true, ...report };
}

function failure(e, ports) {
  if (e instanceof VizError) return { ok: false, code: e.code, message: e.message };
  ports.warn(`viz: ${e && e.stack ? e.stack : e}`);
  return { ok: false, code: 'render_failed', message: `unexpected error: ${e && e.message ? e.message : e}` };
}

// What the caller saw, minus the render list body (list records its count as a step).
function outcomeOf(command, output) {
  return command === 'list' && output.ok ? { ok: true, state_dir: output.state_dir } : output;
}

/**
 * Run one viz call. Returns { output, exitCode }; output is the single JSON
 * object for stdout. Appends one action record to the store, whatever happens.
 */
export async function runAction(argv, ports) {
  const started = ports.clock.now();
  let id;
  do { id = newId(started, ports.random.hex()); } while (await ports.store.isTaken(id));
  const [command, ...args] = argv;
  const steps = [];
  const ctx = { id, started, step: (s) => steps.push(s) };
  let output;
  try {
    if (command === 'render') output = await render(args, ports, ctx);
    else if (command === 'publish') output = await publish(args, ports, ctx);
    else if (command === 'list') output = await list(args, ports, ctx);
    else if (command === 'doctor') output = doctor(args, ports, ctx);
    else if (command === 'help' || command === '--help' || command === '-h') output = { ok: true, usage: USAGE };
    else throw new VizError('bad_input', `${command === undefined ? 'no command' : `unknown command ${JSON.stringify(command)}`}\n${USAGE}`);
  } catch (e) {
    output = failure(e, ports);
  }
  const record = {
    id, ts: new Date(started).toISOString(), duration_ms: ports.clock.now() - started,
    command: command ?? null, args, steps, outcome: outcomeOf(command, output),
  };
  try {
    await ports.store.appendAction(record);
  } catch (e) {
    ports.warn(`viz: cannot append the action record: ${e && e.message ? e.message : e}`);
  }
  return { output, exitCode: output.ok ? 0 : EXIT_CODES.get(output.code) };
}
