# Follow-ups

**Change:** polish-review-convergence-surfaces
**Created:** 2026-07-03 (first out-of-scope routing)

## Queue

| # | Finding | Severity | Origin (review type, round) | Routing reason | Status |
|---|---|---|---|---|---|
| 1 | `adversarial-review-cycle` SKILL's "Convergent findings (this round)" table performs literal cross-reviewer finding matching — the pattern the convergence discipline's ledger rule avoids. Decide whether that standalone skill should adopt the discipline's max-across-reviewers consolidation or keep its own methodology (it is user-invoked, not loop-dispatched). | P3 | code-review, round 1 (opus) | Out of scope: intent's stated surface is the loop skill / apply ref / code-review template / surface test; adversarial-review-cycle is a distinct skill, and reconciling it is not required to meet this change's frozen intent | open |

| 2 | Worktree-locator bootstrap gap: apply records `Worktree Path`/`Diff Base SHA` only on the opsx branch, but the gate resolves the worktree from the INTEGRATION checkout's review.md — so the extension's plain gate run red-loops on stale main copies until the locator is manually published (commit 750fd1a). Fix belongs in the apply skill (commit locator to integration checkout at worktree creation) and/or gate (fall back to `opsx worktree` convention path). Related: extension kickoff cannot latch pre-existing changes (2026-07-03 session finding). | P2 | gate run, extension continuation (2026-07-03) | Out of scope: apply-skill/gate behavior change, not this change's prose-surface intent | open |

## Waivers

- None.

## Promotion

- (filled at archive)
