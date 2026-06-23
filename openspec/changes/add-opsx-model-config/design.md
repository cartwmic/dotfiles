# Design — add-opsx-model-config

## Context

Observed bug: artifact authoring was silently delegated to a subagent running a
different model (gpt-5.5) than the parent session (opus 4.8). Config alone doesn't
fix this — the issue is delegation + un-passed model. We add harness-neutral model
config PLUS deterministic enforcement (author-in-session default + gate-checked
delegated provenance).

References: intent.md, proposal.md, specs/**/spec.md, clarify.md (all answered).

## Goals / Non-Goals

- **Goal:** configure author/review/impl models (uncoupled from pi) and FORCE them —
  author in-session by default; delegated work stamped + gate-checked.
- **Non-Goal:** validating model auth/existence; a model UI; changing the judge model.

## Decisions

### D1 — Harness-neutral `opsx-models` resolver CLI + layered files
**Choice:** `opsx-models <role> [--change <c>]` on PATH prints resolved model(s); layered
env > review.md front-matter > `openspec/opsx-models.yaml` > `~/.config/opsx/models.yaml`
> defaults. Env + front-matter parsed dependency-free; YAML files via yq (jq+JSON fallback).
**Rationale:** mirrors opsx-gate/opsx-gates.yaml (ADR-0005); every harness reads one truth.

### D2 — Author-in-session by default (the primary fix)
**Choice:** authoring stays in the parent session unless `author_in_session: false`. The
skills' authoring steps run in-session; only on opt-out do they delegate (with author model).
**Rationale:** makes "parent authors" definitional; directly resolves the observed surprise.
4-point: multiple ✓, lasting ✓, contestable ✓, constrains ✓ → ADR-worthy (note).

### D3 — Delegated model provenance, gate-enforced FAIL-CLOSED (the "force")
**Choice:** the subagent-dispatch adapter stamps `{role, requested_model, actual_model,
adapter, harness}` into the produced artifact's provenance. `opsx-gate` resolves the role via
`opsx-models --json` (source-aware) and, for a CONFIGURED role, **fails closed**: missing
stamp, unverifiable stamp, or `actual_model` mismatch all fail. Compare EXACT on provider-
qualified ids; aliases only via an explicit `aliases:` table (no suffix matching — it failed
its own `4.8`↔`4-8` example and collides). `review` = required set (every configured model
must have run). Resolver absent on PATH → fail-closed for configured roles.
**Rationale:** prose can't force a model; a fail-closed gate can. The stamp must record the
runner-observed `actual_model`, not merely the requested one — if pi-subagents cannot expose
the actual model, the run is stamped unverifiable and fails rather than rubber-stamping.
4-point: all four ✓ → ADR-worthy.

### D4 — In-session authoring is detectable via a marker (not policy-only)
**Choice:** the gate cannot read the live pi session model, BUT in-session authoring stamps
an `authored: in-session` marker. The gate FAILS an authoring artifact that instead carries a
delegated model stamp, or carries no marker when a role is configured. The original bug
(silent authoring delegation) becomes DETECTABLE. Residual: the EXACT in-session model id is
not verified — only that authoring was not delegated.
**Rationale:** upgrades author-in-session from policy-only (opus P1-5 / gpt F-004) to a
detectable, gate-enforced guarantee.

## Risks / Trade-offs

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Provider-prefix/alias mismatch (`opus-4.8` vs `anthropic/claude-opus-4-8`) | Med | Med | EXACT provider-qualified compare + explicit `aliases:` table (NO suffix matching); `pi --list-models` for exact ids |
| Adapter can't stamp on a non-pi harness | Med | Med | Configured role + missing/unverifiable stamp → gate FAILS (exit non-zero), never a warning/pass |
| In-session author model id unverifiable | High | Low | D4: scoped to "not delegated" + `authored: in-session` marker; a delegated stamp on an authoring artifact FAILS the gate |
| yq absent | Low | Low | env + front-matter dependency-free; yq via mise for YAML files |

## Migration Plan

1. `opsx-models` CLI + helpers + tests + `opsx-models.yaml` template (incl. an `author-in-session` resolver surface returning `{value:boolean, source}`).
2. Gate: add FAIL-CLOSED model-provenance check (resolve via `opsx-models --json --change`; EXACT + alias compare; missing/unverifiable/mismatch = fail; review required-set; resolver-absent = fatal `model-resolver-unavailable`) + tests.
3. review.md front-matter fields (`author_model`/`review_models`/`impl_model`/`author_in_session`).
4. Skills: author-in-session default (the in-session authoring STEP writes the `authored: in-session` marker); delegated dispatch passes model + the adapter stamps provenance.
5. opsx-loop extension: resolve via `opsx-models --json --change` + export `OPSX_*_MODEL` + `OPSX_AUTHOR_IN_SESSION` on loop start.

## Open Questions

- Whether to canonicalize model ids via `pi --list-models` in the resolver (deferred; EXACT + explicit alias table is the enforced behavior — no lenient/suffix compare).
