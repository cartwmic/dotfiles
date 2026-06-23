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

## Check 2 — EARS pattern check
| # | Match | True positive? | Note |
|---|---|---|---|
| E1 | "IF ... stamped model differs ... THEN ... fail" | n/a | correct IF…THEN error form |

## Check 3 — AC↔design coverage
| Capability | Design | Status |
|---|---|---|
| opsx-model-config | D1,D2,D3,D4 | covered |
| opsx-gate-enforcement (delta) | D3 | covered |
| opsx-skill-integration (delta) | D2,D3 | covered |
| opsx-workflow-schema (delta) | D2 | covered |
| opsx-loop-kickoff (delta) | D1 | covered |

## Check 4 — design↔ADR candidates (Scale ≥ L)
| Decision | 4-point | ADR? |
|---|---|---|
| D2 author-in-session | 4 | yes |
| D3 gate-enforced provenance | 4 | yes |
| D1 resolver CLI | 3 | follows ADR-0005 (note) |
| D4 in-session not stamped | 2 | no |

## Check 5 — Duplicate detection
| # | Locations | Action |
|---|---|---|
| — | none | model-provenance appears in opsx-model-config + opsx-gate-enforcement deltas — intentionally split (policy vs gate check) |

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
| 4 | 0 | 0 | BOTH APPROVE |

- **Gate status:** READY for tasks
