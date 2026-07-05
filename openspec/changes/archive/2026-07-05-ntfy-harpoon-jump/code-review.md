# Code Review

**Change:** ntfy-harpoon-jump
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** pi-subagents `worker` adapter — claude-bridge/claude-opus-4-8 + openai-codex/gpt-5.5 (2 distinct blind models)
**Diff Base SHA:** 59e2168189d42fd116cd7dbbe3f0ed1f9c737798
**Reviewed Range:** 59e2168189d42fd116cd7dbbe3f0ed1f9c737798..5f02dd1704a9c40e5353423d768824c21ab5d099
**Baseline:** intent.md + proposal + specs + plan + tasks status
**Generated:** 2026-07-05

## Verdict contract (embedded in every reviewer dispatch prompt)

A reviewer may FAIL only for (a) a frozen-baseline violation (intent.md, delta ACs
as written, design decisions, constitution/domain) or (b) an objective
correctness/security defect even where the baseline is silent. Taste, style,
alternative-design preference, and beyond-scope demands (incl. fixes exceeding the
frozen intent's stated scope) are advisory (P2/P3) and cannot gate. Severity: P0
confirmed baseline violation / critical defect; P1 must-fix within the contract;
P2 should-fix advisory; P3 nit. Verdict: pass ⇔ no open P0/P1.

## Round tracker

Consolidated counts = MAX across reviewers per severity. Rounds 1-5 ran at the
original Diff Base 25f6f22 (pre-landing). During archive/landing, a concurrent
session committed the disjoint `harden-opsx-repo-portability` change onto main, so
the branch was merged current and a FRESH review cycle (rounds 6-7) ran at Diff
Base 27fa74e. Round 6 surfaced a real P1 (idempotence-breaking `rm` inside
`run-as`) fixed at c968bfb; round 7 was quiet. The Diff Base was then re-pointed to
current main HEAD 59e21681 for landing; because that base moved only past DISJOINT
harden commits, the impl diff is byte-identical to the round-7 reviewed range and
the round-7 verdict is carried forward (no per-race re-dispatch).

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 2 | 1 | 3 | opus:pass gpt:fail | 99ddc3b (base 25f6f22) |
| 2 | blind | 0 | 1 | 1 | 3 | opus:pass gpt:fail | 6afcd61 (base 25f6f22) |
| 3 | blind | 0 | 1 | 1 | 3 | opus:pass gpt:fail | bf7077f (base 25f6f22) |
| 4 | blind | 0 | 1 | 0 | 3 | opus:pass gpt:fail | a44d6e6 (base 25f6f22) |
| 5 | blind | 0 | 0 | 1 | 2 | opus:pass gpt:pass | 741371b (base 25f6f22) |
| 6 | blind | 0 | 1 | 0 | 2 | opus:fail gpt:pass | df45994 (base 27fa74e, currency merge) |
| 7 | blind | 0 | 0 | 0 | 2 | opus:pass gpt:pass | c968bfb (base 27fa74e) |
| land | reuse (byte-identical impl) | 0 | 0 | 0 | 2 | round-7 carried forward | 5f02dd1 (base 59e21681) |

## Findings

Gate/validation-manifest check: the diff does NOT touch `openspec/opsx-gates.yaml`
or any gate/validation manifest — weakens nothing (every round confirmed).

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Jump payload rode non-propagated custom `X-*` headers → pane id never reached the phone. | P1 | fixed (6afcd61) |
| 2 | Wrapper omitted the env-sourced remote host the spec requires. | P1 | fixed (6afcd61) |
| 3 | Idempotence guard only recognized its own sentinel (spec AC as originally written). | P1 | resolved (scope narrowed to managed block at 741371b) |
| 4 | Pre-existing-ControlMaster detection heuristics kept introducing new false-skip/over-match edges. | P1→P3 | resolved (741371b: sentinel-only; unmanaged-config detection → follow-ups.md non-goal) |
| 5 | `rm -f "$tmp"` ran INSIDE `run-as com.termux` → Termux app uid can't delete the shell-owned /data/local/tmp file → EACCES → with `set -euo pipefail` aborts the sync on every run, breaking Const IV idempotence. | P1 | fixed (c968bfb: move rm outside run-as, mirroring push_file) |
| 6 | `curl -d` treats an `@`-leading message as a filename. | P2 | fixed (6afcd61: `--data-raw`) |
| 7 | urlencode is per-character not per-byte (non-ASCII session names); no-op path bumps config mtime via `touch`. | P3 | open (advisory — inputs ASCII; mtime-only, not a content diff) |
| 8 | Unmanaged hand-written pre-existing `Host remote` ControlMaster stanza not reconciled. | P2/P3 | out-of-scope (explicit spec non-goal) → follow-ups.md #1 |

## Applied fixes

- 6afcd61 — Click deep-link jump payload from `JUMP_SSH_HOST`; `curl --data-raw`.
- bf7077f → a44d6e6 → 741371b — pre-existing-block handling, then simplified to sentinel-only + spec-AC scope narrowing.
- c968bfb — delete pushed tmp OUTSIDE run-as (Const IV idempotence).

## Residual risks

- urlencode/mtime P3s: reachable inputs are ASCII; `touch` bumps mtime only, no content change (Const IV satisfied on content). Accepted.
- Unmanaged pre-existing ssh stanza (follow-ups #1): sentinel guard is fully idempotent for this script's own application; a manual duplicate is user-reconcilable (README caveat).

## Verdict rationale

Round 7 is a quiet round: both distinct blind reviewer models (opus-4-8, gpt-5.5)
returned pass with 0 open P0/P1 against the frozen baseline over the impl diff
(reviewed at base 27fa74e, HEAD c968bfb). The landing Diff Base 59e21681 advanced
only past the disjoint concurrent `harden-opsx-repo-portability` change, leaving
the impl diff byte-identical, so the round-7 verdict is carried forward rather than
re-dispatched per race against the live-moving integration branch. The wrapper
stamps the STABLE `$ZELLIJ_PANE_ID` onto the ntfy `Click` deep link, env-sources
all config incl. the remote host with fail-closed guards and no literal secrets
(Const III), and the ControlMaster snippet + sentinel-fenced sync are idempotent
(Const IV — the run-as tmp-cleanup uid bug is fixed) and staged under `termux/`
(Const VII). No gate/validation manifest is touched. review_mode is
adversarial-multimodel (2 distinct models).
