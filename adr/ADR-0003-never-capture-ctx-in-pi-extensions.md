# ADR-0003: Never capture `ctx` in a long-lived pi extension closure

**Status:** Accepted
**Date:** 2026-06-07
**Source change:** `openspec/changes/add-pi-goal-extension/`

## Context

Pi passes an `ExtensionContext` (`ctx`) into each command handler and event callback. It is tempting to capture one `ctx` once (e.g. at `session_start`) and reuse it from later callbacks or timers. A spike surfaced a real crash from exactly this pattern in another installed extension (`pi-session-search`): a captured `ctx` used after session teardown threw `"This extension ctx is stale after session replacement or reload."` This is a cross-cutting authoring rule that applies to *every* pi extension, not just `goal-loop`.

## Decision Drivers

- Pi replaces `ctx` across `newSession` / `fork` / `switchSession` / `reload` and at teardown.
- A stale `ctx` throws on access (e.g. `ctx.ui`), crashing the process.
- The rule must generalize to all future extensions in this repo.

## Considered Options

### Option A: never capture `ctx`; use the per-call `ctx`
The long-lived closure holds only the `pi` API object and plain serializable state. Every handler/command uses the `ctx` it is handed.

**Pros:**
- Immune to the stale-ctx crash; always operates on a live context.
- Simple, mechanical rule.

**Cons:**
- State that needs context must thread it through each callback (minor).

### Option B: capture `ctx` once and reuse
**Pros / Cons:** Convenient, but throws after any session replacement/reload or at teardown — the observed crash.

### Option C: capture `ctx` but guard every use with a try/catch
**Pros / Cons:** Defensive but noisy and easy to forget; treats the symptom, not the cause.

## Decision Outcome

**Chosen option:** A

**Rationale:** Using the per-call `ctx` removes the failure mode entirely with no ongoing discipline cost. For the `newSession`/`fork`/`switchSession`/`reload` paths, do post-replacement work inside the provided `withSession` callback and use *its* `ctx`.

## Consequences

**Positive:**
- No stale-ctx crashes; the rule is easy to audit (`grep` for captured `ctx`).

**Negative:**
- Long-lived closures cannot hold a context reference for convenience.

**Neutral:**
- Establishes a reusable convention for all future pi extensions in this repo.

## Links

- Source design discussion: `openspec/changes/add-pi-goal-extension/design.md` (Decision D5)
- Related ADRs: ADR-0001, ADR-0002
