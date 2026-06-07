# Analyze Findings

**Mode:** single-model (Scale = M; adversarial-review-cycle reserved for Scale ≥ L)
**Generated:** 2026-06-07 by claude-opus

## Check 1 — Constitution compliance

| Principle | Status | Rationale | Severity |
|---|---|---|---|
| I. Chezmoi single source of truth | compliant | Extension source at `dot_pi/agent/extensions/ntfy/` → `~/.pi/...` (design Context, Impact) | — |
| II. Skills in canonical-harness pipeline | inapplicable | This is a pi extension, not a cross-harness skill | — |
| III. No secrets in source | inapplicable | ntfy URL `https://ntfy.internal.cartwmic.com/pi` is internal-only / not externally reachable — not a secret; committed as plain config (design D2) | — |
| IV. Install scripts idempotent | inapplicable | No install/run_onchange script introduced | — |
| V. mise tasks own dev-tool install | inapplicable | No dev-tool install; zero new deps | — |
| VI. launchd jobs declare PATH | inapplicable | No `.plist` introduced | — |
| VII. Termux config not chezmoi-deployed | compliant | No `dot_termux/`; phone uses GUI ntfy app (design Context) | — |
| VIII. openspec workspace not deployed | compliant | Change lives under `openspec/changes/`, excluded by `.chezmoiignore` | — |
| IX. Skill changes adversarial review ≥ M | inapplicable | No existing skill modified | — |
| X. Memory promotion opt-in | inapplicable | No automatic memory writes | — |

## Check 2 — EARS pattern check (major, human-triage)

Regex `/WHEN\s+[^.]*\b(error|fail|invalid|reject|deny|unauthor)/i` over `specs/**/*.md`: **0 matches.**

| # | File:line | AC | True positive? | Suggested rewrite | Status |
|---|---|---|---|---|---|
| — | — | (no matches) | — | — | clean |

All error/unwanted conditions correctly use `IF…THEN` (verified: lines 14, 18, 30, 42, 46, 54, 62 use IF; the `WHEN`-introduced error reference at line 62 is inside an `IF` scenario antecedent, not a `WHEN` trigger).

## Check 3 — AC↔design coverage

| AC ID | Design section reference | Status | Severity |
|---|---|---|---|
| pi-ntfy-notify.notify-on-turn-end | D1 (trigger), D5 (guards) | covered | — |
| pi-ntfy-notify.notification-identifies-session | D4 (shape: pi name + zellij) | covered | — |
| pi-ntfy-notify.notification-includes-content-excerpt | D4 (excerpt, maxExcerptChars) | covered | — |
| pi-ntfy-notify.no-op-when-unconfigured | D5 (no-op), D2 (config) | covered | — |
| pi-ntfy-notify.delivery-failures-are-non-fatal | D3 (fire-and-forget), R5 (timeout) | covered | — |

## Check 4 — design↔ADR promotion candidates

| Decision | 4-point score | ADR-candidate? | Rationale or "ADR not warranted because…" |
|---|---|---|---|
| D1 (agent_end vs turn_end) | 4/4 | yes | Defines core behavior; flag for ADR offer at archive |
| D2 (plain URL config value) | 1/4 | no | ADR not warranted; plain config detail (URL is non-secret after user confirmation) |
| D3 (global fetch fire-and-forget) | 1/4 | no | ADR not warranted; conventional implementation detail |
| D4 (notification shape) | 1/4 | no | ADR not warranted; cosmetic/behavioral detail |
| D5 (guards/no-op) | 0/4 | no | ADR not warranted; direct encoding of ACs |

Note: Scale M < L, so adversarial-review not invoked. ADR promotion offered by `openspec-archive-change` at archive for D1 only (D2 demoted after the URL was confirmed non-secret).

## Check 5 — Duplicate detection

| # | Locations | Restated constraint | Action |
|---|---|---|---|
| Dup1 | spec `delivery-failures-are-non-fatal` + design D3 | "never block the turn" | differentiate — spec states WHAT (non-fatal), design states HOW (fire-and-forget + timeout). Expected layering; no action. |

Note: requirement `channel-secret-excluded-from-source` was REMOVED from specs (URL confirmed non-secret); coverage/checklist updated accordingly.
| Dup2 | clarify I1 + design D5 | unconfigured precedence over deliver | keep — clarify records the resolution, design implements it. No action. |

## Check 6 — Implementation language in specs

| # | AC ID | Tech mentioned | Rewrite suggestion |
|---|---|---|---|
| Imp1 | pi-ntfy-notify.notify-on-turn-end | "print or json mode" (scenario, line 18) | Minor: pi-specific mode names used as a behavioral proxy for "non-interactive session". Acceptable — the Requirement text says "interactive session"; scenario names concrete modes for testability. No change required. |

No AC names ntfy/fetch/agent_end/1Password — those live only in design. Specs remain solution-free at the Requirement level.

## Check 7 — Unresolved clarify findings

| # | clarify.md ref | Status | Risk |
|---|---|---|---|
| — | all (A1–A3, I1–I2, C1–C3) | answered | none — gate READY for design was satisfied |

## Outstanding risks

- R1 (excerpt content exposure) — mitigated by internal-only ntfy host (not externally reachable). Low/Low.
- No open questions block tasks; ntfy server at `ntfy.internal.cartwmic.com` assumed provisioned.

## Summary

- Blockers: 0
- Major findings: 0
- Minor findings: 1 (Imp1 — accepted, no change)
- Scope change (post-design): URL confirmed non-secret → removed `channel-secret-excluded-from-source` requirement + D2 secret handling; 5 requirements remain.
- **Gate status:** READY for tasks
