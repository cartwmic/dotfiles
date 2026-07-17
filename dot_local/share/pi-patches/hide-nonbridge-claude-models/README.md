# pi-patch: hide-nonbridge-claude-models

Hides every non-`claude-bridge` Claude model from pi's model picker and
`pi --list-models`, **on the chezmoi `personal` profile only**, without
removing any provider auth.

## Why

pi has no per-model or per-provider "disable" setting. `enabledModels` in
settings.json only scopes sessions and preselects the picker checkboxes — it
does **not** filter `pi --list-models` or the available-models list. A model is
available iff its provider has configured auth. Both the interactive model
picker and `cli/list-models.js` (`pi --list-models`) read the runtime's
available list.

On the `personal` profile, `~/.pi/agent/auth.json` carries auth for `anthropic`
and `openrouter`, which makes ~25 `anthropic` Claude models and all `openrouter`
`anthropic/claude-*` models pickable — even though the only Claude path we use
is `claude-bridge`. We cannot just drop `anthropic` auth: that token is injected
by the `com.cartwmic.sync-claude-pi-auth` launchd agent because the native
Anthropic `web_search`/`web_fetch` tools and the pi-sub-bar token widget read it.
`claude-bridge` is independent (`pi.registerProvider("claude-bridge", { apiKey: "not-used" })`,
infers via the `claude` CLI), so it is unaffected.

This patch keeps `hasConfiguredAuth` intact (auth preserved) and only filters the
returned list.

## What it changes

Target: `@earendil-works/pi-coding-agent/dist/core/model-runtime.js`
(revision 2; up to 0.80.6 the target was `model-registry.js#getAvailable()`,
which 0.80.10 refactored into a facade over `ModelRuntime`).

Three edits, all applying the same exclusion
`!(/claude/i.test(model.id) && model.provider !== "claude-bridge")`:

1. `updateModelSnapshot()` — `snapshot.available` built from configured
   providers.
2. `runAvailabilityRefresh()` — `snapshot.available` rebuilt from
   `models.getAvailable()`.
3. `getAvailable(providerId)` — the provider-specific path that bypasses the
   snapshot when no refresh is in flight.

`ModelRegistry.getAvailable()`/`getAvailableSnapshot()` both read
`snapshot.available`, so the facade is covered transitively.

"Claude model" = model id matches `/claude/i`. That covers `anthropic`
(`claude-opus-4-8`, `claude-fable-5`), `openrouter` (`anthropic/claude-*`,
`~anthropic/claude-*`), and bedrock (`*.anthropic.claude-*`); `claude-bridge`
ids also contain `claude` but are exempted by the `provider !== "claude-bridge"`
guard. No non-Claude model id contains `claude`.

## Profile gate

This patch applies **only** when `PI_CHEZMOI_PROFILE=personal`. That variable is
exported by the templated wrapper `run_onchange_apply_pi_patches.sh.tmpl`
(`export PI_CHEZMOI_PROFILE="{{ .profile }}"`) before it runs the apply loop.

- `PI_CHEZMOI_PROFILE=personal` → apply.
- Any other value, or unset (e.g. a manual `apply_pi_patches.sh` run) → do not
  apply; and if a previous run applied this patch, restore the original file from
  `<target>.orig.chezmoi-pi-patch` (un-patch). Fail-safe default is "do not apply".

The sibling `anthropic-idle-watchdog` patch ignores `PI_CHEZMOI_PROFILE` and
continues to run on all profiles.

## Safety properties

Mirrors the `anthropic-idle-watchdog` patch: marker comment + `PATCH_REVISION`,
single-occurrence anchor pre-check (aborts on drift without touching the file),
backup before first edit, `node --check` validation, atomic `mv` replace,
idempotent re-runs, stale-revision restore, and a `--check` mode.

State is written to `~/.local/state/chezmoi-pi-patches/hide-nonbridge-claude-models.json`.

## Scope / limitations

- Affects the **available-models list** (picker + `pi --list-models`). It does
  **not** block `--model anthropic/...` on the CLI or a previously-saved default,
  which resolve through `getAll()`/`find()`. The goal is to declutter the list,
  not to hard-enforce bridge-only usage.
- Does not modify `auth.json`, the sync agent, web tools, pi-sub-bar, or
  `enabledModels`.

## Verify

```sh
PI_CHEZMOI_PROFILE=personal node patch.mjs           # apply
PI_CHEZMOI_PROFILE=personal node patch.mjs --check    # exit 0 when patched
pi --list-models | awk 'NR>1 && $1!="claude-bridge" && tolower($2) ~ /claude/'  # must be empty
pi --list-models | awk '$1=="claude-bridge"'          # 5 rows
jq '.anthropic | {has_access:(.access!=null),type}' ~/.pi/agent/auth.json  # auth intact
```

## Removal

Delete this directory and re-run `apply_pi_patches.sh` with a non-`personal`
`PI_CHEZMOI_PROFILE` (un-patches), or reinstall pi-coding-agent. If upstream pi
adds a native model-hide setting, delete this patch and use that instead.
