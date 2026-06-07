## Context

The user runs OpenSpec across multiple projects (investigator-ai eval work, pi-session-search fork, dotfiles, harpoon/zellij plugins) using the four opsx-* pi skills (`openspec-explore`, `openspec-propose`, `openspec-apply-change`, `openspec-archive-change`). These skills are sourced from `dot_local/share/agent-harness/canonical/skills/` in chezmoi, deployed to `~/.local/share/agent-harness/canonical/skills/`, and symlinked into each agent harness's skill discovery dir (`~/.pi/agent/skills/`, `~/.claude/skills/`, etc.) by the chezmoi-managed `run_onchange_apply_harness_config.sh.tmpl` pipeline. The default OpenSpec workflow is `spec-driven` (proposal → specs → design → tasks). That workflow is good but lossy:

- Decisions in `design.md` die at archive (no durable ADR equivalent)
- Acceptance criteria default to ad-hoc bullet lists, not a structured form like EARS
- There is no explicit phase between specs and code that checks for ambiguity / inconsistency / completeness
- There is no machine-readable mode switchboard letting the workflow scale from a typo fix to a new capability
- There is no hard gate on AC↔test mapping before archive
- There is no enforced output-redirection contract preventing tools like Superpowers from writing to parallel doc trees

Three months of audits across pi-specdocs (ADR convention), ralphy-openspec (file contracts + intent-aware repair prompts), Superpowers (Iron Law / Red Flags / HARD-GATE / verification-before-completion / two-stage per-task review), Veath/openspec-spec-driven-superpowers (mode switchboard + writeback discipline + schema-only fallback), danielhanold/superspec (pre-flight commit + verify-as-artifact + retrospective), intent-driven-dev/openspec-schemas (six reference schemas demonstrating the mechanism, including ADR-as-artifact escaping the change dir), GitHub Spec Kit (constitution + clarify + analyze), Kiro (EARS + 5 quality properties + neuro-symbolic clarify pipeline), BMAD (scale-adaptive paths), plus academic evidence (Larbi et al. 2025 measuring 20-40% Pass@1 drop on ambiguous prompts; Yang et al. 2025 measuring ~2× regression rate under prompt underspecification) converge on the artifact graph and discipline this change introduces.

OpenSpec's `openspec/schemas/<name>/` mechanism + `openspec schema fork/init` CLI is the right integration surface: a single YAML + a set of markdown templates declares the contract. The opsx skills follow whatever dependency order the schema declares because they already call `openspec instructions <artifact> --json`. No fork. No new dependency.

Constraints:

- The user is solo-to-small-team. Heavy ceremony for typo fixes is a non-starter. Scale-adaptive is non-negotiable (Fowler's #1 critique of Kiro and Spec Kit).
- The user already has `adversarial-review-cycle`, `pi-subagents` (with worktrees + parallel + intercom), `systematic-debugging`, `review-plans`, `pi-tui-scenario-tests`, mcp-memory, and pi-session-search. The schema must invoke these by name, not replace them with Superpowers-flavored equivalents.
- The schema must work on hosts that don't have Superpowers installed (the user does not). Skill invocations are advisory; the schema must degrade gracefully to documented manual procedures.
- Chezmoi persistence is required: the schema lives in the dotfiles repo at `dot_local/share/openspec/schemas/opsx-superpowers/` and deploys to `~/.local/share/openspec/schemas/opsx-superpowers/` so the user gets it on every host. Skills live at `dot_local/share/agent-harness/canonical/skills/` and get symlinked into each harness's discovery dir via the apply-harness-config pipeline, so opsx-* + clarify-spec + the schema all flow through one `chezmoi apply` on a fresh machine.

Stakeholders: only the user (single-author dotfiles repo).

## Goals / Non-Goals

**Goals:**
- Persist a single user-level `opsx-superpowers` schema canonically in chezmoi at `dot_local/share/openspec/schemas/opsx-superpowers/` so `chezmoi apply` deploys it to `~/.local/share/openspec/schemas/opsx-superpowers/` (OpenSpec's XDG_DATA_HOME-compliant `getGlobalDataDir()` location)
- Encode the synthesized best-practice artifact graph from three months of cross-repo audits and the 2025-2026 SDD literature
- Make adoption per-project opt-in (`schema: opsx-superpowers` in `openspec/config.yaml`); default `spec-driven` remains untouched and fully functional
- Adapt the four existing opsx-* pi skills to drive the new graph **only when the resolved schema is `opsx-superpowers`**; pure-additive behavior for default-schema changes
- Add one new `clarify-spec` skill implementing the three-pass clarify procedure as a reusable subagent
- Add chezmoi-tracked `openspec/constitution.md` and `openspec/domain.md` to the dotfiles repo so the schema can be dogfooded on a follow-up dotfiles change
- Keep every artifact's `instruction` prose under ~80 lines and use tables/checklists rather than long-form prose, addressing Fowler's "markdown review overload" critique

**Non-Goals:**
- Replacing the default `spec-driven` schema or auto-migrating existing changes
- Implementing Kiro's neuro-symbolic SMT-backed requirements analysis (too heavy; the prose-only three-pass clarify gets ~80% of the value at 0% of the dependency cost)
- Spec-as-source (Tessl-style) — the schema's default `Spec Level` is `spec-anchored`; selecting `spec-as-source` warns about MDD-era trade-offs and is for experimentation only
- Per-task SQLite ledger (ralphy-style) — conversation history + git log are the ledger
- A `ralphy-spec run`-style headless autonomous loop — the user's mode is interactive, adversarially-reviewed, manually-driven
- A new CLI binary — everything is markdown + a YAML schema + skill prose
- Mandatory ADRs on every change — ADRs are optional, only required at Scale ≥ L when a decision passes the 4-point test
- Brainstorming as a required phase (rejecting Superspec's required-on-every-change `brainstorm` artifact in favor of scale-adaptive optionality)

## Decisions

### D1: Mode-driven, not per-artifact-hard-coded, integration with optional Superpowers-style skills

**Choice:** Adopt Veath's mode-switchboard approach: `review.md` declares modes; the apply instruction reads modes and dispatches to local skills by capability. Do not hard-code `superpowers:X` invocations like superspec does.

**Alternatives considered:**
- **Per-artifact hard-coded (superspec style)**: each artifact instruction names a specific skill. Simpler conceptually, but couples the schema to a specific harness's skill names and makes degradation when those skills are missing brittle.
- **Tool-agnostic capability hooks (chosen)**: artifacts name a *capability* ("verification before completion", "subagent-driven implementation"), and the apply instruction maps capability → locally available skill. Adds one indirection layer; pays off when the user is cross-harness (pi mainly, occasionally Codex/Claude Code).

**Rationale:** The user is on pi, not Anthropic Claude Code. Hard-coding `superpowers:subagent-driven-development` would require Pi to register a similarly-named alias or break. Capability-hook indirection makes the schema portable.

### D2: EARS as the required acceptance-criteria format, with WHEN/IF discipline

**Choice:** Require EARS (Mavin et al., RE'09). Forbid `WHEN` on error/unwanted-behavior ACs. Use `IF…THEN` for errors. Use `WHILE` for state preconditions. Use `WHERE` for optional features. Use the bare `THE …SHALL` form for ubiquitous invariants.

**Alternatives considered:**
- **Free-form bullet ACs (default OpenSpec)**: maximally flexible; lowest LLM parseability. Empirically associated with the ambiguity/incompleteness failure modes documented by Larbi/Yang.
- **Gherkin Given/When/Then**: closer to BDD culture; less strict about error-path discipline than EARS; common but not state-of-the-art for LLM consumption (Kiro production team explicitly chose EARS over Gherkin).
- **EARS (chosen)**: strict superset of Gherkin's expressiveness with stronger discipline (no WHEN-on-errors). LLM-parseable into formal logic via clause mapping (Kiro production proof). Tools already exist (Inflectra.ai EARS analyzer, etc.).

**Rationale:** EARS gives the LLM structured antecedent/consequent it can reason about. The WHEN-vs-IF discipline catches the most common AC bug class (nominal/error path conflation) deterministically via grep. Empirical evidence from Kiro's production pipeline shows EARS clauses map cleanly to formal logic for downstream consistency checking, even when we don't formalize.

### D3: Scale-adaptive artifact gating (`Scale: XS | S | M | L | XL`)

**Choice:** Borrow BMAD's scale-adaptive principle. Declare a `Scale` mode in `review.md` controlling which artifacts are required for apply completion. XS = proposal + tasks only; S = + specs + plan; M = + clarify + design + analyze + review + verify; L = + adr (when warranted) + adversarial-review at analyze; XL = + retrospective.

**Alternatives considered:**
- **One workflow fits all (Spec Kit / Kiro)**: Fowler's empirical complaint — "sledgehammer to crack a nut" on small bugs. Causes the user to bypass the schema entirely for trivial work, undermining its discipline-building value.
- **Per-section optionality (Veath)**: every mode is independently selectable. Powerful but loose — easy to under-specify.
- **Scale class as a top-level mode (chosen)**: one variable picks the entire profile; individual mode flags can still override within the chosen scale. Best of both.

**Rationale:** Fowler's sledgehammer critique is the single biggest predicted failure mode of this kind of integration. Scale-class is the smallest mechanism that addresses it. Per-mode overrides remain available for unusual cases.

### D4: ADRs are skill-managed at archive time, NOT a schema artifact (revised after adversarial review)

**Choice:** Promote design Decisions to `<repo>/adr/ADR-NNNN-<slug>.md` via `openspec-archive-change` at archive time. The schema ships `templates/adr.md` (MADR 4.0 short form) for the skill's use. The analyze artifact's check 4 flags ADR candidates pre-apply for visibility. The schema does NOT declare an `adr` artifact.

**Alternatives considered:**
- **Decision blocks inside design.md only**: simplest. Loses durability — `openspec-archive-change` archives `design.md`, hiding the decision rationale.
- **Separate `docs/adr/` tree à la pi-specdocs**: duplicates content; risks drift between archived design.md and persisted ADR.
- **ADR-as-artifact with `generates: ../../../adr/ADR-*.md` (initially chosen, then withdrawn)**: An adversarial review (Claude Opus 4.7, blind context) demonstrated this approach is broken. OpenSpec's resolver path-joins `generates` against the change dir then runs `fast-glob`; the resulting glob `<repo>/adr/ADR-*.md` matches ANY pre-existing ADR from any prior change. `openspec status --change <new-change> --json` reports the `adr` artifact as `"done"` from the moment the change is created (existence-only completion check; `graph.js isComplete`). Verified by reproducing on a sandbox change with a pre-existing `ADR-0001`. The escape pattern was lifted from intent-driven-dev/openspec-schemas but the underlying behavior wasn't tested against multi-change repos before adoption.
- **Skill-managed at archive (chosen)**: `openspec-archive-change` scans `design.md` Decisions, applies the 4-point test, and offers to promote qualifying decisions to `<repo>/adr/ADR-NNNN-<slug>.md` before archive. Template `templates/adr.md` provides the MADR 4.0 short form. The analyze artifact's check 4 lists ADR candidates pre-apply so the user knows what's coming.

**Rationale:** ADR persistence past archival remains the strongest single idea from the pi-specdocs audit. Doing it via the archive skill (which already operates outside the change-dir lifecycle) sidesteps OpenSpec's existence-only completion check and avoids cross-change false-positives. The cost is that ADR promotion is no longer reflected in `openspec status`; it's a skill-managed lifecycle event.

### D5: Three-pass prose-only clarify, no SMT solver

**Choice:** Implement `clarify-spec` as a pi skill running three prose-only passes: ambiguity (paraphrase × 3 → semantic-divergence flag), inconsistency (pairwise antecedent overlap), completeness (event/state combination enumeration). Surface every finding as a 2-option question.

**Alternatives considered:**
- **Full neuro-symbolic à la Kiro (LLM auto-formalization → SMT)**: state-of-the-art; requires Z3 + custom auto-formalization pipeline + LLM-as-judge orchestration. Months of work; new heavy dependencies.
- **No clarify phase**: status quo; LLM authoring + adversarial review at the design stage. Loses the early-detection benefit Kiro's pipeline exists to deliver.
- **Prose-only three-pass (chosen)**: ~80 lines of skill prose; reuses paraphrase + comparison capabilities the LLM already has. Empirically the highest-leverage subset of Kiro's pipeline (per Kiro's own ablation language: "refinement does most of the work"). Easy to upgrade to neuro-symbolic later if value materializes.

**Rationale:** The user's stack is markdown + skills. Adding Z3 dependency would be the largest infrastructure change in this entire integration. The prose-only version is achievable today and gives ~80% of the demonstrated value. Upgrade path stays open.

### D6: AC↔test ID mapping as a hard verify gate

**Choice:** `verify.md` enforces, by grep against the change diff, that every EARS AC has at least one test citing it by slug or numeric ID, and every test cites at least one AC. Reverse-check exemptions via `# spec-exempt: <reason>` markers. Archive blocked if mapping incomplete.

**Alternatives considered:**
- **Test count threshold (e.g., ≥N tests per change)**: cheap to gate on; doesn't actually ensure coverage of specific behaviors.
- **LLM-judged coverage review**: high cost, soft gate, doesn't scale to large diffs.
- **AC↔test ID grep (chosen)**: deterministic. Cheap (a single grep over `specs/**/spec.md` + a single grep over changed test files). Catches the most common LLM coding failure mode (test passes but exercises unrelated behavior).

**Rationale:** Fowler's "false sense of control" critique applies. Don't trust LLM self-audits for coverage. Use a hard, deterministic gate.

### D7: spec-anchored (not spec-as-source) is the schema's default

**Choice:** Default `Spec Level: spec-anchored`. Selecting `spec-as-source` produces a warning citing MDD-era trade-offs and is intended for experimentation only.

**Alternatives considered:**
- **Spec-first (Kiro default)**: spec is consumed once then discarded; loses living-document value.
- **Spec-as-source (Tessl)**: code marked DO-NOT-EDIT, regen-from-spec. Recreates MDD's worst pitfalls — inflexibility + LLM non-determinism — per Fowler's MDD parallel.
- **Spec-anchored (chosen)**: specs persist as the capability-behavior contract; code remains canonical. Matches OpenSpec's existing model.

**Rationale:** OpenSpec is structurally spec-anchored already. Documenting it explicitly in the schema's README prevents future drift toward spec-as-source (which would undermine the validate-strict + delta-spec contract).

### D8: Chezmoi persistence layout (revised after deployment audit)

**Choice:**
- Schema at `dot_local/share/openspec/schemas/opsx-superpowers/` → chezmoi deploys to `~/.local/share/openspec/schemas/opsx-superpowers/` (verified during apply: OpenSpec's `getGlobalDataDir()` uses `${XDG_DATA_HOME:-~/.local/share}/openspec/`, not `~/.openspec/`).
- Skill edits and the new clarify-spec skill at `dot_local/share/agent-harness/canonical/skills/` → chezmoi deploys to `~/.local/share/agent-harness/canonical/skills/`, then `run_onchange_apply_harness_config.sh.tmpl` triggers `apply_harness_config.sh` which **symlinks each skill into every harness's skill dir** (`~/.pi/agent/skills/<name>`, `~/.claude/skills/<name>`, `~/.codex/skills/<name>`, `~/.agents/skills/<name>`).
- Dotfiles-repo-specific exemplars at `openspec/constitution.md` and `openspec/domain.md` (the chezmoi repo's own OpenSpec workspace; gitignored from chezmoi deploys per `.chezmoiignore` line `openspec/`).

**Deployment-audit correction:** initial implementation placed skills at `.pi/skills/<name>/` at the chezmoi source root. This was wrong — `.pi/` at the chezmoi source root is treated as a `.`-prefixed metadata path by chezmoi and is **not deployed**. The skills worked on the authoring machine only because pi discovers `<cwd>/.pi/skills/` as a project-local skill path when launched from the chezmoi repo. On a fresh `chezmoi apply` from any other CWD, those skills would have been invisible. The harness-config pipeline (`dot_local/share/agent-harness/canonical/skills/`) is the canonical cross-machine path; skills moved there in the same change before commit.

**Alternatives considered:**
- **Project-local schema (openspec/schemas/opsx-superpowers in every project)**: fork-and-customize per project. Loses single-source-of-truth value across the user's many projects.
- **Schema in a separate repo, vendored as a submodule**: extra moving piece. The schema is short enough to live alongside dotfiles.
- **Schema in chezmoi (chosen)**: matches the user's existing convention for cross-machine dev environment.
- **Source-path naming**: original proposal said `dot_openspec/` mapping to `~/.openspec/`. **Corrected during implementation** after reading OpenSpec's `getGlobalDataDir()` source: the resolver looks under `${XDG_DATA_HOME:-~/.local/share}/openspec/schemas/<name>/`, NOT `~/.openspec/schemas/<name>/`. Source path is therefore `dot_local/share/openspec/schemas/opsx-superpowers/`.

**Rationale:** The user explicitly requested chezmoi persistence. The `dot_local/share/openspec/` source path is the standard chezmoi mapping for the XDG_DATA_HOME location OpenSpec actually uses. Skills go at `dot_local/share/agent-harness/canonical/skills/` per the established canonical-skills-symlinked-into-each-harness pattern (verified in `dot_local/user_scripts/executable_apply_harness_config.sh` `link_skill_dirs` calls at lines 338, 440, 482, 494).

### D9: New clarify-spec skill, not a fork of an existing one

**Choice:** Create `dot_local/share/agent-harness/canonical/skills/clarify-spec/SKILL.md` with three references files. Do not bake the procedure into `openspec-propose` directly.

**Alternatives considered:**
- **Inline in `openspec-propose`**: simpler; couples propose to the clarify procedure.
- **Standalone skill (chosen)**: reusable from `openspec-apply-change` (e.g., rerunning clarify after specs are amended mid-implementation) and from manual invocations (e.g., the user wants to clarify an existing spec without driving a full propose flow).

**Rationale:** The three-pass procedure is general enough to warrant its own skill. Keeps propose lean.

### D10: Backward compatibility via schema-name detection

**Choice:** Every opsx-* skill checks the resolved schema name returned by `openspec status --change <name> --json`. If `opsx-superpowers`, run the new path. If `spec-driven` (or anything else), run the current path.

**Alternatives considered:**
- **Replace existing behavior**: simplest implementation; breaks every existing project not opted in.
- **Add a new family of `opsx-superpowers-*` skills**: clean separation; doubles the skill surface area.
- **Schema-name detection (chosen)**: one skill, two code paths. No new files; minimal new prose; user can A/B-test on different projects.

**Rationale:** The user has multiple active projects. They must remain unaffected unless explicitly opted in. Schema-name detection is the smallest mechanism that achieves this.

## Risks / Trade-offs

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Schema-on-default-spec-driven-projects: confused state if user accidentally invokes new path | Low | Medium | All opsx-* skills detect schema name first; explicit "feature off" log line when default schema is in use |
| Scale-XS bypass: user picks XS for non-trivial work and skips quality gates | Medium | Medium | Schema's README documents Scale tiers with examples per tier; openspec-propose's Scale prompt includes Fowler-cited examples |
| Markdown review fatigue (Fowler critique): 9 artifacts per change is more verbose than 4 | High at Scale L/XL, Low at XS/S/M | Medium | Templates kept ≤80 lines each; tables preferred over prose; Scale-adaptive skipping; the schema README's "When to use Scale X" tables prevent over-ceremony |
| Clarify pass false positives: paraphrase divergence triggered by stylistic vs. semantic differences | Medium | Low | 2-option questions let the user resolve quickly; deferred status preserves progress |
| ADR escape-path breakage if a project moves its `<repo>/adr/` location | Low | Low | Schema's `adr` artifact instruction declares the path expectation; project-local override possible via per-project schema fork |
| Capability-hook mapping drift: a future skill rename breaks the mode→skill lookup | Low | Low | Mode names in `review.md` reference *capabilities*, not skill names; the lookup table in `openspec-apply-change` is the only place that needs to change on a rename |
| User has no `openspec/constitution.md` yet on first non-XS change in a project | High on first use | Low | openspec-propose detects missing constitution and prompts the user with the schema's `constitution-template.md`; XS changes don't require it |
| File-contract enforcement breaks legitimate cross-cutting refactors | Low | Low | Per-task `intent: refactor` lifts the constraints; `allow_new_files: true` permits scaffolding tasks |
| `verify.md` AC↔test grep produces false negatives for tests using non-standard ID conventions | Medium | Low | Test-side exemption marker `# spec-exempt: <reason>`; alternative: ID conventions documented in schema README |
| `mcp_memory_store_memory` of retrospective Promote-candidates ingests over-eagerly | Low | Low | openspec-archive-change prompts per-candidate for confirm/skip; never auto-stores |
| Chezmoi deploys partial schema on `chezmoi apply` interrupt → broken `~/.openspec/schemas/opsx-superpowers/` | Very low | Medium | Tasks include a verification step: `openspec schema validate opsx-superpowers` after deploy; failure surfaces immediately |
| Future OpenSpec version changes schema file format | Unknown | Medium | Pin a minimum OpenSpec version in the schema README; document the version of OpenSpec used during authoring (1.3.0) |

## Migration Plan

- **No migration of existing changes required.** All existing changes in any project remain on whatever schema they were created under (almost certainly `spec-driven`).
- **Per-project opt-in is a single edit:** add `schema: opsx-superpowers` to the project's `openspec/config.yaml`. From that point onward, new changes use the new graph; existing changes finish on their original schema.
- **Rollback**: revert the `openspec/config.yaml` edit. New changes go back to `spec-driven`. No data migration involved.
- **Removal from chezmoi**: delete `dot_openspec/schemas/opsx-superpowers/` and run `chezmoi apply`. Skill detection of `opsx-superpowers` will fail to resolve the schema; affected projects will need to revert their `config.yaml`.

### D11: verify.md and retrospective.md are skill-managed, NOT schema artifacts (added after adversarial review)

**Choice:** Templates ship in the schema (`templates/verify.md`, `templates/retrospective.md`) but neither file is declared in `schema.yaml artifacts:`. `openspec-apply-change` produces `verify.md` at apply end when Verification Mode is `retained-required` or `retained-recommended`. `openspec-archive-change` prompts the user to produce `retrospective.md` from the template at Scale = L (optional) or XL (required) before archive.

**Alternatives considered:**
- **Declare both as schema artifacts (initially chosen, then withdrawn)**: The intent was for `openspec status` to track them as part of the change lifecycle. The adversarial review (Claude Opus 4.7, blind) demonstrated that OpenSpec has no optionality concept (`graph.js isComplete` returns false unless every artifact has a generated file; `getNextArtifacts` marks downstream-unreferenced artifacts `ready` perpetually). Reproduced: with no `verify.md`/`retrospective.md`, `isComplete: false` and both show `"status": "ready"` indefinitely. The naming "dangling dependency = optional" was mythology — OpenSpec doesn't honor that pattern.
- **Skill-managed templates (chosen)**: schema ships the template files; skills know when and how to author them based on review.md modes. `openspec status` reports the 8-artifact graph honestly. The schema's `apply.instruction` documents the skill contract for each post-apply template.

**Rationale:** Honest status reporting > clever graph tricks. The schema graph reflects what OpenSpec mechanically tracks; the apply skill contract documents what additional discipline lives outside that tracking. This also makes it cleaner to skip verify/retrospective entirely on XS/S scales without leaving "ready" artifacts in CLI output forever.

## Open Questions

- Should the `Promote candidates` parser in `openspec-archive-change` infer memory `type` automatically (e.g., bullets under "Decision:" → `decision`, "Learning:" → `learning`) or always ask? Lean: infer with override.
- Should `clarify.md` capture the LLM's confidence per finding (e.g., "ambiguity high / medium / low") to help the user prioritize? Lean: include severity field; default to `medium` if not inferable.
- Should the schema include a `pi-tui-scenario-test` artifact for projects with TUI surface area, or leave that to the project's own per-capability spec? Lean: leave to the project; offer a reusable instruction snippet in `dot_local/share/openspec/schemas/opsx-superpowers/README.md`.
- How should the schema interact with `pi-session-search`'s session digest when a session spans multiple changes? Likely just by referencing the change name in the session's headline; codifying this can wait for evidence.
- Should `verify.md` include a "stale spec detection" check (git log to find specs unchanged since last code change to the same area)? Possibly valuable for spec-anchored discipline; defer until empirically motivated.
- (Adversarial review M3 follow-up) Should the TDD-test-files exemption be extended to OTHER common patterns (e.g., `**/*.test.*`, `**/__tests__/**`)? Currently the exemption matches `tests/**/*` only. Lean: extend the exemption set to match the user's actual test layouts; default safe set: `tests/**/*`, `**/*.test.*`, `**/*_test.*`, `**/__tests__/**`.
- (Adversarial review M6 follow-up) Should Check 6 (constitution sampling) escalate to mandatory exhaustive audit at N > 100 changed files? Currently the schema caps stratified sampling at 1-per-dir-plus-5-random. Lean: no, because changes with N > 100 are themselves a problem; warn the user that the change is too large rather than trying harder to sample it.
