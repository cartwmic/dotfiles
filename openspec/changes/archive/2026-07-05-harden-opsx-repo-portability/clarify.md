# Clarify: harden-opsx-repo-portability

<!-- authored: in-session -->

<!--
Scale S ambiguity-only pass (Pass 1). Blind dispatch: claude-bridge/claude-opus-4-8
(pi-subagents delegate, fresh context), report /tmp/hrp-clarify-r1.md, reviewed
specs at commit 9943781. Findings resolved in-place by the orchestrator per the
2-option discipline; spec deltas patched same turn.
-->

## Findings (ambiguity pass — 3 found, 3 resolved, 0 unanswered)

### C1 — placeholder token unpinned across resolver + template — **resolved: Option A**
Ambiguity: resolver step (1) skips a "non-placeholder" field but no spec fixed
the token; an unfilled literal `main` could read as a real branch.
Resolution: single shipped sentinel `<detected-at-capture>` — template ships
exactly it, resolver recognizes exactly it (after whitespace trim); "non-empty"
= non-whitespace. Rationale: intent Q1 makes the field the locator's source of
truth filled by detection; one fixed token is the only reading that stops a
wrong literal from winning. Specs patched: opsx-cli resolver requirement +
locator-wins scenario; opsx-workflow-schema locator-default requirement.

### C2 — preflight "non-empty" vs whitespace-only files — **resolved: Option A**
Ambiguity: byte-size test vs non-whitespace-content test for
constitution.md/domain.md.
Resolution: size > 0 bytes (`test -s` semantics). Rationale: intent D4 says
"empty file counts as missing" and Q2 names a "file-existence/size test" —
literal, BSD-compatible, no content parsing. Spec patched:
opsx-gate-enforcement Project Artifact Preflight.

### C3 — resolver fail-loud vs `opsx status` exit-0-always — **resolved: Option A**
Ambiguity: unresolvable branch in the status view — propagate named error
(non-zero) or degrade to placeholder (exit 0)?
Resolution: loud failure is reserved for blocking invokers (gate,
archive/land); `opsx status` degrades to its stable placeholder and exits 0.
Rationale: status is spec'd as a never-crash view (exit 0 always); intent's
fail-loud targets the functional comparison checks. Spec patched: opsx-cli
resolver requirement + split fail-loud scenario into blocking vs status-view
scenarios.
