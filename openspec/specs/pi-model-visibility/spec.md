# pi-model-visibility Specification

## Purpose
A personal-profile-only runtime patch that removes non-bridge Claude models from pi's available-model list, enforcing that all Claude traffic on this machine routes through claude-bridge.
## Requirements
### Requirement: Non-bridge Claude models are hidden on the personal profile

On the `personal` chezmoi profile, pi SHALL NOT surface any Claude-family model
(`/claude/i` match on the model id) as available unless its provider is `claude-bridge`.
Availability is the set returned by `ModelRegistry.getAvailable()`, which backs both the
interactive model picker and `pi --list-models`.

#### Scenario: list-models omits anthropic Claude models
- **WHEN** the patch is applied and the user runs `pi --list-models`
- **THEN** no row whose provider is `anthropic` appears in the output
- **AND** no row from any provider other than `claude-bridge` whose model id contains `claude` appears

#### Scenario: claude-bridge models remain available
- **WHEN** the patch is applied and the user runs `pi --list-models`
- **THEN** every `claude-bridge` Claude model (e.g. `claude-opus-4-8`, `claude-sonnet-4-6`) still appears

#### Scenario: non-Claude models remain available
- **WHEN** the patch is applied and the user runs `pi --list-models`
- **THEN** non-Claude models from other authed providers (e.g. `openai-codex/gpt-5.4`, `deepseek/*`,
  and `openrouter` non-Claude models) still appear

### Requirement: Provider auth is preserved

The change SHALL NOT modify provider authentication. The `anthropic` token in
`~/.pi/agent/auth.json` MUST remain intact so the native Anthropic `web_search`/`web_fetch`
tools and the pi-sub-bar token widget keep functioning.

#### Scenario: anthropic auth untouched after apply
- **WHEN** the patch is applied
- **THEN** `~/.pi/agent/auth.json` still contains `.anthropic.access`, `.anthropic.type == "oauth"`,
  and `.anthropic.expires`
- **AND** `hasConfiguredAuth` for the `anthropic` provider still returns true

### Requirement: Application is gated to the personal profile

The patch SHALL apply only when the chezmoi profile is `personal`. The gate is conveyed at
runtime via the `PI_CHEZMOI_PROFILE` environment variable exported by the templated apply
wrapper. On any other value, or when the variable is unset, the patch MUST NOT modify the
target; if the patch was previously applied it MUST restore the original file from backup.

#### Scenario: applies on personal
- **WHEN** the apply loop runs with `PI_CHEZMOI_PROFILE=personal`
- **THEN** `getAvailable()` in the installed `model-registry.js` carries the patch marker

#### Scenario: skips on non-personal
- **WHEN** the apply loop runs with `PI_CHEZMOI_PROFILE` set to a non-personal value (e.g. `axon-work-computer`)
  and the target is currently unpatched
- **THEN** the target file is left byte-for-byte unchanged

#### Scenario: un-patches when profile flips away from personal
- **WHEN** the patch is currently applied and the apply loop later runs with a non-personal `PI_CHEZMOI_PROFILE`
- **THEN** the target is restored from its `*.orig.chezmoi-pi-patch` backup and no longer carries the marker

### Requirement: Patch is safe and idempotent

The patch SHALL reuse the established patch-framework safety properties.

#### Scenario: idempotent re-apply
- **WHEN** the apply loop runs twice on the personal profile
- **THEN** the second run is a no-op and the file carries exactly one marker

#### Scenario: anchor drift aborts cleanly
- **WHEN** the `getAvailable()` anchor does not appear exactly once in the target (upstream changed shape)
- **THEN** the patch aborts with a diagnostic and leaves the target file unchanged

#### Scenario: check mode reports state
- **WHEN** `patch.mjs --check` runs on the personal profile against a patched target
- **THEN** it exits 0
- **AND** when run against an unpatched target it exits non-zero

