# viz

`viz` turns Mermaid, SVG or HTML into a PNG and keeps the page and source on
disk, so an agent can look at the image and send it to the owner. `viz publish`
also puts the page and PNG on a static site and prints the link. Agents learn
when and how to use it from the canonical skill `using-viz`.

```sh
viz render <file|-> [--as mermaid|svg|html] [--width 1200] [--scale 2]
viz publish <file|id> [--as mermaid|svg|html] [--width 1200] [--scale 2]
viz list [--limit N]
viz doctor
```

- `--as` is guessed from `.mmd`, `.svg` or `.html`; stdin (`-`) needs it.
- `--width` is the page width in CSS px; `--scale` is the device pixel ratio.
  The PNG is sized to the content: an HTML page is the full document height at
  `--width`; a Mermaid or SVG drawing is cropped to the drawing plus 16 px.
- `--width` must be a positive integer and `--scale` a positive number; there
  are no other bounds (a size Chromium cannot capture fails as `render_failed`).
- `page.html` holds the page that was shot:
  - **HTML file:** a byte-exact copy of the source. Chromium loads the original
    file, so relative URLs (and any `<base>`) resolve exactly as written, against
    the source's directory. Opening the saved copy later from the state dir
    finds relative assets only if they are still reachable from there.
  - **HTML on stdin:** the input as written, shot from the state dir; there is
    no source directory, so keep such pages self-contained.
  - **SVG or Mermaid:** a page viz writes around the drawing. For an SVG file it
    carries a `<base>` pointing at the source's directory.

## Publish

`viz publish <id>` uploads a saved render; `viz publish <file>` renders the
file first (same options as `render`) and uploads that. An argument shaped like
a render id (`20261028-120000-000-abc123`) is an id; anything else is a file.

- It PUTs `image.png` to `$VIZ_PUBLISH_URL/<id>/image.png` and `page.html` to
  `$VIZ_PUBLISH_URL/<id>/index.html`, with basic auth: user `viz`, password
  `$VIZ_PUBLISH_PASSWORD`. Any static site that accepts authenticated PUTs works.
- It prints the render's fields plus `url` (`$VIZ_PUBLISH_URL/<id>/`, the page)
  and `png_url`.
- The site config is checked before rendering. If an upload fails after a file
  was rendered, the render is kept and the message names the `viz publish <id>`
  that retries it.
- A published HTML page is the byte-exact `page.html`: relative assets beside
  the source file are not uploaded, so only self-contained pages work online.
- Nothing is unpublished or pruned yet.

The shim `~/.local/bin/viz` wires in Michael's site for `publish` only:
`VIZ_PUBLISH_URL` defaults to `https://viz.internal.cartwmic.com`
(cartwmic-homelab-v2 `k8s/viz`, LAN and WireGuard only), and an unset
`VIZ_PUBLISH_PASSWORD` is read with `op read op://developer/viz-publish/password`.
`viz.mjs` itself reads only the two variables.

## Output contract

Every outcome prints exactly one JSON object on stdout; logs and page errors go
to stderr.

| Exit | `code` | When |
|------|--------|------|
| 0 | — | `{"ok":true,"id","png","html","source","width","height","bytes"}` (`publish` adds `"url","png_url"`; `list`: `{"ok":true,"renders":[...]}`, newest first) |
| 2 | `bad_input` | usage error, unknown format, missing file, bad option value |
| 3 | `render_failed` | the render failed; for Mermaid the message is the parser's text (`Parse error on line ...`) |
| 4 | `missing_dependency` | no Chromium, `mmdc`, headless shell or `node`; for `publish`, no `VIZ_PUBLISH_URL` or `VIZ_PUBLISH_PASSWORD` |
| 5 | `publish_failed` | an upload failed: the site was unreachable or answered with an error (401: wrong password) |

`width` and `height` are the PNG's pixels; `bytes` is its file size.

## State

Each render is `$VIZ_STATE_DIR/<id>/` (default `~/.local/state/viz`) with
`source.{mmd,svg,html}`, `page.html`, `image.png` and `meta.json`. Renders
outlive the call because an attachment is read later by another process
(`reach` reads the file when it sends). Nothing prunes them yet. A render is
built in a `.staging-*` directory and renamed into place only on success.

### Action log

Every call (`render`, `publish`, `list`, `doctor`, usage errors too) appends one JSON line
to `$VIZ_STATE_DIR/actions.jsonl`, whatever the outcome. `list` ignores it.

| Field | Meaning |
|-------|---------|
| `id` | action id; for a render it is the render id (and directory name) |
| `ts`, `duration_ms` | UTC start time and how long the call took |
| `command`, `args` | what was run: arguments and paths, never source bodies |
| `steps` | what viz did: `request` (input as given, resolved format, width, scale), `input` (absolute path, bytes), `chromium` (path), `mmdc` (`ok`, and the parser `message` on failure), `screenshot` (page loaded, PNG size, bytes, page errors), `site` (publish base URL), `render` (id of a saved render being published), `upload` (remote path, bytes, HTTP status, or `ok: false` and the message), `list` (count), `doctor` (missing dependencies). Never the password. |
| `outcome` | the JSON object printed on stdout (`list` records its count instead of the renders) |

A failed Mermaid render leaves no render directory, but its record names the
input and the parser's message. Nothing rotates the log yet.

## Layout

- `core/` is the domain (`domain.mjs`: formats, option validation, ids, page
  building, list ordering, publish URLs) and the use cases (`use_cases.mjs`:
  `render`, `publish`, `list`, `doctor` and the action record). It imports
  nothing from `node:` and nothing outside `core/`; it reaches the outside only
  through the ports listed at the top of `use_cases.mjs` (store, input, browser,
  mermaid, site, clock, random).
- `adapters/` implements those ports: `fs_store.mjs` (state dir and action log),
  `chromium.mjs` (screenshot), `mmdc.mjs` (Mermaid), `http_site.mjs` (PUT
  uploads with Node's `fetch`) and `executables.mjs`.
- `viz.mjs` is the CLI entry that wires the adapters into the core and prints
  the result.

## Dependencies

No npm packages. Only `publish` uses the network.

- **Node 24** runs `viz.mjs`. The shim `~/.local/bin/viz` finds it at
  `$HERE/../share/viz`, so the source tree's `dot_local/bin/executable_viz` also
  works before `chezmoi apply`.
- **Chromium:** `$VIZ_CHROMIUM`, else `chromium` on `PATH`. `adapters/chromium.mjs`
  starts it headless with `--remote-debugging-pipe` and speaks the DevTools
  Protocol over fds 3 and 4 (NUL-terminated JSON): set the viewport width and
  scale, load the page (the original HTML file, else `page.html`), measure the content, then `Page.captureScreenshot`
  with a clip and `captureBeyondViewport`. A plain `--screenshot` would crop to
  the window size.
- **Mermaid:** `mmdc` on `PATH` (11.16.0, mise task `install-mermaid-cli`) turns
  the source into SVG, with `-p` pointing its puppeteer at the newest Playwright
  `chrome-headless-shell` (under `$PLAYWRIGHT_BROWSERS_PATH`, else the
  Playwright cache). The SVG is then shot like any other page.

`viz doctor` reports the paths it would use.

## Tests

- `python3 -B tests/viz/test_viz.py` runs the CLI as a black box against
  `tests/viz/fixtures/` with a temporary `VIZ_STATE_DIR` (needs Chromium and
  mmdc).
- `python3 -B tests/viz/test_core.py` runs the core use cases with fake ports
  (needs only node).
- `python3 -B tests/viz/test_publish.py` runs `viz publish` as a black box
  against a scripted local site and a fake `op` (needs only node; publishing a
  file also needs Chromium and mmdc).
- `python3 -B tests/viz/test_boundaries.py` fails if a `core/` file imports a
  `node:` builtin, a package or anything outside `core/`.
