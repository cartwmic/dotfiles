# ADR-0021: Goal-mode kickoff never latches existing changes; explicit resume is the sole latch

**Status:** Accepted
**Date:** 2026-07-03
**Source change:** `openspec/changes/harden-opsx-loop-latch-and-stop/`

## Context

`/opsx-loop goal <text>` had no defined relationship to pre-existing changes: kickoff
prose told the agent to "use an existing change as-is," but the extension could not
observe an in-prose latch (green change → kickoff re-injection → a machine re-prompt
was misread as human archive authorization on 2026-07-03). Green-vs-goal matching is
undecidable by a deterministic extension: "green change IS the goal" and "green
bystander" are indistinguishable repo states.

## Decision

Goal/conversation kickoff NEVER latches a pre-existing change — it is new-change
distillation by construction. The explicit `/opsx-loop <change-name>` spelling is the
sole latch path (Guard 1 handles the green case). NO goal-text↔change-name matching,
exact or substring: successor goals naturally reference predecessor names as context,
making text matching a false-latch hazard. Mitigation for "user forgot the change
exists": the distill kickoff carries a deterministic active-change inventory
(committed-intent dirs + front-matter status; no gate runs, no model calls) with an
advise-resume instruction.

## Consequences

- Extends the extension's explicit-keywords-over-heuristics grammar decision from
  parse-time to latch-time; extension stays model-free (ADR-0007 lineage).
- Superseded alternatives: green-sweep at distill agent_end (cost/staleness machinery
  for a tie the extension cannot decide), semantic latch (model in extension path).
- Cost: resuming requires knowing the change name (`/opsx-loop` status lists them).
