# pi-ai patch: anthropic-idle-watchdog

A chezmoi-managed runtime patch for `@mariozechner/pi-ai`'s native Anthropic
provider. Wraps the SSE response-body reader in an idle watchdog, and forwards
Anthropic's keep-alive `ping` events through pi-ai's event stream.

## Why this exists

Diagnosed 2026-04-30 against pi-coding-agent 0.71.1 + pi-ai 0.71.1. See:

- Upstream issue: <https://github.com/badlogic/pi-mono/issues/3020>
  ("feat: add stream idle timeout watchdog for streaming providers")
- Filed 2026-04-10 by `@weihao-m`. **Closed but never merged into the
  `anthropic-messages` provider** — the codex provider got a similar idle
  pattern, but `providers/anthropic.js` still has an unbounded `await
  reader.read()` with no per-chunk timeout.

### Symptoms (without this patch)

In the pi-coding-agent TUI, mid-turn the spinner says "working…" indefinitely
(60s–several minutes) with zero new content rendered. Manual interrupt + sending
"continue" reliably unsticks it. Most common on long-thinking turns against
Claude Opus 4.7 (1M context, adaptive thinking, xhigh effort).

### Root cause

`pi-ai/dist/providers/anthropic.js`:

- `iterateSseMessages` awaits `reader.read()` with no `Promise.race`,
  no `setTimeout`, no `AbortSignal.timeout`. If TCP stays open but no bytes
  arrive (proxy buffering, server stall, transient blackhole), the read
  parks forever.
- The `@anthropic-ai/sdk` `timeout` (default 10 min) is cleared in `finally`
  the moment fetch headers arrive — it does not cover mid-stream silence.
- Anthropic emits `event: ping` every ~15s but `ANTHROPIC_MESSAGE_EVENTS`
  filters them out, so even on a healthy slow turn the spinner sees no
  progress signal.

## What the patch does

Three surgical edits to `pi-ai/dist/providers/anthropic.js`:

1. **Add `"ping"` to `ANTHROPIC_MESSAGE_EVENTS`** so iterateAnthropicEvents
   yields ping events instead of dropping them.
2. **Wrap `reader.read()` in `Promise.race` against a 90s idle timer** in
   `iterateSseMessages`. On timeout the reader is cancelled and an error
   bubbles up; the existing `streamAnthropic` catch + pi-coding-agent's
   retry layer in `agent-session.js` then auto-retry — same effect as the
   manual interrupt + "continue" workaround, but automatic.
3. **Forward ping events** as `{ type: "ping", partial: output }` from
   `streamAnthropic` so future TUI changes can render "still streaming…"
   on long thinking turns. Existing consumers ignore the new event type
   safely (no exhaustive switches; `AssistantMessageEventStream` only
   completes on `done`/`error`).

Idle timeout default: **90000ms** (90s, matches issue #3020 recommendation).
Override via env: `PI_STREAM_IDLE_TIMEOUT_MS=120000 pi`.

## How it's deployed

Patch is applied by `~/.local/user_scripts/apply_pi_patches.sh`, triggered by
chezmoi's `run_onchange_apply_pi_patches.sh.tmpl`. The onchange template
embeds:

- sha256 of `patch.mjs`
- sha256 of the apply script
- the currently installed `@mariozechner/pi-coding-agent` version
  (captured via `{{ output "node" "-e" "..." }}`)

So the patch re-applies whenever you (a) bump pi-coding-agent, (b) edit the
patch logic, or (c) edit the apply script. **User-facing rule: after
`npm update -g @mariozechner/pi-coding-agent`, run `chezmoi apply`.**

State (last-applied version, backup path, fingerprint) is recorded at
`~/.local/state/chezmoi-pi-patches/anthropic-idle-watchdog.json`. Backup of
the unpatched file lives next to the target as
`anthropic.js.orig.chezmoi-pi-patch`.

## Failure modes & resolution

### F1. "Anchor not found" — upstream changed the code shape

**Symptom:** `chezmoi apply` exits non-zero with a message like
`anchor 'iterateSseMessages reader.read' not found in <file>` and a context
dump.

**Causes & fixes:**

- **Upstream merged a real fix** for #3020. Verify by reading the new
  `iterateSseMessages` in pi-ai (look for `Promise.race`, `setTimeout`,
  `streamIdleTimeoutMs`). If yes, **delete this patch entirely**:
  ```sh
  rm -rf ~/.local/share/chezmoi/dot_local/share/pi-patches/anthropic-idle-watchdog
  rm  ~/.local/share/chezmoi/dot_local/user_scripts/executable_apply_pi_patches.sh
  rm  ~/.local/share/chezmoi/run_onchange_apply_pi_patches.sh.tmpl
  rm -rf ~/.local/state/chezmoi-pi-patches
  ```
  Then `chezmoi apply` to commit the removal.
- **Upstream just refactored** (whitespace, identifier rename, etc.) without
  fixing the bug. Update the anchor strings in `patch.mjs` to match the new
  code, bump `PATCH_REVISION`, re-run `chezmoi apply`. The diff dump in the
  failure log shows what changed.

### F2. "Marker present but state file missing"

**Symptom:** `chezmoi apply` reports the file already has our patch marker but
no state file matches the install. Common after restoring `~/.local/state`
from a fresh machine.

**Fix:** the script auto-recovers — on this branch it trusts the marker
(file is already patched) and rewrites the state file. No user action needed.

### F3. `node --check` fails after applying

**Symptom:** Apply script restores the backup and exits non-zero with
`syntax error after patch application — restored backup`.

**Cause:** the anchor strings matched but the replacement produced invalid
JS (e.g. brace imbalance from a partial upstream change that we didn't
detect).

**Fix:** treat as an F1. Inspect the file, bump `PATCH_REVISION`, fix the
patch, re-run.

### F4. mise / npm reinstall blew away the patch silently

**Symptom:** stalls return after `npm update -g`. No `chezmoi apply` run since.

**Fix:** `chezmoi apply`. The onchange hash includes the installed version,
so any reinstall (even same version) should still re-trigger the script
because the `.orig.chezmoi-pi-patch` backup is gone. The script's "already
patched" check looks for the marker in the file itself, not the state file
— so a fresh reinstall is detected and the patch is reapplied.

### F5. Patch revision bump (developer scenario)

When editing `patch.mjs`:

1. Bump the `PATCH_REVISION` constant at the top.
2. Update the marker in any anchor strings if you changed them.
3. `chezmoi apply` will detect the stale marker, restore from backup, and
   reapply with the new revision.

### F6. Want to disable temporarily

Run `pi` with the watchdog effectively off:
```sh
PI_STREAM_IDLE_TIMEOUT_MS=0 pi
```
The patch interprets `0` as "disabled" (no timer is set).

To remove the patch entirely, delete the four chezmoi-managed files listed
under F1 and run `chezmoi apply` (it will not auto-restore the upstream file
on removal — manually delete the patched file and run the user's package
manager to reinstall, or just restore from `<file>.orig.chezmoi-pi-patch`).

## Verifying the patch is active

```sh
grep -c 'chezmoi-pi-patch:anthropic-idle-watchdog' \
  "$(node -e "console.log(require.resolve('@mariozechner/pi-ai/dist/providers/anthropic.js'))")"
# Should print: 3
```

```sh
cat ~/.local/state/chezmoi-pi-patches/anthropic-idle-watchdog.json
```
