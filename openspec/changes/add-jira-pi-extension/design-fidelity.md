# Design Fidelity — add-jira-pi-extension

<!--
Sealed from /tmp/opsx-fidelity-add-jira-pi-extension/judge3-findings.md
(findings-file-sole-verdict-source). Round 3 full-sweep after human re-arm.
-->

**Fidelity:** delivered

**Judge Provenance:** anthropic/claude-sonnet-5 via pi-subagents delegate; review_mode: blind-single-judge
**Attested HEAD:** b1096102456e6e133f084b6a27ad17ed325707c2
**Attested Path:** /Users/mcartwright/.local/share/chezmoi

**Digest sha256 (intent.md):** 5296a1c1fa6398052df52a38a8e74eb9eed8342451ec92b39a8d44bf70b538e3
**Digest sha256 (design.md):** 0916f59bd910461bd817d34b2a6c7aeaaaf58d5ec28b2fe245571a71582e9faf
**Digest sha256 (specs/pi-jira-extension/spec.md):** 7428594594afd7819e09d361db8fa18c9d3795d3805058b45c4a041cfaa8e493

## Per-AC verdict table

| # | Capability / Requirement / Scenario (AC key) | Verdict | Evidence (design section) |
|---|---|---|---|
| 1 | pi-jira-extension / Extension Is Standalone From Opsx / Opsx workflows unchanged | entailed | Goals/Non-Goals + Migration Plan (no opsx touch) |
| 2 | pi-jira-extension / Own Mcp Client Transport / Command completes without agent turn | entailed | D1 |
| 3 | pi-jira-extension / Own Mcp Client Transport / Transport failure surfaces warning | entailed | D8 |
| 4 | pi-jira-extension / Session Only Ticket Binding / Bind and clear | entailed | D5 |
| 5 | pi-jira-extension / Master Toggle And Status / Status reports state | entailed | D6 |
| 6 | pi-jira-extension / Search Bind Show Create Sync Transition Commands / Search then bind | entailed | D6 |
| 7 | pi-jira-extension / Search Bind Show Create Sync Transition Commands / Sync requires confirm | entailed | D4 |
| 8 | pi-jira-extension / Search Bind Show Create Sync Transition Commands / Sync refuses when unbound | entailed | D5 |
| 9 | pi-jira-extension / On Demand Context Inject Only / Explicit context inject | entailed | D3 |
| 10 | pi-jira-extension / On Demand Context Inject Only / Context refuses when unbound | entailed | D5 |
| 11 | pi-jira-extension / On Demand Context Inject Only / No auto-inject without latch | entailed | D3 + R4 |
| 12 | pi-jira-extension / Configurable Ui Nudge Only / Nudge when unbound | entailed | D7 |
| 13 | pi-jira-extension / Configurable Ui Nudge Only / Nudge disabled when off | entailed | D7 |
| 14 | pi-jira-extension / Work Profile Only Deploy / Personal profile skips deploy | entailed | D2 |
| 15 | pi-jira-extension / No Secrets In Logs Or Source / Failure message has no token material | entailed | D8 |
| 16 | pi-jira-extension / Agent Independent Unit Tests / Tests pass offline | entailed | D9 |

## Advisory Findings

- AC9 / D3 — intent.md blanket "No before_agent_start hook" vs latch-gated consume authorized by spec.md + D3; non-blocking. Recommend archive-time intent wording reconcile ("no auto-inject" vs "no hook").
- AC6 — parent requirement names six MCP tools; D4/D5/D6 cover scenarios without naming every tool string; informational only.

## Verdict rationale

All 16 canonical AC rows entailed by D1–D9 after round-2 fixes (D8/D9 + latch wording). Fidelity delivered.
