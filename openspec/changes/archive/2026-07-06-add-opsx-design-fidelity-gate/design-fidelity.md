# Design Fidelity — add-opsx-design-fidelity-gate

<!--
Sealed fidelity verdict. Dogfood note: this change SHIPS the
templates/design-fidelity.md template; this artifact is hand-sealed to the
delta's own contract (Design Fidelity Artifact Template) since the template
lands at apply. Bounded judge contract: rows block only on clear
non-entailment of the AC as written; ambiguity routes to Advisory Findings.
Re-judgments are full sweeps — never delta-scoped, no cross-round finding
matching.
-->

**Fidelity:** delivered
**Judge Provenance:** pi-subagents delegate adapter; review_mode: adversarial-multimodel (claude-bridge/claude-opus-4-8 + claude-bridge/claude-sonnet-5, review role)
**Attested HEAD:** 2ba9951b0808320e34797bf108e2ef1d43408e69
**Attested Path:** /Users/cartwmic/.local/share/chezmoi

**Digest sha256 (intent.md):** e217a707d75b6a39368fd5b7977f63b0f72dc3d88afef791c049939208d94f57
**Digest sha256 (design.md):** 500c7752db03c350b504e08d79c080c5769460bd1f959fc775bac447900994ea
**Digest sha256 (specs/opsx-gate-enforcement/spec.md):** 44b16bed5393ae5980fd2ba1c5519439b2e0d0a3d3167519d75e04f7daf51fa1
**Digest sha256 (specs/opsx-adversarial-review/spec.md):** af8735e064762ff208764973fd9db3196da558ef927b1301e557584156c7a784
**Digest sha256 (specs/opsx-workflow-schema/spec.md):** a82695e221c8b0e3cf001703ea3fcb3d4dbe7b8734f78c76dc654791cedb25d6
**Digest sha256 (specs/opsx-skill-integration/spec.md):** bd8005c329e174b0483a299b2b1854ba2059968401181a83a75d42370b462c91
**Digest sha256 (specs/opsx-loop/spec.md):** a7ec80f36564ed66cd5bd9d7a1a9dd15ca2a8334746ca1c274d8895eb6acdda3
**Digest sha256 (specs/opsx-cli/spec.md):** 4563b8bcaa4ef1217924175edf0dd29cc3c6ccaa1bc8aa9272c687216edb6657

## Per-AC verdict table (round 9 consolidated — key-indexed worst-of across both judges; uniformly-entailed scenario groups collapsed per requirement)

| # | Capability / Requirement (AC group) | Verdict | Evidence |
|---|---|---|---|
| 1 | gate-enforcement / Design Fidelity Verdict Enforcement (10 scenarios) | entailed | D1 (committed main-root digest recompute + field read, set-equality C6, literal digest keys, fail-closed enumeration, review_mode vocabulary) + D3 (waiver) |
| 2 | gate-enforcement / Worktree Mandatory Gate Enforcement (3 scenarios) | entailed | D7(a)(b) + C8 migration shape; key-parse-not-grep pinned in D1 |
| 3 | gate-enforcement / Post Seal Bookkeeping Non Staling (3 scenarios) | entailed | D8 structural HEAD-binding + committed-read (scale/full_rigor included) + misplacement backstop |
| 4 | gate-enforcement / Required Artifact By Scale (MOD — fidelity slot) | entailed | D1 guidance-order slot (unconditional cheap check, analyze→tasks, not doneness rc-gated) |
| 5 | gate-enforcement / Manifest Validation Execution (MOD) | entailed | D7 worktree-only (see Advisory Findings #1) |
| 6 | gate-enforcement / Migration Sweep Gate Check (MOD) | entailed | D7 + main-root resolver pattern |
| 7 | gate-enforcement / Verdict Freshness And Provenance (MOD — fidelity attestation) | entailed | D2 (40-hex literal, no range, digest-carried freshness) |
| 8 | gate-enforcement / Land Base Currency (MOD) | entailed | D7(c) |
| 9 | adversarial-review / Design Fidelity Judge (8 scenarios) | entailed | D2 (channels, worst-of consolidation, canonical AC keys, review role) + D4 (ledger valve, waiver streak-break) |
| 10 | adversarial-review / Findings File Sole Verdict Source (3 scenarios) | entailed | D5 |
| 11 | adversarial-review / Reviewer Tree Identity Attestation (MOD — 9 scenarios) | entailed | D2 purpose-keyed carve-out; post-impl unconditional |
| 12 | adversarial-review / Read Only Reviewer Dispatch (MOD — 8 scenarios) | entailed | D6 (dual-tree, narrow exclusion, judged-input voiding, carve-outs, symmetric restore) |
| 13 | adversarial-review / Orchestrator Round Ledger (MOD — fidelity host) | entailed | D4 (review.md host, pinned columns, append-only, waived rows) |
| 14 | adversarial-review / Post Apply Code Review Artifact (MOD) | entailed | D7 |
| 15 | workflow-schema / Design Fidelity Artifact Template (2 scenarios) | entailed | D1 (field set + digest grammar + Advisory Findings section) |
| 16 | workflow-schema / Mode switchboard in review.md (MOD) | entailed | D7 |
| 17 | workflow-schema / Worktree Lifecycle Ownership (MOD) | entailed | D7 |
| 18 | workflow-schema / Per-task file contracts (MOD) | entailed | D7 |
| 19 | workflow-schema / Apply-time writeback and workspace discipline (MOD) | entailed | D7 + D8 |
| 20 | skill-integration / Worktree Always Skill Discipline (3 scenarios) | entailed | D7 + D8 backstop |
| 21 | skill-integration / Mode-driven openspec-apply-change (MOD) | entailed | D7 |
| 22 | skill-integration / Analyze gates tasks generation (MOD) | entailed | D1/D2 pre-tasks gating |
| 23 | opsx-loop / Worktree resolution convention fallback (MOD) | entailed | D7 |
| 24 | opsx-cli / Migration Completeness Sweep Command (MOD) | entailed | D7 + main-root resolver |

No blocking `not-entailed` or `not-covered` rows. Prior rounds' blocking rows
(R1 valve substrate, R3 escalation host, R5 window exclusion, R7 review_mode
vocabulary, R8 guidance-order slot) were resolved by design/delta fixes and
re-judged as full sweeps — history in review.md's Fidelity Round Ledger.

## Advisory Findings (ambiguity-routed, non-blocking)

1. Manifest Validation Execution cwd guarantee is entailed by D7's general
   worktree-only principle rather than a separately named mechanism
   (R9 sonnet Part B #5 — discoverable, not nominal; routed advisory).
2. Pre-worktree judged-input committed-vs-working-tree divergence: judge
   reads working tree, digests bind committed content; self-heals on commit
   (R9 opus F1). Apply-time pin recorded in analyze.md residuals.
