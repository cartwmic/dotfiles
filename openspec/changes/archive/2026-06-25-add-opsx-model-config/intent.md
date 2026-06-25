# Intent — add-opsx-model-config

## Intent

Let the user configure default models — AND their providers — for three workflow roles:
artifact authoring, review subagents, implementation subagents. Expose that configuration
**uncoupled from pi**, so the same workflow honors it when driven from Codex, Claude,
or the bash driver. The pi extension consumes the config; it does not own it.

## Constraints

- **Harness-neutral source of truth.** Config lives in layered files + an `opsx-models`
  resolver CLI on PATH (sibling to `opsx-gate`), NOT inside the pi extension.
- **Layered resolution, highest wins:** env > change `review.md` front-matter >
  `openspec/opsx-models.yaml` (project) > `~/.config/opsx/models.yaml` (user) > defaults.
- **Three roles:** `author` (single model), `review` (one or more models, for multi-model
  adversarial review), `impl` (single model).
- **Provider per model:** values are provider-qualified (`<provider>/<id>`, pi's native form,
  since the same id can exist on multiple providers, e.g. `gpt-5.5` on openai-codex vs
  openrouter); an optional `provider` (default + per-role) qualifies bare ids.
- **Degrade gracefully:** when a role is unset at every layer, consumers fall back to the
  session/default model — never hard-fail.
- **Consumer, not owner:** the `opsx-loop` extension resolves + exports `OPSX_*_MODEL` on
  loop start; deleting it must not remove the config (the resolver + files remain).
- **Do not break existing behavior:** unset config ⇒ today's behavior unchanged.
- **Author in the parent session by default:** artifact authoring is NOT delegated to a subagent unless `author_in_session: false`. Fixes the observed bug AT THE SOURCE — authoring no longer runs on a subagent's model because it is not delegated.
- **Self-attested author marker, not post-hoc model forcing:** in-session authoring writes an `authored: in-session` marker; `opsx-gate` fails an authoring artifact lacking it when the `author` role is configured — a cheap tripwire for recurrence. The change does NOT attempt to force the delegated review/impl model via a post-hoc gate: adversarial review showed a same-UID actor can write any file the gate reads, so run-history provenance enforcement was scoped out. Delegated dispatch passes the resolved model best-effort.

## Invariants honored

- Constitution II (CLI + extension + skills at canonical chezmoi source paths).
- Constitution IX (edits existing skills at Scale L → adversarial review).
- Domain inv 8 (`dot_local/bin` gitignore allowlist already present), V (yq via mise).
- ADR-0005 (harness-neutral exit-code/CLI tooling), ADR-0007 (pi adapter consumes neutral core).

## Non-goals

- Validating that a configured model id exists/authenticates (consumers/`pi --list-models`
  do that; the resolver only resolves strings).
- A model-selection UI.
- Changing the judge model (that is the goal extension's separate concern, ADR-0002).
