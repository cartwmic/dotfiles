# Clarify Findings

Three passes over the delta ACs.

## Pass 1 — Ambiguity

| # | AC ref | Question | Option A | Option B | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | model-provenance-enforcement | How is the AUTHOR model enforced if authoring is in-session (no subagent to stamp)? | In-session authoring is a POLICY (not delegated); the gate only enforces stamped DELEGATED provenance | Try to read the live pi session model into a stamp | answered | A — in-session = "not delegated" guarantee; delegated work is stamped + gate-checked. pi doesn't reliably expose the live session model to a CLI |
| A2 | role-model-resolver (review) | review_models is a list; how does the gate match multiple stamped reviewer models? | Required set: every configured review model MUST have a matching stamp | Allowed pool (subset ok) | answered | B→A reversal after review (opus P2-1/gpt F-006): REQUIRED SET — if you configure [A,B] for multi-model adversarial review, both must have run, else the gate fails. Subset would let "3 configured, 1 ran" pass |

## Pass 2 — Inconsistency

| # | AC pair | Conflict | Option A | Option B | Status | Resolution |
|---|---|---|---|---|---|---|
| I1 | author-in-session-by-default × skills "authoring uses the author model" | if authoring is in-session, the author_model is moot | author_model applies ONLY when author_in_session=false (opt-in delegation) | author_model always applies | answered | A — author_model governs delegated authoring; in-session uses the session model. Documented in design |

## Pass 3 — Completeness

| # | Combination | Question | Option A | Option B | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | WHEN opsx-models runs WHILE neither yq nor a JSON config is present | how are YAML config files read? | yq required for YAML; document JSON+jq fallback like opsx-gates | fail | answered | A — yq for YAML (already a mise tool); env + review.md front-matter parsed dependency-free so the resolver works without yq for those layers |
| C2 | WHEN a stamped model uses a provider prefix but config omits it (e.g. `opus-4.8` vs `anthropic/claude-opus-4-8`) | exact string match or normalized? | Exact provider-qualified ids + an EXPLICIT alias table | Lenient suffix match | answered | A (reversed after review: opus P1-1/gpt F-005) — suffix matching fails its own example (`4.8` vs `4-8`) and is collision-prone. Use exact provider-qualified ids; aliases only via an explicit `aliases:` table in config |

## Outstanding

- None. All findings answered.

## Summary

- Pass 1: 2/0 · Pass 2: 1/0 · Pass 3: 2/0
- **Gate status:** READY for design
