## 1. Scaffolding & schema skeleton

- [x] 1.1 Create chezmoi source directory `dot_local/share/openspec/schemas/opsx-superpowers/` (NOTE: corrected from initial `dot_openspec/` — OpenSpec resolves user schemas via `getGlobalDataDir()` which uses `${XDG_DATA_HOME:-~/.local/share}/openspec/`, not `~/.openspec/`)
- [x] 1.2 Used `openspec schema fork spec-driven opsx-superpowers` in a sandbox to generate a baseline `schema.yaml` + 4 default templates (proposal/spec/design/tasks); copied result into chezmoi source path
- [x] 1.3 Authored `dot_local/share/openspec/schemas/opsx-superpowers/README.md` documenting activation, Scale-tier examples, mode reference, schema-only fallback semantics, and OpenSpec minimum version 1.3.0
- [x] 1.4 Verified `chezmoi managed | grep openspec` lists `.local/share/openspec/...` paths; first chezmoi-managed user-level OpenSpec dir
- [x] 1.5 Sanity-check passed: after `chezmoi apply`, `openspec schema which opsx-superpowers` returns `Schema: opsx-superpowers / Source: user / Path: /Users/cartwmic/.local/share/openspec/schemas/opsx-superpowers`; `openspec schemas` lists `opsx-superpowers (user override)` alongside the default `spec-driven`

## 0. Adversarial-review findings (post-Group-4)

*A blind adversarial review using claude-bridge/claude-opus-4-7 (reviewer agent, fresh context) was run after Groups 1-4. Verdict: `block-on-major-findings`. Four blockers + ten major findings + six minor findings. Material schema changes were made before continuing.*

- [x] 0.1 B1 fix: drop `adr` from artifact graph; promote ADR-as-skill-managed via `openspec-archive-change` at archive time. Schema's `templates/adr.md` remains for the skill to use. The escape-glob `generates: ../../../adr/ADR-*.md` was demonstrated broken (matches any pre-existing ADR, reports done before any work). Design D4 revised; spec scenarios updated; analyze check 4 updated to flag candidates pre-apply.
- [x] 0.2 B2 fix: `apply.requires` confirmed as `[tasks]` (full graph reachable transitively); `apply.tracks` confirmed as single string `tasks.md` (zod requires `string | null`, not array). Spec scenario "Apply block references tracked artifacts" rewritten to match implementation.
- [x] 0.3 B3 fix: drop `verify` and `retrospective` from artifact graph. "Dangling dependency = optional" was mythology — OpenSpec's `isComplete` is existence-only and `getNextArtifacts` marks dangling artifacts `ready` forever. Both become skill-managed (templates remain in schema). Design D11 added documenting the rationale.
- [x] 0.4 B4 fix: canonical AC ID format pinned as `<capability>.<requirement-slug>` (slug = lowercased name, non-alnum → `-`, repeated `-` collapsed, leading/trailing stripped). spec.md template + verify.md template + analyze.md template + spec quality spec all updated.
- [x] 0.5 M2 fix: Worktree Base SHA captured at apply start in review.md; file-contract diff base is `<worktree-base-sha>..HEAD`, not `HEAD`. review.md template + apply instruction + spec scenario updated.
- [x] 0.6 M3 fix: TDD-mode auto-allows `tests/**/*` regardless of `allow_new_files: false`. Schema apply instruction + tasks.md template + spec scenario updated.
- [x] 0.7 M4 fix: Promote-candidates enum extended to all 9 mcp-memory types (added `bug`, `error`, `code`). `code` requires ≥600 chars per upstream contract. Retrospective template updated.
- [x] 0.8 M5 fix: EARS pattern check 2 downgraded from auto-blocker to major-with-human-triage; documented false-positive modes (substring matches in entity names; "failed attempt" in non-error context). Confirmed true positives still block tasks. Analyze template + analyze instruction + spec scenario updated.
- [x] 0.9 M7 fix: Clarify Pass 3 capped at 10 highest-impact uncovered combinations per spec file (not full cartesian product). Pass 2 N² scaling acknowledged with prioritization at >20 ACs. Schema clarify instruction + spec scenario updated. Pass scope restricted to delta content only (brownfield viability).
- [x] 0.10 M8 fix: Completion Decision is now binary green/red (removed "yellow" which had no closed-form criterion). Verify template + spec scenario updated. Override path via human-recorded decision at archive time.
- [x] 0.11 M10 cosmetic fix: proposal.md `templates/{...,specs,...}` corrected to `spec` (singular, matches actual filename).
- [x] 0.12 M1 RESOLVED: clarify-spec skill shipped (Group 5, 492 lines); 4 opsx-* skill edits shipped (Group 6, 498 lines of references + ~50 lines of in-skill schema-detection blocks); change is no longer split-candidate — single change covers everything per reviewer question #3 path A.
- [x] 0.13 M6 RESOLVED: stratified sampling for Check 6 documented in `verify.md` template + the apply skill's `references/opsx-superpowers-mode.md` step 6 (sampling strategy: all if N≤10, all-with-note if N≤50, stratified 1-per-top-level-dir+5-random if N>50).
- [x] 0.14 M9 RESOLVED: Verification Mode `retained-required` enforcement implemented in `openspec-archive-change/references/opsx-superpowers-mode.md` HARD-GATE 1 (refuses archive if verify.md missing or red). Plus defense-in-depth re-grep of AC↔test in HARD-GATE 2.
- [x] 0.15 Minors addressed inline where possible (m1 indirection rationale documented in capability-hooks.md; m2 checklist dedup handled by removing duplication from spec.md template; m3 strict sub-bullet format documented in tasks.md template + apply instruction; m4 README note added about XS noise in status output). Remainders are retrospective-track.

## 2. Schema YAML — artifact graph

- [x] 2.1 Declared schema metadata in `schema.yaml`: name, version 1, description
- [x] 2.2 `proposal` artifact (no deps) authored with constitution + domain referencing
- [x] 2.3 `specs` artifact (`requires: [proposal]`) with EARS patterns + 5-property checklist embedded in instruction
- [x] 2.4 `clarify` artifact (`requires: [specs]`) with 3-pass procedure + capability hook to `clarify-spec` skill
- [x] 2.5 `design` artifact (`requires: [clarify]`) with Decisions block + 4-point test
- [x] 2.6 `adr` artifact (`requires: [design]`, dangling = optional); `generates: ../../../adr/ADR-*.md` escapes change dir; MADR 4.0 short form + immutability rule in instruction
- [x] 2.7 `analyze` artifact (`requires: [design]`) with 7 cross-artifact checks; capability hook to `adversarial-review` at Scale ≥ L. NOTE: `requires` set to `[design]` only since clarify+specs are transitive deps of design
- [x] 2.8 `review` artifact (`requires: [analyze]`) with the 8 modes (Scale / Execution / Verification / Debug / Review-Status / Delegation / Worktree / Spec-Level)
- [x] 2.9 `tasks` artifact (`requires: [review]`) with per-task contract fields (`files_allowed`, `files_forbidden`, `allow_new_files`, `intent`) documented in instruction
- [x] 2.10 `plan` artifact (`requires: [tasks]`) with 5-step micro-task structure + tasks-vs-plan granularity distinction
- [x] 2.11 `apply` block: `requires: [tasks]` (full graph reachable transitively); `tracks: tasks.md` (zod requires string, not array); pre-flight commit + writeback discipline + output redirection + file-contract enforcement (with Worktree Base SHA) + intent-aware repair prompts + TDD test-file exemption + post-apply skill contract for verify/adr/retrospective all in apply.instruction
- [x] 2.12 ~~`verify` artifact~~ **REMOVED from artifact graph per B3** — became skill-managed; template `templates/verify.md` ships in schema for `openspec-apply-change` to author at apply end. Apply instruction documents the contract.
- [x] 2.13 ~~`retrospective` artifact~~ **REMOVED from artifact graph per B3** — became skill-managed; template `templates/retrospective.md` ships in schema for `openspec-archive-change` to author pre-archive at Scale L (optional) or XL (required). Apply instruction documents the contract.
- [x] 2.14 `openspec schema validate opsx-superpowers` → green; `openspec schemas` lists `opsx-superpowers (user override)` with the 8-artifact chain (proposal → specs → clarify → design → analyze → review → tasks → plan)

**Schema design notes** (consolidated post-adversarial-review):

1. OpenSpec's zod `ArtifactSchema` has no `optional` field. "Dangling dependency = optional" was tested and refuted: `isComplete` is existence-only and dangling artifacts remain `ready` perpetually. → verify, retrospective, adr removed from artifact graph; managed by skills instead.
2. `ApplyPhaseSchema.tracks` is `string | null`, not an array. apply.tracks pinned to `tasks.md`.
3. The `generates: ../../../adr/ADR-*.md` escape-glob is broken in multi-change repos. → ADR promotion is now an archive-time skill responsibility.
4. Scale-adaptive gating lives in the opsx-* skills, not the schema. The schema's artifact graph is static; the skills decide what to author per Scale (documented in README's `What's tracked vs. skill-managed` section).

## 3. Templates — body content (all 13 deployed)

- [x] 3.1 `constitution-template.md` — ≤10 numbered Core Principles, Governance, Versioning placeholders
- [x] 3.2 `domain-template.md` — invariants list, entity glossary, units/conventions, out-of-scope domains
- [x] 3.3 `proposal.md` — Why / What Changes / Capabilities / Impact; ~30 lines
- [x] 3.4 `spec.md` — EARS pattern reference comment header + ADDED/MODIFIED/REMOVED/RENAMED Requirement sections + per-AC 5-property checklist table
- [x] 3.5 `clarify.md` — 3 pass sections each with findings table (id, AC ref, question, option-A, option-B, status, resolution); Outstanding section; Summary with gate status
- [x] 3.6 `design.md` — Context / Goals-Non-Goals / Decisions (numbered with alternatives + 4-point test) / Risks-Trade-offs table / Migration / Open Questions
- [x] 3.7 `adr.md` — MADR 4.0 short form: Title, Status, Date, Source change, Supersedes/Superseded-by, Context, Decision Drivers, Considered Options, Decision Outcome, Consequences, Links + immutability rule footer
- [x] 3.8 `analyze.md` — per-check sub-tables for all 7 checks (constitution / EARS pattern / AC↔design / design↔ADR / duplicate / impl-language / unresolved-clarify) + Outstanding risks + Summary with gate status
- [x] 3.9 `review.md` — Modes table (8 modes with controlled-vocab values + notes); Manual Adjustments section; Execution Notes section
- [x] 3.10 `tasks.md` — task group structure with examples showing optional `files_allowed` / `files_forbidden` / `allow_new_files` / `intent` per task; instruction footer documenting contract enforcement + intent semantics
- [x] 3.11 `plan.md` — execution-driver structure with Covers/Pre-conditions/Action(5-step micro-tasks)/Verification/Rollback per step; systematic-debugging extension comments; Completion Verification + Manual Adjustments
- [x] 3.12 `verify.md` — Completion Decision (green/yellow/red) + 6-check table + AC↔test forward+reverse sub-tables + Constitution sampling sub-table + Summary
- [x] 3.13 `retrospective.md` — 6 sections (Wins / Misses / Plan deviations / Skill compliance / Surprises / Promote candidates) with Promote-candidates row template `{type, tags, content ≥300 chars}` matching mcp-memory contract

## 4. Capability-hook lookup

- [x] 4.1 Authored `dot_local/share/openspec/schemas/opsx-superpowers/capability-hooks.md` with resolution algorithm + capability table mapping 8 capabilities (clarify-spec, adversarial-review, subagent-driven-implementation, file-isolation-via-worktree, verification-before-completion, systematic-debugging, finish-development-branch, memory-promotion) → candidate skills in priority order
- [x] 4.2 Documented manual fallback procedure for each capability with explicit DEGRADED MODE note expectations when a capability resolves to fallback

## 5. Clarify-spec skill (new)

- [x] 5.1 `dot_local/share/agent-harness/canonical/skills/clarify-spec/SKILL.md` (131 lines): frontmatter + input/output contracts + 6-step procedure + guardrails + reference pointers. Supports both opsx-superpowers schema use and standalone use.
- [x] 5.2 `dot_local/share/agent-harness/canonical/skills/clarify-spec/references/three-pass-procedure.md` (154 lines): per-pass algorithms with N² boundary rules for Pass 2, priority caps for Pass 3, brownfield vs greenfield scope, findings file structure
- [x] 5.3 `dot_local/share/agent-harness/canonical/skills/clarify-spec/references/ears-patterns.md` (106 lines): 5 patterns + compound + WHEN/IF discipline + common errors table + formal-logic mapping for Pass 2
- [x] 5.4 `dot_local/share/agent-harness/canonical/skills/clarify-spec/references/quality-properties.md` (101 lines): 5 properties with positive AND negative examples + canonical AC ID slug rules + test-exemption marker convention
- [ ] 5.5 Smoke-test deferred to Group 8 e2e (will exercise the skill on a sacrificial sandbox change)

## 6. Skill edits — schema-aware backward-compatible

- [x] 6.1 `dot_local/share/agent-harness/canonical/skills/openspec-explore/SKILL.md`: added "Schema awareness (opsx-superpowers)" subsection under "OpenSpec Awareness". When active change uses opsx-superpowers, the explore skill recommends a Scale tier, reads constitution.md/domain.md/current spec.md before drafting any proposal, and surfaces ambiguity early. Default behavior unchanged.
- [x] 6.2 `dot_local/share/agent-harness/canonical/skills/openspec-propose/SKILL.md`: added step 2.5 schema-detection block. opsx-superpowers branch loads `references/opsx-superpowers-mode.md` (161 lines) which: prompts for Scale + Spec Level up-front, walks the 8-artifact graph with Scale-aware skip table, presents EARS-pattern picker for specs, surfaces canonical AC IDs, invokes clarify-spec skill before design, blocks on unanswered findings, invokes adversarial-review-cycle at Scale ≥ L for analyze, prompts for per-task file contracts. Default schema behavior unchanged.
- [x] 6.3 `dot_local/share/agent-harness/canonical/skills/openspec-apply-change/SKILL.md`: added step 2.5 schema-detection block. opsx-superpowers branch loads `references/opsx-superpowers-mode.md` (172 lines) which: parses review.md modes, runs pre-flight commit before worktree, captures Worktree Base SHA for stable diff base, dispatches via pi-subagents when Delegation Mode=subagent-*, runs intent-specific repair prompts (fix/feature/refactor/infra), enforces file contracts with TDD test-file exemption, produces verify.md post-apply with 6 hard checks. Default schema behavior unchanged.
- [x] 6.4 `dot_local/share/agent-harness/canonical/skills/openspec-archive-change/SKILL.md`: added step 2.5 schema-detection block. opsx-superpowers branch loads `references/opsx-superpowers-mode.md` (165 lines) which: HARD-GATEs on verify.md green when Verification Mode=retained-required, re-runs AC↔test grep as defense-in-depth, prompts ADR promotion for decisions passing the 4-point test (writing to `<repo>/adr/ADR-NNNN-<slug>.md`), parses retrospective.md Promote-candidates with per-row mcp-memory confirm/skip prompts (validating content thresholds: ≥300 chars / ≥600 for code type), provides --override path with rationale recording. Default schema behavior unchanged.
- [x] 6.5 Each schema-detection block explicitly logs `[opsx-superpowers mode] following alternate procedure` when activated and `[feature off] running default flow` otherwise, so the user can confirm which path executed.
- [x] 6.6 Verified by reading each edited skill: the schema-detection block is inserted as a new step (2.5) that returns control to existing steps when schema is default. Pre-existing steps 3, 4, 5, 6, etc. are UNTOUCHED. For default-schema projects every code path matches the unmodified original behavior.

## 7. Dotfiles-repo dogfooding artifacts

- [x] 7.1 `openspec/constitution.md` authored (10 numbered principles I–X covering chezmoi-as-source-of-truth, skills-at-`dot_local/share/agent-harness/canonical/skills/`-not-deployed, no-secrets, idempotent-install, mise-owns-dev-tools, launchd-PATH-explicit, termux-sibling-not-chezmoi, openspec-workspace-not-deployed, adversarial-review-on-skill-edits, memory-promotion-opt-in)
- [x] 7.2 `openspec/domain.md` authored: 17 invariants (XDG_DATA_HOME OpenSpec path, .chezmoiignore openspec/, `.pi/` not deployed, launchd minimal PATH, termux uid sandbox, atomic-write fsevents quirks, mcp-memory contract reminders) + entities + units/conventions + out-of-scope domains. Sourced from mcp-memory hash 4ecb27b6 + subsequent work.
- [x] 7.3 Verified `openspec/` is in `.chezmoiignore`; `chezmoi managed | grep openspec` returns only the user-level schema paths (`.local/share/openspec/...`), not the repo-root `openspec/constitution.md` or `openspec/domain.md`. These exemplars are version-controlled but not deployed.

## 8. Validation & end-to-end smoke

- [x] 8.1 `openspec validate add-opsx-superpowers-schema --strict` → green
- [x] 8.2 `openspec schema validate opsx-superpowers` → green
- [x] 8.3 `chezmoi diff /Users/cartwmic/.local/share/openspec` → empty diff (in sync; deployment is correct; corrected source path is `dot_local/share/openspec/`, NOT `dot_openspec/`)
- [x] 8.4 Deployed state verified: `ls ~/.local/share/openspec/schemas/opsx-superpowers/` shows 13 templates + README.md + capability-hooks.md + schema.yaml; `openspec schemas` lists `opsx-superpowers (user override)` with the 8-artifact chain
- [ ] 8.5 (deferred to a separate manual session) End-to-end XS and M test on a sacrificial sandbox project — requires multi-minute interactive walkthrough of every artifact + archive
- [ ] 8.6 (deferred) End-to-end Scale-L test — requires adversarial-review-cycle invocation + ADR promotion exercise
- [ ] 8.7 (deferred) Backward-compat regression on a default-schema project — requires a live default-schema change to validate `[feature off]` log line

## 9. Documentation & memory

- [x] 9.1 Updated `/Users/cartwmic/.local/share/chezmoi/CLAUDE.md` with new "OpenSpec workflow schemas" section above AI Assistant Integration. Documents activation path, scope of changes, when-to-opt-in heuristic, and pointers to schema README + dogfooding files.
- [x] 9.2 Stored `implementation` memory (hash 6e296a19a0d7): deployment locations, four touched skills + new clarify-spec skill, backward-compat guarantee details. Tagged `project:dotfiles`, `openspec`, `schema:opsx-superpowers`, `ears`, `chezmoi`.
- [x] 9.3 Stored `decision` memory (hash f3cf97f996b7): all 10 design Decisions D1–D11 (D11 added post-adversarial-review), each with Choice + Alternatives + Rationale summary. Tagged `decision`, `important`, `project:dotfiles`, `design-decisions`, `adversarial-review`.
- [x] 9.4 Stored `context` memory (hash f985439f1043) cross-linking the synthesis chain: three audit memories (pi-specdocs, ralphy-openspec, Superpowers) + three custom-schema repos + 2025-2026 SDD literature + 8-layer convergence + adversarial-review-cycle pass. Future sessions can reconstruct the full rationale chain from this memory + cross-references.

## 10. Optional follow-on (not blocking archive of THIS change)

- [ ] 10.1 Adopt `opsx-superpowers` for the chezmoi repo itself by switching its `openspec/config.yaml` to `schema: opsx-superpowers` in a separate follow-on change
- [ ] 10.2 Implement Kiro-style agent hooks (Pi `tool_result` extensions): post-edit EARS lint, post-edit AC↔test mapping grep, post-design constitution re-check — defer until empirical motivation
- [ ] 10.3 Investigate upgrade path to SMT-backed clarify pass if/when the prose-only version proves insufficient on real changes
