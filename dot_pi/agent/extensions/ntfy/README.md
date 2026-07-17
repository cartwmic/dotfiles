# ntfy notify (pi extension)

Pushes an [ntfy](https://ntfy.sh) notification on every `agent_end` so you know
when a remote pi session is awaiting input — and which session.

Topology: `phone → Termux → SSH → remote PC → zellij → pi`. The extension runs
on the remote PC (where pi runs) and pushes to a self-hosted ntfy server; the
phone receives it via the ntfy app, decoupled from SSH/zellij liveness.

## Prerequisites

- ntfy server reachable at the `url` in `config.json`
  (`https://ntfy.internal.cartwmic.com/pi` — internal-only host, not a secret).
- ntfy Android app installed and subscribed to topic `pi` on that server.

## Config (`config.json`)

```json
{ "url": "https://ntfy.internal.cartwmic.com/pi", "maxExcerptChars": 200 }
```

- `url` — full ntfy publish URL (base + topic). Empty/missing → extension no-ops.
- `maxExcerptChars` — max length of the assistant-message excerpt in the body.
- `enabled` — default on/off (default `true`). Set `false` to ship disabled.

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

- Notifies on every `agent_end` (the awaiting-input boundary), not per internal turn.
- Title: `<zellij session> / <zellij tab> / <pi session name>`.
  - **zellij session** = `ZELLIJ_SESSION_NAME`; omitted when not under zellij.
  - **zellij tab** resolved via `zellij action dump-layout`, matching this
    session's `cwd` to its enclosing tab (focus-independent); omitted when not
    under zellij or no match. Costs one subprocess per turn (1.5s timeout).
  - **pi session name** = `getSessionName()`, falling back to a short session
    id; always present. Name sessions with `pi -n <name>` for readable titles.
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
