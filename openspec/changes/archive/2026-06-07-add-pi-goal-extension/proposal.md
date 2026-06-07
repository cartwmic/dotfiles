## Why

Pi has no way to keep working autonomously toward a verifiable end state — every turn returns control to the user. Claude Code's `/goal` solves this by pairing the worker model with a separate small "judge" model that decides, after each turn, whether a stated completion condition holds. A spike against the live pi runtime confirmed pi exposes every primitive needed (`agent_end` hook, `sendUserMessage` follow-up, separate `complete()` judge call, transcript read) to clone this as a pure userland extension — no fork of pi.

## What Changes

- Add a new local pi extension at `dot_pi/agent/extensions/goal/index.ts` (single TypeScript file), following the established extensions convention set by `dot_pi/agent/extensions/web-search/` — NOT the skills pipeline (Principle II/IX govern skills, not extensions).
- Register a `/goal` command with three modes: set (`/goal <condition>`), status (`/goal` no-arg), clear (`/goal clear` + aliases `stop|off|reset|none|cancel`).
- Setting a goal immediately starts a worker turn directed by the condition.
- After each agent turn (`agent_end`), a separate small "judge" model evaluates the condition against the transcript and returns a JSON verdict `{met, reason}`. Not met → inject the reason as a follow-up, starting another turn. Met → clear the goal and notify.
- Enforce a hard max-turns runaway guard (default 25) so the loop always terminates.
- Show a `◎ goal active` footer status indicator via `ctx.ui.setStatus` while a goal runs.

## Capabilities

### New Capabilities
- `goal-loop`: A session-scoped autonomous completion loop for pi — set/check/clear a completion condition, judge it after each turn with a separate small model, and keep the worker running until the condition is met or a turn budget is exhausted.

### Modified Capabilities
<!-- None. Additive standalone extension; no existing capability spec changes. -->

## Impact

**Affected files:**
- New: `dot_pi/agent/extensions/goal/index.ts` → deploys via `chezmoi apply` to `~/.pi/agent/extensions/goal/index.ts` (Principle I: deployed home config lives at its chezmoi source path; `dot_pi/` prefix → `~/.pi/`, distinct from the non-deployed root `.pi/` per domain invariant #4).

**Dependencies:** imports `@mariozechner/pi-coding-agent` (ExtensionAPI types) and `@mariozechner/pi-ai` (`complete`), both already resolvable for pi extensions; no new package installs, no mise task (Principle V untouched).

**Runtime:** one command + one `agent_end` handler; one extra small-model `complete()` call per worker turn while a goal is active (negligible vs main turn).

**Non-goals (deferred):** tool auto-approval / unattended permission bypass (worker keeps pi's existing approval mode); token-budget conditions; cross-resume goal persistence.

**No secrets** introduced (Principle III): judge auth reuses pi's existing model-registry credential resolution; no keys in source.
