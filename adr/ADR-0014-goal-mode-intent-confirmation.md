# ADR-0014: Goal-mode kickoff pauses for one-shot human intent confirmation

**Status:** Accepted
**Date:** 2026-07-02
**Source change:** direct-edit audit remediation (docs/audits/2026-07-02-opsx-workflow-audit.md, finding 9)
**Supersedes:** — (amends the goal/conversation kickoff behavior from add-opsx-loop-kickoff)
**Superseded by:** —

## Context

`/opsx-loop goal [text]` distills a goal (or the live conversation) into a new OpenSpec
change and previously ADOPTED that change the moment a `intent.md` appeared — arming the
autonomous drive-to-green loop with an agent-authored frozen baseline and no human
checkpoint. But `intent.md` is the immutable baseline every blind reviewer and the
doneness judge (ADR-0012) scores against; letting the loop being scored author AND freeze
its own scoring baseline dilutes the owner's stated control model
(explore → intent **(human)** → loop-to-done) precisely at its only load-bearing
human checkpoint before archive.

## Decision

On detecting the distilled change, the extension STOPS the loop and notifies the user:
review/edit `openspec/changes/<name>/intent.md`, then arm the deterministic-judge loop
explicitly with `/opsx-loop <name>`. The distill directive is correspondingly scoped to
DRAFT the intent baseline only (no implementation in the distill phase). Cost: exactly
one interaction per goal-mode kickoff. `/opsx-loop <change>` (explicit-change mode) is
unchanged — there the human chose the change, and its intent.md was frozen at explore
time.

## Consequences

- Goal mode is no longer single-command fire-and-forget; it is two commands with a human
  read in between. That is the point: the intent checkpoint is preserved.
- The pause is enforced by the extension (loop cleared), not by prompt prose — an agent
  that keeps working in its final distill turn still cannot re-inject turns.
- The `opsx-loop-kickoff` spec's goal-and-conversation-kickoff requirement and scenario
  were amended to the paused-for-confirmation semantics.
