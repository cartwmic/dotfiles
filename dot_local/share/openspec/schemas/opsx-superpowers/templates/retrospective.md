# Retrospective

<!--
Pre-archive learning capture. Required when full_rigor is set (the former
L/XL); skipped otherwise. The Promote-candidates section drives
memory promotion: openspec-archive-change parses each row and prompts
confirm/skip per candidate before calling the hindsight `retain` tool.

This artifact is produced by openspec-archive-change as a pre-archive
step (NOT declared in the schema's artifact graph — same rationale as
verify.md). Template lives at
~/.local/share/openspec/schemas/opsx-superpowers/templates/retrospective.md.
-->

**Change:** <change-name>
**Date:** YYYY-MM-DD
**Author:** <username>

## Wins

<!-- What went better than expected. Specific. Cite which artifact /
which skill / which decision delivered the win. -->

- <win>

## Misses

<!-- What went worse than expected. Specific. What would we change about
the process next time? -->

- <miss>

## Plan deviations

<!-- Where actual differed from plan.md. Why? Was the deviation correct
in retrospect, or should we have stuck to the plan? -->

| Step | Planned | Actual | Reason | Correct? |
|---|---|---|---|---|
| <step> | <what> | <what> | <why> | yes\|no\|partial |

## Skill compliance

<!-- Which skills helped, which got ignored, which fired when they
shouldn't have. Drives skill-edit candidates. -->

| Skill | Invoked? | Helpful? | Notes |
|---|---|---|---|
| <skill> | yes\|no | yes\|no\|mixed | <notes> |

## Surprises

<!-- Unforeseen discoveries — about the codebase, about the agent,
about the tools, about ourselves. These often become learnings. -->

- <surprise>

## Promote candidates

<!--
Durable knowledge for long-term memory (hindsight MCP server). Each
candidate becomes one `retain` call after a per-row confirm/skip prompt
from openspec-archive-change.

The hindsight contract (see CLAUDE.md "Memory: hindsight MCP server"):
  - Do NOT classify: there is no memory-type taxonomy. Write the fact
    plainly; hindsight does its own extraction and consolidation.
  - content: self-contained prose. Future-you will not have this
    conversation's context. Preserve exact identifiers VERBATIM —
    commit SHAs, versions, file paths, config keys, ADR numbers, AC IDs.
    Capture temporal markers ("supersedes X") so decision evolution
    stays traceable.
  - tags: `project:<name>` always; optional `topic:<x>` facet
    (short, lowercase, no invented prefix schemes). No memory_type
    tag, no harness tag.
  - Never store secrets/credentials/tokens — record only that they
    exist and where they live, never values.

Scalability note: if you produce more than ~10 candidates, prefer
consolidating related items into single multi-paragraph entries rather
than emitting 20 separate per-paragraph memories. openspec-archive-change
prompts per-candidate; ≥20 candidates produces a fatiguing confirm loop.
-->

### Candidate 1

- **tags:** project:<name>, topic:<facet>
- **content:**
  > <durable knowledge. Self-contained — future-you will not have this
  > conversation's context. Cite specific files, commit hashes, ADR
  > numbers, AC IDs verbatim where relevant.>

### Candidate 2

- **tags:** <…>
- **content:** <…>

---

<!--
After archive, hindsight will contain these candidates. To audit:
  recall with the project name, or list_memories filtered by
  tags project:<name>.
-->
