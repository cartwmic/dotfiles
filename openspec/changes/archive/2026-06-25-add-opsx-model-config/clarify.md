# Clarify Findings

Three passes over the delta ACs.

## Pass 1 — Ambiguity

| # | AC ref | Question | Option A | Option B | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | author-in-session-by-default | How is the AUTHOR model enforced if authoring is in-session? | Self-attested `authored: in-session` marker only; no model verification | Try to read the live pi session model | answered | A — in-session authoring is fixed at the SOURCE (not delegated); the gate only checks for the cheap self-attested marker. pi doesn't reliably expose the live session model to a CLI, and a post-hoc gate can't force a model anyway (scope-out, see C3) |
| A2 | role-model-resolver (review) | review_models is a list; how does dispatch use multiple models? | One reviewer dispatched per configured review model | Pick one | answered | A — configure [A,B] ⇒ dispatch one blind reviewer per model for multi-model adversarial review (best-effort `model:` pass; not gate-verified) |

## Pass 2 — Inconsistency

| # | AC pair | Conflict | Option A | Option B | Status | Resolution |
|---|---|---|---|---|---|---|
| I1 | author-in-session-by-default × skills "authoring uses the author model" | if authoring is in-session, the author_model is moot | the SKILLS consume author_model only when author_in_session=false (opt-in delegation); the RESOLVER stays unconditional | author_model always applies | answered | A — author_model governs delegated authoring; in-session uses the session model. NOTE: `opsx-models` resolves strings unconditionally; only the skills/gate branch on `author_in_session` |

## Pass 3 — Completeness

| # | Combination | Question | Option A | Option B | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | WHEN opsx-models runs WHILE neither yq nor a JSON config is present | how are YAML config files read? | yq required for YAML; document JSON+jq fallback like opsx-gates | fail | answered | A — yq for YAML (already a mise tool); env + review.md front-matter parsed dependency-free so the resolver works without yq for those layers |
| C2 | WHEN a stamped model uses a provider prefix but config omits it (e.g. `opus-4.8` vs `anthropic/claude-opus-4-8`) | exact string match or normalized? | Exact provider-qualified ids + an EXPLICIT alias table | Lenient suffix match | answered | A (reversed after review: opus P1-1/gpt F-005) — suffix matching fails its own example (`4.8` vs `4-8`) and is collision-prone. Use exact provider-qualified ids; aliases only via an explicit `aliases:` table in config |
| C3–C6 | delegated model-provenance ENFORCEMENT (gate reads run-history, binds by `agent` identity, snapshot, fail-closed) | how should the gate FORCE the delegated review/impl model? | (various designs across rounds 3–6) | — | SUPERSEDED — SCOPED OUT | Rounds 5–6 adversarial review proved a post-hoc gate cannot force a model against a same-UID actor (every gate-read source is worker-writable; the dispatch `agent` key is worker-chosen). User chose to right-size: ship resolver + author-in-session; DROP run-history provenance enforcement. These findings no longer apply |
| C7 | role model configuration | should the PROVIDER be configurable too? | Yes — provider-qualified values (`<provider>/<id>`, pi-native) + optional `provider` default/per-role for bare ids | Model id only | answered | A (user request) — same id can exist on multiple providers (`gpt-5.5` on openai-codex vs openrouter); provider-qualify to pin billing/route. Explicit `provider/id` wins; `provider` keys qualify bare ids |

## Outstanding

- None. All findings answered (C3–C6 superseded by the scope-out).

## Summary

- Pass 1: 2/0 · Pass 2: 1/0 · Pass 3: C1–C2 + C7 active, C3–C6 superseded
- **Gate status:** READY for design
