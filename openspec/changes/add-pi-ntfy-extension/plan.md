# Execution Plan

<!-- Execution Mode = standard (review.md). Pure helpers get unit tests
(step 3); the event/delivery path is integration-verified (step 5). Steps
are ordered, not full TDD micro-tasks. -->

## Plan step 1: Scaffold extension + reference config

- **Covers:** T1.1, T1.2
- **Pre-conditions:**
  - `dot_pi/agent/extensions/` exists in chezmoi source (it does — `web-search/`, `subagent/`).
- **Action:**
  1. Create `dot_pi/agent/extensions/ntfy/index.ts` with default factory + type-only `ExtensionAPI` import.
  2. Create `dot_pi/agent/extensions/ntfy/config.json` with `{ "url": "https://ntfy.internal.cartwmic.com/pi", "maxExcerptChars": 200 }`.
  3. Commit `feat(pi): scaffold ntfy notify extension`.
- **Verification:** `tsc --noEmit` on the file typechecks.
- **Rollback:** `rm -rf dot_pi/agent/extensions/ntfy`.

## Plan step 2: Config loading

- **Covers:** T2.1, T2.2
- **Pre-conditions:** step 1 committed.
- **Action:**
  1. `loadConfig()` reads sibling `config.json`; missing/unreadable → disabled config (no throw).
  2. Read `url` verbatim at init; empty/absent → disabled. (No secret resolution — plain URL.)
  3. Commit `feat(pi): ntfy config load`.
- **Verification:** manual: temporarily blank `url` → extension disables silently.
- **Rollback:** revert the commit.

## Plan step 3: Pure helpers + unit tests

- **Covers:** T3.1, T3.2, T5.1
- **Pre-conditions:** step 2 committed.
- **Action (test-first for pure helpers):**
  1. Write failing tests citing `pi-ntfy-notify.notification-includes-content-excerpt` (excerpt: truncation+`…`, whitespace collapse, no-text placeholder, reasoning excluded) and `pi-ntfy-notify.notification-identifies-session` (title fallback, zellij segment omitted when env unset).
  2. Run → expect FAIL.
  3. Implement `extractExcerpt` + `buildNotification`.
  4. Run → expect PASS.
  5. Commit `feat(pi): ntfy excerpt + notification assembly (+tests)`.
- **Verification:** `vitest --run` green; AC IDs grep-match in test files.
- **Rollback:** revert the commit.

## Plan step 4: Event wiring + delivery

- **Covers:** T4.1, T4.2
- **Pre-conditions:** steps 1–3 committed.
- **Action:**
  1. `pi.on("agent_end")` with guards: `!ctx.hasUI`, `event.willRetry`, disabled config → early return (AC `pi-ntfy-notify.notify-on-turn-end`, `pi-ntfy-notify.no-op-when-unconfigured`).
  2. POST via global `fetch` with `Title`/`Priority`/`Tags` headers, body from `buildNotification`, `AbortSignal.timeout(5000)`, `.catch(() => {})` (AC `pi-ntfy-notify.delivery-failures-are-non-fatal`).
  3. Commit `feat(pi): ntfy agent_end delivery with guards`.
- **Verification:** `tsc --noEmit`; manual smoke in step 5.
- **Rollback:** revert the commit.

## Plan step 5: Integration verification + docs

- **Covers:** T6.1, T6.2
- **Pre-conditions:** steps 1–4 committed; ntfy server reachable at `ntfy.internal.cartwmic.com`; ntfy Android app installed + subscribed to topic `pi`.
- **Action:**
  1. `chezmoi apply` on the remote host.
  2. Run `pi` interactively; complete a turn; confirm phone receives notification with correct pi session name + zellij name + excerpt.
  3. Blank/remove `url` → confirm no notification, no error (no-op path).
  4. Write `verify.md` with these steps + results; add prerequisites note to the extension dir.
  5. Commit `docs(pi): ntfy verify steps + prerequisites`.
- **Verification:** notification observed on device; no-op path confirmed; `verify.md` complete.
- **Rollback:** blank config `url` (disables) or `rm -rf` the extension dir.

## Completion Verification

- `vitest --run` (pure-helper unit tests) green.
- Integration: a real `agent_end` on the remote produces a phone notification with correct session identity + excerpt (step 5.2).

## Manual Adjustments

- No TDD micro-task expansion for the event/delivery path (step 4): its dependencies (pi `ExtensionAPI`, live `agent_end`, network) make integration verification the honest acceptance gate. Pure helpers (step 3) are test-first.
