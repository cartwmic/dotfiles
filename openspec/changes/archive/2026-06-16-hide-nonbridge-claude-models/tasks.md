## 1. Author the runtime patch

- [x] 1.1 Create `dot_local/share/pi-patches/hide-nonbridge-claude-models/patch.mjs` modeled on
      the `anthropic-idle-watchdog` patch (marker, `PATCH_REVISION`, backup, `node --check`,
      atomic replace, idempotency, stale-revision restore, `--check` mode).
- [x] 1.2 Target `@earendil-works/pi-coding-agent/dist/core/model-registry.js`; locate via
      `createRequire` resolve with an npm-global-root fallback.
- [x] 1.3 Single anchor on the `getAvailable()` body; replace the filter with
      `hasConfiguredAuth(m) && !(/claude/i.test(m.id) && m.provider !== "claude-bridge")`.
- [x] 1.4 Add the profile gate: read `process.env.PI_CHEZMOI_PROFILE`; when not `personal`,
      skip applying and, if the marker is present, restore from backup (un-patch); honor `--check`.
- [x] 1.5 Write `dot_local/share/pi-patches/hide-nonbridge-claude-models/README.md` (rationale,
      target, gating, failure modes, removal).

## 2. Wire profile gating into the apply trigger

- [x] 2.1 In `run_onchange_apply_pi_patches.sh.tmpl`, export `PI_CHEZMOI_PROFILE="{{ .profile }}"`
      before `exec`-ing the apply script.
- [x] 2.2 Add a hash-trigger comment line for the new `patch.mjs` so chezmoi re-applies on change.

## 3. Apply and verify (smoke tests)

- [x] 3.1 Run the apply loop with `PI_CHEZMOI_PROFILE=personal` to patch the installed pi; confirm success.
- [x] 3.2 Smoke test: `pi --list-models` shows zero non-`claude-bridge` Claude rows (no `anthropic` provider rows).
- [x] 3.3 Smoke test: all 5 `claude-bridge` Claude rows still present; representative non-Claude rows
      (`openai-codex/gpt-5.4`, `deepseek/*`) still present.
- [x] 3.4 Confirm `~/.pi/agent/auth.json .anthropic` is intact (auth preserved).
- [x] 3.5 Gate tests: `PI_CHEZMOI_PROFILE=axon-work-computer` un-patches (marker gone, file restored);
      re-apply with `personal` re-patches; `patch.mjs --check` exits 0 when patched.

## 4. Finalize

- [x] 4.1 Archive the change via openspec.
- [x] 4.2 Sync via `chezmoi apply` (deploy patch files, regenerate run_onchange hashes); confirm no drift.
- [x] 4.3 Commit and push the runtime patch and supporting changes.
