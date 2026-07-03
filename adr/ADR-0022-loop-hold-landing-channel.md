# ADR-0022: loop_hold front-matter is the landing channel; only human named re-arm clears it

**Status:** Accepted
**Date:** 2026-07-03
**Source change:** `openspec/changes/harden-opsx-loop-latch-and-stop/`

## Context

Agents had no invokable loop-stop: `clear` is a TUI slash command, so decision-audit
and terminal landings depended on agent prose plus stall-guard burn (3 wasted turns
minimum, and directive-sensitive). The review-convergence discipline's "halt loop
continuation" was unenforceable agent-side.

## Decision

review.md front-matter gains `loop_hold: true` + `loop_hold_reason`, written to the
INTEGRATION-checkout copy (the one the loop host resolves — a worktree-only write
split-brains the hold into invisibility). The extension checks it at `agent_end`
before injecting any continuation and disarms with the reason. Setting requires no
privilege (fail-safe direction; honored even with an empty reason). Clearing happens
ONLY via explicit named re-arm `/opsx-loop <change>` — a human-only slash command —
which strips the fields BEFORE the turn-0 gate check, surfaces the stored reason, and
appends an Execution Notes audit line. Goal kickoff never clears any hold.

## Consequences

- The same human-only channel property that stops agents halting the loop stops them
  un-halting it — symmetry is the security argument.
- Rejected: sentinel file (unversioned, outside the structured-field convention);
  pi keyword/tool (harness-coupled, ADR-0007 violation); manual front-matter edit as
  the clear path (ceremony mismatch; only prose would stop agent self-clearing).
- Deferred seam: soft/hard hold tiers (front-matter cannot verify an audit ruling
  happened; the reason string carries the audit pointer).
- Gate stays ignorant of hold state by spec.
