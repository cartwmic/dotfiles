# Follow-ups

<!--
Out-of-scope finding queue (opsx-adversarial-review). Skill-managed, NOT in the
schema artifact graph — authored from this template at the lifecycle moment the
FIRST out-of-scope finding is routed. Findings here are advisory for THIS
change: they never gate, never force a fix round.
-->

| # | Finding | Severity | Origin (review type, round) | Routing reason | Status |
|---|---|---|---|---|---|
| 1 | `opsx sweep` root-resolution preamble structurally diverges from `opsx gate`'s (explicit `opsx_repo_main_root` normalization vs gate's helper-internal normalization); converges in all tested/documented invocation shapes (independently re-verified R2). Factor a shared root-resolution helper. `dot_local/bin/executable_opsx` | P2 | code-review round 1 (sonnet) | Not required for the frozen intent's outcomes — no observable behavior differs in any documented invocation; pure latent-divergence refactor | open |
| 2 | SWEEP-HIT line malformed for binary-file hits (`git grep` emits `Binary file X matches`, awk yields stray-colon line); exit code + GATE-FAIL still correct — no false pass. Fix: `git grep -I` (skip binaries, matches prose intent) or shape-guard. `dot_local/bin/executable_opsx` opsx_sweep_run | P2 | code-review round 2 (sonnet) | Output-format nit on a narrow input class; detection + gating behavior correct; not required for intent outcomes | open |
| 3 | `opsx sweep` adopts a valid `opsx/<change>` worktree without the gate's `[ -d change-dir ]` guard — pathological pre-artifact branch could soft-pass while gate correctly falls back + fails. Mirror the gate's guard. | P3 | code-review round 2 (opus) | Unreachable in the documented flow (worktree branches after artifacts commit); gate is the enforcement backstop | open |
| 4 | `awk -v p="$pat"` C-escape-mangles backslash-bearing patterns in SWEEP-HIT display (match itself uses the verbatim pattern; exit codes correct). | P3 | code-review round 2 (opus) | Display-only cosmetic | open |
| 5 | SKILL.md sweep-before-round-1 directive lacks the `(with --worktree <path> when worktree-required)` parenthetical the gate directive carries. | P3 | code-review round 2 (sonnet) | Documentation-parity nit; resolution converges in all healthy topologies | open |

## Waivers

- (none)

## Promotion

- (pending archive)
