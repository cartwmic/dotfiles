# Retrospective

<!--
Pre-archive learning capture. Required at Scale = XL; optional at L
(recommended); skipped at XS/S/M. The Promote-candidates section drives
mcp-memory promotion: openspec-archive-change parses each row and prompts
confirm/skip per candidate before calling mcp_memory_store_memory.

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
Durable knowledge for mcp-memory. Each candidate becomes one
mcp_memory_store_memory call after a per-row confirm/skip prompt from
openspec-archive-change.

Required fields per row:
  - type: one of the 9 canonical mcp-memory types
        decision       — choices made: "we're going with X over Y"
        bug            — a specific defect observed + root cause
        error          — runtime/integration error that recurs + resolution
        convention     — repeated pattern: naming, layout, idioms
        learning       — non-obvious fact discovered
        implementation — how it's built: schemas, configs, integration shapes
        context        — project background, who's involved, goals
        important      — flagged as critical by user
        code           — code snippet/pattern (≥600 chars; smaller skip)

  - content: ≥300 chars for all types EXCEPT `code` which requires ≥600 chars
        (matches the upstream mcp-memory contract; smaller memories
         degrade retrieval relevance)

  - tags: type-name MUST be included as a tag; plus project:<name>;
          plus any natural facets (short, lowercase, no prefixes)

Scalability note: if you produce more than ~10 candidates, prefer
consolidating related items into single multi-paragraph entries rather
than emitting 20 separate per-paragraph memories. openspec-archive-change
prompts per-candidate; ≥20 candidates produces a fatiguing confirm loop.
-->

### Candidate 1

- **type:** <decision | bug | error | convention | learning | implementation | context | important | code>
- **tags:** <type-name>, project:<name>, <facet>, <facet>
- **content:**
  > <≥300 chars (≥600 for code) of durable knowledge. Self-contained —
  > future-you will not have this conversation's context. Cite specific
  > files, commit hashes, ADR numbers, AC IDs where relevant.>

### Candidate 2

- **type:** <…>
- **tags:** <…>
- **content:** <…>

---

<!--
After archive, mcp-memory will contain these candidates. To audit:
  search_by_tag --tags project:<name> --created-after YYYY-MM-DD
-->
