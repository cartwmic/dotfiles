## Context

pi (installed as `@earendil-works/pi-coding-agent` under the mise node) decides model
availability in `dist/core/model-registry.js`:

```js
getAvailable() {
    return this.models.filter((m) => this.hasConfiguredAuth(m));
}
```

`hasConfiguredAuth(m)` is true when `authStorage.hasAuth(provider)` or a provider apiKey is
configured. Both the interactive model picker (`model-selector.js`) and `cli/list-models.js`
(`pi --list-models`) call `getAvailable()`, so it is the single chokepoint for "which models
can I pick". `settings.json.enabledModels` only *scopes* (the Ctrl+P cycle); it does not hide
unscoped models from the picker.

On the `personal` profile, `auth.json` carries auth for `anthropic`, `openrouter`, and
`openai-codex`. That makes 25 `anthropic` Claude models and all `openrouter` `anthropic/claude-*`
models pickable. The `anthropic` token is injected by the `com.cartwmic.sync-claude-pi-auth`
launchd agent specifically so the native Anthropic `web_search`/`web_fetch` tools and the
pi-sub-bar widget have a fresh token — so we cannot remove it. `claude-bridge` registers its own
provider with `apiKey: "not-used"` and infers via the `claude` CLI, independent of `anthropic` auth.

The repo already ships a runtime-patch framework: `dot_local/user_scripts/executable_apply_pi_patches.sh`
iterates `dot_local/share/pi-patches/*/patch.mjs` (read from the chezmoi source dir) and runs each
under node; `run_onchange_apply_pi_patches.sh.tmpl` is the chezmoi trigger that re-runs the loop when
a patch's hash or the installed pi version changes. The existing `anthropic-idle-watchdog/patch.mjs`
establishes the conventions we reuse.

## Goals / Non-Goals

**Goals:**
- Hide every non-`claude-bridge` Claude model from `getAvailable()` (picker + `pi --list-models`)
  on the `personal` profile, with zero change to provider auth.
- Reuse the existing patch framework's safety properties: idempotency, backup, `node --check`,
  atomic replace, stale-revision restore, `--check` mode.
- Gate strictly on profile: apply only when the chezmoi profile is `personal`; on any other
  profile, do nothing — and if the patch was previously applied, restore the original file.

**Non-Goals:**
- No change to `auth.json`, the sync agent, web tools, pi-sub-bar, or `enabledModels`.
- No hiding of non-Claude models (openrouter non-Claude, openai-codex, deepseek stay visible).
- Not fixing the pre-existing `anthropic-idle-watchdog` patch (it targets the now-absent
  `@mariozechner/pi-ai` and currently no-ops; out of scope).
- No upstream pi feature work.

## Decisions

**D1 — Patch `getAvailable()` rather than drop auth.** Filtering the returned list keeps
`hasConfiguredAuth` (and thus the anthropic token for web tools / sub-bar) intact. Alternative
(remove `anthropic`/`openrouter` auth) breaks web tools and all openrouter models — rejected.

**D2 — Define "Claude model" as `/claude/i.test(m.id)`.** Every anthropic id (`claude-opus-4-8`,
`claude-fable-5`), every openrouter Claude id (`anthropic/claude-*`, `~anthropic/claude-*`), and
bedrock (`*.anthropic.claude-*`) contains `claude`; no non-Claude model does. The filter is
`hasConfiguredAuth(m) && !(/claude/i.test(m.id) && m.provider !== "claude-bridge")`. Matching by id
is more robust than enumerating provider names (covers future Claude-serving providers automatically).

**D3 — Profile gating via env var injected by the templated wrapper.** Patches run from the chezmoi
*source* dir and have no chezmoi template context at runtime, so the gate can't live as a `.tmpl`
inside `patch.mjs`. Instead `run_onchange_apply_pi_patches.sh.tmpl` exports
`PI_CHEZMOI_PROFILE="{{ .profile }}"` before `exec`-ing the apply script. This new patch reads
`process.env.PI_CHEZMOI_PROFILE`; the existing patch ignores it. Alternatives considered:
making `patch.mjs` a `.tmpl` (breaks the source-execution glob `*/patch.mjs`), or shelling out to
`chezmoi data` from the patch (couples the patch to a chezmoi binary on PATH) — both rejected.

**D4 — Fail-safe default = do not apply.** When `PI_CHEZMOI_PROFILE` is unset (e.g. a manual
`apply_pi_patches.sh` run) or any value other than `personal`, the patch treats it as "not personal":
skip applying, and if our marker is present, restore from the backup so the install is returned to
stock. This makes the gate correct under profile switches and safe when run standalone.

## Risks / Trade-offs

- **Upstream changes the `getAvailable()` shape** → the single-occurrence anchor check fails loudly and
  the patch aborts without touching the file; bump `PATCH_REVISION` and update the anchor. Same contract
  as the existing patch.
- **`/claude/i` false positive** (a non-Claude model with "claude" in its id) → it would be hidden.
  None exist today; risk is theoretical. Mitigation: the `m.provider !== "claude-bridge"` guard and an
  id-substring that is effectively Anthropic-only.
- **Reinstalling/upgrading pi reverts the patch** → the existing run_onchange trigger keys on the
  installed pi version, so `chezmoi apply` re-applies after upgrades. Same as today.
- **Profile var not threaded on a manual run** → by D4 this is safe (no-op/un-patch), never a wrong apply.

## Migration Plan

1. Add the new patch dir + README; modify the wrapper template (export var, add hash line).
2. `apply` step: run the apply loop with `PI_CHEZMOI_PROFILE=personal` to patch the installed pi.
3. `verify`: `pi --list-models` shows zero non-bridge Claude rows, all 5 `claude-bridge` rows, and
   intact non-Claude rows; `patch.mjs --check` exits 0; `auth.json .anthropic` still present.
4. Rollback: `patch.mjs` restores from `<target>.orig.chezmoi-pi-patch`; or run the loop with a
   non-personal `PI_CHEZMOI_PROFILE` to un-patch; or reinstall pi.

## Open Questions

None.
