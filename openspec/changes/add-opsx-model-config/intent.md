# Intent — add-opsx-model-config

## Intent

Let the user configure default models for three workflow roles — artifact authoring,
review subagents, implementation subagents — and expose that configuration
**uncoupled from pi**, so the same workflow honors it when driven from Codex, Claude,
or the bash driver. The pi extension consumes the config; it does not own it.

## Constraints

- **Harness-neutral source of truth.** Config lives in layered files + an `opsx-models`
  resolver CLI on PATH (sibling to `opsx-gate`), NOT inside the pi extension.
- **Layered resolution, highest wins:** env > change `review.md` front-matter >
  `openspec/opsx-models.yaml` (project) > `~/.config/opsx/models.yaml` (user) > defaults.
- **Three roles:** `author` (single model), `review` (one or more models, for multi-model
  adversarial review), `impl` (single model).
- **Degrade gracefully:** when a role is unset at every layer, consumers fall back to the
  session/default model — never hard-fail.
- **Consumer, not owner:** the `opsx-loop` extension resolves + exports `OPSX_*_MODEL` on
  loop start; deleting it must not remove the config (the resolver + files remain).
- **Do not break existing behavior:** unset config ⇒ today's behavior unchanged.
- **Author in the parent session by default:** artifact authoring is NOT delegated to a subagent unless `author_in_session: false`. Fixes the observed bug where authoring silently ran on a subagent's model.
- **Force via the gate, not prose:** delegated review/impl work is stamped with the actual model by the dispatch adapter; `opsx-gate` blocks archive on a model mismatch vs the configured role model. Unconfigured roles are not enforced (degrade to session).

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
