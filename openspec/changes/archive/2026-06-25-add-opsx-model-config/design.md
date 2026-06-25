# Design — add-opsx-model-config

## Context

Observed bug: artifact authoring was silently delegated to a subagent running a
different model (gpt-5.5) than the parent session (opus 4.8). Root cause = delegation
plus an un-passed model. The fix is at the SOURCE: author in the parent session by
default, plus a harness-neutral resolver so review/impl dispatch passes a configured
model (and provider).

An earlier iteration tried to FORCE the delegated review/impl model via a post-hoc
`opsx-gate` check reading pi-subagents run-history. Adversarial review (rounds 5–6)
established a fundamental ceiling: a post-hoc gate cannot force a model against a
same-UID actor — it can write any file the gate reads (the worktree snapshot, the
global run-history) and chooses the dispatch `agent` label the binding relied on. The
only achievable guarantee (detect ACCIDENTAL wrong-model) did not justify a pi-subagents
companion change + per-change snapshot + agent-identity binding. That path is scoped OUT.

References: intent.md, proposal.md, specs/**/spec.md, clarify.md (all answered).

## Goals / Non-Goals

- **Goal:** configure author/review/impl models AND their providers (uncoupled from pi);
  author in-session by default; review/impl dispatch passes the resolved model best-effort.
- **Non-Goal:** forcing the delegated model via a post-hoc gate (proven unachievable against
  a same-UID actor); validating model auth/existence; a model UI; changing the judge model.

## Decisions

### D1 — Harness-neutral `opsx-models` resolver CLI + layered files (model AND provider)
**Choice:** `opsx-models <role> [--change <c>]` on PATH prints the resolved model(s); layered
env > review.md front-matter > `openspec/opsx-models.yaml` (project) > `~/.config/opsx/models.yaml`
(user) > defaults. Model values are **provider-qualified** by convention — pi's native form
`<provider>/<id>` (e.g. `claude-bridge/claude-opus-4-8`, `openai-codex/gpt-5.5`) — so the
provider is configured inline. The SAME model id can exist on multiple providers
(`gpt-5.5` on `openai-codex` AND `openrouter/openai/gpt-5.5`), so provider-qualifying pins the
billing / rate-limit / routing path. For convenience an optional `provider` key (a top-level
default and/or per-role) qualifies BARE ids. Provider detection keys PURELY on a `/`: a value
CONTAINING `/` is a complete pi model id used VERBATIM (provider = leading segment; provider
keys do NOT apply) — so an openrouter-style multi-segment id is written in full
(`openrouter/openai/gpt-5.5`); a BARE id (no `/`) is prefixed with the role's `provider`, else
the top-level default `provider`, else left bare for the consumer (pi) to resolve. No
known-provider registry is needed. Env: `OPSX_AUTHOR_MODEL` / `OPSX_REVIEW_MODELS` (plural) /
`OPSX_IMPL_MODEL` plus optional `OPSX_<ROLE>_PROVIDER` and a default `OPSX_PROVIDER`.
Env + front-matter parsed dependency-free; YAML via yq (jq+JSON fallback).
**Rationale:** mirrors opsx-gate/opsx-gates.yaml (ADR-0005); aligns with pi's `provider/id` +
preferred-provider resolution; one truth every harness reads.

### D2 — Author-in-session by default (the primary fix)
**Choice:** authoring stays in the parent session unless `author_in_session: false`. The
skills' authoring steps run in-session; only on opt-out do they delegate (with the author model).
**Rationale:** makes "parent authors" definitional; directly resolves the observed surprise.
4-point: multiple ✓, lasting ✓, contestable ✓, constrains ✓ → ADR-worthy (note).

### D3 — No post-hoc model-provenance gate (scoped OUT after adversarial review)
**Choice:** do NOT enforce delegated review/impl model provenance via `opsx-gate`. An iteration
designed it (read pi-subagents native run-history, bind runs to a role by the dispatch `agent`
identity, fail-closed on mismatch). Rounds 5–6 blind review found the ceiling: every gate-read
source is worker-writable (a per-change snapshot lives in the worktree the worker edits; the
global `~/.pi/agent/run-history.jsonl` is equally writable) and the binding key (the `agent`
field passed at `recordRun`) is worker-chosen — so a deliberate same-UID actor forges a
satisfying line or dispatches real work off-identity with a decoy under the role identity. The
residual achievable value was only ACCIDENTAL-wrong-model detection, not worth a pi-subagents
companion change + snapshot + identity binding.
**What remains:** review/impl dispatch passes the resolved `model:` (+ provider) best-effort,
which covers the common case by construction; the authoring bug is fixed at the source by D2.
**Rationale:** honesty + proportion. True per-role model forcing requires the EXECUTION layer
(the runtime that picks the model), not a post-hoc gate — out of scope.

### D4 — In-session authoring marker (cheap self-attested tripwire)
**Choice:** the in-session authoring STEP writes an `authored: in-session` marker; `opsx-gate`
fails an authoring artifact that lacks it WHILE `author_in_session` is true/unset AND the
`author` role specifically is configured. The check scans an enumerated authoring-artifact set
(proposal/intent/design/clarify/tasks/plan/specs).
**Residual (disclosed):** the marker is SELF-ATTESTED — a worker that both delegates authoring
AND forges the marker is out of the threat model (per D3's ceiling). Its value is catching the
OBSERVED accidental bug: a silently-delegated authoring path does not run the in-session
marker step, so the missing marker trips the gate.

## Risks / Trade-offs

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Same model id on multiple providers (`gpt-5.5` on openai-codex vs openrouter) → wrong billing/route | Med | Med | Provider-qualified model values (`<provider>/<id>`) pin the path; optional `provider` default for bare ids |
| Bare vs provider-qualified ambiguity | Med | Low | Explicit `provider/id` always wins; bare id qualified by role `provider` → default `provider` → left for pi to resolve |
| Delegated review/impl model not enforced (best-effort only) | Med | Low | ACCEPTED: a post-hoc gate cannot force a model against a same-UID actor (D3); the author bug is fixed at the source (D2); review/impl pass-through is best-effort |
| In-session author model id unverifiable / forged marker | High | Low | D4: self-attested tripwire for the accidental case; default does not delegate authoring at all |
| yq absent | Low | Low | env + front-matter dependency-free; yq via mise for YAML files |

## Migration Plan

1. `opsx-models` CLI + helpers + tests + `opsx-models.yaml` template (roles + provider + `author_in_session` + aliases + resolution order).
2. Gate: add the In-Session Authoring Marker check — WHILE `author_in_session` true/unset AND the `author` role is configured (resolved via `opsx-models author --json --change`), fail an authoring artifact lacking the `authored: in-session` marker; skip otherwise. NO run-history reading.
3. review.md front-matter fields (`author_model`/`review_models`/`impl_model`/`author_in_session` + provider keys).
4. Skills: author-in-session default (the in-session authoring STEP writes the marker); review/impl dispatch passes the resolved model + provider best-effort.
5. opsx-loop extension: resolve via `opsx-models --json --change` + export `OPSX_*_MODEL` / `OPSX_*_PROVIDER` / `OPSX_AUTHOR_IN_SESSION` on loop start; consumer only (no config parsing, no run-history snapshot).

## Open Questions

- Whether to canonicalize model ids via `pi --list-models` in the resolver (deferred; the
  resolver stays a string resolver; consumers/pi resolve bare ids and providers).
- Review list providers: each `review` list entry MAY be independently provider-qualified;
  the top-level/per-role `provider` default applies to any bare entry.
