# <Project> Constitution

<!--
The project's immutable principles. Every artifact in this schema reads this
file. Keep principles ≤10. Each principle: name + one-paragraph behavioral
rule + rationale + enforcement note. Update via dedicated change with
adversarial review.
-->

**Version:** 1.0.0
**Ratified:** YYYY-MM-DD
**Last updated:** YYYY-MM-DD

## Core Principles

### I. <Principle name>
<!-- Example: I. Capability boundaries are sacred
     Behavioral rule: every behavioral change MUST be expressed as an
     ADDED/MODIFIED/REMOVED requirement in a capability spec.
     Rationale: keeps spec the source of truth for behavior; prevents drift.
     Enforcement: analyze artifact check 3 (AC↔design coverage). -->
<one-paragraph rule>

**Rationale:** <why this rule exists>
**Enforcement:** <which artifact/check enforces it>

### II. <Principle name>
<one-paragraph rule>

**Rationale:** <…>
**Enforcement:** <…>

### III. <Principle name>
<one-paragraph rule>

**Rationale:** <…>
**Enforcement:** <…>

<!-- Add up to ~10 numbered principles. Resist the urge to grow indefinitely. -->

## Governance

- Amendments to this constitution require a dedicated change at full_rigor
  (Scale M + full_rigor: true) with adversarial-review-cycle invoked.
- The constitution is read before every artifact in this schema. Violations
  are flagged by the analyze artifact's constitution check.
- Principles in this file override schema instructions and individual
  artifact prose when they conflict.

## Versioning

- Major: a principle is removed or reversed.
- Minor: a principle is added.
- Patch: clarification, no semantic change.

## See also

- Schema activation: `~/.local/share/openspec/schemas/opsx-superpowers/README.md`
- Domain invariants: `openspec/domain.md`
