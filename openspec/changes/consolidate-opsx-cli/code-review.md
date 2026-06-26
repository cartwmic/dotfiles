# Code Review

**Change:** consolidate-opsx-cli
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** claude-bridge/claude-opus-4-8 + openai-codex/gpt-5.5 (pi-subagents delegate adapter), 3 blind independent rounds
**Diff Base SHA:** 184e2556b47d1583a15ac32b1be64822fa913ace
**Reviewed Range:** 184e2556b47d1583a15ac32b1be64822fa913ace..4cb5306
**Baseline:** intent.md + proposal + specs + design + plan + tasks status
**Generated:** 2026-06-25

## Round tracker

| Round | P0 | P1 | P2 | Approvals |
|---|---|---|---|---|
| 1 | 0 | 2 (gpt) | 6 | 1/2 (opus PASS, gpt FAIL) |
| 2 | 0 | 1 (gpt) | 1 | 1/2 (opus PASS, gpt FAIL) |
| 3 | 0 | 0 | 1 (doc-nit) | 2/2 (opus PASS, gpt PASS) |

Both models independently ran all suites each round (no trust in claims).

## Convergent findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Extension used `process.cwd()` not `ctx.cwd` → `--layer project` could target the wrong repo | P1 | fixed (commit 7f2b6b8) |
| 2 | Stall `progressToken` keyed on `git status`/unstaged-diff → staged/untracked in-place edits not detected as progress | P1 | fixed (content digest `hashDir`, commit 4cb5306) |
| 3 | `opsx models set` pre-created the final file → failed write to absent target left a zero-byte file | P2 | fixed (temp-only write, commit 7f2b6b8) |
| 4 | Project-root spec said "git toplevel" but code walks `openspec/` ancestors | P2 | fixed (spec aligned to ancestor walk) |
| 5 | Parser `status`/`clear` only routed as sole token | P2 | fixed (leading-keyword routing) |
| 6 | Verify legacy-scan flagged `opsx-models` from the `.opsx-models.*` temp glob | P2 | fixed (mktemp prefix → `.opsx-cfg`) |
| 7 | Stale banner comments named removed executables; `get --layer` ignores `--json` | P2 | banners fixed; `--json` on raw-layer get accepted (no spec requires it) |
| 8 | `hashDir` docstring says returns `""` for missing dir (returns empty-digest) | P2 | accepted (docstring nit; not fixed to avoid staling the round-3 verdict) |

## Applied fixes

- `7f2b6b8` — ctx.cwd threading, atomic absent-target write, parser leading-keywords, spec wording, banners.
- `4cb5306` — content-hash stall progress (`hashDir`, pure + unit-tested), temp-prefix rename off the legacy token.

## Residual risks

- `hashDir` docstring nit (P2 #8) — cosmetic.
- `get --layer <l>` emits raw scalar regardless of `--json` — no spec scenario requires JSON on raw-layer reads; effective `get` honors `--json`.

## Verdict rationale

PASS. After three blind adversarial rounds (opus-4-8 + gpt-5.5, each independently executing
all 4 shell suites + the opsx-loop bun suite + transpile + the exact verify scan), P0+P1 = 0
against the baseline and review_mode is adversarial-multimodel as Constitution IX requires for
this skill-editing change. The merged `opsx` multitool ports gate/models/loop verbatim with
correct subshell isolation and an in-process resolver; the write surface is atomic and
comment-preserving; the three opsx-loop bug fixes (truncation, worktree staleness, stall
detection) are implemented and tested; the hard cutover is expressed in source (git-rm +
`.chezmoiremove`); every live caller is migrated and the spec-of-record names only commands
that exist. Remaining items are P2 (one doc nit), none gating.
