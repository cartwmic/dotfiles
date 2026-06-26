<!-- authored: in-session -->
# Analyze Findings

**Mode:** adversarial-review-cycle
**Generated:** 2026-06-25 by openspec-propose (opsx-superpowers, Scale L) — adversarial review by claude-bridge/claude-opus-4-8 + openai-codex/gpt-5.5

## Check 1 — Constitution compliance

| Principle | Status | Rationale | Severity |
|---|---|---|---|
| I. Chezmoi single source of truth | compliant | New `executable_opsx` + `.chezmoiremove` express both the add and the removals in source; no out-of-band machine edits | — |
| II. Skills in canonical pipeline | compliant | Skill edits are to `dot_local/share/agent-harness/canonical/skills/**`; deployed via `apply_harness_config.sh` | — |
| III. No secrets | compliant | No credentials touched | — |
| IV. Idempotent install | inapplicable | No install scripts added | — |
| VIII. openspec/ not deployed | compliant | Change lives under `openspec/`; only `dot_*` paths deploy | — |
| IX. Skill edits → adversarial review | compliant | Canonical skill edits present → two-model adversarial review run (this artifact); Scale L | — |
| Domain inv. 8 (`bin/` allowlist) | compliant | `dot_local/bin/` already allowlisted; new `executable_opsx` deploys | — |

## Check 2 — EARS pattern check (major, human-triage)

| # | File | AC | True positive? | Note | Status |
|---|---|---|---|---|---|
| E1 | opsx-cli, opsx-loop-kickoff, opsx-model-config | all error/unwanted paths | no | All error paths use `IF … THEN` (invalid role/layer/boolean, project-root-not-found, failed write, neither-verb-nor-role, judge failure). No `WHEN … <error>` violations. | clear |

## Check 3 — AC↔design coverage

| AC ID | Design ref | Status |
|---|---|---|
| opsx-cli.unified-subcommand-dispatch | D1 | covered |
| opsx-cli.hard-cutover-no-legacy-entrypoints | D2, Migration Plan, verify scan | covered |
| opsx-cli.model-config-write-surface | D3 | covered |
| opsx-loop-kickoff.argument-parsing-preserves-full-input | D5 | covered |
| opsx-loop-kickoff.stall-detection-stops-the-loop | D5 | covered |
| opsx-loop-kickoff.model-config-subcommand | D4 | covered |
| opsx-loop-kickoff.opsx-gate-is-the-deterministic-judge (MOD) | D5 (worktree re-resolve) | covered |
| opsx-{gate-enforcement,model-config,workflow-schema,loop-orchestration,skill-integration} (MOD renames) | D6 | covered |

## Check 4 — design↔ADR promotion candidates (Scale ≥ L)

| Decision | ADR? | Rationale |
|---|---|---|
| D1 single `opsx` multitool + hard cutover (folds D2 removal mechanism, D6 spec-migration trade-off) | **YES** | Lasting, reasonable disagreement (libexec vs single-file), constrains future CLI structure; supersedes the implicit one-script-per-tool pattern. Promote post-archive as a new ADR. |
| D3/D4/D5 write surface, wrapper, bug fixes | no | Implementation detail; specced |

## Check 5 — Duplicate detection

No duplicate requirements. The write surface lives only in `opsx-cli`; model-config reserves the verbs but does not restate the write contract. Stall/worktree/parser logic is only in `opsx-loop-kickoff`.

## Check 6 — Implementation language in specs

Specs describe WHAT (subcommand dispatch, atomic write, normalized stall key) not HOW, except where a mechanism is contractually required and observable (temp+rename atomicity, `check_id`-set stall key, `$OPSX_ROOT`/git-toplevel project discovery) — these are testable contracts, acceptable.

## Check 7 — Unresolved clarify findings

None. clarify.md: 0 unanswered, 0 deferred.

## Outstanding risks

- R6 (design): hard-cutover blast radius for out-of-repo callers — accepted owner choice, documented.
- The HEAD-or-change-dir-edit stall progress signal is heuristic; preserved-worktree + human notify on false-halt keeps it recoverable.

## Summary

**Blockers: 0. Majors: 0.** Two adversarial rounds, both models, converged. Ready for review + tasks.

---

## Appendix A — Adversarial review rounds

### Round 1 — REQUEST-CHANGES (both)
- opus: P0×1, P1×4, P2×6. gpt: P0×0, P1×5, P2×6.
- Converged blockers: (1) spec-of-record left stale + legacy-token scan tripping on `openspec/specs/**`; (2) model-config reject-arg AC vs new `set/get/list` verbs; (3) opsx-loop-kickoff half-migrated (Single-command guaranteed loop + req title); (4) stall key undefined + defeated by per-turn worktree refresh; (5) `author-in-session` readable but not settable.
- **All resolved:** full-content MODIFIED deltas for 5 reference capabilities (D6); reserved-verb precedence in model-config + opsx-cli; Single-command guaranteed loop migrated, req-name kept as AC-ID key; stall keyed on `check_id` set + progress signal + four reset paths; `author-in-session` made settable (key map + boolean coercion). P2s: set-review warn, get `--layer` round-trip, atomic-failure IF/THEN, project-root discovery, single-file guardrails, exact verify commands, clarify→scenarios, rollback orphan, `opsx loop` consumer, migration inventory — all applied.

### Round 2 — convergence
- opus: **APPROVE**, P0×0/P1×0/P2×4. gpt: P0×0/P1×0/P2×2 (verdict REQUEST-CHANGES but P2-only; the reviewer subagent crashed post-write on an unrelated pi-session-search stale-ctx bug — verdict file intact).
- R2 P2s **all applied:** stall progress broadened to credit uncommitted change-dir edits (false-halt fix); token-level verify scan including the `opsx-loop` driver; pi wrapper passes repo cwd/`OPSX_ROOT` for `--layer project`; invalid-boolean reject for `set author-in-session`; `get author-in-session` effective-default-`true` vs raw-`--layer` scenario; unset-empty narrowed to scalar roles.
- **Net: 0 P0 / 0 P1 across both models; all P2 polish applied.**

### Flag (next phase)
`intent.md` (frozen baseline) + `tasks.md` must exist before `opsx gate` runs (Scale L). Authored in the apply setup.
