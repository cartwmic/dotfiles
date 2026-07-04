# ADR-0026: Plain-M review stack thins; doneness rides the code-review dispatch but keeps its own artifact

**Status:** accepted (2026-07-03, simplify-and-parallelize-opsx-workflow)

## Context

At Scale M — the tier defined as "typical feature" — the workflow stacked five
blind judgment layers (clarify, analyze, 2-model code review, disclosure,
doneness) and nine authored documents. The simplicity audit rated this the
top structural over-investment. The 2-model adversarial code review is
load-bearing (the antidote to agent self-certification) and is explicitly not
weakened; the question was where the other judgments live at the common tier.

## Decision

At plain M (no `full_rigor`):

- Clarify questions live in proposal.md `## Open Questions` under the same
  2-option self-resolution discipline — no standalone clarify.md.
- Analyze thins to its deterministic checks run inline — no blind dispatch.
- design.md is decision-gated (authored when a decision warrants it), not
  gate-required.
- The doneness question rides the code-review dispatch as a mandatory final
  section answered by the DESIGNATED reviewer (first entry of the resolved
  `review` role), with the verdict still sealed to a SEPARATE doneness.md
  (`review_mode: blind-single-judge`). The gate's doneness artifact
  requirement, freshness/provenance binding, and the Scale≥M doneness policy
  are unchanged — only the extra dispatch is eliminated.

`full_rigor: true` restores the full independent stack (standalone blind
clarify, blind analyze, independently dispatched doneness judge, required
design.md).

## Consequences

- One fewer subagent dispatch and two fewer documents at the most common
  tier; the doneness gap-set ratchet keeps working at every tier ≥ M because
  doneness.md always exists.
- Independence between the diff reviewer and the doneness judge is retained
  only where stakes justify it (full_rigor); at plain M the designated
  reviewer answers both questions in one blind context.
