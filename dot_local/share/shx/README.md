# shx-note-image

`shx-note-image` is the agent's side of shartifacts' drawing tool. Michael draws on a page with a finger; the
server stores the stroke as data. This command turns one stroke into a PNG an agent can read, and tells the server
which comments still find their place after a page changed. Agents learn when to use it from the canonical skill
`using-shartifacts`. The stroke format is the `Comment.stroke` contract of the shartifacts fork.

```sh
shx-note-image <base-url> <artifact-id> <comment-id> [--version N] [--out file.png] [--pad 24]
shx-note-image check <base-url> <artifact-id>
```

`<base-url>` may be left out when `SHARTIFACTS_URL` is set. The MCP side is the `shartifacts` entry in
`canonical/mcp/servers.json.tmpl`.

`shx-waiting` is the other command of this component (below, "shx-waiting"); it does not draw anything.

## The picture

1. `GET <base>/api/artifacts/<id>/comments`; take the root comment's `stroke`.
2. Open `<base>/view/<id>?version=N` in headless Chromium (N is `--version`, else `stroke.version`) at
   `stroke.viewport.w` x `stroke.viewport.h`, then load the frame's own address in the same tab at that size. The
   frame is what Michael drew on; loading it alone gives the page his exact viewport, without the bar `/view` puts
   above it.
3. Find `stroke.anchor`. The points are offsets from the anchor element's box, so the stroke is placed from the
   element's current box. If the element is gone, the stroke goes where it was drawn (`stroke.box`) and
   `anchor_found` is `false`.
4. Draw the stroke (perfect-freehand outline, the stroke's `color` and `width`) over the page and crop to the
   stroke's box plus `--pad` CSS px (default 24), joined with the anchor element when that fits on the screen the
   stroke was drawn on. The picture is at pixel ratio 2.

## `check`

Renders the latest version at 390 x 844 and, for every open root comment that has a `quote` or an anchor, decides
whether it is still there, by the rule of the frame (`web/runtime.js`, `locate`): a comment with a quote needs the
quote's words on the page (whitespace matched loosely), in its anchor element or anywhere; one without a quote needs
its anchor selector to match an element, and for a drawing that element must be the one drawn on (its `anchor_tag` and `anchor_text`, both recorded in the stroke: the first 120 characters of its text, cut at whole
characters; an element's text includes its `alt`, `aria-label` or `title`), since a path such as
`p:nth-of-type(4)` names a slot that an edit can fill with something else. It then posts `{"version": N, "results": [{"id", "found"}]}` to
`<base>/api/artifacts/<id>/comments/matches`. Resolved comments, replies, comments that point at nothing and drawings on an element with no text (a chart bar, an
image with no label: `anchor_text` is empty, and nothing can tell it from its neighbour) are left out; the last stay
`unchecked` on a later version. With nothing to check it posts nothing and starts no browser.

## shx-waiting

```sh
shx-waiting [<base-url>] [--file F]... [<page-id>...]
```

Lists the comment threads that wait for an agent, so none goes unanswered. The server's comment list for a page is
flat: a thread's first comment has no `parent`, each reply names the first comment, and `author` is `you` (the
owner) or `agent`. A thread waits when it is not resolved and its latest message, by `created_at` (fractions padded to
a fixed width, ties by list order), is the owner's. An agent's reply is never shown as his comment. The command reads
only (`GET`) and changes nothing.

- No page ids and no `--file`: every page `GET <base>/api/artifacts` lists (read twelve at a time). Page ids, or
  `--file F` (each 24-character hex word in the file is one id, so a plain list or a tab-separated table both work):
  only those pages. `<base-url>` is the first argument that starts with `http://` or `https://`, else
  `SHARTIFACTS_URL`, else `https://shartifacts.internal.cartwmic.com`.
- stdout: one block per waiting thread, longest waiting first (page id and title, link, thread id and when his first
  unanswered message came, the text he pointed at, his unanswered messages), then a count line such as
  `2 threads waiting on 1 page (1012 pages read)` or `none waiting (1012 pages read)`. Failures print one line on stderr.
- Exit: `0` none waiting, `1` at least one waits, `2` bad usage or an unreadable `--file`, `3` unexpected failure (an
  uncaught error, a broken install: Node's own `1` is never allowed through), `4` no `node`, `5` shartifacts
  unreachable, answered an error or answered something that is not comments (the line names the page). A failure on
  any page fails the run: "could not read" is never "nothing waits".
- Log: one JSON line per run in `${XDG_STATE_HOME:-~/.local/state}/shx/waiting.log`: `id`, `ts`, `command`
  (`waiting`), `base`, `scope` (`all` or `ids`), `pages`, `waiting`, `duration_ms`, `error`. Counting the lines
  answers how often agents run it and how often a run found something waiting.

## Output

The two commands above (`shx-note-image` and `check`) print one JSON object on stdout:

| Exit | `code` | When |
|------|--------|------|
| 0 | | the picture: `{"ok":true,"path","width","height","anchor_found","version"}` (`width` and `height` are PNG pixels); `check`: `{"ok":true,"version","results":[{"id","found"}]}` |
| 2 | `bad_input` | usage error, no such comment, a reply, a comment without a stroke, an unusable stroke |
| 3 | `render_failed` | Chromium would not start or load the page, or the page never loaded an artifact |
| 4 | `missing_dependency` | no `node` or no Chromium (`SHX_CHROMIUM`, else `chromium` on PATH) |
| 5 | `request_failed` | shartifacts unreachable or answered with an error |

`SHX_NO_SANDBOX=1` starts Chromium with `--no-sandbox`, for a machine whose kernel does not allow its sandbox (the tests set it on a hosted CI runner).

One render, from starting Chromium to the last read of the page, must end within 60 s (`SHX_RENDER_TIMEOUT_MS` changes it). When it does not, the `render_failed` message names the step it was in, how long each step took, and what Chromium printed on stderr. The wait for `/view` to load an artifact into its frame is half of that limit. A page whose renderer dies fails at once with `the page crashed ...`, and the run starts a new Chromium and tries once more before it reports the failure.

Without `--out` the PNG is `${XDG_STATE_HOME:-~/.local/state}/shx/images/note-<artifact>-<comment>-v<N>.png`.

## Log

Every run (failures and usage errors too) appends one JSON line to
`${XDG_STATE_HOME:-~/.local/state}/shx/note-image.log`: `id`, `ts` (UTC), `command` (`note` or `check`), `base`
(scheme and host only), `artifact`, `comment`, `version`, `pad`, `viewport`, `out`, `duration_ms` and `error`
(`null`, or `{code, message}`). The wrapper's own "no node" refusal is not logged, since only node writes the log.

## Layout

```
dot_local/bin/executable_shx-note-image   wrapper: finds node, runs shx.mjs
dot_local/bin/executable_shx-waiting      wrapper: finds node, runs waiting.mjs
dot_local/share/shx/
  shx.mjs                 wires the real adapters into the core
  waiting.mjs             the same for shx-waiting
  core/                   domain.mjs (arguments, stroke, placement, crop, log record), use_cases.mjs, waiting.mjs (shx-waiting); no node: imports
  adapters/               chromium.mjs (DevTools Protocol over a pipe), shartifacts_http.mjs, freehand.mjs, fs_store.mjs
  vendor/                 perfect-freehand 1.2.3 (MIT) and its licence
```

`adapters/chromium.mjs` is the DevTools Protocol pipe plumbing, kept inside this component (components do not import each
other's adapters).

## Tests

- `python3 -I tests/shx/test_note_image.py` runs the command against a stdlib server that plays shartifacts, with
  real Chromium (skips without it).
- `python3 -I tests/shx/test_waiting.py` runs `shx-waiting` against a stdlib server that plays shartifacts (needs node only).
- `python3 -I tests/shx/test_boundaries.py` fails if a `core/` file imports anything outside `core/`.
- `python3 -I tests/shx/test_skill.py` and `python3 -I tests/shx/test_agent_access.py` check the skill and what
  chezmoi renders for both desktop profiles.
