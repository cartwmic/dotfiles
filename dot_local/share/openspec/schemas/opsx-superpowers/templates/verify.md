# Verify

<!--
Six hard-gate checks before archive. All 6 must pass for green.
openspec-archive-change HARD-GATES on Completion Decision = green when
Verification Mode = retained-required.

This artifact is produced by openspec-apply-change at the end of apply
(NOT declared in the schema's artifact graph — see schema.yaml apply
instruction for rationale). Template lives at
~/.local/share/openspec/schemas/opsx-superpowers/templates/verify.md.
-->

**Generated:** YYYY-MM-DD by <model / skill>
**Change:** <change-name>

## Completion Decision

<!--
green  — all 6 pass; archive allowed
red    — any check fails; archive refused

There is no "yellow" — keeping the decision binary defeats Fowler's
"false sense of control" critique. If you want to ship despite a minor
issue, document the exception in the row's Details column and the user
authorizing must explicitly override at archive time.
-->

**Status:** <pending | green | red>

## Checks

| # | Check | Status | Details |
|---|---|---|---|
| 1 | Structural validation (`openspec validate --strict --json`) | pass\|fail | <stdout summary> |
| 2 | Task completion (zero `- [ ]` in tasks.md) | pass\|fail | <count of unchecked> |
| 3 | Delta vs current spec coherence | pass\|fail | <per-capability diff summary> |
| 4 | Commit hygiene (subject ≤72; body explains why) | pass\|fail | <list of offending commits> |
| 5 | AC↔test mapping (canonical IDs) | pass\|fail | <forward + reverse coverage> |
| 6 | Constitution compliance audit (sampling) | pass\|fail | <violations if any> |

## Check 5 detail — AC↔test mapping (canonical ID format)

<!--
Canonical AC ID format: <capability>.<requirement-slug>
Where <requirement-slug> = lowercased requirement name, non-alnum → '-',
repeated '-' collapsed, leading/trailing '-' stripped.

Forward: every Requirement in specs/**/*.md → ≥1 test file in the
change's diff contains the literal AC ID string.

Reverse: every test file added or modified in the change's diff →
contains ≥1 AC ID string OR a `# spec-exempt: <reason>` marker.

Greps used (deterministic, no LLM judgment):
  Forward:
    For each Requirement R in specs:
      Compute id = <capability>.<slug-of-R-name>
      Run: git diff --name-only <base-sha>..HEAD | xargs grep -l "$id"
      Pass if any match.

  Reverse:
    Get list of test files in diff (heuristic: paths matching
    /(^|/)tests?/ or /\.(test|spec)\.[^.]+$/).
    For each test file:
      grep -E '<capability>\.[a-z0-9-]+' file → if ≥1 match, pass
      OR grep -E '# *spec-exempt:' file → exempt, pass
      Else: orphan.
-->

### Forward coverage (each AC has ≥1 test)

| AC ID | Test references | Status |
|---|---|---|
| <capability>.<slug> | <test file(s) + line(s) where ID appears> | covered\|uncovered |

### Reverse coverage (each changed test references ≥1 AC)

| Test file | AC references | Status |
|---|---|---|
| <test file> | <AC ID(s)> or `# spec-exempt: <reason>` | referenced\|orphan\|exempt |

## Check 6 detail — Constitution sampling

<!--
Sampling strategy:
  Let N = number of files changed.
  If N ≤ 10: audit ALL changed files (no sampling).
  If 10 < N ≤ 50: audit all + emit a coverage note.
  If N > 50: stratified sample — one file per top-level dir, plus 5
    random additional files. Coverage note in Details column gives
    the residual false-negative envelope.
-->

| Sampled file | Principles checked | Status | Notes |
|---|---|---|---|
| <file> | I, III, V | compliant\|violated | <details> |

**Sampling coverage:** <N audited of M changed = X%>

## Summary

- Pass count: <n>/6
- Decision: <green | red>
- **Archive gate:** <READY | BLOCKED reason>

## Override (if archiving despite red)

<!-- If the user explicitly authorizes archive despite a red status,
record here:
  - Which check failed
  - Why it's acceptable for this change
  - Follow-up action (e.g., "addressed in change Y")
The override MUST be authorized by an explicit human decision recorded
in the user's terminal; openspec-archive-change refuses silent overrides.
-->
