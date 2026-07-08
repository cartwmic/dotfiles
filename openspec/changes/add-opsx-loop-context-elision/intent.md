# Intent — add-opsx-loop-context-elision

Status: explore-frozen

## Intent

opsx-loop worker runs accumulate context to context-rot levels *within a single
agent run*, before `agent_end` — so the two shipped compaction layers do not
help there: between-turns compaction (`42dc012`) only fires at `agent_end`, and
overflow recovery (`a8275a0`) only fires on a hard overflow error. Benchmarks
(Lost-in-the-Middle, NoLiMa, context-rot) show model accuracy degrading well
before the window is full, so a run that climbs to ~80% mid-flight makes worse
decisions on every step after the climb.

Evidence — session `019f3d32-76d6-7469-b42d-d05cd51c8d28` (opus, single run,
peaked >80% before it ended): of the accumulated context, **71% was stale
`toolResult` text** (bash/read/grep/write output the model had already consumed
and moved past), 24% old `assistant/thinking`, ~5% tool calls, <1% actual
conversation. The bloat is not irreplaceable reasoning — it is spent tool-output
dumps.

This change adds a mid-run, per-request **context elision** layer: before each
provider request within an active loop, present the model a slimmer *view* of
the conversation that drops stale tool-output bodies, keeping the model in its
low-context / high-accuracy regime — without aborting the turn and without
mutating stored history — and, when elision fires during a run, durably
consolidates the masked bloat via the existing between-turns compaction at that
run's end.

## Frozen design decisions

1. **Mechanism — ephemeral `context`-event transform.** Register the pi
   `context` event (backed by `transformContext`, `agent-loop.js`: it runs before
   every provider request within a run). The handler returns a pruned `messages`
   view used only to build that request's payload; `agent.state.messages` and the
   persisted session are never mutated. No abort, no `ctx.compact()` mid-run.
   REJECTED: mid-turn `ctx.compact()` (it calls `abort()` — kills the run,
   truncates the reasoning chain, resumes from a lossy summary); graceful
   steer-to-yield (coarse — ends the turn early, gives no per-request control).

2. **Trim = elide stale tool-result BODIES beyond a recent-K window.** Replace
   the *text* of `toolResult` messages older than the most recent K turns with a
   short stub (`[output elided to conserve context — re-run to view]`). KEEP the
   `toolResult` message itself (so `tool_call ↔ tool_result` pairing stays intact
   — no provider 400), KEEP all tool calls, all assistant/user text, and the
   recent-K tool results in full (active working memory). Deterministic; no LLM
   call inside the transform.

3. **Scope — active opsx loop only.** The `context` handler is a no-op unless a
   loop is armed (`loop.active`). Interactive / non-loop sessions are untouched.
   Global session-wide trimming is a NON-GOAL here; if wanted later it belongs in
   a dedicated standalone context-trim extension, not opsx-loop.

4. **Tool outputs only in the first cut; thinking deferred.** Old
   `assistant/thinking` (the 24%) is left intact. It is stored bytes, not
   necessarily payload bytes — Claude via the bridge generally does not need
   prior-turn thinking resent, so eliding it may be a no-op. Confirming whether
   thinking is actually re-sent to the provider is a prerequisite to any future
   thinking-elision, and is out of scope for this change.

5. **Elision → compaction coupling.** When elision fires during a run, that run's
   `agent_end` treats it as an additional between-turns compaction trigger
   (effectively lowering the L1 compaction threshold to the elision band for that
   decision). Rationale: elision is ephemeral and stored history keeps growing
   full; compacting between turns durably consolidates the same stale outputs,
   upgrades the lossy `re-run` stubs into an LLM summary that retains findings,
   and keeps stored history near the elision band instead of drifting up to L1's
   higher bar. Self-rate-limited: compaction shrinks history → the next run
   starts slim → elision does not re-fire until it grows back (worst case ≈ once
   per run, already L1's cadence). NOTE: `getContextUsage()` measures full stored
   history (not the transformed view), so L1 would eventually fire regardless —
   this coupling is for tighter history + better consolidation, not to prevent
   unbounded growth.

6. **Cache discipline.** The transform is threshold-band gated and advances the
   elision boundary in bands (not continuously), so the slim prefix stays stable
   across turns and re-caches after the first eliding turn — bounding prompt-cache
   misses to boundary-advance events rather than every request.

7. **Recovery valve.** The stub's "re-run to view" is a real escape hatch: within
   a resumable loop, re-running a `read`/`grep`/`bash` is cheap and safe, so a
   model that needs an elided result can reconstruct it. This is why active-loop
   scope is the safe first home.

## Constraints

- **Structural integrity (fail-closed).** The transform MUST NOT orphan a
  `tool_result` from its `tool_call`, MUST preserve the current in-flight
  exchange (the newest turn), and MUST NOT touch the system prompt (added
  downstream in `convertToLlm`, not present in the `context` messages).
- **No LLM call in the transform.** It runs before every request; summarization
  belongs to the between-turns compaction layer, not here.
- **Degrade safely.** `typeof` guards on the `context` hook and usage APIs;
  absent support ⇒ no-op, prior behavior preserved.
- **Respect existing layers.** Compose with L1 (between-turns compaction) and L2
  (overflow recovery); do NOT re-enable pi general auto-compaction
  (`compaction.enabled` stays `false`).

## Invariants

- Elision never mutates stored session history — it is a per-request view only.
- `tool_call ↔ tool_result` pairing is preserved in every emitted view.
- The system prompt and the most-recent-K turns are always sent in full.

## Non-goals

- Global / interactive-session trimming (a future standalone extension).
- Eliding thinking blocks (deferred pending payload confirmation).
- Any summarization inside the per-request transform.
- Re-enabling pi built-in auto-compaction.

## Deferred to design phase

- Exact elision band default (`OPSX_ELIDE_AT_*`) and recent-K default — must sit
  at/below L1's compaction threshold; tuned in design.
- Whether the decision-5 coupling is unconditional on any eliding run or itself
  gated by a secondary stored-context floor.

## Supersedes

- Nothing. Extends the compaction stack: L1 between-turns compaction (`42dc012`)
  and L2 overflow recovery (`a8275a0`).
