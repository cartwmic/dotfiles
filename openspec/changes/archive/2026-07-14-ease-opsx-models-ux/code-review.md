# Code Review

<!--
Sealed from findings-file-sole-verdict-source:
  /tmp/opsx-cr-ease-opsx-models-ux/r1-sonnet-findings.md
  /tmp/opsx-cr-ease-opsx-models-ux/r1-opus-findings.md
  /tmp/opsx-cr-ease-opsx-models-ux/r2-sonnet-findings.md
  /tmp/opsx-cr-ease-opsx-models-ux/r2-opus-findings.md
  /tmp/opsx-cr-ease-opsx-models-ux/r3-sonnet-findings.md
  /tmp/opsx-cr-ease-opsx-models-ux/r3-opus-findings.md
Quiet round R3 after rebase onto main (P0+P1 = 0) → seal pass.
-->

**Change:** ease-opsx-models-ux
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** anthropic/claude-sonnet-5 + anthropic/claude-opus-4-8 via pi-subagents delegate (fresh, blind)
**Diff Base SHA:** 9debc1e7327158f570e20df6c726bc46bc16edc5
**Reviewed Range:** 9debc1e7327158f570e20df6c726bc46bc16edc5..5c0e3f6d77cc9886bbe35f8c68d5ef48f0bedfd9
**Attested HEAD:** 5c0e3f6d77cc9886bbe35f8c68d5ef48f0bedfd9
**Baseline:** intent.md + proposal + specs + design + plan + tasks status
**Generated:** 2026-07-14

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 1 | 2 | 2 | anthropic/claude-sonnet-5:fail; anthropic/claude-opus-4-8:pass | cc666ebd36384f0445c84c26eacbab4ec27a0ff5 |
| 2 | blind | 0 | 0 | 0 | 3 | anthropic/claude-sonnet-5:pass; anthropic/claude-opus-4-8:pass | b2da2ef86c4eeb77158dd5d4edfc9a4d1925e354 |
| 3 | blind | 0 | 0 | 1 | 2 | anthropic/claude-sonnet-5:pass; anthropic/claude-opus-4-8:pass | 5c0e3f6d77cc9886bbe35f8c68d5ef48f0bedfd9 |

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | fzf `-m` multi-select emitted catalog order, not selection order | P1 | fixed |
| 2 | unguarded `jq` in review write path (implicit dep) | P2 | open |
| 3 | interactive tests forced `OPSX_MODELS_NO_FZF=1` (masked fzf path) | P2 | fixed |
| 4 | bare `opsx models set` role-prompt path untested hermetically | P2 | open |
| 5 | `append_thinking_suffix` dense `||`/`&&` short-circuit | P3 | open |
| 6 | `models_catalog` trusts columnar `pi --list-models` format | P3 | open |
| 7 | unused local `tgt` / shellcheck nits in interactive path | P3 | open |
| 8 | review lists rewritten flow-style (still `!!seq`) | P3 | open |

Gate-manifest note: diff does not touch `openspec/opsx-gates.yaml`.

## Applied fixes

- R1 P1 → sequential single-select fzf loop + hermetic order test (`5c0e3f6` post-rebase)
- R3 = freshness re-review after rebase onto main for archive land-base currency

## Residual risks

- Implicit `jq` on review write (P2 #2) — already required by `opsx models list`
- Columnar `pi --list-models` drift (P3 #6) → empty-catalog actionable error

## Verdict rationale

Round 1: sonnet fail on P1 fzf order; fix landed. Round 2: quiet pass.
Round 3 (post-rebase HEAD `5c0e3f6`): both reviewers attested worktree path + HEAD,
**pass**, P0+P1=0. Suites green (models 46/46, cli 67/67). Residual P2/P3 advisory only.
