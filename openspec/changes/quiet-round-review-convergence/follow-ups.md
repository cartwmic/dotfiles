# Follow-ups

<!--
Out-of-scope finding queue (opsx-adversarial-review). Skill-managed, NOT in the
schema artifact graph — authored from this template at the lifecycle moment the
FIRST out-of-scope finding is routed. Findings here are advisory for THIS
change: they never gate, never force a fix round.
-->

| # | Finding | Severity | Origin (review type, round) | Routing reason | Status |
|---|---|---|---|---|---|
| 1 | `opsx sweep` root-resolution preamble structurally diverges from `opsx gate`'s (explicit `opsx_repo_main_root` normalization vs gate's helper-internal normalization); converges in all tested/documented invocation shapes. Factor a shared root-resolution helper. `dot_local/bin/executable_opsx` | P2 | code-review round 1 (sonnet) | Not required for the frozen intent's outcomes — no observable behavior differs in any documented invocation; pure latent-divergence refactor | open |

## Waivers

- (none)

## Promotion

- (pending archive)
