---
name: using-shartifacts
description: Use when you publish a page, chart, diagram or picture on shartifacts for Michael, read the comments and drawings he leaves on it, need a drawing as a picture (shx-note-image), run the check after changing a page, or wait for his feedback.
---

# Using shartifacts

shartifacts is Michael's self-hosted page server at `https://shartifacts.internal.cartwmic.com`.
He reads a page on his phone, selects text or draws on it with a finger, and you get what he
marked back.

Pages for Michael's review or input go on shartifacts: reports he comments on, pickers, plans,
explainers, anything interactive. He selects, draws and comments on the page, and you read his
highlights, drawings and comments here and wait on them. Do not ask him to paste text back.
Charts, diagrams and pictures go here too (see "Charts, diagrams and pictures").

You reach it two ways: the `shartifacts` MCP server (its tools are named below) and the
command `shx-note-image`.

## Publish a page

- `create_artifact` with `title`, `kind: "html"` and `content` returns the `id` and `version`.
  Keep the page self-contained: inline CSS and data, no network fetches.
- `update_artifact` adds a version. Pass `id` and `base_version` (the latest from
  `get_artifact`) and either `edits` (small changes) or `content`.
- Give Michael `https://shartifacts.internal.cartwmic.com/view/<id>`. The page needs the
  `/view` frame: commenting, drawing and live updates come from the page around it. A bare
  `/preview/<id>` address has none of them.

## Charts, diagrams and pictures

shartifacts is the only place to publish these.

- Mermaid and SVG: `create_artifact` with `kind: "mermaid"` or `kind: "svg"` and the source as
  `content`. Both render directly; there is no render step. Link `/view/<id>`.
- PNG or other image: upload the file, then show it in an `html` page with
  `<img src="/media/<id>.png">`, or hand over the `/media/` URL on its own.

  ```sh
  curl --fail-with-body --silent --show-error -H 'Content-Type: image/png' \
    --data-binary '@./chart.png' --url 'https://shartifacts.internal.cartwmic.com/api/media?name=chart.png'
  ```

  It returns `{"id":...,"url":"/media/<id>.png",...}`. Give Michael the URL with the
  `https://shartifacts.internal.cartwmic.com` prefix.
- A script or cluster pod with no MCP publishes over HTTP. `POST /api/artifacts` with JSON
  `{"title","kind","content"}` returns `201` and the `id`. Update in place with
  `PUT /api/artifacts/<id>` and `{"base_version": N, "content": ...}`, where N is the latest
  version. A stale `base_version` returns `409`: read the artifact again and retry. The link
  stays the same.

## Read his comments and drawings

`artifact_comments` with `op: "list"` and the artifact `id` returns the open threads. Each has:

- `body`, `replies`, `version` (the version he saw) and `author`.
- `quote`, `element` and `anchor`: the text he selected, the opening tag of what he pointed at
  (search your source for it) and its CSS path.
- `stroke`: present when he drew. It names the element the drawing sits on (`stroke.anchor`)
  and the elements under it (`stroke.elements`), plus a `version` and the screen size he drew
  at. `quote` is empty for a drawing. Do not read the points; ask for the picture instead.
- `status`: `current` (he commented on the latest version), `ok` (the latest version still has
  what he pointed at), `lost` (it no longer does: the text was reworded or the element is
  gone) or `unchecked` (he commented on an older version and nobody has checked the latest).
  A drawing on an element with no text (a chart bar, an image) stays `unchecked` after any new
  version, because nothing can tell it from its neighbour: `check` skips it. Look at its picture.

Pass `all: true` to include resolved threads.

## Look at a drawing

```sh
shx-note-image https://shartifacts.internal.cartwmic.com <artifact-id> <comment-id> [--version N] [--out file.png] [--pad 24]
```

`<comment-id>` is the thread's `id`. The command renders the page version he drew on at his
screen size, draws his stroke over the element it was drawn on, crops to the stroke and prints
`{"ok":true,"path":...,"width":...,"height":...,"anchor_found":...,"version":...}`. Read the PNG
at `path` with your file-reading tool. The command starts its own headless Chromium.

- `anchor_found: false`: the element is gone from that version. The picture shows where he
  drew, on the page as it was.
- `--version N` draws the same stroke on a newer version, so you can see what it points at now.
- Without `--out` the PNG goes under `~/.local/state/shx/images/`. Leave it there.

If `SHARTIFACTS_URL` is set you may leave out the base URL.

## After you update a page: check

```sh
shx-note-image check https://shartifacts.internal.cartwmic.com <artifact-id>
```

It renders the latest version, finds out which open comments still have their text or element,
and tells shartifacts, so each thread's `status` becomes `ok` or `lost`. It prints
`{"ok":true,"version":N,"results":[{"id":...,"found":...}]}`. Run it after every
`update_artifact` on a page that has open comments. Then list the comments again: a `lost` one
needs a look. Either the change was what he asked for (reply and resolve), or the page lost the
thing he pointed at (put it back, or tell him what moved).

## Reply and resolve

- Reply: `artifact_comments` with `op: "add"`, `id`, `parent` (the thread's id) and `body`.
  Say what you changed, in one or two sentences.
- Resolve: `op: "resolve"` with `comment_id`, only once the page has the change. `reopen`
  undoes it.

## Wait for him

`watch_artifacts` with `ids: ["<artifact-id>"]`, `kinds: ["comments"]`, `after: <cursor>` and
`wait_seconds` (up to 50) returns `events` and a `cursor`. Start with `after: 0`, keep the
returned `cursor` and pass it next time.

If the reply has `gap: true`, the cursor was older than the history the server keeps or the
server's history was reset. You may have missed events. List the comments again instead of
trusting `events`.

Wait only when the task says to wait for his answer. Otherwise hand off with the link.

## When it fails

`shx-note-image` always prints one JSON object. On failure it is
`{"ok":false,"code":...,"message":...}` with exit 2 `bad_input` (wrong id, a comment without a
stroke), 3 `render_failed`, 4 `missing_dependency` (no `node` or Chromium: report it, do not
install anything) or 5 `request_failed` (shartifacts unreachable or an error answer). Each run
adds one line to `~/.local/state/shx/note-image.log` with the steps and the error.
