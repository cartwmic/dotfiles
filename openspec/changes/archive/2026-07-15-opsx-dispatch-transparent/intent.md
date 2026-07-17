# Intent — opsx-dispatch-transparent

**Status:** FROZEN (explore concluded 2026-07-14)
**Recommended Scale:** M, `full_rigor: false`

Schema: opsx-superpowers. This intent.md is the frozen baseline; do not edit
without explicit human authorization.

## Intent

Make armed-loop `opsx_dispatch` a **transparent thin shim** over pi-subagents'
programmatic spawn surface: same live TUI progress / metadata / result shape
the generic `subagent` tool shows, while still mechanically binding configured
opsx role models.

Today's failure (post `opsx-loop-role-dispatch`): bind works, but the shim
throws away the subagent UX. `spawnViaRunSync` ignores `onUpdate`, returns a
one-liner (`spawn complete model=… exit=…`), skips `renderCall`/`renderResult`,
and fans review models out as **sequential** custom loops instead of native
parallel `tasks[]`.

Target armed-loop flow:

```
/opsx-loop <change>
  → mute generic `subagent`; expose `opsx_dispatch` (unchanged)
  → worker calls opsx_dispatch({ role, task | tasks[], agent?, … })
       → resolve role (configured only; unset = refuse)
       → role is sole source of model id(s); strip/ignore caller model
       → review multi-list + single `task`
            → expand to native parallel `tasks[]`
              (one entry per review model, same task body, model forced)
       → single-model roles stay single-mode (or pass through `tasks[]`
         with each entry's model forced to the role value)
       → spawn via pi-subagents library / executor path with `onUpdate`
         forwarded; return subagent-shaped Details + reuse renderers
/opsx-loop clear
  → restore tool snapshot
```

This **supersedes** the sequential review fan-out behavior shipped in
`opsx-loop-role-dispatch` (archived 2026-07-14). Bind / mute / unset-refuse /
OPSX-blind pi-subagents constraints remain; transparency + parallel fan-out
are the new outcomes.

## Constraints

- **Shim, not rewrite:** keep `opsx_dispatch` as the armed-only tool; do not
  unmute generic `subagent` while armed; do not same-name-override `subagent`.
- **Schema (v1):** expose `role` plus a **narrow** subagent subset:
  `task` (single) **or** `tasks[]` (parallel), plus minimal companions needed
  for those modes (`agent`, optional `concurrency`). No chain / async /
  worktree / management `action` surface in v1.
- **Parallel review fan-out:** when `role: "review"` resolves to N>1 models
  and the caller passes a single `task`, the shim MUST expand into native
  pi-subagents parallel `tasks[]` (one spawn per model, order preserved,
  models forced per entry) — not a sequential `runSync` loop.
- **Caller `tasks[]`:** when the caller already passes `tasks[]`, the shim
  MUST allow it (passthrough shape) and still force role model(s):
  single-model roles stamp every entry; review multi-list stamps by index
  (length must match the resolved review list, else refuse with an actionable
  error). Caller-supplied per-task `model` is ignored/stripped.
- **Transparency:** forward `onUpdate` into the spawn path; return
  subagent-shaped `Details` (progress / results / usage / paths); attach
  `renderCall` / `renderResult` that reuse pi-subagents renderers (import
  or thin wrap — no one-liner-only result).
- **Library composition stays:** spawn through pi-subagents programmatic API
  (`runSync` / executor / parallel entry — whichever preserves onUpdate +
  parallel Details). Pi-subagents remains OPSX-blind (no role names, no
  `OPSX_*`, no models.yaml knowledge).
- **Role sole source / unset = refuse / author_in_session:** unchanged from
  archived role-dispatch intent.
- **Skills:** update armed-path docs so review fan-out is described as native
  parallel via `opsx_dispatch` (not N sequential calls); disarmed path still
  uses generic `subagent`.
- **Code homes:** primarily `dot_pi/agent/extensions/opsx-loop/` (+ skill
  prose under `dot_local/share/agent-harness/canonical/skills/`); delta
  specs under `opsx-loop` / `opsx-skill-integration` (and adjacent if needed).
- **Validation:** hermetic tests for (a) onUpdate forwarded, (b) Details
  shape non-empty vs one-liner regression, (c) review multi-list → parallel
  `tasks[]` expansion (count + forced models + order), (d) caller `tasks[]`
  length mismatch refuse, (e) existing arm/mute/unset/sole-source invariants
  still green.

## Invariants honored

- Constitution I — opsx-loop extension under chezmoi
  (`dot_pi/agent/extensions/opsx-loop/`).
- Constitution II — skill edits in canonical harness skills.
- Constitution III — no secrets.
- Constitution VIII — `openspec/` not chezmoi-deployed.
- Constitution IX — skill edits at Scale M → adversarial / gating review.
- Domain — kebab-case change name; ADDED/MODIFIED full requirement bodies.
- Prior `opsx-loop-role-dispatch` bind contract remains: mute while armed,
  role sole source, unset refuse, one-way library dep, pi-subagents
  OPSX-blind.
- Capability-hooks: `subagent-dispatch` stays dumb; role→model fill stays
  opsx-loop-owned.

## Non-goals

- Unmuting or soft-honoring generic `subagent` while a loop is armed.
- Full SubagentParams parity in v1 (chain, async, worktree, management
  actions, slash-command mute) — deferred.
- Teaching pi-subagents about OPSX roles / env / models.yaml.
- Gate provenance↔config match (still deferred from role-dispatch).
- Changing `opsx-loop-models-interactive` (sibling active change).
- Requiring `opsx_dispatch` outside an armed loop.
- Cursor/Claude host Task-tool bind.
- Making unset roles hard-fail loop start itself.
