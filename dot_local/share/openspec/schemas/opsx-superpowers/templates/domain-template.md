# <Project> Domain

<!--
Implicit invariants the AI agent does NOT know about your business. Kiro's
"dark matter": facts experienced engineers leave unwritten because they're
obvious to humans in the domain. The agent needs them written down to
reason about consistency and completeness.
-->

**Version:** 1.0.0
**Last updated:** YYYY-MM-DD

## Entities

<!-- Glossary of domain entities, one paragraph each. Use the names that
will appear in EARS acceptance criteria. -->

- **<Entity>** — <one-sentence definition>
- **<Entity>** — <one-sentence definition>

## Invariants

<!-- Constraints that always hold, regardless of any specific feature.
Format: imperative statement, no "may"/"should". -->

1. <Invariant — e.g., "An order cannot be canceled before submission.">
2. <Invariant — e.g., "No two active leases can exist for one property.">
3. <Invariant — e.g., "A refunded payment cannot be refunded again.">
4. <Invariant — e.g., "Timestamps are stored UTC; durations are non-negative.">

<!-- These feed the clarify artifact's inconsistency + completeness passes
as ground-truth constraints that bound reachability. -->

## Units and conventions

- **Time**: <e.g., "UTC; ISO 8601 strings on the wire; epoch millis in memory">
- **Money**: <e.g., "minor units (cents); never floating-point">
- **IDs**: <e.g., "UUIDv7 for new entities; legacy ULIDs grandfathered">
- **Naming**: <e.g., "snake_case in DB, camelCase in API, kebab-case in URLs">

## Out-of-scope domains

<!-- What this project explicitly does NOT model. Helps the agent recognize
when a requirement leaks into adjacent territory. -->

- <e.g., "Tax calculation — delegated to <service>; this project never
  computes tax internally.">
- <e.g., "Identity provider implementation — we are a consumer of <IdP>,
  not an issuer.">

## See also

- Constitution: `openspec/constitution.md`
- Schema docs: `~/.local/share/openspec/schemas/opsx-superpowers/README.md`
