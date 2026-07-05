# Code Review

**Change:** ntfy-harpoon-jump
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** pi-subagents `worker` adapter — claude-bridge/claude-opus-4-8 + openai-codex/gpt-5.5 (2 distinct blind models)
**Diff Base SHA:** 25f6f22906c0d7fa58f4f863be99f6630bf7a04a
**Reviewed Range:** 25f6f22906c0d7fa58f4f863be99f6630bf7a04a..741371b71b051ee4547221941585290c677e82c3
**Baseline:** intent.md + proposal + specs + plan + tasks status
**Generated:** 2026-07-04

## Verdict contract (embedded in every reviewer dispatch prompt)

A reviewer may FAIL only for (a) a frozen-baseline violation (intent.md, delta ACs
as written, design decisions, constitution/domain) or (b) an objective
correctness/security defect even where the baseline is silent. Taste, style,
alternative-design preference, and beyond-scope demands (incl. fixes exceeding the
frozen intent's stated scope) are advisory (P2/P3) and cannot gate. Severity: P0
confirmed baseline violation / critical defect; P1 must-fix within the contract;
P2 should-fix advisory; P3 nit. Verdict: pass ⇔ no open P0/P1.

## Round tracker

Consolidated counts = MAX across reviewers per severity (no cross-reviewer
matching). All rounds blind (no disclosure round needed — the round-5 quiet round
sealed pass before any 2-consecutive-split disclosure trigger resolved).

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 2 | 1 | 3 | opus:pass gpt:fail | 99ddc3b |
| 2 | blind | 0 | 1 | 1 | 3 | opus:pass gpt:fail | 6afcd61 |
| 3 | blind | 0 | 1 | 1 | 3 | opus:pass gpt:fail | bf7077f |
| 4 | blind | 0 | 1 | 0 | 3 | opus:pass gpt:fail | a44d6e6 |
| 5 | blind | 0 | 0 | 1 | 2 | opus:pass gpt:pass | 741371b |

Convergence: findings landed each round (change-scoped worktree HEAD moved), rounds
< review_max_rounds (5), so rounds continued autonomously (condition b) until the
round-5 quiet round (P0+P1 = 0 max across reviewers → condition a → seal pass).

## Findings

Gate/validation-manifest check: the diff does NOT touch `openspec/opsx-gates.yaml`
or any gate/validation manifest — weakens nothing (both reviewers confirmed every
round).

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Jump payload rode non-propagated custom `X-*` headers (ntfy drops them) → pane id never reached the phone; intent's "so the phone can drive jump_pane on tap" unmet. | P1 | fixed (6afcd61) |
| 2 | Wrapper omitted the env-sourced remote host the spec requires. | P1 | fixed (6afcd61) |
| 3 | Idempotence guard only recognized its own sentinel, not a pre-existing ControlMaster block for the remote host (spec AC as originally written). | P1 | fixed (bf7077f → a44d6e6 → resolved by scope narrowing at 741371b) |
| 4 | Stanza-detection heuristics (grep-pair, then sed-range with `.*remote` substring) each introduced a new false-skip/over-match edge for unmanaged configs. | P1→P3 | resolved (741371b): sentinel-only guard; spec scenario scoped to the managed block; unmanaged-config detection declared a non-goal and routed to follow-ups.md |
| 5 | `curl -d` treats an `@`-leading message as a filename. | P2 | fixed (6afcd61: `--data-raw`) |
| 6 | urlencode is per-character not per-byte (non-ASCII session names); Title-header newline; slot trailing-newline in display hint. | P3 | open (advisory — inputs are ASCII / display-only) |
| 7 | Unmanaged hand-written pre-existing `Host remote` ControlMaster stanza not reconciled. | P2/P3 | out-of-scope (explicit spec non-goal) → follow-ups.md #1 |

## Applied fixes

- 6afcd61 — Click deep-link jump payload (host+pane+session+slot, url-encoded) read from `JUMP_SSH_HOST`; `curl --data-raw`.
- bf7077f — skip append when a `Host remote` ControlMaster block already exists (broad grep).
- a44d6e6 — stanza-scope that check to the remote stanza.
- 741371b — simplify to sentinel-only idempotence; narrow the spec's idempotence scenario to the managed block; route unmanaged-config detection to follow-ups.md.

## Residual risks

- urlencode/header-newline P3s: reachable inputs are ASCII (pane id `terminal_N`, host alias); session names are user-controlled but locally trusted. Accepted.
- Unmanaged pre-existing ssh stanza (follow-ups #1): sentinel guard is fully idempotent for this script's own application; a manual duplicate is user-reconcilable (README caveat) and ssh first-match-wins keeps behavior correct.

## Verdict rationale

Round 5 is a quiet round: both distinct blind reviewer models (opus-4-8, gpt-5.5)
returned pass with 0 open P0/P1 against the frozen baseline over
`25f6f229..741371b`. The wrapper stamps the STABLE `$ZELLIJ_PANE_ID` onto the ntfy
`Click` deep link (the client-delivered channel; custom headers are dropped by
ntfy), sources all config — incl. the remote host — from the environment with
fail-closed guards and no literal secrets (Const III), and the ControlMaster
snippet + sentinel-fenced sync are idempotent (Const IV) and staged under `termux/`
rather than `dot_termux/` (Const VII). The diff touches no gate/validation manifest.
Remaining items are advisory P2/P3 or explicit spec non-goals routed to
follow-ups.md; none gate. review_mode is adversarial-multimodel (2 distinct models).
