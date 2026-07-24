# openrouter-gate

Pi extension: OpenRouter provider **default-OFF**, with an in-session opt-in
toggle. Keeps OpenRouter out of every pi session and subagent unless explicitly
enabled — without breaking Hindsight recall (its OpenRouter key lives
server-side on hindsight-api, not in pi's auth.json).

## Why this shape

Pi gates model availability strictly at the **auth layer**: a provider is
configured iff `~/.pi/agent/auth.json` has a matching entry or the provider's
env API key (`OPENROUTER_API_KEY`) is set. There is no per-provider disable
switch, extensions cannot unregister builtin providers
(`unregisterProvider` only clears extension-registered ones), and availability
filtering alone would leave `--model openrouter/x` working (model resolution
bypasses availability). Missing auth blocks the actual API call — airtight.

## Setup (one-time)

Rename the live entry in `~/.pi/agent/auth.json`:

```diff
- "openrouter":         { "type": "api_key", "key": "sk-or-v1-..." }
+ "openrouter-stashed": { "type": "api_key", "key": "sk-or-v1-..." }
```

`openrouter-stashed` matches no provider id → registry blind to it → provider
unconfigured everywhere by default. Key bytes stay in the same 600-perm file.

## Usage

| Command | Effect |
|---|---|
| `/openrouter on` | Read stash → `setRuntimeApiKey("openrouter", key)` (in-memory overlay, same primitive as pi's `--api-key` flag; never persisted) + set `OPENROUTER_API_KEY` in `process.env` so subagent children inherit access. Models appear immediately. |
| `/openrouter off` | `removeRuntimeApiKey` + unset env var. |
| `/openrouter status` | Gate state + stash health. |

Session exit discards the overlay and env — every new session starts locked.

## Known weak point

If pi ever rewrites auth.json wholesale (login/logout flows), the unknown
`openrouter-stashed` key could be **silently dropped** — the stashed API key
would be lost. Mitigations:

- `/openrouter on` and `/openrouter status` warn loudly when the stash is missing.
- `session_start` warns if a *live* `openrouter` entry reappears (gate bypassed,
  e.g. after `/login openrouter`).
- Fallback if this ever bites: move the key to a sibling 600-perm file
  (`~/.pi/agent/openrouter.key`) and point `readStash` at it.

## Internals caveat

Reaches `ctx.modelRegistry.runtime` — a public field on the extension-facing
facade but not part of the documented surface. Shape is validated at call time;
if a pi upgrade removes it, `/openrouter on` reports it instead of throwing.

## Tests

```sh
node --test dot_pi/agent/extensions/openrouter-gate/index.test.ts
```
