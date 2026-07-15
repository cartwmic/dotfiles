# Intent — opsx-loop-pure-router

**Status:** FROZEN (explore concluded 2026-07-15)
**Recommended Scale:** M, `full_rigor: true`

Schema: opsx-superpowers. This intent.md is the frozen baseline; do not edit
without explicit human authorization.

## Intent

Make an armed `/opsx-loop` parent session a **pure router**: it may read,
run gate/status commands, ask the user, and dispatch role-bound work — but
it MUST NOT perform judged writes (propose artifacts, product/code/tasks,
review verdicts) itself. Those writes happen only through `opsx_dispatch`
with the phase-correct role. Integration bookkeeping that today lives on
the parent (`loop_hold`, fidelity ledger, follow-ups) moves onto a narrow
structured meta tool so weak orchestrator models cannot path-cheat into
product files via generic edit/write.

Today (post `opsx-loop-role-dispatch` + `opsx-dispatch-transparent`):
review is already hard-forced through `opsx_dispatch`; generic `subagent`
is muted; role is sole model source. But edit/write/bash stay on the
parent, `author_in_session` defaults to in-session authoring (and refuses
`opsx_dispatch(author)` when true/unset), and impl is skill-optional —
so a weak parent can ship session-model code and skip role models.

Target armed-loop flow:

```
/opsx-loop <change>
  → snapshot tools; mute: subagent, edit, write
  → expose: opsx_dispatch, opsx_bookkeep (+ read / bash / ask_*)
  → WHILE armed: ignore author_in_session — author work MUST
       opsx_dispatch(author)
  → gate says missing propose arts  → opsx_dispatch(author)
  → gate says unchecked tasks       → opsx_dispatch(impl)
  → gate says review needed         → opsx_dispatch(review)
  → parent meta (hold / ledger / follow-ups)
       → ONLY via opsx_bookkeep (schema-validated; INTEGRATION paths)
/opsx-loop clear (or disarm)
  → restore tool snapshot
  → author_in_session meaning restored for disarmed/manual propose
```

Skills (`openspec-loop`, `openspec-propose`, `openspec-apply-change`) are
rewritten so every judged phase is phrased as MUST-dispatch via
`opsx_dispatch` while armed; prose is routing guidance, not the primary
enforcement — tool surface is.

This **extends** (does not replace) the bind/mute/unset-refuse/transparent
shim contracts from archived `opsx-loop-role-dispatch` and
`opsx-dispatch-transparent`. Those stay; pure-router is the new outcome.

## Constraints

- **Mute while armed:** `applyArmedToolSet` (or successor) MUST drop
  `subagent`, `edit`, and `write` from the parent active tool set, and
  MUST ensure `opsx_dispatch` + `opsx_bookkeep` are present. Exact host
  tool name strings match whatever pi exposes today for edit/write.
- **Keep while armed:** read tools, `bash`, user-ask tools, `opsx_dispatch`,
  `opsx_bookkeep`. Bash retained so parent can run `opsx gate`,
  `git status`/`log`, `openspec list`, etc.
- **Shell residual (accepted, documented):** muting edit/write does NOT
  stop `bash` from rewriting files (`sed`, scripts, `git apply`). v1
  accepts this residual bypass; skill prose says prefer read-only bash;
  harden (argv allowlist / dedicated gate tool / provenance) is Non-goal.
- **`opsx_bookkeep`:** one structured tool (ops enum, not free-path edit)
  that may mutate ONLY the armed change's INTEGRATION copies of
  `openspec/changes/<change>/review.md` and
  `openspec/changes/<change>/follow-ups.md` (and any narrowly listed
  sibling meta files design names). Refuse unknown ops, wrong change,
  worktree-only paths, and agent-initiated hold clear (human re-arm
  remains sole clear path — existing loop_hold invariant).
- **Armed author override:** WHILE a loop is armed, `author_in_session`
  is ignored for routing — authoring MUST go through
  `opsx_dispatch(author)` when an author role model is configured; if
  author role is unset, keep existing refuse/no-session-fallback
  semantics (do not silently author in parent). Disarmed / manual propose
  keeps today's `author_in_session` meaning (default true).
- **Phase → role (skill + mute):** judged propose work → `author`;
  judged apply/code/task work → `impl`; judged review/doneness →
  `review`. Parent MUST NOT use edit/write for those (tools gone).
- **Prior bind contracts retained:** role sole source of model;
  unset = refuse; caller model stripped; pi-subagents OPSX-blind;
  transparent `opsx_dispatch` shim behavior from
  `opsx-dispatch-transparent` unchanged.
- **Code homes:** primarily `dot_pi/agent/extensions/opsx-loop/`
  (helpers, index, tests) + skill prose under
  `dot_local/share/agent-harness/canonical/skills/openspec-{loop,propose,apply-change}/`.
  Delta specs under `opsx-loop` + `opsx-skill-integration` (adjacent
  capabilities only if design proves necessary).
- **Validation:** hermetic tests for (a) armed mute drops edit/write/
  subagent and restores on clear, (b) `opsx_bookkeep` allow/refuse matrix,
  (c) armed author override (dispatch allowed / in-session path gone),
  (d) existing arm/mute/unset/sole-source/transparent invariants still
  green, (e) skill routing tables describe MUST-dispatch for all three
  roles while armed.
- **Scale / rigor:** `Scale: M`, `full_rigor: true` — cross-capability
  (loop runtime + skill-integration), breaking change to default armed
  authoring UX, ADR-worthy tool-surface decision. Expects clarify +
  design + blind analyze + adversarial-on-analyze + independent
  doneness + retrospective.

## Invariants honored

- Constitution I — opsx-loop extension under chezmoi
  (`dot_pi/agent/extensions/opsx-loop/`).
- Constitution II — skill edits in canonical harness skills.
- Constitution III — no secrets.
- Constitution VIII — `openspec/` not chezmoi-deployed.
- Constitution IX — skill edits at Scale M → adversarial / gating review
  (multi-model); `full_rigor` adds analyze-time adversarial cycle.
- Domain — kebab-case change name; ADDED/MODIFIED full requirement bodies;
  OpenSpec workspace not deployed.
- Prior `opsx-loop-role-dispatch` bind contract: mute while armed, role
  sole source, unset refuse, one-way library dep, pi-subagents OPSX-blind.
- Prior `opsx-dispatch-transparent` contract: transparent shim, XOR
  schema, native parallel review fan-out, caller `tasks[]` length rules.
- Existing loop_hold: agents cannot clear holds; only explicit human
  `/opsx-loop` re-arm clears (bookkeep must not invent a clear path).

## Non-goals

- Shell argv allowlisting, muting bash, or a dedicated `opsx_gate` tool
  that replaces bash for gate invocation.
- Gate provenance matching (impl/author/review commits ↔ dispatch
  stamps) — still deferred; soft-shell residual is the related risk.
- Extension auto-stamping ledger/hold from spawn results (no
  `opsx_bookkeep` call).
- Phase-scoped `setActiveTools` flips (one armed tool set for the whole
  loop; role choice is skill + dispatch, not per-gate tool menus).
- Unmuting or soft-honoring generic `subagent` while armed.
- Teaching pi-subagents about OPSX roles / env / models.yaml.
- Changing global default `author_in_session` for disarmed sessions
  (armed override only).
- Requiring `opsx_dispatch` outside an armed loop.
- Cursor/Claude host Task-tool bind.
- Making unset roles hard-fail loop start itself (unchanged).
