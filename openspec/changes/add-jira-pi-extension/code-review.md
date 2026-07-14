# Code Review

<!--
Sealed from findings-file-sole-verdict-source:
  /tmp/opsx-cr-add-jira-pi-extension/r1-sonnet-findings.md
  /tmp/opsx-cr-add-jira-pi-extension/r1-opus-findings.md
Quiet round (P0+P1 = 0 max across reviewers) → seal pass.
-->

**Change:** add-jira-pi-extension
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** anthropic/claude-sonnet-5 + anthropic/claude-opus-4-8 via pi-subagents delegate (fresh, blind)
**Diff Base SHA:** 7aac986d5e1cfa3b6b608b74d162365c363300b0
**Reviewed Range:** 7aac986d5e1cfa3b6b608b74d162365c363300b0..9b17da260e6a736fc982afe48c9e6160173e4d48
**Attested HEAD:** 9b17da260e6a736fc982afe48c9e6160173e4d48
**Baseline:** intent.md + proposal + specs + design + plan + tasks status
**Generated:** 2026-07-14

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 0 | 0 | 1 | 3 | anthropic/claude-sonnet-5:pass; anthropic/claude-opus-4-8:pass | 9b17da260e6a736fc982afe48c9e6160173e4d48 |

## Findings

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | `client.ts` `resolveSdkRoot` hardcodes mise node version paths (fragile on upgrade; failure graceful via D8) | P2 | open |
| 2 | `getArgumentCompletions` returns `[]` vs documented `null` idiom | P3 | open |
| 3 | `domain.md` blank line splits Out-of-scope list (cosmetic) | P3 | open |
| 4 | `agentEndCount` increments while disabled (harmless; nudges still gated) | P3 | open |
| 5 | Jira MCP URL committed in config.json (public endpoint, not a secret) | P3 | open |
| 6 | `looksLikeIssueKey` requires ≥2-char project key (Jira practice) | P3 | open |

Gate-manifest note: diff adds required `jira-extension-tests` row to
`openspec/opsx-gates.yaml` — additive only; no existing gate removed or
`required:true→false` flip.

## Applied fixes

- (none — quiet round; no P0/P1)

## Residual risks

- Hardcoded SDK path may need a follow-up after mise node bumps (P2 #1) —
  route to follow-ups at archive if desired; does not block intent outcomes.

## Verdict rationale

Both blind reviewers attested the worktree HEAD and returned **pass** with
zero open P0/P1 (max-across-reviewers). Diff delivers the frozen intent
(standalone jira extension, own mcp-remote client, session bind, full v1
commands, latch-gated context, UI nudges, work-profile deploy, offline
tests + gate). Advisory P2/P3 recorded; do not force another round.
