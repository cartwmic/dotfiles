# ntfy notify (pi extension)

Pushes an [ntfy](https://ntfy.sh) notification on terminal `agent_settled`
boundaries so you know when a remote pi session is truly awaiting input — and
which session. Aborted runs (user ESC / "Operation aborted") and resumed
auto-compaction abort boundaries are excluded.

Topology: `phone → Termux → SSH → remote PC → Herdr or Zellij → pi`. The
extension runs on the remote PC and pushes to a self-hosted ntfy server; the
phone receives it independently of SSH or multiplexer liveness. Tapping routes
to the correct Herdr agent or Zellij pane.

## Prerequisites

- ntfy server reachable at the `url` in `config.json`
  (`https://ntfy.internal.cartwmic.com/pi` — internal-only host, not a secret).
- ntfy Android app installed and subscribed to topic `pi` on that server.

## Config (`config.json`)

Per-machine identity is `jumpSshHost` in chezmoi data (this host's Termux SSH
alias: `remote`, `cartwmic-server`, `macbook`, or `laptop`). The rendered
`config.json` includes it when set. The zellij notify wrapper uses the same
alias via `JUMP_SSH_HOST`.

```json
{
  "url": "https://ntfy.internal.cartwmic.com/pi",
  "maxExcerptChars": 200,
  "enabled": true,
  "herdrJumpDeepLinkBase": "termux://herdr-jump",
  "jumpSshHost": "macbook"
}
```

- `url` — full ntfy publish URL (base + topic). Empty/missing → extension no-ops.
- `maxExcerptChars` — max length of the assistant-message excerpt in the body.
- `enabled` — default on/off (default `true`). Set `false` to ship disabled.
- `jumpDeepLinkBase` — optional Zellij route; defaults to
  `termux://zellij-jump`.
- `herdrJumpDeepLinkBase` — optional Herdr route; defaults to
  `termux://herdr-jump`.
- `jumpSshHost` — Termux SSH alias of **this** pi host. Grammar:
  `^[A-Za-z][A-Za-z0-9_-]{0,63}$`. A valid alias is the Click `?host=` value and
  the title's first segment. Unset or invalid omits the host query (phone jump
  scripts keep the default `remote` SSH path) and still titles as `remote`.
  Set it in `~/.config/chezmoi/chezmoi.yaml` as `data.jumpSshHost`.

## Apply scope

`chezmoi apply` on a pi host only renders this extension, including `jumpSshHost`
from that machine's `~/.config/chezmoi/chezmoi.yaml`. It does not:

- install or update the Termux APK (separate `termux-app` repo; `?host=` session
  focus requires that build)
- name Termux sessions (the visible session must match the alias exactly for focus)
- update phone jump scripts or SSH ControlMaster (`bin/**` is ignored on the
  personal profile — apply on the phone; see `termux/README.md`)
- export `JUMP_SSH_HOST` for the zellij notify wrapper; set that in the remote
  environment if you use Zellij notify

## Toggle on/off

Use the `/ntfy` command at runtime:

```
/ntfy            # show current state (on/off)
/ntfy status     # same as above
/ntfy on         # enable
/ntfy off        # disable
/ntfy toggle     # flip
```

The runtime choice is persisted to a sidecar `state.json` (next to `index.ts`,
NOT chezmoi-managed) that overrides the `enabled` config default, so live
toggling survives restarts without drifting the chezmoi source. To reset to the
config default, delete `state.json`.

## Behavior

- Notifies on `agent_settled`, after retries, compaction, and queued continuations
  are exhausted. `agent_end` only captures the final assistant text.
- Suppresses the internal aborted settlement when `auto-compact` announces that
  it will resume the interrupted run. User/operation aborts (`stopReason`
  `aborted`, shown in the TUI as "Operation aborted") also do not notify.
- Title: `<host> / <workspace/session> / <tab> / <pi session name>`.
  - **host:** `jumpSshHost` / `JUMP_SSH_HOST` when grammar-valid, otherwise `remote`.
  - **Herdr:** `herdr pane current` supplies canonical current ids and stable
    `terminal_id`; `herdr workspace get` and `herdr tab get` supply labels.
    Labels fall back to ids if lookup fails. Herdr takes precedence when both
    Herdr and Zellij environment variables exist.
  - **Zellij:** session comes from `ZELLIJ_SESSION_NAME`; tab comes from
    `zellij action dump-layout`, cwd-matched and focus-independent.
  - **pi session name:** `getSessionName()`, falling back to short session id.
- Herdr Click URLs carry `terminal_id`, not movable `pane_id`. Phone and remote
  helpers resolve that stable terminal to its current pane at tap time, then run
  `herdr agent focus <pane-id>`. Failed Herdr resolution produces no Click rather
  than accidentally targeting nested Zellij.
- Body: the **excerpt** only (last assistant response text, truncated).
- Excerpt: last assistant response text only (reasoning/thinking excluded), truncated.
- Publishes title, body, priority, tags, and click target through ntfy's UTF-8
  JSON API. Unicode session/tab names therefore remain valid.
- Skips non-interactive sessions (via `ctx.hasUI`).
- Honors the on/off toggle (`/ntfy` command / `enabled` config); no delivery while off.
- Delivery remains fire-and-forget with a 5-second timeout. Failures do not
  block turns; each failure produces a TUI warning and a `send.log` entry.
- Failure diagnostics include request phase, elapsed milliseconds, error
  name/code, and nested transport cause name/code. URLs, credentials, titles,
  and message bodies are excluded.
- `/ntfy status` shows current-session success/failure counts and latest outcomes.
- `send.log` lives beside `index.ts`, rotates to `send.log.old` at 200 KiB,
  and can be watched with `tail -f ~/.pi/agent/extensions/ntfy/send.log`.

## Tests

```bash
node --test dot_pi/agent/extensions/ntfy/index.test.ts
```
