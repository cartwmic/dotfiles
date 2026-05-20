# Capability: <kebab-name>

<!--
EARS pattern reference (Mavin et al., RE'09)
============================================
  Ubiquitous:    THE <system> SHALL <response>
  Event-driven:  WHEN <trigger>, THE <system> SHALL <response>
  State-driven:  WHILE <state>, THE <system> SHALL <response>
  Optional:      WHERE <feature>, THE <system> SHALL <response>
  Unwanted:      IF <condition>, THEN THE <system> SHALL <response>
  Compound:      WHILE <state>, WHEN <trigger>, THE <system> SHALL <response>

  HARD RULE: error/unwanted conditions MUST use IF…THEN, never WHEN.
  The analyze artifact's check 2 flags violations as major (human-triage,
  not auto-blocker — false positives possible when "fail"/"invalid"/etc.
  appears in a non-error context).

Canonical AC ID format (used by verify gate check 5):
============================================
  <capability>.<requirement-slug>

Where <requirement-slug>:
  - lowercased
  - non-alnum chars → '-'
  - repeated '-' collapsed to one
  - leading/trailing '-' stripped

Example:
  Requirement: "User can export data"
  Capability:  user-export
  AC ID:       user-export.user-can-export-data

Tests cite ACs by this exact ID string in a comment, docstring, or
string literal. The verify gate greps for the literal ID match.

Five quality properties (per AC):
  - Testable      — explicit inputs, outputs, condition
  - Solution-free — describes WHAT, not HOW
  - Unambiguous   — two readers formalize identically
  - Consistent    — no conflict with other ACs (verified in clarify pass 2)
  - Complete      — covers the input space (verified in clarify pass 3)
-->

## ADDED Requirements

### Requirement: <Name in Title Case>

<!-- AC ID auto-derives: <capability>.<slug-of-name> -->

<!-- One-sentence description using SHALL/MUST. -->

#### Scenario: <name>
- **WHEN** <nominal trigger>
- **THEN** <expected outcome>

#### Scenario: <error path>
- **IF** <unwanted condition>
- **THEN** <expected error response>

<!-- Repeat ### Requirement: blocks as needed.
     For modified capabilities also include sections below. -->

## MODIFIED Requirements
<!-- Each MODIFIED requirement MUST include the FULL updated content,
not just the diff. Locate the existing requirement in
openspec/specs/<capability>/spec.md, copy the entire block, edit. -->

## REMOVED Requirements
<!--
### Requirement: <name>
**Reason**: <why removed>
**Migration**: <what consumers should do>
-->

## RENAMED Requirements
<!--
### FROM: <old name>
### TO: <new name>
-->

---

## Acceptance criterion quality checklist

<!-- One row per requirement. Mark each property [x] or note the gap.
This checklist is the lightweight version; the analyze artifact's
check 6 (Implementation language in specs) is the deeper enforcement
mechanism — don't duplicate that detail here. -->

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| <capability>.<slug> | [ ] | [ ] | [ ] | [ ] | [ ] |
