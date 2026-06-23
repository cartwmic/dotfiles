## Why

The opsx workflow hard-codes no model policy: artifact authoring uses the session model, and review/implementation subagents are dispatched with ad-hoc model choices. The user wants to configure (a) the default artifact-authoring model, (b) the default review-subagent models, and (c) the default implementation-subagent model — and to set these **uncoupled from pi** so the same workflow run from Codex/Claude/bash honors them too.

## What Changes

- Add `opsx-models`, a harness-neutral resolver CLI (sibling to `opsx-gate`) that prints the resolved model(s) for a role (`author` / `review` / `impl`) using layered config: env > change `review.md` front-matter > `openspec/opsx-models.yaml` (project) > `~/.config/opsx/models.yaml` (user) > built-in defaults.
- Add the `opsx-models.yaml` config convention + `review.md` front-matter fields (`author_model`, `review_models`, `impl_model`).
- The `opsx-loop` pi extension CONSUMES the resolver: on loop start it resolves the three roles and exports `OPSX_AUTHOR_MODEL` / `OPSX_REVIEW_MODELS` / `OPSX_IMPL_MODEL` into the worker turns, so the skills' subagent dispatches and authoring pick them up. The config is NOT owned by the extension.
- The `openspec-loop`, `openspec-propose`, and `openspec-apply-change` skills read role models (via `opsx-models` / the env) when authoring artifacts and dispatching review/impl subagents, degrading to the session model when unset.
- **Author-in-session by default + detectable:** artifact authoring stays in the PARENT session (its model) and is NOT delegated unless explicitly opted in. In-session authoring carries an `authored: in-session` marker, and `opsx-gate` FAILS if an authoring artifact instead carries a delegated model stamp (or no marker when a role is configured) — so the observed bug (silent authoring delegation) becomes a hard gate failure on recurrence, not just discouraged by prose. (Residual: the exact in-session model id is not verified, only that authoring was not delegated.)
- **Model-provenance enforcement (the "force"):** when review/impl work is delegated, the subagent-dispatch adapter stamps the ACTUAL model that ran into the artifact's provenance; `opsx-gate` FAILS if a stamped model does not match the configured role model. Prose can't force a model; the gate can.

## Capabilities

### New Capabilities
- `opsx-model-config`: the `opsx-models` resolver CLI, the layered resolution order, the `opsx-models.yaml` convention, and the `review.md` front-matter model fields.

### Modified Capabilities
- `opsx-loop-kickoff`: the extension resolves + exports the three role models on loop start (consumer, not owner).
- `opsx-skill-integration`: openspec-loop / propose / apply read role models for authoring + subagent dispatch; author-in-session by default; delegated dispatch passes the model + stamps provenance.
- `opsx-workflow-schema`: `review.md` front-matter gains `author_model` / `review_models` / `impl_model` / `author_in_session`.
- `opsx-gate-enforcement`: a new check fails the gate when a delegated artifact's stamped model does not match the configured role model.

## Impact

- **New files:** `dot_local/bin/executable_opsx-models`, `tests/opsx-models/`, `dot_local/share/openspec/schemas/opsx-superpowers/templates/opsx-models.yaml`.
- **Edited:** `dot_pi/agent/extensions/opsx-loop/{index.ts,helpers.ts,helpers.test.ts}`; the openspec-loop / propose / apply skill bodies + opsx-mode refs; schema `review.md` template + `schema.yaml` + README.
- **Constitution IX:** edits existing skills (openspec-loop/propose/apply) at Scale L → adversarial review at analyze + gating adversarial post-impl code-review.
- **Deps:** none new (`yq` already a mise tool; JSON fallback documented).
- **Not coupled:** delete the pi extension → models still resolve via `opsx-models` for the bash driver / any harness. The extension only conveniently exports env.
