# Code Review

**Change:** preserve-opsx-loop-across-native-retries
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** openai-codex/gpt-5.6-sol via pi-subagents; claude-bridge/claude-opus-4-8 via pi-subagents
**Diff Base SHA:** a5cc8de5040107e121a199caf845358a395b98d0
**Reviewed Range:** a5cc8de5040107e121a199caf845358a395b98d0..f4d2173a342da91cba4064543ee74de54556e001
**Attested HEAD:** f4d2173a342da91cba4064543ee74de54556e001
**Baseline:** intent.md + proposal + specs + plan + tasks status
**Generated:** 2026-07-14

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---:|---:|---:|---:|---|---|
| 1 | blind | 0 | 0 | 1 | 2 | gpt-5.6-sol:pass claude-opus-4-8:pass | f4d2173a342da91cba4064543ee74de54556e001 |

One Opus output with malformed severity-field labels was excluded and re-dispatched at the same HEAD. Pre-rebase verdicts remain superseded by rewritten SHAs.

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Sealed evidence needed post-main-advance SHA refresh; this artifact and trailing verify refresh provide it. | P2 | fixed |
| 2 | Lifecycle compatibility remains bound to Pi 0.80.6 event ordering; rerun s07-s17 after Pi upgrades. | P3 | deferred |
| 3 | Exact replacement directive matching assumes Pi preserves queued user text verbatim. | P3 | deferred |

## Validation evidence

- Helper tests: 94 pass, 0 fail.
- Real Pi TUI suite: 18 pass, 0 fail, 0 timeout; explicit interrupt enabled path also passes.
- Strict OpenSpec validation, shell/Node syntax, TypeScript bundling, and `git diff --check` pass.
- Unrelated integration commit `542edbe22dc8b34621571729618b5123c333183a` touches only `.gitignore` and zellij status helpers; no opsx interaction.
- No gate, validation manifest, stable capability spec, Constitution, or goal-extension file changed by this capability.

## Applied fixes

- `c66cf07` lineage (rebased in current range) binds Pi-owned overflow compaction cancellation to exact loop settlement.
- Generation, duplicate-rearm, prequeued-user, async-gate, and extension-compaction abort fixes remain present and covered by s12-s17.

## Residual risks

- Rerun lifecycle scenarios after Pi extension lifecycle upgrades.
- A future stable message-identity API should replace byte-exact directive matching if Pi begins normalizing follow-up text.

## Verdict rationale

Both blind reviewers attested current post-main-advance worktree HEAD and found zero P0/P1. Runtime meets frozen retry/settlement/abort/ownership contract, all eighteen TUI scenarios pass, unrelated integration work is path-isolated, and no gate was weakened.
