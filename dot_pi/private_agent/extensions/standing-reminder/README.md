# Standing reminder

## Overview

`standing-reminder` keeps one editable, multiline reminder for the current Pi
session. Use it for an instruction that should stay salient while you work.
Permanent rules belong in agent instructions; track task progress elsewhere.

## Setup

The extension and its `standing-reminder-origin` Pi patch deploy together on
`personal` and `axon-work-computer`. Termux excludes `.pi`. From the chezmoi
source root, review the full apply before installing; it runs the Pi patch
onchange script. The delivered behavior was tested with Pi 0.87.1. A later
Pi version needs updated patch anchors and version-pinned proof before the
isolated journey can validate it.

```sh
chezmoi --source "$PWD" apply --dry-run --verbose
PI_PATCHES_ROOT="$PWD/dot_local/share/pi-patches" chezmoi --source "$PWD" apply
pi
```

Pi needs an authenticated, usable model for a real request. For a built-in
provider, use `/login` to sign in and `/model` to select one; compatible custom
endpoints follow Pi's [model setup](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md).
The extension supplies no
model or credentials. In the Pi terminal UI, run `/reminder`, save the editor
file, then send a message. The widget previews the saved reminder and the next
processed operator message receives it. The installed Pi package must have the
origin patch; without known input provenance, delivery fails closed with a
warning.

## Usage

- `/reminder` opens Pi's configured external editor. It works while idle or
  while a response is streaming. Pi temporarily gives the terminal to the
  editor and redraws accumulated output when the editor closes.
- A successful close commits the editor's final contents exactly, including
  line breaks and spacing. Intermediate writes remain drafts until exit status
  is successful. An unchanged close is view-only; saving an empty file clears
  the reminder. A canceled or unsuccessful editor keeps the previous value and
  warns.
- `/reminder-clear` clears it without starting an agent request.
- The status widget shows a short preview. A saved edit or clear shows that it
  applies to the next request until Pi processes an eligible operator message.

These controls do not add chat bubbles or rewrite a user's request. The
reminder is advisory; the extension does not detect conflicts or enforce
compliance.

## Delivery and lifetime

Pi reads the saved value when it processes an operator-submitted message,
including queued steering. That request gets one hidden context projection
with the exact saved wording. Ordinary tool continuations carry the existing
projection; an extension-generated follow-up does not get a new one. A
successful edit saved during an active response takes effect for the next
operator message processed: already-started requests keep their original
snapshot, while queued steering receives the new text and no superseded
extension-owned projection. The status preview shows the saved value and an
explicit next-request cue until delivery. A compaction during ongoing work can
remove that request's projection; Pi does not insert another reminder into
that work's next model request, and the next operator message gets the living
value again. The configured editor can remain open while Pi processes queued
work; its accumulated output is redrawn after the editor exits.

The current value belongs to the saved session. It survives `/reload`,
compaction, and resuming the same session. `/tree` keeps that value unchanged.
`/fork` and `/clone` copy the value current at creation
time into a separate session; later edits do not cross between sessions. New
sessions and delegated child agents do not inherit it.

The extension stores only current state in a private sidecar under Pi's
session directory (`standing-reminder/<session-id>.json`, mode `0600` in a
mode `0700` directory). Reminder contents are not in this public source tree.
Treat Pi session storage as private: the sidecar contains the reminder in
plain text. If saved state is unreadable or missing after a session previously
used the extension, Pi warns and completes the request without sending stale
text. A missing sidecar on a marked saved session is covered separately from
corrupt state. In print/JSON modes the warning goes to stderr; RPC sends it
through the extension UI notification protocol. Noninteractive modes deliver
reminders but do not open the editor. If an external editor exits unsuccessfully
after writing its draft, the previous value remains active and reaches the next
model request.

The desktop-profile runtime patch at
`dot_local/share/pi-patches/standing-reminder-origin/` carries each submission
source on the exact user-message object and exposes it
as `message_start.source`. This extension admits only `interactive` and `rpc`,
ignores known `extension` messages, and never pairs events by submitted text.
The isolated real-Pi journey also checks a mixed-origin `steeringMode=all`
batch: both queued operator messages must receive one reminder in the same
provider request, while the extension-origin steering message receives none.
If the patch is absent or the origin is missing or unknown, it warns and omits
the reminder. The patch preserves provenance through prompt expansion and
queued steering; run the isolated Pi proof again after Pi upgrades. Chezmoi's
Pi-patch onchange applies the bridge alongside this extension on desktop
profiles.

## Validation

From the chezmoi source root, run the focused tests and the isolated real-Pi
journey. It stages and patches a private copy of the installed Pi package,
then drives the terminal UI with a scripted provider and editor. It makes no
live model request and does not edit installed Pi. The journey checks editor
save/rollback during streaming, queued input origin, continuation and
compaction boundaries, session copy/resume, and failed-state warnings.

```sh
node --test dot_pi/private_agent/extensions/standing-reminder/index.test.ts
python3 tests/standing-reminder/isolated_pi.py -- python3 tests/standing-reminder/proof.py
chezmoi --source "$PWD" apply --dry-run --verbose --force
```

The source-only proof guide at `tests/standing-reminder/README.md` gives the
full check list. The separate live cache proof uses `openai-codex/gpt-6-sol`
and may spend up to $5; run it only with owner approval. That proof checks
cache-read counters on an isolated patched Pi copy. The command and budget
are in the proof guide.

## Troubleshooting

- A warning about unknown message origin means the installed Pi origin patch
  is missing or no longer matches Pi. Review the patch under
  `dot_local/share/pi-patches/standing-reminder-origin/`. The isolated journey
  validates a private copy; it does not repair installed Pi. After source
  anchors and the version-pinned proof pass for the installed Pi version, an
  owner-approved full `chezmoi apply` runs the version-sensitive patch onchange
  script. A separate worktree needs the patch-root choice from repo-root
  `AGENTS.md`. The request proceeds without a reminder until repaired.
- A missing or unreadable marked sidecar leaves the reminder unavailable.
  Run `/reminder` to save a new value; Pi does not send stale text.
- A canceled or unsuccessful editor leaves the previous reminder active. Check
  the configured editor command before reopening `/reminder`.
