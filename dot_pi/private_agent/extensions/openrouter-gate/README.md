# openrouter-gate

Pi extension: OpenRouter provider **default-OFF**, with a persistent on/off
toggle and a fail-closed per-model allowlist. Keeps the live OpenRouter catalog
(from pi-openrouter-plus or the builtin provider) down to ids you list in
`config.json` — without breaking Hindsight recall (its OpenRouter key lives
server-side on hindsight-api, not in pi's auth.json).

Do **not** add `openrouter/*` to Pi `enabledModels`. The allowlist lives only
in this extension's machine-local `config.json`.

## Why this shape

Pi gates model availability strictly at the **auth layer**: a provider is
configured iff `~/.pi/agent/auth.json` has a matching entry or the provider's
env API key (`OPENROUTER_API_KEY`) is set. There is no per-provider disable
switch, extensions cannot unregister builtin providers
(`unregisterProvider` only clears extension-registered ones), and availability
filtering alone would leave `--model openrouter/x` working (model resolution
bypasses availability). Missing auth blocks the actual API call.

pi-openrouter-plus then **replaces** the OpenRouter catalog with the full live
list whenever it syncs. This extension re-registers a subset via
`pi.registerProvider("openrouter", { models })` (merge: plus stream/headers
stay). Empty allowlist or `enabled: false` registers zero models.

## Setup (one-time)

In a Pi session, run `/openrouter stash`. That prompts for the API key (or
adopts a live `"openrouter"` entry from `/login openrouter`) and writes
`openrouter-stashed` into `~/.pi/agent/auth.json` at mode 600, removing any
live `openrouter` key so the provider stays default-off. Then `/openrouter on`.

Do not pass the key as a slash-command argument in the TUI — it lands in the
session transcript. Headless/scripts may use `/openrouter stash sk-or-...`.

Hand-edit still works if you prefer:

```diff
- "openrouter":         { "type": "api_key", "key": "sk-or-v1-..." }
+ "openrouter-stashed": { "type": "api_key", "key": "sk-or-v1-..." }
```

`openrouter-stashed` matches no provider id → registry blind to it → provider
unconfigured everywhere by default.

Allowlist is a chezmoi `create_` target. After the first apply, edit
`~/.pi/agent/extensions/openrouter-gate/config.json` (machine-local; later
`chezmoi apply` will not overwrite it):

```json
{
  "enabled": false,
  "allowedModels": ["z-ai/glm-5.3-flash"]
}
```

- `enabled`: persisted by `/openrouter on|off`. Default off.
- `allowedModels`: exact ids or globs (`*`, `?`). Case-insensitive. Plus
  `@or:provider:quant:id` variants match if the base id is allowed.
  Prefer `/openrouter allow` / `/openrouter deny` (searchable picker) over
  hand-editing. `/openrouter reload` still works after a JSON edit.
- Empty `allowedModels` is fail-closed: no models, no runtime key.

## Usage

| Command | Effect |
|---|---|
| `/openrouter on` | Persist `enabled: true`. If the allowlist is non-empty and the stash has a key, inject the runtime credential + `OPENROUTER_API_KEY` (subagent children inherit it) and register only allowlisted models. |
| `/openrouter off` | Persist `enabled: false`, drop the runtime key/env, register zero OpenRouter models. |
| `/openrouter status` | Toggle, allowlist, stash health, config path. |
| `/openrouter reload` | Re-read `config.json` (after a hand-edit) and re-apply. |
| `/openrouter allow` | Searchable overlay of the live OpenRouter catalog (public `/models`, no key). Completions work after `/openrouter allow `. Tab-complete or pick an id; globs (`z-ai/*`) can be typed. Writes `config.json`. |
| `/openrouter deny` | Same overlay, but only the current allowlist. Removing the last entry fail-closes. |
| `/openrouter allow <id>` / `deny <id>` | Skip the picker and edit that entry directly. |
| `/openrouter stash` | Prompt for an API key and write `openrouter-stashed`. If a live `openrouter` entry exists, adopt it and delete the live key. Does not enable the provider. |

New sessions honor the persisted `enabled` flag. Session exit still drops the
in-memory runtime overlay; `session_start` re-injects when enabled.

Plus loads after this extension and re-syncs on `session_start`. The catalog
is re-filtered on `resources_discover`, `before_agent_start`, and
`model_select`. `/openrouter-sync` can briefly re-expand the picker until the
next one of those events.

## Known weak point

If pi ever rewrites auth.json wholesale (login/logout flows), the unknown
`openrouter-stashed` key could be **silently dropped** — the stashed API key
would be lost. Mitigations:

- `/openrouter on` and `/openrouter status` warn loudly when the stash is missing.
- `/openrouter stash` re-writes the stash (and adopts a live `openrouter` entry
  left by `/login openrouter`).
- `session_start` warns if a *live* `openrouter` entry reappears (auth always-on,
  e.g. after `/login openrouter`). The allowlist still applies.
- Fallback if this ever bites: move the key to a sibling 600-perm file
  (`~/.pi/agent/openrouter.key`) and point `readStash` at it.

## Internals caveat

Reaches `ctx.modelRegistry.runtime` — a public field on the extension-facing
facade but not part of the documented surface. Shape is validated at call time;
if a pi upgrade removes it, `/openrouter on` reports it instead of throwing.

## Tests

```sh
cd ~/.local/share/chezmoi/dot_pi/private_agent/extensions/openrouter-gate && node --test
```
