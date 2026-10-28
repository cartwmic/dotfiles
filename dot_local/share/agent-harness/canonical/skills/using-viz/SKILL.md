---
name: using-viz
description: Use when a picture would explain better than text (comparing more than a handful of numbers, a trend, a flow, state machine, architecture, timeline or dependency graph) or when asked for a diagram or chart; renders Mermaid, SVG or HTML to a PNG with viz render, checks it, and shows or sends it to Michael.
---

# Using viz

`viz` turns Mermaid, SVG or HTML into a PNG and keeps it on disk. Reading the PNG
shows it to you and, in Pi or Claude Code, to the person at the terminal.

## When to make a visual

Make one when:

- you compare more than a handful of numbers;
- you show a trend over time;
- you explain a flow, state machine, architecture, timeline or dependency graph;
- you are asked for a diagram, chart or picture.

Do not make one when a sentence says it as well.

## Which format

| Content | Format |
|---------|--------|
| Flow, sequence, state, gantt | Mermaid (`.mmd`) |
| Small custom drawing | SVG (`.svg`) |
| Anything else, such as a chart drawn in a page | HTML (`.html`) |

Write the source to a file in a scratch directory (not in a repository), or pipe
it on stdin with `--as`. Keep HTML self-contained: inline CSS and data, plain
SVG or canvas drawing, no network fetches.

## Render

```sh
viz render diagram.mmd
viz render chart.html --width 1000
cat flow.mmd | viz render - --as mermaid
```

Options: `--as mermaid|svg|html` (guessed from `.mmd`, `.svg`, `.html`),
`--width` page width in CSS px (default 1200), `--scale` pixel ratio (default 2).

stdout is one JSON object:

- `{"ok":true,"id":...,"png":"/abs/image.png","html":...,"source":...,"width":...,"height":...,"bytes":...}`
- `{"ok":false,"code":...,"message":...}` with exit 2 `bad_input`, 3
  `render_failed`, or 4 `missing_dependency`.

On `render_failed` for Mermaid the message is the parser's text (`Parse error on
line ...`); fix the source and render again. On `missing_dependency`, run
`viz doctor` and report what it names; do not install anything.

If a failure's message is not enough, the last line of
`~/.local/state/viz/actions.jsonl` records that call's steps and outcome.

`viz list [--limit N]` shows earlier renders, newest first. Renders stay under
`~/.local/state/viz/<id>/`; do not delete them, a message may still point at one.

## Check it

Read the PNG with your file-reading tool before you show or send it. Look for
cut-off or overlapping labels, unreadable text, wrong numbers, empty space and
a wrong title or axis. If anything is wrong, fix the source and render again.

## Show it in Pi or Claude Code

Read the PNG path from the JSON; the image appears inline. Add one line saying
what it shows.

## Send it to Michael

- **A worker** rings `notify_owner` with kind `review`, a one-line `summary` of
  what the image shows, and the PNG path in `attachments`.
- **The coordinator** runs `reach send --attach <png>` with one line saying what
  it shows.

Send the `png` path exactly as `viz render` printed it. `viz` itself never sends
anything; the only contract is the file path.
