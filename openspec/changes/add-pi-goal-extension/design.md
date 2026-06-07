## Context

Pi extensions are TypeScript modules auto-discovered from `~/.pi/agent/extensions/<name>/index.ts`, managed in this chezmoi repo at `dot_pi/agent/extensions/` (Principle I; domain invariant #4 — `dot_pi/` deploys, root `.pi/` does not). The established single-file extension pattern is `dot_pi/agent/extensions/web-search/index.ts`. This is an **extension, not a skill**, so Principles II and IX (skill canonical-pipeline; skill adversarial review) do not apply.

A spike against the live pi runtime (`pi -p … -e spike.ts`) validated the four load-bearing mechanisms:

1. `pi.on("agent_end")` fires once per full agent run (after the whole tool loop) — the correct evaluation point. `turn_end` fires per assistant message mid-loop (wrong).
2. `pi.sendUserMessage(text, { deliverAs: "followUp" })` from inside `agent_end` starts a fresh worker turn; the worker observably acts on the injected text (spike turn 2 derived its output from the injected message).
3. Transcript is readable via `ctx.sessionManager.getEntries()`, each entry's `message.content[]` carrying `{type:"text", text}` blocks.
4. A separate judge resolves via `ctx.modelRegistry.find()` → `getApiKeyAndHeaders()` → `complete()` from `@mariozechner/pi-ai`, returning a clean JSON verdict.

The spike also surfaced a teardown crash in another extension caused by a captured `ctx` used after session replacement — informing D5.

## Goals / Non-Goals

**Goals:** single-file extension reproducing Claude Code `/goal`'s worker-vs-judge loop; deterministic termination; crash-free failure modes; match the existing extension convention.

**Non-Goals:** tool auto-approval / unattended permission bypass (worker keeps pi's approval mode); token-budgeted conditions; cross-resume goal persistence. Deferred follow-ups.

## Decisions

**D1 — Evaluate on `agent_end`, not `turn_end`.** Choice: hook `agent_end`. Alternatives: `turn_end` (fires mid-tool-loop, judges incomplete work), polling. Rationale: spike-confirmed `agent_end` = control returns to user, mirroring Claude Code's Stop-hook semantics. *(ADR test: 4/4 — promote candidate.)*

**D2 — Separate judge model via `complete()`.** Choice: resolve a small/cheap model from a preference list (`PI_GOAL_JUDGE_MODEL` env override → e.g. `anthropic/claude-haiku-4-5` → `deepseek/deepseek-v4-flash` → fall back to `ctx.model`); first that authenticates wins. Alternatives: reuse the worker model (biases "done", defeats independent-evaluator design); fixed hard-coded model (breaks when unauthenticated). Rationale: the worker/judge split is the feature; reuses pi's credential resolution (Principle III — no keys in source). *(ADR test: 4/4 — promote candidate.)*

**D3 — Tolerant JSON verdict contract.** Choice: judge system prompt demands `{"met":boolean,"reason":string}`; parser extracts the first JSON object; on parse/auth failure default to `met:false` with raw text as reason (spec `goal-loop.handle-evaluation-failure`). Alternatives: strict parse (a chatty judge deadlocks or false-completes). Rationale: never false-complete, never crash. *(ADR test: 3/4.)*

**D4 — In-memory session-scoped state + re-entrancy guard.** Choice: closure-held `{condition, turns, maxTurns, active, lastReason, evaluating}`. `evaluating` flag prevents the injected follow-up's own `agent_end` from launching an overlapping evaluation; `turns` increments once per evaluation (spec `goal-loop.evaluate-each-turn-once`). Alternatives: persisted/sqlite state (over-engineered for session scope; resume persistence is a non-goal). Rationale: spike's working guard pattern. *(ADR test: 2/4.)*

**D5 — Never capture `ctx`; use the handler/command `ctx`.** Choice: the long-lived closure holds only the `pi` API and plain state, never a `ctx`. Alternatives: capture `ctx` once (causes the stale-context crash seen in the spike). Rationale: pi replaces `ctx` across session switch/fork/reload. *(ADR test: 3/4 — promote candidate; cross-cutting extension-authoring rule.)*

**D6 — Hard max-turns guard (default 25, `PI_GOAL_MAX_TURNS`).** Choice: budget counts every evaluated turn including the initial set turn (clarify A2); checked before each injection; met-result wins when met and budget reached on the same turn (clarify I1). Alternatives: no cap (runaway), wall-clock cap (deferred open question). Rationale: only guaranteed stop; mirrors `jthack/claude-goal`. *(ADR test: 3/4 — promote candidate.)*

**D7 — Bounded transcript to the judge.** Choice: feed only the latest worker turn's surfaced text (and its tool results when cheaply available), not full history (clarify A1). Alternatives: full transcript (cost/latency growth). Rationale: preserves "judge sees only surfaced output" while capping spend. *(ADR test: 2/4.)*

**D9 — Settings via co-located `config.json` with env override.** Choice: ship a seed `create_config.json` (chezmoi `create_` — deployed once to `~/.pi/agent/extensions/goal/config.json`, never clobbering user edits) holding `judgeModel` and `maxTurns`; resolve each setting by precedence env var > `config.json` > built-in default. Alternatives: env-only (not persistent/discoverable); pi global `settings.json` (ExtensionContext exposes no settings accessor — would require reading pi internals); a managed (non-`create_`) file (chezmoi would revert user edits). Rationale: matches the established extension-config convention (`subagent/config.json`, token-usage) and Principle I (config persists in source) while keeping the deployed copy user-editable. *(ADR test: 3/4 — promote candidate.)*

**D8 — Set during active streaming queues as follow-up (clarify C1).** Choice: if a worker turn is mid-stream when `/goal <cond>` is set, deliver the condition via `deliverAs: "followUp"` rather than rejecting. Alternatives: reject with "agent busy" (worse UX, inconsistent with the loop's own injection mechanism). Rationale: uniform delivery path. *(ADR test: 2/4.)*

## Risks / Trade-offs

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Worker blocks on tool-approval prompts → loop stalls | High | Med | Document: unattended use needs approvals already relaxed (out of scope to change pi's mode); status indicator makes a stall visible |
| Judge under-feeding → false negatives burn the budget | Med | Med | Budget caps cost (D6); D7 feeds the most relevant recent output; command help guides provable conditions |
| Judge over-trust / hallucinated "met" | Med | Med | Strict prompt + JSON contract (D3) + default-not-met on parse failure; user can `/goal clear` |
| Re-entrancy / runaway turns | Low | High | `evaluating` guard (D4) + hard budget (D6) |
| Interactive-mode behavior unverified (spikes were `-p`) | Med | Low | Verify `setStatus` indicator + live loop during apply (tasks 5.2) |
| Judge cost every turn | High | Low | Small/cheap default model; negligible vs main turn |

## Migration Plan

Add `dot_pi/agent/extensions/goal/index.ts`; `chezmoi apply` deploys to `~/.pi/agent/extensions/goal/index.ts`; pi auto-discovers on next launch. Rollback: delete the file + `chezmoi apply` (or `git revert`). No state migrations, no other files, no mise task (Principle V), no secrets (Principle III). The `openspec/` workspace is not deployed (Principle VIII).

## Open Questions

- Final default judge model + preference order (pending which providers authenticate reliably day-to-day).
- Whether to add a wall-clock bound alongside the turn budget.
- Whether to persist an active goal across `--resume`/`--continue` in a later iteration.
