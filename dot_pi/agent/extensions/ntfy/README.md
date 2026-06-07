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
- Title: `pi ready: <session name | short id>`.
- Body: `zellij:<name> · <cwd> · <excerpt>` (zellij segment omitted when not under zellij).
- Excerpt: last assistant response text only (reasoning/thinking excluded), truncated.
- Skips non-interactive sessions (via `ctx.hasUI`); failures are swallowed.
- Honors the on/off toggle (`/ntfy` command / `enabled` config); no delivery while off.

## Tests

```bash
node --test dot_pi/agent/extensions/ntfy/index.test.ts
```
