<!-- authored: in-session -->
# Design — opsx-loop-pure-router

## Context

Post `opsx-loop-role-dispatch` + `opsx-dispatch-transparent`, an armed loop mutes
generic `subagent`, exposes transparent `opsx_dispatch`, and forces role models
for review/impl/(opt-in author). Parent `edit`/`write` stay live;
`author_in_session` defaults true and **refuses** `opsx_dispatch(author)`. Weak
orchestrators can ship session-model code.

Frozen intent: pure-router parent — mute mutate tools, judged writes only via
`opsx_dispatch(role)`, meta via `opsx_bookkeep`, armed author override. Clarify
sealed READY (17 findings resolved). Constitution I/II (chezmoi + canonical
skills); IX (skill edits → multimodel review). Domain: OpenSpec workspace not
deployed; kebab change name; ADDED/MODIFIED full bodies.

## Goals / Non-Goals

**Goals:**
- Armed mute: drop `subagent`, `edit`, `write`; expose `opsx_dispatch` + `opsx_bookkeep`.
- `opsx_bookkeep` enum floor: `append_ledger`, `set_hold`, `append_followup`,
  `append_execution_note`; refuse clear-hold / wrong change / not-armed /
  empty set-hold reason.
- Armed: ignore `author_in_session` for `role: author` (configured → accept;
  unset → refuse, no session fallback).
- Skill tables: MUST-dispatch + MUST-bookkeep while armed (routing; tools enforce).
- Hermetic tests for mute/restore, bookkeep matrix, author override; prior suite green.

**Non-Goals:**
- Shell argv allowlist / mute bash / dedicated `opsx_gate` tool.
- Gate commit provenance; extension auto-stamp from spawn; phase-scoped tool sets.
- Global `author_in_session` default flip; requiring `opsx_dispatch` when disarmed.
- Teaching pi-subagents about OPSX.

## Decisions

### D1: Extend `applyArmedToolSet` (+ restore) for edit/write/bookkeep

**Choice:** Mutate the existing pure helpers — drop `edit`/`write`/`subagent`/
`opsx_dispatch`/`opsx_bookkeep` from the walk, then ensure `opsx_dispatch` +
`opsx_bookkeep` are appended. `restoreToolSetAfterClear` keeps exact snapshot
restore (already drops armed-only tools unless they were pre-arm).

**Alternatives considered:**
- **Path-gated edit wrapper:** keep `edit`, refuse non-meta paths — weaker for
  weak models; more code paths.
- **Phase-scoped tool menus:** flip tools per gate check — Scale L; intent Non-goal.

**Rationale:** Same shape as today's mute; lowest risk to latch/restore tests.

**4-point test:** Y/Y/Y/Y → ADR candidate **Y** (tool-surface contract).

### D2: One `opsx_bookkeep` tool with structured `op` enum

**Choice:** Single registered tool `opsx_bookkeep` with
`op: append_ledger | set_hold | append_followup | append_execution_note | clear_hold`.
`clear_hold` always refuses for agents. Refuse also: not-armed, wrong change,
worktree-only path, unknown op, and **empty/missing `set_hold` reason**.
Writes only INTEGRATION `openspec/changes/<armedChange>/{review,follow-ups}.md`
(resolve integration cwd the same way hold-clear / review.md writes already do
in `index.ts`). Optional sibling allowlist = constant array (empty at v1;
design can grow).

**Alternatives considered:**
- **Split tools** (`opsx_set_hold`, …): more surface, same trust.
- **Extension auto-stamp:** no parent call — bigger schema; intent Non-goal.

**Rationale:** Matches clarify I3/C1; one schema to test; weak model can't invent paths.

**4-point test:** Y/Y/Y/Y → ADR candidate **Y**.

### D3: Armed author override in `planOpsxDispatch`

**Choice:** WHEN `armed && role === "author"`, skip the
`authorInSession !== false` refuse branch. Unset author still returns
`reason: "unset"` (no session fallback). Disarmed path unchanged
(`opsx_dispatch` still not-armed refuse).

**Alternatives considered:**
- **Force `author_in_session=false` at arm:** mutates config; surprises disarmed propose.
- **Require false to arm:** fail-loud but poorer UX vs ignore-while-armed.

**Rationale:** Intent "armed ignores flag"; disarmed default preserved.

**4-point test:** Y/Y/Y/N → ADR candidate **N** (local to plan helper).

### D4: Skill prose as routing; tools as enforcement

**Choice:** Rewrite `openspec-{loop,propose,apply-change}` armed sections:
author/impl/review → `opsx_dispatch`; meta → `opsx_bookkeep`; remove
"implement the next task" / in-session author while armed. No skill-only path
allowlist. Armed multi-model review remains **one** `opsx_dispatch` call
(tool-owned native parallel from `opsx-dispatch-transparent` — skills MUST NOT
N-loop). Provider-qualified `<provider>/<id>` values stay forced by
`opsx_dispatch` role resolve (prior role-sole-source; skills pass through on
disarmed `subagent` path).

**Alternatives considered:**
- **Skill-only bookkeeping paths:** rejected at explore (weak models).

**Rationale:** Constitution II + clarify A5/A6; retain transparent fan-out +
provider bind contracts.

**4-point test:** Y/Y/N/Y → ADR candidate **N**.

### D5: Host tool name literals

**Choice:** Constants `EDIT_TOOL_NAME = "edit"`, `WRITE_TOOL_NAME = "write"`
matching pi coding-agent built-ins (same as compaction case labels). If a
pre-arm snapshot lacks a name, mute is a no-op for that name (idempotent).

**Alternatives considered:**
- **Detect by capability metadata:** no stable API today.

**Rationale:** Intent pins "whatever pi exposes"; literals match current host.

**4-point test:** Y/N/N/Y → ADR candidate **N**.

### D6: Bookkeep write implementation

**Choice:** Pure helpers for path resolve + refuse matrix + text transforms
(hold YAML front-matter, ledger table append, follow-ups append, Execution Notes
append) in `helpers.ts` (or `bookkeep.ts`); `index.ts` registers tool and
performs the single `writeFileSync` on the resolved INTEGRATION path. Mirror
existing `clearHoldText` / `parseLoopHold` style — extension owns meta file
bytes for bookkeep ops only (product/spec/code still never written by ext).

**Alternatives considered:**
- **Shell out to a small CLI:** extra binary; unnecessary.

**Rationale:** Keep testable pure core; one write owner for meta ops.

**4-point test:** Y/Y/N/Y → ADR candidate **N**.

### D7: Retain worktree-always skill discipline (carry-forward)

**Choice:** This change does **not** reopen worktree execution. Skills keep
prior worktree-always prose intact: worktree is the only execution model at
every Scale (XS included — ensure → locator → apply → review → merge →
cleanup); no same-tree guidance on skill surfaces. Misplaced bookkeeping onto
the `opsx/<change>` worktree branch remains fail-closed via the existing
verdict range-freshness gate (not a new mechanism). The pure-router delta only
adds: WHILE armed, integration bookkeeping (`loop_hold`, ledger, follow-ups,
Execution Notes) MUST go through `opsx_bookkeep` (D2/D4) instead of parent
edit/write.

**Alternatives considered:**
- **Re-specify full worktree lifecycle in this design:** redundant with archived
  worktree-always change; risk of drift.

**Rationale:** MODIFIED `Worktree Always Skill Discipline` carries prior ACs
plus armed-bookkeep; D7 names the retained substrate so fidelity can entail
carry-forward scenarios without inventing new gate logic.

**4-point test:** N/Y/N/Y → ADR candidate **N**.

## Risks / Trade-offs

| # | Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|---|
| R1 | Bash still mutates product files while armed | Medium | Medium | Documented Non-goal; skill read-only bash; future provenance |
| R2 | Exact `edit`/`write` names drift in pi | Low | High | Constants + tests; fail-loud if mute no-ops unexpectedly in dogfood |
| R3 | Bookkeep enum misses a skill-needed op | Medium | Medium | Clarify floor ops; add op in follow-up if dogfood finds gap |
| R4 | Author role unset → armed propose stuck | Medium | High | Pre-existing unset refuse; operators set `opsx models set author` |
| R5 | Skill edits trigger Constitution IX multimodel review cost | High | Low | Expected at Scale M; review_models already pinned |

## Migration Plan

1. Land extension + tests on `opsx/opsx-loop-pure-router` worktree; merge to main.
2. `chezmoi apply` deploys skills + extension; existing armed loops clear/re-arm
   to pick up new tool set (in-session arm snapshot is per-start).
3. Rollback: revert commit; re-arm restores prior mute-only-subagent behavior.
4. Compat: disarmed sessions unchanged; armed sessions **BREAKING** (no parent
   edit/write; author must be configured for propose-phase dispatch).

## Open Questions

- Exact ledger/Execution-Notes append format (match skill templates) — decide
  during apply from current `openspec-loop` SKILL.md examples; record in
  Execution Notes if any deviation.
- Empty sibling allowlist at v1 — confirmed; grow only via follow-up change.
