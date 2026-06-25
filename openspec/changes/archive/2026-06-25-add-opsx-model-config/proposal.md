## Why

The opsx workflow hard-codes no model policy: artifact authoring uses the session model, and review/implementation subagents are dispatched with ad-hoc model choices. The user wants to configure (a) the default artifact-authoring model, (b) the default review-subagent models, (c) the default implementation-subagent model, and (d) the **provider** for each — and to set these **uncoupled from pi** so the same workflow run from Codex/Claude/bash honors them too.

## What Changes

- Add `opsx-models`, a harness-neutral resolver CLI (sibling to `opsx-gate`) that prints the resolved model(s) for a role (`author` / `review` / `impl`) using layered config: env > change `review.md` front-matter > `openspec/opsx-models.yaml` (project) > `~/.config/opsx/models.yaml` (user) > built-in defaults. Model values are provider-qualified (`<provider>/<id>`, pi's native form); an optional `provider` (default + per-role) qualifies bare ids.
- Add the `opsx-models.yaml` config convention + `review.md` front-matter fields (`author_model`, `review_models`, `impl_model`, and the provider keys `provider` / `author_provider` / `review_provider` / `impl_provider`).
- The `opsx-loop` pi extension CONSUMES the resolver: on loop start it resolves the three roles and exports `OPSX_AUTHOR_MODEL` / `OPSX_REVIEW_MODELS` / `OPSX_IMPL_MODEL` into the worker turns, so the skills' subagent dispatches and authoring pick them up. The config is NOT owned by the extension.
- The `openspec-loop`, `openspec-propose`, and `openspec-apply-change` skills read role models (via `opsx-models` / the env) when authoring artifacts and dispatching review/impl subagents, degrading to the session model when unset.
- **Author-in-session by default (the fix for the observed bug):** artifact authoring stays in the PARENT session (its model) and is NOT delegated unless explicitly opted in. The observed bug — authoring silently delegated to a subagent's model — is fixed AT THE SOURCE: the skills do not delegate authoring under the default. In-session authoring writes an `authored: in-session` marker, and `opsx-gate` FAILS an authoring artifact that carries no marker when the `author` role is configured — a cheap, SELF-ATTESTED tripwire for recurrence (a silently-delegated authoring path would not run the in-session marker step).
- **No post-hoc model-provenance gate (scoped out, deliberately):** an earlier iteration tried to make `opsx-gate` *force* the delegated review/impl model by reading subagent run-history. Adversarial review established a fundamental ceiling: a post-hoc gate cannot force a model against a same-UID actor (the agent can write any file the gate reads and chooses the dispatch identity). The achievable guarantee was only "detect ACCIDENTAL wrong-model," at the cost of a pi-subagents companion change, a per-change snapshot, and agent-identity binding — disproportionate. This change therefore ships the resolver + author-in-session and does NOT add run-history provenance enforcement. Delegated review/impl dispatch passes the resolved model best-effort; it is not gate-verified.

## Capabilities

### New Capabilities
- `opsx-model-config`: the `opsx-models` resolver CLI, the layered resolution order, the `opsx-models.yaml` convention, and the `review.md` front-matter model fields.

### Modified Capabilities
- `opsx-loop-kickoff`: the extension resolves + exports the three role models on loop start (consumer, not owner).
- `opsx-skill-integration`: openspec-loop / propose / apply read role models for authoring + subagent dispatch; author-in-session by default; delegated dispatch passes the resolved model best-effort.
- `opsx-workflow-schema`: `review.md` front-matter gains `author_model` / `review_models` / `impl_model` / `author_in_session`.
- `opsx-gate-enforcement`: a cheap self-attested check fails the gate when an authoring artifact lacks the `authored: in-session` marker while the `author` role is configured (NO run-history / model-provenance enforcement).

## Impact

- **New files:** `dot_local/bin/executable_opsx-models`, `tests/opsx-models/`, `dot_local/share/openspec/schemas/opsx-superpowers/templates/opsx-models.yaml`.
- **Edited:** `dot_local/bin/executable_opsx-gate` (add the author-marker check); `dot_pi/agent/extensions/opsx-loop/{index.ts,helpers.ts,helpers.test.ts}`; the openspec-loop / propose / apply skill bodies + opsx-mode refs; schema `review.md` template + `schema.yaml` + README.
- **Constitution IX:** edits existing skills (openspec-loop/propose/apply) at Scale L → adversarial review at analyze + gating adversarial post-impl code-review.
- **Deps:** none new (`yq` already a mise tool; JSON fallback documented). NO pi-subagents companion dependency (the run-history provenance path was scoped out).
- **Not coupled:** delete the pi extension → models still resolve via `opsx-models` for the bash driver / any harness. The extension only conveniently exports env.
- **Harness-neutral:** resolver + author-in-session + the marker check work on every harness; nothing depends on pi-specific run-history.
