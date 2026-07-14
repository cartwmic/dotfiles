# cartwmic dotfiles Domain

<!--
Implicit invariants the AI agent does NOT know about this repo's environment.
Kiro's "dark matter": facts experienced engineers leave unwritten because
they're obvious to humans in the domain. The agent needs them written down
to reason about consistency and completeness.

Sourced from mcp-memory entries on chezmoi gotchas (memory hash 4ecb27b6,
2026-05-08) plus subsequent dotfiles work.
-->

**Version:** 1.0.0
**Last updated:** 2026-05-18

## Entities

- **Chezmoi source root** — `~/.local/share/chezmoi/`. The git-tracked tree from which `chezmoi apply` materializes the user's home directory state.
- **Source-prefix convention** — `dot_<name>/` in source → `~/.<name>/` deployed. Unprefixed names like `Library/`, `termux/`, `openspec/` deploy as-is OR are not deployed at all per `.chezmoiignore`.
- **mise** — version manager at `~/.local/share/mise/`. Provides shims at `~/.local/share/mise/shims/<tool>` that resolve to the user-configured version of `<tool>`.
- **Pi skill** — markdown file at `.pi/skills/<skill-name>/SKILL.md` (sometimes with `references/` subdir). Loaded by pi directly from this path; not deployed via chezmoi.
- **OpenSpec change** — directory at `openspec/changes/<name>/` containing proposal/specs/design/tasks markdown; the unit of behavior change tracked by OpenSpec.
- **Capability spec** — a stable file at `openspec/specs/<capability>/spec.md` that accumulates requirements over time via change deltas (ADDED/MODIFIED/REMOVED/RENAMED).
- **User-level OpenSpec schema** — directory at `~/.local/share/openspec/schemas/<name>/` (deployed from chezmoi source `dot_local/share/openspec/schemas/<name>/`). Resolved by OpenSpec's `getGlobalDataDir()` per XDG_DATA_HOME convention.

## Invariants

1. **macOS user library is `~/Library`, NOT `~/.Library`.** The chezmoi source for macOS user library files is `Library/` UNPREFIXED. `dot_Library/` would deploy to the wrong path and is wrong.

2. **OpenSpec resolves user schemas from `${XDG_DATA_HOME:-~/.local/share}/openspec/schemas/<name>/`.** It does NOT use `~/.openspec/schemas/<name>/`. The chezmoi source path for user-level schemas is `dot_local/share/openspec/schemas/<name>/`.

3. **`.chezmoiignore` excludes `openspec/`.** The OpenSpec workspace at the chezmoi repo root is NOT deployed. It tracks changes TO the dotfiles repo itself.

4. **`.pi/` at the chezmoi root is not chezmoi-deployed.** Chezmoi treats `.`-prefixed names at the source root as metadata. Anything placed at `<chezmoi-root>/.pi/` is git-tracked but invisible to `chezmoi apply`. The canonical cross-harness skill path is `dot_local/share/agent-harness/canonical/skills/<name>/` which deploys + symlinks per the apply-harness-config pipeline.

5. **launchd jobs receive a minimal PATH.** They do not source shell rc files. Plists deploying via chezmoi MUST set `EnvironmentVariables.PATH` explicitly to include `/Users/cartwmic/.local/share/mise/shims` plus any homebrew paths.

6. **Atomic file writes may not always be detected by launchd's WatchPaths.** Pair `WatchPaths` with a `StartInterval` safety net for credential-rotation files.

7. **chezmoi `run_onchange_after_*.sh.tmpl` rerun trigger is content-based.** To force a rerun when a sibling file changes, embed a content-hash comment: `# Plist hash: {{ include "<source-relative-path>" | sha256sum }}`. The include path is relative to chezmoi SOURCE root, not target.

8. **A `bin/` rule in `.gitignore` matches `dot_local/bin/`.** Explicit allowlist required: `!dot_local/bin/` + `!dot_local/bin/**`.

9. **launchd reload idempotence requires bootout-bootstrap-enable-kickstart in that order.** `bootout` may fail with input-output errors if not currently loaded — ignore. `enable` is needed if `launchctl disable` was ever run on the label. `kickstart -k` forces immediate run + kills in-flight instances.

10. **Termux config is owned by app uid (u0_a528) and not directly writable from adb.** Reading + writing requires `adb shell 'run-as com.termux <cmd>'`. Direct `cat` of Termux files from adb hits Permission denied.

11. **Termux reload broadcast:** `adb shell 'am broadcast --user 0 -a com.termux.app.reload_style com.termux'` is the canonical way to refresh extra-keys / config changes.

12. **Skills authored at `dot_local/share/agent-harness/canonical/skills/<name>/` are visible to every harness at runtime as `<name>`.** `chezmoi apply` deploys to `~/.local/share/agent-harness/canonical/skills/<name>/` then `apply_harness_config.sh` creates symlinks `~/.pi/agent/skills/<name>` (and equivalent for claude/codex/agents). The SKILL.md frontmatter `name:` field is the canonical name.

13. **OpenSpec changes are immutable once archived.** `openspec archive` moves the change dir to `openspec/changes/archive/<date>-<name>/` and merges delta specs into `openspec/specs/<capability>/spec.md`. Re-opening an archived change is not supported.

14. **Capability spec deltas use ADDED/MODIFIED/REMOVED/RENAMED headers exactly.** MODIFIED MUST include the FULL updated content (not a patch); partial content loses detail at archive time.

15. **mcp-memory is a shared store across coding-agent harnesses.** It is NOT per-project; project scope is achieved via the `project:<name>` tag. The host is `mcp-memory.internal.cartwmic.com`.

16. **The 9 mcp-memory types are canonical.** `decision | bug | error | convention | learning | implementation | context | important | code`. Inventing new types fragments the corpus and degrades retrieval.

17. **Memory content thresholds:** ≥300 chars for all types except `code` which requires ≥600 chars. Smaller entries are filtered for retrieval relevance.

## Units and conventions

- **Time:** UTC for timestamps in stored data; local timezone (America/Los_Angeles) for human-displayed times in TUI / logs.
- **Paths:** absolute paths preferred in scripts; relative paths only inside chezmoi templates and within a single config file.
- **Git authors:** `Michael Cartwright <carmichael1197@gmail.com>` for personal repos; project-default authors for organization repos.
- **Naming:** `kebab-case` for repo names, OpenSpec change names, capability names, and skill names. `snake_case` for shell variables. `camelCase` only when matching upstream API conventions.
- **Versioning:** semver for releases; chezmoi script versions tracked via stamp files inside the install dir (e.g., `.room.version`).
- **Branches:** `main` is the default branch; feature branches are short-lived; commits prefixed `custom:` when this repo's content diverges from an upstream fork.

## Out-of-scope domains

- **Stakeholder management** — this is a single-user dotfiles repo. Stakeholder-facing artifacts (status pages, comms templates, org-wide tracker process) are not modeled. **Exception:** a work-profile (`axon-work-computer`) developer-workstation Jira *session helper* (pi extension: bind/search/sync/nudge for the local coding agent) is in-scope as personal tooling — it is not a stakeholder status surface and does not gate opsx workflows.

- **Multi-tenant workspaces** — the user runs as a single identity across all hosts. No tenant isolation concerns.
- **Production deployment** — chezmoi targets developer workstations, not servers. Production server config is owned by separate org infra repos.
- **Mobile dev environments other than Termux** — iOS dev configuration is not modeled; iPad dev surfaces are not modeled.
- **Windows surfaces** — chezmoi can target Windows but this repo is macOS + Linux + Termux only.

## See also

- Constitution: `openspec/constitution.md`
- mcp-memory contract: `CLAUDE.md` "Memory: mcp-memory MCP server"
- Schema activation: `~/.local/share/openspec/schemas/opsx-superpowers/README.md`
