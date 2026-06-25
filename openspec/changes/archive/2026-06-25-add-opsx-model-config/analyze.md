# Analyze Findings

**Mode:** adversarial-review-cycle (Scale L)
**Generated:** 2026-06-23

## Check 1 — Constitution compliance
| Principle | Status | Rationale |
|---|---|---|
| II canonical path | compliant | opsx-models CLI, extension, skills at chezmoi source paths |
| III no secrets | compliant | model ids are not secrets |
| V mise tools | compliant | yq already a mise tool; no new install |
| IX skill edits ≥ M | compliant | edits openspec-loop/propose/apply → adversarial review (this artifact) + gating post-impl code-review |

## Check 2 — EARS pattern check (current B+provider surface)
| # | Match | True positive? | Note |
|---|---|---|---|
| E1 | author-marker: "WHILE author configured … IF no `<!-- authored: in-session -->` … THEN fail" | yes | correct WHILE/IF/THEN error form |
| E2 | provider: "WHILE bare id + provider configured … THEN print `<provider>/<id>`" | yes | correct state-driven form |

## Check 3 — AC↔design coverage
| Capability | Design | Status |
|---|---|---|
| opsx-model-config | D1 (resolver+provider), D2 (author-in-session), D4 (marker) | covered |
| opsx-gate-enforcement (delta) | D4 (author-marker check) | covered |
| opsx-skill-integration (delta) | D1,D2 | covered |
| opsx-workflow-schema (delta) | D1 | covered |
| opsx-loop-kickoff (delta) | D1 | covered |
| (D3 = decision to NOT add a provenance gate — no AC, by design) | D3 | n/a |

## Check 4 — design↔ADR candidates (Scale ≥ L)
| Decision | 4-point | ADR? |
|---|---|---|
| D2 author-in-session | 4 | yes (promote at archive) |
| D3 NO post-hoc provenance gate (ceiling) | 4 | yes (promote at archive — records why forcing is out of scope) |
| D1 resolver CLI + provider | 3 | follows ADR-0005 (note) |
| D4 self-attested author marker | 2 | no |

## Check 5 — Duplicate detection
| # | Locations | Action |
|---|---|---|
| — | none | the gate delta is the In-Session Authoring Marker Check only; author-in-session POLICY (model-config) vs the marker GATE CHECK (gate-enforcement) are intentionally split, not duplicated |

## Check 6 — Implementation language in specs
| # | AC | Note |
|---|---|---|
| Imp1 | role-model-resolver | `opsx-models`, env var names are the capability's public interface — acceptable |

## Check 7 — Unresolved clarify findings
| # | ref | Status |
|---|---|---|
| — | A1,A2,I1,C1,C2 | all answered |

## Adversarial review appendices

Round 1: blind reviewers opus-4.8 (claude-bridge) + gpt-5.5, review-plans skill, no cross-talk. Both REQUEST-CHANGES; strongly convergent. All applied to specs/design/clarify/proposal:

| Theme | Reviewers | Sev | Resolution |
|---|---|---|---|
| Built-in default masks "unconfigured" → gate/consumer can't tell unset from default | opus P0-1, gpt F-001 | P0 | Source-aware resolver: unset = empty stdout; `--json {value,source}`; gate enforces only source≠unset/default |
| Enforcement opt-in: missing stamp bypasses the check (the original bug class) | opus P0-2, gpt F-002 | P0 | FAIL-CLOSED: configured role + missing/unverifiable stamp = fail, not pass |
| Adapter actual-model proof unspecified | gpt F-003 | P1 | Stamp schema `{role,requested_model,actual_model,adapter,harness}`; unverifiable → fail |
| Suffix match fails its own `4.8`↔`4-8` example + collides | opus P1-1, gpt F-005 | P1 | Exact provider-qualified ids + explicit `aliases:` table; no suffix matching |
| Exporter vs gate `--change` resolution mismatch → false fail | opus P1-2 | P1 | Extension resolves via `opsx-models --json --change <name>` (same inputs as gate) |
| `OPSX_REVIEW_MODELS` delimiter undefined | opus P1-3, gpt F-007 | P1 | Newline/comma-delimited, trimmed, empty=unset, order preserved |
| Provenance schema (artifact/key/shape) undefined | opus P1-4 | P1 | Specified in model-provenance-enforcement + stamp schema |
| Author-in-session policy-only, undetectable on recurrence | opus P1-5, gpt F-004 | P1 | `authored: in-session` marker + gate fails delegated-stamp/no-marker authoring artifacts (D4) |
| `author_in_session` propagation + delegated-author not gate-checked | opus P1-6, gpt F-008 | P1 | Export `OPSX_AUTHOR_IN_SESSION`; gate covers author role on opt-in; flag in front-matter + config files |
| Review subset passes (3 configured, 1 ran) | opus P2-1, gpt F-006 | P2 | Required set: every configured review model must have a matching stamp |
| List cross-layer merge replace vs union | opus P2-2 | P2 | Highest layer fully replaces |
| Missing-resolver behavior | opus P2-3 | P2 | Fail-closed for configured roles |
| Extension parsing config itself (2nd impl) | gpt F-009 | P2 | Must invoke `opsx-models`, not re-parse config |
| Resolver edge cases (missing change/review.md, project root) | gpt F-010 | P2 | Fall-through + invalid-root exit non-zero (layered-resolution scenarios) |

Round 2 (re-validation): opus 0 P0/2 P1, gpt 3 P1 — convergent cleanup of round-1 edits. All applied:

| Theme | Reviewers | Resolution |
|---|---|---|
| Stale lenient/suffix/warn language left in design Risks/Migration/Open-Questions | opus P1-1, gpt P1-2 | rewrote to EXACT+alias+fail-closed everywhere |
| `author_in_session` had no resolver surface | gpt P1-1 | added `opsx-models author-in-session --json` {value:boolean,source} |
| In-session marker writer contradiction (adapter doesn't run when not delegated) | opus P1-2 | writer = the in-session authoring STEP (parent session), not the adapter; tasks 3.2 updated |
| gate-enforcement spec omitted the author-marker check | opus P1-2 | added In-Session Authoring Marker Check requirement + scenarios |
| resolver-absent under-specified | gpt P1-3, opus note | fatal `model-resolver-unavailable` check when provenance checking enabled |
| "a role model is configured" ambiguous | opus P1-2 | disambiguated to the `author` role specifically |

Round 5 (provenance source RE-SCOPE — user steer): provenance moved from an agent-written
opsx artifact stamp → pi-subagents NATIVE run-history (`RunEntry.{model,requestedModel,cwd}`,
runner-observed actual model). Gate now READS `~/.pi/agent/run-history.jsonl` and correlates by
worktree `cwd` + Diff Base time window. Rationale: the worker the gate constrains must not
write the provenance it is judged by (the self-attestation hole). Decoupled — RunEntry carries
NO opsx role tag; companion pi-subagents change adds the native fields. New design points:
the original draft used required-set + global-union foreign-exclusion. clarify C3/C4 added.

Round 5 (re-scope review, opus blind; gpt rate-limited — deferred to round 6): opus
REQUEST-CHANGES, 2 P0 + 4 P1 + 5 P2. Both P0s correct and applied:
- **P0-2 (binding):** model-presence in the worktree window was decoy-bypassable (a 1-token
  decoy run on the configured model passes while real work runs cheap). FIX (user steer): bind
  each delegated role to a stable native `agent` identity (`opsx-author`/`opsx-review`/
  `opsx-impl`) + foreign-WITHIN-ROLE — catches accidental wrong-model with even one role set and
  closes the decoy. Global-union carve-out dropped. Residual disclosed (off-mechanism work fails
  required-set).
- **P0-1 (window/which-review):** pinned the lower bound to the worktree branch-point commit
  time; review provenance scoped to apply-phase `code-review` runs (pre-impl analyze review in
  main cwd is out of scope).
P1s applied: P1-1 durable per-change snapshot (`<worktree>/.opsx/run-history.jsonl`) over the
LRU-rotated global log; P1-2 `OPSX_RUN_HISTORY_PATH` test seam; P1-3 cross-harness =
`model-provenance-unenforceable` WARN+skip when no recorder (degrade, not hard-fail); P1-4
canonicalize both observed + configured ids (don't lean on hand aliases). P2s applied: realpath
cwd, enumerated authoring-artifact set, latest-iteration foreign scope, this trajectory row.

## Summary

- Blockers: 0 remaining (round-1 2 P0 + all P1/P2 applied; round-2 0 P0, 5 P1 applied)
- Reviewers: opus-4.8 + gpt-5.5 (rounds 1-2) — REQUEST-CHANGES → all findings applied; round 3 pending convergence check.
- Round 3: opus + gpt convergent on 1 P1 (gate delegated-stamp scenario must carry the author_in_session guard for the opt-out path) + 2 P2 (unknown-role carve-out, marker-on-authoring-artifacts) — all applied.
- Round 4 (final sign-off): opus + gpt-5.5 BOTH APPROVE, 0 P0/P1. Adversarial cycle CONVERGED.

### Convergence trajectory
| Round | P0 | P1 | Verdict |
|---|---|---|---|
| 1 | 2 | 12 | REQUEST-CHANGES |
| 2 | 0 | 5 | REQUEST-CHANGES |
| 3 | 0 | 1 (+2 P2) | REQUEST-CHANGES |
| 4 | 0 | 0 | BOTH APPROVE (pre-rescope) |
| 5 | 2 | 4 | REQUEST-CHANGES (opus; gpt rate-limited) — applied, then superseded |
| 6 | 1 | 2 | REQUEST-CHANGES (opus) — exposed the post-hoc-gate CEILING |
| 7 | — | — | SCOPE CHANGE (user): drop run-history provenance; ship resolver + author-in-session + provider config |
| 8 | 1 | 1 | REQUEST-CHANGES (opus; grok out-of-credits) — provider slash-rule contradiction + analyze stale tables; all applied |
| 8b | 0 | 2 | APPROVE (deepseek-v4-pro, second-model) — confirms provider rule deterministic, no live-provenance contradiction, no drift; 2 P1 (default sentinel, provider layering shorthand) applied |

### Round 6 → 7: the scope decision
Round-6 opus (gpt-class reviewers rate-limited / out of credits) found the round-5 "fix" merely
RELOCATED trust: the per-change snapshot lives in the worker-writable worktree (forge a line or
`rm` to degrade), and the binding `agent` field is worker-chosen (`recordRun(run.agent,…)`) — so
a deliberate same-UID actor bypasses it. Root cause = a post-hoc gate cannot force a model
against an actor that runs as the user. User chose to RIGHT-SIZE: ship the `opsx-models` resolver
(now with PROVIDER config too) + author-in-session-by-default + a cheap self-attested author
marker; DROP the run-history provenance check, the pi-subagents companion dependency, the
snapshot, and agent-identity binding. The observed bug is fixed at the SOURCE (authoring not
delegated). Specs/design/tasks/clarify rewritten to this scope.

- **Gate status:** RE-SCOPED to B+provider and CONVERGED — two-model adversarial: opus-4-8 (round 8, REQUEST-CHANGES → applied) + deepseek-v4-pro (round 8b, APPROVE). All P0/P1 applied; only spec-tightening P2s remain, addressed. READY for tasks/apply. (gpt-codex + openrouter reviewers were unavailable this cycle; deepseek served as the independent second model.)
