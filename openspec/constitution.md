# cartwmic dotfiles Constitution

<!--
The dotfiles repo's immutable principles. Every artifact in the
opsx-superpowers workflow (if/when this repo adopts that schema) reads
this file. Updates require a dedicated change with adversarial review.
-->

**Version:** 1.0.0
**Ratified:** 2026-05-18
**Last updated:** 2026-05-18

## Core Principles

### I. Chezmoi is the single source of truth for cross-machine config

Any file deployed to a user's home directory across machines lives in this repo at its proper chezmoi source path. Files appearing only on one machine and not version-controlled are NOT considered configuration — they are scratch state and may be lost.

**Rationale:** the value of dotfiles is reproducible environment across hosts. Anything one-off is by definition not a dotfile.

**Enforcement:** new tools whose config the user wants to persist MUST be added to chezmoi at the right source path (`dot_<name>/` for `~/.<name>/`, `Library/` unprefixed for `~/Library/`, etc.) before merging.

### II. Skills live in the canonical-harness pipeline

Cross-harness pi/claude/codex skills live at `dot_local/share/agent-harness/canonical/skills/<skill-name>/` in this chezmoi repo. `chezmoi apply` deploys them to `~/.local/share/agent-harness/canonical/skills/`. `run_onchange_apply_harness_config.sh.tmpl` then triggers `apply_harness_config.sh` which symlinks each skill into every harness's discovery dir (`~/.pi/agent/skills/<name>`, `~/.claude/skills/<name>`, `~/.codex/skills/<name>`, `~/.agents/skills/<name>`). New skills are added by writing files to the canonical path; existing skills are edited in place.

**Rationale:** the canonical-symlinked pattern keeps skill source under version control + diff review + adversarial-review-cycle, AND makes skills work across all harnesses on every machine after a single `chezmoi apply`. Skills placed elsewhere (e.g., `<repo>/.pi/skills/` at the chezmoi source root) are NOT chezmoi-deployed and would only work on the authoring machine.

**Enforcement:** PRs adding skills outside `dot_local/share/agent-harness/canonical/skills/` MUST be rejected with a reason. The `apply_harness_config.sh` script's `link_skill_dirs` calls (lines 338, 440, 482, 494) are the canonical enforcement point at deploy time.

### III. No secrets in source

Credentials, API keys, OAuth tokens, and personal-identifier data MUST NOT appear in this repo. Use 1Password CLI, environment-only injection via chezmoi templates, or external secret stores. If a memory or documentation references a credential, it references its STORAGE LOCATION only, never the value.

**Rationale:** dotfiles repos are commonly shared, leaked, or compromised. Secrets in source survive forever.

**Enforcement:** pre-commit hook + secrets-scanner in CI; the memory contract (CLAUDE.md "Memory: hindsight MCP server") documents this.

### IV. Every install script is idempotent

Scripts named `run_once_*`, `run_onchange_*`, or `*_install_*` MUST be safe to re-run. They MUST detect existing installations, use stamp files or version checks, and exit success without action when the target state is already present.

**Rationale:** chezmoi re-runs `run_onchange_*` scripts whenever their content changes (which depends on `include`d files); non-idempotent scripts double-install or fail mysteriously.

**Enforcement:** install scripts MUST be tested by running them twice in sequence on a clean host; the second run MUST produce no diff.

### V. mise tasks own dev-tool install and update

Dev tools and language plugins are installed via mise tasks in `dot_config/mise/config.toml` (`[tasks.bootstrap].depends` and per-tool install tasks), NOT via chezmoi `run_onchange_` scripts. This includes language runtimes, language plugins, language-specific package managers, and tools managed via mise.

**Rationale:** mise tasks are cleaner, declarative, version-pinned, and can be invoked individually. Chezmoi run-onchange is reserved for system-level setup (launchd, gpg, password manager bootstraps).

**Enforcement:** new dev-tool install logic that uses chezmoi run-onchange MUST be rewritten as a mise task before merge.

### VI. launchd jobs declare their PATH explicitly

Any `.plist` file deploying via chezmoi to `~/Library/LaunchAgents/` MUST set `EnvironmentVariables.PATH` to include mise's shim path (`/Users/cartwmic/.local/share/mise/shims`) plus any other paths the script depends on. Do not rely on the inherited launchd PATH.

**Rationale:** launchd inherits a minimal PATH that does NOT source shell rc files. Scripts depending on `mise`, `jq`, `node`, `python`, etc., fail without explicit PATH.

**Enforcement:** every plist's PATH setting is reviewed during the change that introduces it.

### VII. Termux config is not chezmoi-deployed

Termux on Android cannot be reached by chezmoi (Android sandbox). Termux config lives at `termux/` (unprefixed) in this repo and is synced to the device via `adb push` + `run-as`, NOT via `chezmoi apply`. The `termux/sync.sh` script is the canonical sync mechanism.

**Rationale:** chezmoi has no Android target; treating Termux as a sibling rather than a chezmoi-managed surface keeps the source layout honest.

**Enforcement:** PRs adding `dot_termux/` MUST be rejected.

### VIII. OpenSpec workspace under `openspec/` is NOT chezmoi-deployed

The `openspec/` directory at the chezmoi repo root is gitignored from deploys via `.chezmoiignore`. It is the dotfiles repo's own OpenSpec workspace for proposing and tracking changes TO the dotfiles themselves. It is NOT user-level config.

**Rationale:** users (including the author) do not need the dotfiles repo's change history deployed to their home directory. The user-level OpenSpec schemas live at `dot_local/share/openspec/schemas/` (deploys to `~/.local/share/openspec/schemas/`).

**Enforcement:** `.chezmoiignore` contains `openspec/`; no PR may remove this line without an explicit replacement plan for user-level schema deployment.

### IX. Skill changes require adversarial review at Scale ≥ M

Any change that modifies an existing skill at `.pi/skills/` (rather than adding a new one) MUST run through `adversarial-review-cycle` (multi-model, multi-round) before merge. New-skill additions do not require this.

**Rationale:** existing skills are invoked dozens of times per day. A regression in `openspec-propose` or `openspec-apply-change` affects every project. Adversarial review catches single-model blind spots.

**Enforcement:** `analyze.md` check 4 (when the schema is `opsx-superpowers`) flags skill-edit changes for adversarial review.

### X. Memory promotion is opt-in, never automatic

`openspec-archive-change` may parse `retrospective.md` Promote-candidates and offer to call the hindsight `retain` tool, but it MUST prompt the user per-row for confirm/skip. Memories MUST NOT be created without explicit human authorization.

**Rationale:** the hindsight memory bank is shared across every coding-agent harness the user runs. Polluting it with low-value or duplicate entries degrades retrieval relevance for the user AND for future-agent sessions.

**Enforcement:** `openspec-archive-change` skill code is the enforcement point; spec scenario in `opsx-skill-integration/spec.md` covers this.

## Governance

- Amendments to this constitution require a dedicated change with Scale ≥ L and `adversarial-review-cycle` invoked.
- The constitution is read before every artifact in opsx-superpowers workflows. Violations are flagged by analyze check 1.
- Principles in this file override schema instructions and individual artifact prose when they conflict.

## Versioning

- Major: a principle is removed or reversed.
- Minor: a principle is added.
- Patch: clarification, no semantic change.

## See also

- Schema activation: `~/.local/share/openspec/schemas/opsx-superpowers/README.md`
- Domain invariants: `openspec/domain.md`
- Memory contract: `CLAUDE.md` "Memory: hindsight MCP server"
