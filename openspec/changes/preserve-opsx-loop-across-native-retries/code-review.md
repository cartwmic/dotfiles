# Code Review

**Change:** preserve-opsx-loop-across-native-retries
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** openai-codex/gpt-5.6-sol via pi-subagents; claude-bridge/claude-opus-4-8 via pi-subagents
**Diff Base SHA:** a5cc8de5040107e121a199caf845358a395b98d0
**Reviewed Range:** a5cc8de5040107e121a199caf845358a395b98d0..837197238f762427361c299dbde25b2c7f9f41d5
**Attested HEAD:** 837197238f762427361c299dbde25b2c7f9f41d5
**Baseline:** intent.md + proposal + specs + plan + tasks status
**Generated:** 2026-07-14

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---:|---:|---:|---:|---|---|
| 1 | blind | 0 | 0 | 1 | 2 | gpt-5.6-sol:pass claude-opus-4-8:pass | 837197238f762427361c299dbde25b2c7f9f41d5 |

Post-rebase predecessor verdicts are intentionally superseded because rewritten SHAs are non-ancestors. One Opus output with a malformed preamble was excluded and re-dispatched at the same HEAD before consolidation.

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Retained verify/review artifacts must be refreshed after the final runtime fix and rebase. | P2 | fixed by this seal and trailing verify refresh |
| 2 | Lifecycle contract remains tied to Pi 0.80.6 event ordering; rerun s07-s17 after Pi upgrades. | P3 | deferred |
| 3 | Exact directive-text ownership transfer is intentionally coupled to Pi delivering queued user text verbatim. | P3 | deferred |

## Validation evidence

- Helper tests: 94 pass, 0 fail.
- Real Pi TUI suite: 18 pass, 0 fail, 0 timeout (s00-s17).
- s16 proves extension-owned compaction abort injects no recovery.
- s17 enables Pi auto-compaction and proves host compaction abort cannot be restarted from settlement.
- Strict OpenSpec validation and TypeScript bundling pass.
- No gate/validation manifest, stable capability spec, Constitution, or `goal` extension file changed.

## Applied fixes

- `837197238f762427361c299dbde25b2c7f9f41d5` observes Pi-owned overflow compaction cancellation on the exact loop and lands settlement as abort instead of restarting compaction.
- Earlier generation, duplicate-rearm, prequeued-user, and extension-compaction fixes remain present after rebase and are covered by s12-s16.

## Residual risks

- Host lifecycle compatibility must be retested after Pi lifecycle API upgrades.
- Byte-exact replacement directive matching is safe on current Pi and covered by s13/s15, but host message normalization would require a stable message identity API.
- Advisory owner-state cleanup could make current identity guards more defensive; no current deferred effect omits `loop === session`.

## Verdict rationale

Both blind reviewers attested the same post-rebase worktree HEAD and found zero P0/P1. Implementation preserves loop state across Pi-native retry and queued continuation, lands unresolved settlement visibly, bounds overflow, honors explicit abort across Pi-owned and extension-owned compaction, and prevents stale arm generations or queued work from mutating replacement loops. No gate was weakened.
