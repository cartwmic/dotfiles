# Standing-reminder input origin bridge

Pi 0.99.2 exposes `input.source` before a message is processed, but the later
`message_start` event does not identify where its user message came from. Text
matching cannot safely bridge those events: operator and extension messages
may have identical text, operator input may be expanded by a prompt template,
and an input hook may cancel one message before a same-text neighbor runs.

This patch carries the origin on the **exact user-message object**. A private
`WeakMap` associates the object created for the initial prompt or queued
steering/follow-up message with `interactive`, `rpc`, or `extension`. At
`message_start`, the extension event exposes that origin as optional
`event.source`. The message, its content, and the saved transcript are not
modified. Messages without a captured input origin have no source; extensions
must fail closed rather than infer one.

## Targets and coexistence

The patch updates all three surfaces needed by the installed CLI and TypeScript
extensions:

- `dist/core/agent-session.js` — unbundled runtime implementation
- The discovered `dist/bundle/chunks/*.js` containing Pi's input queue — CLI
  runtime actually loaded by the executable
- `dist/core/extensions/types.d.ts` — `MessageStartEvent.source?: InputSource`

Revision 2 ports the core prompt indentation and bundled declaration anchors
to Pi 0.99.1; the same exact anchors are verified on the supported Pi 0.99.2 pin.
The private stager normalizes an already-patched copy before recording its
sibling-only fingerprint and compares installed fingerprints before/after.
It does not normalize installed files. A previous revision is not migrated by restoring shared backups;
reinstall the current Pi version and reapply all patches when a stale revision
is present.

Every literal anchor must occur exactly once, and every patched block must be
present as a complete set. A changed, duplicate, or partially applied anchor
fails without guessing. Reapplication is a no-op. `--check` only verifies the
desired state for the current profile and does not write files.

This patch deliberately does **not** save and later restore whole-file backups.
The bundle is shared with patches such as `headless-extension-drain`; disabling
this patch reverses only its own exact blocks, preserving sibling changes.

## Profile gate

`personal` and `axon-work-computer` apply the bridge. `termux`, an unset
profile, and any unknown profile leave it unpatched. When switching from a
desktop profile to a non-desktop profile, the apply loop removes only this
patch's blocks. No Pi `dist/` file is edited in the chezmoi source worktree.

The normal apply loop supplies `PI_CHEZMOI_PROFILE`. Manual use must set it as
well:

```sh
PI_CHEZMOI_PROFILE=personal node dot_local/share/pi-patches/standing-reminder-origin/patch.mjs
PI_CHEZMOI_PROFILE=personal node dot_local/share/pi-patches/standing-reminder-origin/patch.mjs --check
PI_CHEZMOI_PROFILE=axon-work-computer node dot_local/share/pi-patches/standing-reminder-origin/patch.mjs --check
PI_CHEZMOI_PROFILE=termux node dot_local/share/pi-patches/standing-reminder-origin/patch.mjs --check
```

A staging tool can set `PI_STANDING_REMINDER_ORIGIN_PACKAGE` to a copied
`@earendil-works/pi-coding-agent` package. That target override suppresses the
installed-package state receipt and is intended for isolated validation only.

## Black-box validation

From the chezmoi source root, stage an isolated package copy and run the real-Pi
journey through it:

```sh
python3 tests/standing-reminder/isolated_pi.py -- \
  python3 tests/standing-reminder/feasibility.py
```

The runner patches and checks the staged package, exercises reapplication and
both desktop profiles, verifies the Termux skip and sibling-patch preservation,
then sets `PI_BIN` for the child scenario. It never applies this patch to the
installed Pi package. The focused boundary scenario uses a local scripted
provider and PTY; no live provider or cache calls are made. The complete
standing-reminder journey is documented in
[`tests/standing-reminder/README.md`](../../../../tests/standing-reminder/README.md).
It checks same-text cross-origin messages, a canceled queue neighbor, expanded
operator input, the mixed-origin `steeringMode=all` batch, and unchanged saved
user text. The real TUI journey proves that a successful editor save and its
next-request cue appear while a response is still active, before queued steering
is processed; the in-flight request keeps its old snapshot and the queued model
request receives only the new reminder. It also requires full editor catch-up,
keeps an intermediate draft inactive until successful close, and proves that a
failed editor's old value reaches the next model request. Resume checks include
removing the sidecar from a marked session and requiring a clear warning,
completed request, and no stale delivery in TUI, print, JSON, and RPC.
The journey also drives threshold compaction within operator work. It requires
an ordinary post-compaction continuation, tolerates repeated summaries,
asserts no reminder on any same-work summary or continuation, then verifies
the next operator receives the current value. The selective proof additionally drives the installed question package's real
multi-tab UI and explicitly loads builtin codemode. See the proof README for
focused and full commands. The separate live-cache driver is a separate owner
duty; scripted traffic does not establish real cache reuse.
