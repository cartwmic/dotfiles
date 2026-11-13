// Use cases: the picture of one drawn comment, and the check that reports which comments still find their place.
// The outside is reached only through these ports (shx.mjs wires the real ones):
//   api      { comments(base, artifact) -> [comment], artifact(base, artifact) -> { revisions },
//              postMatches(base, artifact, body) }
//   browser  { locate() -> path, open({ chromium, url, width, height }) -> page }
//   page     { doc: { w, h }, anchorBox(selector) -> { x, y, w, h } | null,
//              shoot({ d, color, clip }) -> { png, width, height }, find(items) -> [{ id, found }], close() }
//   outline  (points, width) -> SVG path data for the drawn stroke
//   files    { save({ path, name }, bytes) -> absolute path }   path is the --out value, name the default file name
//   log      { append(record) }
//   clock    { now() -> epoch ms }
//   random   { hex() -> short random hex string }
//   warn(line)   diagnostics for stderr
// Adapters signal failures by throwing ShxError with a contract code.
import {
  CHECK_VIEWPORT, EXIT_CODES, ShxError, checkItems, cropRect, latestVersion, logRecord, parseArgs, placePoints, readStroke,
} from './domain.mjs';

const viewUrl = (base, artifact, version) => `${base}/view/${encodeURIComponent(artifact)}?version=${version}`;

async function noteImage(req, ports, ctx) {
  ctx.artifact = req.artifact;
  const stroke = readStroke(await ports.api.comments(req.base, req.artifact), req.comment);
  const version = req.version ?? stroke.version;
  ctx.version = version;
  ctx.viewport = stroke.viewport;
  const chromium = ports.browser.locate();
  const page = await ports.browser.open({ chromium, url: viewUrl(req.base, req.artifact, version), width: stroke.viewport.w, height: stroke.viewport.h });
  try {
    // The stroke is stored as offsets from its anchor element, so it follows the element when the page moved it.
    const found = stroke.anchor ? await page.anchorBox(stroke.anchor) : null;
    const origin = found ?? stroke.box;
    const points = placePoints(stroke, origin);
    const clip = cropRect({ points, width: stroke.width, element: found, viewport: stroke.viewport, pad: req.pad, doc: page.doc });
    const shot = await page.shoot({ d: ports.outline(points, stroke.width), color: stroke.color, clip });
    const path = await ports.files.save({ path: req.out, name: `note-${req.artifact}-${req.comment}-v${version}.png` }, shot.png);
    ctx.out = path;
    return { ok: true, path, width: shot.width, height: shot.height, anchor_found: found !== null, version };
  } finally {
    await page.close();
  }
}

async function check(req, ports, ctx) {
  ctx.artifact = req.artifact;
  const version = latestVersion(await ports.api.artifact(req.base, req.artifact));
  ctx.version = version;
  ctx.viewport = CHECK_VIEWPORT;
  const items = checkItems(await ports.api.comments(req.base, req.artifact));
  if (items.length === 0) return { ok: true, version, results: [] };
  const chromium = ports.browser.locate();
  const page = await ports.browser.open({ chromium, url: viewUrl(req.base, req.artifact, version), width: CHECK_VIEWPORT.w, height: CHECK_VIEWPORT.h });
  let results;
  try {
    results = await page.find(items);
  } finally {
    await page.close();
  }
  await ports.api.postMatches(req.base, req.artifact, { version, results });
  return { ok: true, version, results };
}

/** Runs one command line. Returns the one JSON object for stdout and the exit code; leaves one log record. */
export async function run(argv, ports, defaults = {}) {
  const startedAt = ports.clock.now();
  const ctx = {};
  let request = { command: argv[0] === 'check' ? 'check' : 'note' };
  let output;
  let error = null;
  try {
    request = parseArgs(argv, defaults.base);
    output = await (request.command === 'check' ? check : noteImage)(request, ports, ctx);
  } catch (e) {
    error = e instanceof ShxError ? e : new ShxError('render_failed', `unexpected error: ${e && e.stack ? e.stack : e}`);
    output = { ok: false, code: error.code, message: error.message };
  }
  const record = logRecord({
    id: `${startedAt.toString(36)}-${ports.random.hex()}`, startedAt, durationMs: ports.clock.now() - startedAt, request, error, ...ctx,
  });
  try {
    await ports.log.append(record);
  } catch (e) {
    ports.warn(`[shx-note-image] WARN: cannot append the log record: ${e.message}`);
  }
  return { output, exitCode: error ? EXIT_CODES.get(error.code) : 0 };
}
