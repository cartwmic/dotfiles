<!-- authored: in-session -->
# Proposal — opsx-loop-role-dispatch

## Why

Configured opsx role models do not mechanically bind under `/opsx-loop`:
`OPSX_*` is exported, but pi-subagents never reads it — dispatch relies on
skill prose + optional `model:` on generic `subagent`. Config can be set and
work still runs the session model. Fix the armed-loop bind in the opsx-loop
adapter (Constitution I/II; keep pi-subagents OPSX-blind).

## What Changes

- While loop armed: `setActiveTools` drops `subagent`, activates
  `opsx_dispatch`; on clear/stop restore prior snapshot.
- `opsx_dispatch({ role, task, … })`: resolve via `opsx models` / `OPSX_*`;
  role is sole model source (ignore caller `model`); unset role = refuse with
  actionable `opsx models set` hint; `review` auto fan-out one spawn per list
  entry; spawn via pi-subagents `runSync` library import.
- Skills (`openspec-loop` and related) route role-bound work through
  `opsx_dispatch` when loop armed; document armed vs disarmed surfaces.
- Agent-independent tests: arm/clear tool swap, refuse-when-unset, forced
  model into spawn stub, review fan-out count (no live network).

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `opsx-loop`: Armed-loop tool mute + `opsx_dispatch` bind; clear restores
  snapshot; refuse unset roles on dispatch path only.
- `opsx-skill-integration`: Skills MUST use `opsx_dispatch` for role-bound
  subagent work while loop armed (not soft-honor `subagent` + `model:`).
- `opsx-model-config`: Narrow the "delegated model honor is best-effort"
  gap for the **armed-loop** path — mechanical bind via `opsx_dispatch`
  (resolver contract unchanged; no new layers/keys).

## Impact

**Affected files (expected):**
- `dot_pi/agent/extensions/opsx-loop/` (register tool, arm/clear tool set)
- `dot_local/share/agent-harness/canonical/skills/openspec-loop/` (+ related
  skill refs that dispatch role-bound subagents)
- Tests adjacent to opsx-loop / capability validation hooks
- Delta specs under `openspec/changes/opsx-loop-role-dispatch/specs/`

**Dependencies:** pi-subagents as library (`runSync`); existing `opsx models`
resolver. One-way: opsx-loop → pi-subagents.

**Systems:** pi adapter only for spawn bind. Separate from
`ease-opsx-models-ux` (picker UX).

## Open Questions (plain-M clarify-in-proposal)

### Q1: Bind home?
- **A (chosen):** opsx-loop pi extension (`opsx_dispatch` + tool mute).
- B: Teach pi-subagents to read `OPSX_*`.
- **Resolution:** A — intent constraint; pi-subagents stays OPSX-blind.

### Q2: Mute shape?
- **A (chosen):** `setActiveTools` swap (plan-mode pattern).
- B: Keep `subagent` visible; block via `tool_call`.
- **Resolution:** A — LLM never sees raw `subagent` while armed.

### Q3: Spawn composition?
- **A (chosen):** New tool + `runSync` library import.
- B: Same-name override of `subagent` while armed.
- **Resolution:** A — cleaner restore; one-way dep.

### Q4: Unset role?
- **A (chosen):** Refuse dispatch (actionable error).
- B: Fall back to session model.
- **Resolution:** A — silent session fallback dies on this path.

### Q5: Review multi-model?
- **A (chosen):** Auto fan-out one blind spawn per configured review entry.
- B: Caller picks index/single model.
- **Resolution:** A — matches adversarial multi-judge need.

### Q6: Slash `/run` mute while armed?
- **A (chosen for v1):** Defer — tool mute only; slash escape stays.
- B: Generic mute flag inside pi-subagents slash handlers.
- **Resolution:** A — intent non-goal; follow-up.

### Q7: Gate provenance↔config match (E)?
- **A (chosen for v1):** Defer to follow-up change.
- B: Include in this change.
- **Resolution:** A — dispatch bind only here.

## Deterministic analyze (plain-M, inline)

| Check | Result |
|---|---|
| 1 Tiling | Modified `opsx-loop` + `opsx-skill-integration` + `opsx-model-config` cover mute, dispatch bind, skill routing, soft-honor narrowing |
| 2 Traceability | Intent constraints map to MODIFIED/ADDED ACs in those deltas |
| 7 EARS lint | Event/state for arm/clear/dispatch; IF…THEN for unset refuse / !armed |

No blockers. Outstanding risk: `runSync` import surface / package path for
pi-subagents — pin to exported entry; stub in tests.

## Assumptions recorded

- Design.md skipped (plain-M decision-gated): explore+intent froze bind home,
  mute, spawn, unset, fan-out, deferrals; no ADR-worthy fork left.
- Standalone clarify.md / analyze.md skipped (plain-M; open questions +
  deterministic analyze live here).
- `author` via `opsx_dispatch` only when author-in-session is false /
  delegation opted in; default stays in-session.
- Loop start itself does not hard-fail on unset roles — only
  `opsx_dispatch` for that role refuses.
- Sibling `ease-opsx-models-ux` remains separate; no merge.
