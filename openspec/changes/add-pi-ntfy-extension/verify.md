# Verify

**Change:** add-pi-ntfy-extension
**Generated:** 2026-06-07
**Verification Mode:** retained-recommended
**Worktree Mode:** same-tree (no worktree base SHA; diffs against the apply commit)

## Check 1 — Structural validation

`openspec validate add-pi-ntfy-extension --strict` → `Change 'add-pi-ntfy-extension' is valid`. **PASS**

## Check 2 — Task completion

`grep -c "^- \[ \]" tasks.md` → 0 unchecked; 11/11 tasks `[x]`. **PASS**

## Check 3 — Delta vs current spec coherence

Capability `pi-ntfy-notify` is NEW (no `openspec/specs/pi-ntfy-notify/` exists). Delta is pure `## ADDED Requirements` (5 requirements), parseable. No MODIFIED/REMOVED/RENAMED. **PASS**

## Check 4 — Commit hygiene

`git log` apply commit:
- `feat(pi): ntfy notify extension (agent_end -> ntfy push)` — subject 56 chars (≤72); body explains why (remote-awaiting-input signal, fire-and-forget, non-secret URL). **PASS**

## Check 5 — AC↔test mapping (canonical IDs)

**Forward** — each `### Requirement` canonical ID appears in ≥1 changed file:

| AC ID | Files | Status |
|---|---|---|
| pi-ntfy-notify.notify-on-turn-end | spec, analyze, tasks, clarify, plan | PASS |
| pi-ntfy-notify.notification-identifies-session | spec, analyze, tasks, plan, index.test.ts | PASS |
| pi-ntfy-notify.notification-includes-content-excerpt | spec, analyze, tasks, plan, index.test.ts | PASS |
| pi-ntfy-notify.no-op-when-unconfigured | spec, analyze, tasks, plan, index.test.ts | PASS |
| pi-ntfy-notify.delivery-failures-are-non-fatal | spec, analyze, design | PASS |

**Reverse** — test file `index.test.ts` cites canonical IDs: `notification-includes-content-excerpt`, `notification-identifies-session`, `no-op-when-unconfigured`. **PASS**

## Check 6 — Constitution compliance audit

Changed files: 4 code (`dot_pi/agent/extensions/ntfy/*`) + 10 openspec artifacts (12 total ≤ 50 → audit all, code files material).

| Principle | Status | Note |
|---|---|---|
| I. Chezmoi single source of truth | compliant | Extension at `dot_pi/agent/extensions/ntfy/` → `~/.pi/...`; deployed via `chezmoi apply` |
| III. No secrets in source | compliant | `config.json` holds plain internal-only URL (not a secret); no credentials committed |
| VII. Termux config not chezmoi-deployed | compliant | No `dot_termux/`; phone uses GUI ntfy app |
| VIII. openspec not deployed | compliant | Change under `openspec/`, excluded by `.chezmoiignore` |
| II, IV, V, VI, IX, X | inapplicable | No skill / install script / mise task / plist / skill-edit / memory-write |

**PASS**

## Unit tests

`node --test dot_pi/agent/extensions/ntfy/index.test.ts` → **10 pass, 0 fail.**
Covers excerpt truncation/whitespace/placeholder, reasoning exclusion, session-name fallback, zellij-omission, unconfigured no-op.

## Integration verification (live)

Exercised the extension's real code path (`loadConfig → lastAssistantText → extractExcerpt → buildNotification → fetch`) against the live server:

- `loadConfig` → `{ url: "https://ntfy.internal.cartwmic.com/pi", maxExcerptChars: 200 }`
- Title: `pi ready: ntfy-apply-test`
- Body: `zellij:workspace · /Users/cartwmic/.local/share/chezmoi · Test notification … works end to end.`
- HTTP **200**; ntfy ack `{"id":"EjWN0pOv2HuY","topic":"pi","priority":4,"tags":["robot"], ...}`
- Injected `thinking` block (`internal reasoning that must NOT leak`) was **absent** from the delivered message → reasoning-exclusion confirmed.

## Deployment

`chezmoi apply ~/.pi/agent/extensions/ntfy` → files present at `~/.pi/agent/extensions/ntfy/` (index.ts, config.json, index.test.ts, README.md). Auto-discovered by pi on next launch (no `settings.json` entry needed).

## Completion Decision

**green** — all 6 checks pass; unit + live integration verified; extension deployed.
