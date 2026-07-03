# Analyze Findings

<!--
STRICTLY READ-ONLY. Do not modify other artifacts. Produce a remediation
report. Severity: blocker | major | minor.

Blockers HALT tasks generation.
Majors require human-recorded resolution before archive (track in
verify.md or in this file's resolution column).
Minors are tracked but don't block.
-->

**Mode:** <single-model | adversarial-review-cycle>
**Generated:** YYYY-MM-DD by <model / skill>

## Check 1 — Constitution compliance

| Principle | Status | Rationale | Severity |
|---|---|---|---|
| I. <name> | compliant\|violated\|inapplicable | <citation> | <if violated> |
| II. <name> | … | … | … |

## Check 2 — EARS pattern check (major, human-triage)

<!--
Regex used:
  /WHEN\s+[^.]*\b(error|fail|invalid|reject|deny|unauthor)/i

This regex has known false-positive modes. For each match, READ THE AC IN
CONTEXT before recording as a finding. False positives are common when
keyword appears as substring of an entity name ("unauthor-itative source")
or in non-error context ("a previously failed attempt"). Record true
positives only.
-->

| # | File:line | AC | True positive? | Suggested rewrite | Status |
|---|---|---|---|---|---|
| E1 | <file>:<line> | <AC text> | yes\|no\|ambiguous | <IF…THEN form if true positive> | pending\|fixed\|deferred |

## Check 3 — AC↔design coverage

| AC ID | Design section reference | Status | Severity |
|---|---|---|---|
| <capability>.<slug> | <design §> or MISSING | covered\|missing\|partial | minor\|major |

## Check 4 — design↔ADR promotion candidates (full_rigor)

<!--
ADR promotion is a SKILL responsibility, not a schema artifact. This check
flags candidates; openspec-archive-change actually offers promotion at
archive time. Each decision in design.md is scored against the 4-point
test (multiple-approaches / lasting / disagreement / future-constraint).
Decisions passing ≥3 of 4 are ADR candidates.
-->

| Decision | 4-point score | ADR-candidate? | Rationale or "ADR not warranted because…" |
|---|---|---|---|
| D<n> | <score 0-4> | yes\|no | <…> |

## Check 5 — Duplicate detection

| # | Locations | Restated constraint | Action |
|---|---|---|---|
| Dup1 | <file:section> + <file:section> | <restated text> | keep one\|merge\|differentiate |

## Check 6 — Implementation language in specs

| # | AC ID | Tech mentioned | Rewrite suggestion |
|---|---|---|---|
| Imp1 | <capability>.<slug> | <e.g., "Redis", "JWT 15min TTL"> | <behavioral form> |

## Check 7 — Unresolved clarify findings

| # | clarify.md ref | Status | Risk |
|---|---|---|---|
| U1 | A<n>\|I<n>\|C<n> | unanswered\|deferred | <impact on this change> |

## Outstanding risks

<!-- Mirror of clarify deferred findings + any analyze findings that
weren't blockers but warrant tracking. -->

## Summary

- Blockers: <count> → MUST be resolved before tasks artifact is generated
- Major findings: <count> → confirm/resolve before archive
- Minor findings: <count>
- **Gate status:** <READY for tasks | BLOCKED on N blockers>
