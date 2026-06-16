## Why

On the `personal` chezmoi profile, pi's model picker and `pi --list-models` expose
~25 `anthropic` Claude models plus all `openrouter` `anthropic/claude-*` entries, even
though the only Claude path we want to use is `claude-bridge` (which routes through the
`claude` CLI subscription). pi has no per-model or per-provider disable setting:
availability is decided solely by `ModelRegistry.getAvailable()`, which returns every
model whose provider has configured auth. We cannot simply drop `anthropic` auth — that
token is load-bearing for the native Anthropic `web_search`/`web_fetch` tools and the
pi-sub-bar token widget (it is injected by the `com.cartwmic.sync-claude-pi-auth` launchd
agent). The only collateral-free fix is a runtime patch that keeps the auth but hides the
non-bridge Claude models from the available-models list.

## What Changes

- Add a new chezmoi-managed runtime patch `pi-patches/hide-nonbridge-claude-models/patch.mjs`
  that rewrites `getAvailable()` in `@earendil-works/pi-coding-agent/dist/core/model-registry.js`
  to additionally exclude any model whose id matches `/claude/i` when its provider is not
  `claude-bridge`. Auth (`hasConfiguredAuth`) is untouched, so web tools and the sub-bar keep working.
- The patch follows the existing `anthropic-idle-watchdog` patch conventions: marker comment,
  `PATCH_REVISION`, backup-before-edit, `node --check` validation, atomic replace, idempotent
  re-runs, stale-revision restore, and a `--check` mode.
- **Profile gating:** the patch only applies on the `personal` profile. The templated
  `run_onchange_apply_pi_patches.sh.tmpl` wrapper exports `PI_CHEZMOI_PROFILE={{ .profile }}`
  before running the apply loop; this patch self-skips (and, if previously applied, restores
  the backup to un-patch) whenever `PI_CHEZMOI_PROFILE` is not `personal`. The pre-existing
  `anthropic-idle-watchdog` patch ignores the variable and continues to run on all profiles.
- Update the run_onchange hash-trigger comments to include the new patch so chezmoi re-applies
  when it changes.

## Capabilities

### New Capabilities
- `pi-model-visibility`: Controls which Claude-family models pi surfaces as available
  (picker + `pi --list-models`) on a given chezmoi profile, without altering provider auth.

### Modified Capabilities
<!-- None. No existing openspec capability covers pi model visibility or the patch infra. -->

## Impact

- **New files:** `dot_local/share/pi-patches/hide-nonbridge-claude-models/patch.mjs`,
  `dot_local/share/pi-patches/hide-nonbridge-claude-models/README.md`.
- **Modified files:** `run_onchange_apply_pi_patches.sh.tmpl` (export `PI_CHEZMOI_PROFILE`,
  add new patch hash-trigger line).
- **Runtime target:** `@earendil-works/pi-coding-agent/dist/core/model-registry.js` (`getAvailable()`),
  re-applied by `apply_pi_patches.sh`.
- **Unaffected:** `~/.pi/agent/auth.json` (anthropic token preserved), `web_search`/`web_fetch`
  tools, pi-sub-bar, `claude-bridge` models, non-Claude providers (openai-codex, deepseek, and
  openrouter's non-Claude models), and the work (`axon-work-computer`) profile.
