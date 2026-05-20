## Why

Current opsx workflow runs the default OpenSpec `spec-driven` schema (proposal → specs → design → tasks). Recent research (Kiro deep-spec analysis May 2026; Larbi et al. 2025 measuring 20-40% Pass@1 drop and 60-90% semantically-wrong code on ambiguous/contradictory prompts; Yang et al. 2025 measuring ~2× regression rate under prompt underspecification) plus head-to-head audits of pi-specdocs, ralphy-openspec, Superpowers, Veath/spec-driven-superpowers, danielhanold/superspec, and intent-driven-dev/openspec-schemas converge on a richer, scale-adaptive shape: a constitution/domain layer above changes, EARS-shaped acceptance criteria with explicit quality properties, dedicated clarify + analyze phases between specs and code, ADR persistence past archival, mode-driven Superpowers-style execution discipline, deterministic verify gates, and a retrospective that promotes learnings to long-term memory. None of this requires forking OpenSpec or adding new dependencies — OpenSpec's `openspec/schemas/<name>/` mechanism is purpose-built for this, and `openspec schema fork`/`init` already exists in the CLI. This change captures the synthesis as one persisted user-level schema and adapts the opsx-* skills to drive it, with the default `spec-driven` schema remaining available for projects that don't opt in.

## What Changes

- Add new user-level workflow schema `opsx-superpowers` deployed to `~/.local/share/openspec/schemas/opsx-superpowers/` via chezmoi (`dot_local/share/openspec/schemas/opsx-superpowers/`). OpenSpec resolves user-level schemas from `${XDG_DATA_HOME:-~/.local/share}/openspec/schemas/<name>/` per its `getGlobalDataDir()` implementation.
- New artifact graph (scale-adaptive, 8 schema-tracked artifacts): proposal → specs (EARS) → clarify → design → analyze → review (modes) → tasks → plan. Three additional artifacts (verify.md, retrospective.md, ADR promotion) are **skill-managed post-apply** — their templates live in the schema but they are not declared in `schema.yaml artifacts:` because OpenSpec's `isComplete` is existence-only and `generates: ../../../adr/*.md` escape patterns match pre-existing ADRs from other changes (verified against OpenSpec 1.3.0 source).
- Bake EARS notation (Mavin RE'09; the 5 patterns: ubiquitous, event-driven, state-driven, optional, unwanted) into the specs artifact's instruction prose with a per-AC 5-property checklist (Testable / Solution-free / Unambiguous / Consistent / Complete)
- Introduce per-project supporting files referenced by every artifact: `openspec/constitution.md` (immutable principles) and `openspec/domain.md` (invariants / implicit knowledge — Kiro's "dark matter"). Schema ships template references; first-use prompts the project owner to fill in.
- `review.md` becomes a mode switchboard (lifted near-verbatim from Veath/spec-driven-superpowers and adapted to local skill names): `Scale` (XS/S/M/L/XL — BMAD-style, controls which artifacts are required), `Execution Mode`, `Verification Mode`, `Debug Mode`, `Review Status`, `Delegation Mode`, `Worktree Mode`, `Spec Level` (spec-anchored default).
- `clarify.md` artifact runs three prose-only passes over the EARS ACs: ambiguity (paraphrase × 3 → semantic-divergence flag), inconsistency (pairwise antecedent overlap), completeness (event/state-combination enumeration). Each finding surfaces as a 2-option question. Lightweight port of Kiro's neuro-symbolic pipeline — no SMT dependency.
- `analyze.md` artifact runs read-only cross-artifact lint before code is written (constitution check; EARS pattern check — flag WHEN-on-errors; AC↔design coverage; design↔ADR coverage; duplicate detection; implementation language in specs; unresolved clarify findings). Blocker findings prevent tasks generation. Invokes `adversarial-review-cycle` when `Scale ≥ L`.
- ADR promotion as skill-managed (NOT artifact-tracked): `openspec-archive-change` scans design.md Decisions, applies the 4-point test (multiple approaches / lasting consequences / disagreement potential / future constraints), and offers to promote qualifying decisions to `<repo>/adr/ADR-NNNN-<slug>.md` using the schema's `templates/adr.md` (MADR 4.0 short form). The `analyze` artifact's check 4 flags candidates pre-apply for visibility. ADRs survive archive because the skill writes them outside the change dir; the schema does not need a `generates` escape pattern that would falsely match pre-existing ADRs.
- `verify.md` skill-produced artifact (from danielhanold/superspec): 6 explicit hard checks before archive — `openspec validate --strict`, tasks completion, delta-vs-current spec coherence, commit hygiene, **AC↔test ID mapping** (every EARS AC cited by ≥1 test using canonical ID `<capability>.<requirement-slug>`, every test cites ≥1 AC or carries `# spec-exempt:` marker), constitution compliance audit (proportional sampling: all files if N≤10, stratified at N>50). Binary green/red Completion Decision (no "yellow"). Template at `~/.local/share/openspec/schemas/opsx-superpowers/templates/verify.md`.
- `retrospective.md` skill-produced artifact (optional, pre-archive): Wins / Misses / Plan deviations / Skill compliance / Surprises / Promote-candidates. Promote-candidates support all 9 mcp-memory types (`decision | bug | error | convention | learning | implementation | context | important | code`) with the per-type content thresholds (≥300 chars, except `code` requires ≥600) matching the upstream mcp-memory contract. Parsed by `openspec-archive-change` for per-row `mcp_memory_store_memory` confirm/skip prompts.
- Apply-time discipline (from Veath + ralphy + Superpowers): pre-flight commit of `openspec/changes/<name>/` before worktree creation; **Worktree Base SHA captured at apply start** for stable file-contract diffs (avoids `HEAD` advancing mid-task); main-agent-as-writeback-owner discipline; output-redirection contract (defensive even when Superpowers is not installed: forbids writes to `docs/superpowers/`, `docs/plans/`, `docs/specs/`); per-task file contracts (`files_allowed`/`files_forbidden`/`allow_new_files` enforced via `git diff --name-only <base-sha>..HEAD` against minimatch globs); **TDD interaction with allow_new_files**: tests/**/* auto-permitted when `Execution Mode = tdd-required` AND `allow_new_files = false` (resolves the otherwise-unsatisfiable combination); intent-aware repair-prompt constraints (`fix`/`feature`/`refactor`/`infra`); strict sub-bullet format for contract fields so the parser is deterministic; Iron Law + Red Flags + HARD-GATE prose patterns retrofitted onto the strict gates.
- Adapt opsx skills under `dot_local/share/agent-harness/canonical/skills/`:
  - `openspec-explore`: emit recommended Scale class
  - `openspec-propose`: detect `schema: opsx-superpowers`, prompt for Scale + Spec Level up-front, skip artifacts below the Scale threshold, present EARS-pattern picker for specs, drive clarify before design, drive analyze before tasks, invoke adversarial-review-cycle at Scale ≥ L
  - `openspec-apply-change`: read `review.md` mode flags, enforce file contracts per task, use intent-aware repair-prompt suffixes when validators fail, pre-flight commit before worktree
  - `openspec-archive-change`: HARD-GATE on `verify.md` Completion Decision = green; AC↔test grep gate; ADR promotion check; retrospective-driven mcp-memory ingestion
  - **NEW** `dot_local/share/agent-harness/canonical/skills/clarify-spec/`: lightweight 3-pass clarify subagent driven by clarify artifact
- Update chezmoi exemplar: write `openspec/constitution.md` and `openspec/domain.md` for the dotfiles repo itself so the new schema can be dogfooded on a follow-up dotfiles change

## Capabilities

### New Capabilities
- `opsx-workflow-schema`: defines the contract of the `opsx-superpowers` workflow schema — artifact graph, apply discipline, writeback rules, scale-adaptive gating, schema-only fallback semantics
- `opsx-spec-quality`: defines what makes an acceptance criterion well-formed in this workflow — EARS patterns, 5 quality properties, clarify-pass requirements
- `opsx-skill-integration`: defines the contract between the opsx-* pi skills and the schema — which skill drives which artifact, mode-flag dispatch, hard-gate enforcement, memory-promotion handoff

### Modified Capabilities
<!-- None — this is net-new capability surface. The default spec-driven schema and existing changes are untouched. -->

## Impact

- **Chezmoi source tree (NEW)**:
  - `dot_local/share/openspec/schemas/opsx-superpowers/schema.yaml`
  - `dot_local/share/openspec/schemas/opsx-superpowers/templates/{constitution-template,domain-template,proposal,spec,clarify,design,adr,analyze,review,tasks,plan,verify,retrospective}.md` (13 files)
  - `dot_local/share/openspec/schemas/opsx-superpowers/README.md`
  - `dot_local/share/openspec/schemas/opsx-superpowers/capability-hooks.md`
- **Chezmoi source tree (MODIFIED, skills in the canonical-harness pipeline)**:
  - `dot_local/share/agent-harness/canonical/skills/openspec-explore/SKILL.md`
  - `dot_local/share/agent-harness/canonical/skills/openspec-propose/SKILL.md` + `references/opsx-superpowers-mode.md`
  - `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/SKILL.md` + `references/opsx-superpowers-mode.md`
  - `dot_local/share/agent-harness/canonical/skills/openspec-archive-change/SKILL.md` + `references/opsx-superpowers-mode.md`
- **Chezmoi source tree (NEW skill)**:
  - `dot_local/share/agent-harness/canonical/skills/clarify-spec/SKILL.md`
  - `dot_local/share/agent-harness/canonical/skills/clarify-spec/references/{ears-patterns,quality-properties,three-pass-procedure}.md`
- **Deployment path**: skills deploy via chezmoi to `~/.local/share/agent-harness/canonical/skills/<name>/`, then `apply_harness_config.sh` (triggered by `run_onchange_apply_harness_config.sh.tmpl`) symlinks each into `~/.pi/agent/skills/<name>`, `~/.claude/skills/<name>`, `~/.codex/skills/<name>`, `~/.agents/skills/<name>` automatically. A fresh `chezmoi apply` on a new machine surfaces every skill across every harness.
- **Chezmoi exemplar files (NEW, for dogfooding inside the dotfiles repo only)**:
  - `openspec/constitution.md`
  - `openspec/domain.md`
- **Deploys to user home** (via chezmoi): `~/.local/share/openspec/schemas/opsx-superpowers/` (entire tree) — OpenSpec's XDG_DATA_HOME location
- **No changes** to default `spec-driven` schema. Existing changes in any project remain valid. Per-project opt-in via `schema: opsx-superpowers` in `openspec/config.yaml`.
- **No new runtime dependencies.** Uses existing OpenSpec CLI ≥1.3.0 (`openspec schema fork/init` already available), existing pi-subagents extension, existing mcp-memory MCP server.
- **Affected workflows**: any project that opts in via `schema: opsx-superpowers`. Default opt-out preserved.
- **Documentation impact**: `dot_local/share/agent-harness/canonical/skills/*/SKILL.md` will reference new schema; `dot_openspec/schemas/opsx-superpowers/README.md` documents activation, scale-adaptive paths, and degrade-gracefully semantics if Superpowers skills are absent.
