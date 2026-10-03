# Herdr Overview plugin runtime

## Overview

This source-managed plugin targets Herdr **0.9.1 / protocol 22**. The desktop
`install-herdr-overview` mise task installs Herdr and links/enables its
manifest on `personal` and `axon-work-computer`. Termux remains an SSH client.
It does not host the plugin. The thin Pi adapter lives at
`dot_pi/private_agent/extensions/herdr-overview/`.

Linking leaves the running server untouched. On a compatible server start,
the plugin's `[[startup]]` hook initializes its model without creating a tab.
The `overview.reconcile` action refreshes that model without opening a view.
`overview.open` opens a temporary shared pane-canvas popup, not a native tab.
Herdr 0.9.1 retains its sidebar/tab strip or phone header around this canvas. Chezmoi apply and bootstrap never restart the owner's main server.

An old persistent Overview tab is not destroyed during migration. Close that
old tab manually if desired; the plugin never deletes owner panes to recreate it.

The plugin reads native Herdr pane state through the public protocol. It joins
adapter-owned private Pi prompt files and published `session-recap` records to
those panes, keeping prompt, recap, and live agent state separate. Generic Pi
records join native sessions via `metadata.pi.sessionId` (also accepting
`nativeSessionId`), not their independent history key; `annotations.herdr`
supplies pane/workspace attribution. Legacy records and prompt files remain
readable without migration/deletion. A pane move
can rekey its native ID; a verified live terminal identity keeps its supplied
prompt and recap visible after the move. Reads never generate recaps. The
[component agent guide](./AGENTS.md) covers ID joins, hooks, and tests.

## Setup

On a `personal` or `axon-work-computer` desktop, review the managed files,
apply them, then run the pinned installer/link task from the chezmoi source
checkout:

```sh
chezmoi apply --dry-run --verbose ~/.local/share/herdr-overview
chezmoi apply ~/.local/share/herdr-overview
mise run install-herdr-overview
```

The task links the plugin without starting or restarting Herdr. On a
compatible running server, load the linked action and reconcile the model with:

```sh
herdr plugin action invoke overview.reconcile
```

The server's next start runs the startup hook; no restart is needed for this
manual initialization. `herdr server reload-config` separately applies the
new `prefix+shift+o` shortcut. For desktop provisioning, see `README.md`
(Herdr overview and phone route) at the chezmoi source root. To supply
recaps, set up `dot_local/share/session-recap/README.md` and the Pi adapter at
`dot_pi/private_agent/extensions/herdr-overview/README.md`. These paths are
relative to the source root. Pi recap generation needs explicit new setup via
`/recap settings` in the independent Pi recap extension; it never imports the
CLI's backend or auto preferences. The overview adapter only tracks prompts
and annotates saved recaps. `auto_publish = true` and a local CLI backend
control plugin group generation, not Pi recap generation. Generic manual
`session-recap create` remains supported. Pi recap and the standalone CLI both
work with Herdr stopped.

## Usage

Open the popup with `prefix+shift+o` or
`herdr plugin action invoke overview.open`. Clients share one
session-singleton, 100% native popup with no pane ID; another
modal returns `ui_busy`. Deleting its owner tab dismisses it natively; reopen
from an ordinary surviving pane. There is no anchor, resurrection or background
automatic open on startup, events or reconcile. A selected non-owner target
that disappears while the popup lives produces a notice and cannot focus an
unrelated pane. The responsive native map groups
single-pane tabs together beneath their workspace and keeps multi-pane tabs
as groups. Inside each workspace, tabs and panes are ordered by state:
questions/blocked first, then ready, then working, then the rest; native
order breaks ties, and `[`/`]` follow this displayed order. Wide
layouts use workspace columns; singleton tabs share compact card rows (two
columns from an actual popup-canvas width of 32 columns). Cards are bordered,
word-wrapped, one column apart (two between workspace columns), and vertically tight (no blank border rows, spacer lines, or
unused title/preview rows); shortened collapsed titles end in an ellipsis. `M`
marks manual names. Each workspace is framed by a thin box whose top edge carries the bold name and
counts, `┌─ name ───── N tabs · K needs input ─┐`; on narrow columns the counts
move inside the frame and the frame drops its inner padding. Normal reading
shows prose, not raw JSON. Expanded recap and digest bodies render a small
markdown subset (`src/markdown.mjs`: headings, bold/italic, inline code,
lists, quotes, rules, code fences); collapsed card previews drop the markers
and stay plain text. Recap and digest times are stored in UTC; the overview
shows them in the recap CLI's `time_zone` (`~/.config/session-recap/config.toml`,
`config.local.toml` wins; default `local`), DST-aware, e.g.
`2026-10-03 06:19:35 GMT−7 [America/Los_Angeles]`. Cards show one lean dim
line, `Recap 2026-10-03 06:19 GMT−7` (no seconds or zone name), or
`Recap unavailable`; the expanded view puts the full date on its section
heading (`Latest good recap · …`, `Session digest · …`). Unparseable values
are shown unchanged. An expanded card always starts at the top of the view,
even when it is short. The viewer redraws in place (synchronized update, no
full-screen clear), so scrolling does not flash. Card previews show at least two recap lines and also fill
rows that would otherwise be blank (no newer-attempt warning, or a taller paired
card) without making the card taller. Collapsed previews skip blank lines. Paired cards share one title-block height
(one or two rows) so their rows stay aligned. Supplied prompts and failures stay literal. Outer widths 40/48/120/180 currently yield popup
widths 38/46/92/152. Outer width 32 yields only 30: below the card floor, where
ordinary clipping can occur, not a supported-width claim. The single shared
native popup PTY can clip a narrow attached peer when another client is wide;
detach the other peer for readable single-client geometry. Board/Mosaic and their background tab
are retired.

- Arrows and `h`/`j`/`k`/`l` select in the displayed direction, without wrapping.
  `[`/`]` select the previous/next pane in displayed order.
- The wheel scrolls the map independently of selection, or the expanded recap/digest.
  A left click on a card selects it and opens its recap in place; it never
  focuses a terminal or dismisses.
  Keyboard selection brings its target back into view; resize preserves identity.
- `Enter` expands the selected pane in the map, including its full tab name;
  Enter on the expanded recap or digest focuses that pane (same identity check
  as `f`). `Esc` returns to the map. `d` enters the separate digest view and does nothing if already there.
- In detail, `j`/`k`, Space, and `b` scroll. `n` selects the next blocked pane.
- `Esc` restores the prior recap passage from digest, then returns to map, then
  dismisses; `q` dismisses immediately.
- `r` refreshes native state and saved records. Resize redraws the map.
- `f` checks the selected live terminal identity again, focuses its native pane
  and dismisses only on success. A vanished/conflicting target stays open.

Every collapsed card shows its latest-good recap with at most two excerpt lines.
An ellipsis means text was omitted; short recaps are not marked truncated. Missing
recaps are unavailable, and a newer failed attempt is a separate warning.
Publication time uses `published_at`, then `created_at`, converted for display
only with the recap CLI's `time_zone`. Overview has no timezone setting of its own.

Native blocked status uses the red × symbol. An actual Pi questionnaire wait adds
**Awaiting answer**, including while its dialog is collapsed. Generic blockers do
not claim that reason. Answer/cancel clears only the question contribution; other
blockers remain authoritative. Older settlement-abort v1 makes `ctx.isIdle()` false
in final handlers and suppresses stock native READY reporting. Use a compatible
runtime that preserves main-agent idle there; compatible stock unpatched runtimes
do not require this user patch. The separately reviewed v2 was compatibility-tested
on a private copy of real Pi 0.99.2, not installed live. Before deployment, complete
the source-scoped native/visual driver matrix and independent acceptance, then
obtain explicit apply authorization. Private proof does not authorize apply.
This viewer does not bypass or repair the native idle guard.

The display is passive: it shows only supplied prompt fields and published recap records, with age and missing/failure status. Opening, selection, refresh, scrolling, and focus never run `session-recap` or synthesize recap text. `overview.reconcile` remains a separate plugin action for publication coordination and manual-library refresh. To show a manually generated single recap in a pane's detail, use that native pane ID as the source ID, for example `printf '%s\n' 'Recent work and current state.' | session-recap create --kind single --source-id PANE_ID`, then invoke `herdr plugin action invoke overview.reconcile` while the source pane is live. This lets the overview display its published or failed status and persist the live terminal association used if `pane.move` later rekeys the pane. Manual results are not Pi auto-naming inputs.

A successful Pi recap with durable overview attribution starts or resets a
30-second quiet period for its workspace at publication time. An unannotated
new record waits for the adapter; a session-only record cannot trigger a
workspace group. Startup reconciles durable annotations after a missed wake-up.
Later moves/returns do not reassign the publication's workspace or deadline. At expiry, grouping uses the latest published
recaps for panes in that workspace's **current** native membership, including
manually sourced recaps for non-Pi panes; closed panes are excluded. A
successful workspace group can produce an active Herdr-session group. A failed
group preserves the last good record and cannot trigger a session group.
Pending deadlines resume after restart. With `auto_publish = false`, the
plugin retains those deadlines and existing recaps while suppressing group
model calls and wake-ups. A later reconcile after opt-in can process due
deadlines. Raw non-Pi output is never included.

Unlabelled panes and Herdr's positional numeric tab defaults may be named from
stable current Pi session names, native titles, agent/process metadata and cwd.
Recap and digest bodies are not naming inputs.
Unknown initial labels and owner edits stay manual. The scoped
`overview.auto_name_pane` and `overview.auto_name_tab` actions return one label
to automatic control. Workspace names and Pi identity stay untouched. A
single-pane tab uses its stable pane subject; a two-pane tab combines both short subjects when they fit; otherwise a
multi-pane tab uses the first useful stable subject plus `N more` (remaining
live panes). Body-only recap/digest changes do not rename
it. Private Pi metadata joins the current socket and unique live terminal,
rejecting conflicting native session identity or dead publishers. Herdr may
report a Pi session by id or by its session file path; a path counts only when
its file name ends in `_<uuid>.jsonl`, and that exact UUID is used. Digest bodies
join only the verified current session UUID; missing/malformed digests are
unavailable, and valid dated digests remain explicitly dated. Latest-good recap,
later failed attempt, current prompt and digest remain separate. Reconciliation rereads a target before an
automatic rename; Herdr 0.9.1 has no conditional rename, so a manual edit in
the final snapshot-to-write interval can still race.

The theme adapter uses Herdr 0.9.1's pinned palette, reads the managed
`config.toml` on popup open, and watches for changes. It resolves `[theme].name`
and `[theme.custom]` when `auto_switch = false`. With `auto_switch = true`, it
needs an explicit appearance input; it does not detect host appearance by
itself. Palette provenance and adapter tests are in the
[component agent guide](./AGENTS.md).

## Troubleshooting

- Linked plugin, missing popup: invoke `overview.open` on a compatible server.
  `overview.reconcile` intentionally opens no view. If Herdr reports busy,
  dismiss the other modal first.
- Missing or failed recap: the overview still shows native pane details.
  Check `/recap settings` and `/recap history` for Pi generation. Check
  `session-recap config auto-publish` and the local CLI backend only for plugin
  groups. Consumer setup is in
  `dot_pi/private_agent/extensions/herdr-overview/README.md`.
- Real-server proof needs an isolated socket and cleanup. Use
  `python3 tests/herdr-overview/proof.py --help` for its scenarios; the phone
  journey requires an attended Termux-over-SSH client.

## Validation

From the chezmoi source root, run the package tests and the standalone
recap/review checks:

```sh
npm test --prefix dot_local/share/herdr-overview
python3 tests/herdr-overview/proof.py recap
python3 tests/herdr-overview/proof.py review
python3 tests/herdr-overview/proof.py chezmoi-dry-run
```

The complete isolated journey is `python3 tests/herdr-overview/map_journey.py
--scenario all`. It composes native interaction/lifetime, real Pi publication,
identity/lifecycle, naming, digest and rekey assertions on one owned server.
`interactions` and `identity` remain focused diagnostics; `smoke` is not the
complete matrix. Receipts default to a fresh private `/tmp` directory; failures
exit nonzero and retain their evidence. Install the pinned `pyte==0.8.2` from
`tests/herdr-overview/requirements-interactions.txt` into a private environment
and use its interpreter for the journey and harness tests (the checked task
interpreter is `/tmp/hm-pyte-t4a/bin/python`). Run `python3 -m unittest discover
-s tests/herdr-overview -p 'test_*.py'` with that interpreter too.

The fixture commands in [AGENTS.md](./AGENTS.md) use the same transient native
popup contract, not a dedicated viewer pane. Physical phone proof and live
rollout remain owner-pending: a local 40-column PTY checks layout, not an
attended Termux-over-SSH route.

Focused follow-up fixtures: `tests/herdr-overview/follow_up_journey.py` takes
`--receipts`, `--reference`, and `--browser-python`; `question_wait_journey.py`
takes `--receipts`. They use owned native servers and scripted/dummy backends.
Whole native color cells/SVG/PNG and same-data v1 browser reference images are
review evidence, not automatic visual acceptance. The full driver matrix and
independent visual review remain separate obligations.
