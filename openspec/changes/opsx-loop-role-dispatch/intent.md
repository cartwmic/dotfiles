# Intent — opsx-loop-role-dispatch

**Status:** FROZEN (explore concluded 2026-07-14)
**Recommended Scale:** M, `full_rigor: false`

Schema: opsx-superpowers. This intent.md is the frozen baseline; do not edit
without explicit human authorization.

## Intent

Make configured opsx role models **mechanically bind** when an opsx loop is
armed: the orchestrator must dispatch review/impl/(opt-in author) work through
a loop-scoped `opsx_dispatch` tool that resolves the role via `opsx models` /
exported `OPSX_*` env and forces that model into the spawn path.

Today's failure: `/opsx-loop` exports `OPSX_*` into the parent process and
child env inherits them, but pi-subagents never reads those vars for model
selection — the LLM must honor skill prose and pass `model:` on the generic
`subagent` tool. Config can be set and dispatch still runs the session model.

Target armed-loop flow:

```
/opsx-loop <change>
  → export OPSX_* (existing)
  → snapshot active tools; drop `subagent`; activate `opsx_dispatch`
  → worker uses opsx_dispatch({ role, task, … })
       → resolve role (configured only; unset = refuse)
       → role is sole source of model id (ignore caller model)
       → review list → auto fan-out one spawn per entry
       → spawn via pi-subagents `runSync` as a library import
/opsx-loop clear
  → restore tool snapshot (`subagent` returns)
```

pi-subagents stays OPSX-blind. Dependency is one-way: opsx-loop imports spawn
code; subagents never learns opsx role names or config.

This change is **separate** from frozen `ease-opsx-models-ux` (picker UX only;
that intent's non-goals already exclude gate/loop dispatch semantics).

## Constraints

- **Bind home:** mechanical bind lives in the **opsx-loop pi extension**
  (loop-continuation adapter), not inside pi-subagents and not as a
  harness-neutral CLI spawn runner.
- **Mute while armed:** on arm, `pi.setActiveTools` removes `subagent` from
  the active set and enables `opsx_dispatch` (plan-mode snapshot/restore
  pattern). On clear/stop, restore the prior snapshot exactly.
- **Spawn path:** `opsx_dispatch` execute path imports pi-subagents'
  programmatic spawn (`runSync` or equivalent public library entry) — library
  composition, not extension inheritance and not same-name tool override of
  `subagent`.
- **Role sole source:** when a role is configured, the resolved model id is
  forced; caller-supplied `model` is ignored/stripped. No silent coerce of a
  different configured role.
- **Unset = refuse:** if the requested role's resolver source is
  unset/default (no configured value), `opsx_dispatch` fails closed with an
  actionable error pointing at `opsx models set` / config layers — do not
  fall back to the session model on this path.
- **Review fan-out:** `role: "review"` with a multi-value review config
  dispatches one blind spawn per list entry (order preserved). Skills must
  not invent a single-model review when multiple are configured.
- **Roles in scope:** `author`, `review`, `impl` (plus existing
  `author_in_session` semantics for whether authoring is delegated at all).
  Authoring remains in-session by default; `opsx_dispatch` for `author` only
  applies when delegation is opted in.
- **Decoupling:** no OPSX role names, env keys, or models.yaml knowledge
  inside the pi-subagents package. Generic spawn API only.
- **Skills:** openspec-loop / openspec-propose / openspec-apply-change (and
  related references) MUST route role-bound subagent work through
  `opsx_dispatch` when a loop is armed; document the armed vs disarmed
  surfaces clearly.
- **Resolver contract preserved:** layered resolution
  (env > change front-matter > user > default), `session` sentinel,
  slash-verbatim qualification, and `opsx models` stdout/JSON contracts
  remain byte-compatible. This change consumes them; it does not redesign
  them.
- **Code homes:** primarily `dot_pi/agent/extensions/opsx-loop/` (+ canonical
  skill prose under `dot_local/share/agent-harness/canonical/skills/`),
  capability specs under `openspec/specs/` (`opsx-loop`,
  `opsx-skill-integration`, and/or adjacent), agent-independent tests where
  practical.
- **Validation:** agent-independent tests for arm/clear tool-set swap,
  refuse-when-unset, role-forced model passed into spawn stub, and review
  fan-out count; no live network required.

## Invariants honored

- Constitution I — opsx-loop extension source stays under chezmoi
  (`dot_pi/agent/extensions/opsx-loop/`) and deploys via `chezmoi apply`.
- Constitution II — skill edits stay in
  `dot_local/share/agent-harness/canonical/skills/`.
- Constitution III — no secrets; model ids are not credentials.
- Constitution VIII — `openspec/` workspace not chezmoi-deployed.
- Constitution IX — skill changes at Scale ≥ M require adversarial /
  gating code review (Scale M defaults `code_review_mode` to
  gating-required).
- Domain naming — kebab-case change name; capability deltas use
  ADDED/MODIFIED headers with full requirement bodies.
- Existing `opsx-model-config` layered resolution remains authoritative;
  this change hardens **consumption** on the armed-loop dispatch path.
- Capability-hooks indirection: `subagent-dispatch` remains the dumb
  adapter; role→model fill is loop-continuation / opsx-owned.

## Non-goals

- Teaching pi-subagents about OPSX roles, `OPSX_*` env, or models.yaml.
- Muting or wrapping pi-subagents slash commands (`/run`, `/chain`,
  `/parallel`, etc.) while armed — deferred; tool mute only for v1.
- Gate-verifying sealed provenance model ids against resolved role config
  (gate belt / approach E) — follow-up change.
- Changing `ease-opsx-models-ux` frozen intent or merging this into that
  change.
- Harness-neutral CLI that itself spawns judges (`opsx dispatch` runner).
- Requiring `opsx_dispatch` outside an armed loop (disarmed sessions keep
  generic `subagent`).
- Cursor/Claude host Task-tool bind (pi adapter first; other hosts later).
- Same-name override of the `subagent` tool while armed.
- Project-layer `openspec/opsx-models.yaml` (still retired).
- Making unset roles hard-fail the **loop start** itself — only
  `opsx_dispatch` for that role refuses; loop may still run for roles that
  are configured.
