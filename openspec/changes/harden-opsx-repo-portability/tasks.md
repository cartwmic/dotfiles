# Tasks: harden-opsx-repo-portability

<!-- authored: in-session -->

<!-- File contracts recorded autonomously (loop mode — no user prompt):
intent per task; files_allowed globs; allow_new_files true only where noted. -->

## 1. Integration-branch resolver

- [x] 1.1 Add `opsx_integration_branch()` helper to `dot_local/bin/executable_opsx`: args `<root> [change]`; order = review.md `**Integration Branch:**` (trimmed, non-empty, != `<detected-at-capture>`) → `git symbolic-ref --short refs/remotes/origin/HEAD` (strip `origin/`) → local `main` → local `master` → return non-zero with named stderr error. No model calls, BSD-safe.
      <!-- contract: intent=feature; files_allowed=dot_local/bin/executable_opsx; allow_new_files=false -->
- [x] 1.2 Route `opsx status` Diff-Base staleness through the resolver; unresolvable → existing stable placeholder, still exit 0 (clarify C3).
      <!-- contract: intent=fix; files_allowed=dot_local/bin/executable_opsx; allow_new_files=false -->
- [x] 1.3 Route archive-check base-currency through the resolver; failure/remedy messages name the resolved branch (never literal `main`); unresolvable → ARCHIVE-CHECK-FAIL named error.
      <!-- contract: intent=fix; files_allowed=dot_local/bin/executable_opsx; allow_new_files=false -->
- [x] 1.4 Route the multi-dir detector scan range (`DIFF_BASE..<resolved>`) through the resolver; skip advisory scan silently only when branch unresolvable AND no locator (same posture as today's missing-locator skip).
      <!-- contract: intent=fix; files_allowed=dot_local/bin/executable_opsx; allow_new_files=false -->

## 2. Project-artifact preflight + template

- [x] 2.1 Add `project-artifacts` cheap gate check: `test -s "$ROOT/openspec/constitution.md"` and `test -s "$ROOT/openspec/domain.md"`; each miss emits `GATE-FAIL project-artifacts 1 <file> absent or empty — scaffold from <template> under ~/.local/share/openspec/schemas/opsx-superpowers/templates/`; runs at every Scale, no waiver key, no auto-scaffold (intent D3/D4, clarify C2).
      <!-- contract: intent=feature; files_allowed=dot_local/bin/executable_opsx; allow_new_files=false -->
- [x] 2.2 review.md template: `**Integration Branch:** main` → `**Integration Branch:** <detected-at-capture>`; locator comment documents capture-time detection via the resolver (clarify C1).
      <!-- contract: intent=fix; files_allowed=dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md; allow_new_files=false -->
- [x] 2.3 Prose audit: update skill/schema surfaces that assert literal `main` for these checks (apply reference locator section, archive reference land step) to resolved-branch language; opsx-loop extension untouched (out of scope).
      <!-- contract: intent=fix; files_allowed=dot_local/share/agent-harness/canonical/skills/**,dot_local/share/openspec/schemas/opsx-superpowers/**; allow_new_files=false -->

## 3. Tests

- [x] 3.1 opsx-cli suite: resolver order — locator wins; sentinel/whitespace field skipped; origin/HEAD; master-only; unresolvable → status placeholder + exit 0; non-main staleness counted.
      <!-- contract: intent=feature; files_allowed=tests/opsx-cli/test_opsx_cli.sh; allow_new_files=false -->
- [x] 3.2 opsx-gate suite: preflight — missing constitution red (names template), empty domain red, both present green; fires at XS/S/M alike.
      <!-- contract: intent=feature; files_allowed=tests/opsx-gate/test_opsx_gate.sh; allow_new_files=false -->
- [x] 3.3 archive-check: non-main repo (`trunk`) base-currency pass when current, fail (naming `trunk` + remedy) when stale.
      <!-- contract: intent=feature; files_allowed=tests/opsx-cli/test_opsx_cli.sh,tests/opsx-gate/test_opsx_gate.sh; allow_new_files=false -->

## 4. Verify

- [x] 4.1 Full validator sweep green (`bash -n`, opsx-cli, opsx-gate, opsx-models, opsx-review-convergence, author-marker, bun opsx-loop, both `openspec validate --strict`); fill verify.md from the shipped template with AC↔test map for the 6 delta ACs.
      <!-- contract: intent=infra; files_allowed=openspec/changes/harden-opsx-repo-portability/verify.md; allow_new_files=true -->
