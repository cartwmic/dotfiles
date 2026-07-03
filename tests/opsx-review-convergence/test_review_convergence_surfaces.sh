#!/usr/bin/env bash
# Deterministic assertions that the review-convergence discipline is present
# in its prose surfaces (schema templates + canonical skills). Guards against
# silent regression of the discipline text during future template/skill edits.
#
# Cites acceptance criteria by canonical ID so the verify gate's forward
# AC<->test mapping (check 5) finds literal matches:
#   opsx-review-convergence.baseline-bounded-verdict-contract
#   opsx-review-convergence.severity-rubric-and-floor
#   opsx-review-convergence.finding-routing-and-follow-ups
#   opsx-review-convergence.orchestrator-round-ledger
#   opsx-review-convergence.trajectory-stop-and-round-budget
#   opsx-review-convergence.disclosure-round
#   opsx-review-convergence.decision-audit-landing
#   opsx-review-convergence.scope-widening-protocol
#   opsx-review-convergence.advisory-surface-audit
#   opsx-review-convergence.reviewer-model-stability
#   opsx-loop-orchestration.review-dispatch-bound-by-convergence-discipline
#   opsx-loop-orchestration.pre-apply-surface-audit-dispatch
#   opsx-loop-orchestration.scope-widening-handled-in-the-loop
#   opsx-post-impl-review.verdict-under-the-severity-floor
#   opsx-post-impl-review.round-ledger-sealed-in-code-review
#   opsx-post-impl-review.disclosure-consensus-review-mode
#   opsx-post-impl-review.waiver-sealed-pass
#   opsx-post-impl-review.adversarial-review-with-degradation
#   opsx-workflow-schema.review-max-rounds-front-matter
#   opsx-workflow-schema.convergence-template-support
# Intentional: no `set -e` — assertions drive explicit pass/fail counters and
# the final exit is `[ "$failc" -eq 0 ]`; -e would abort on the first failed
# grep instead of reporting every failed assertion.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TPL="$ROOT/dot_local/share/openspec/schemas/opsx-superpowers/templates"
LOOP_SKILL="$ROOT/dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md"
APPLY_REF="$ROOT/dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md"

pass=0; failc=0
ok()  { printf 'ok   - %s\n' "$1"; pass=$((pass+1)); }
nok() { printf 'NOT OK - %s\n' "$1"; failc=$((failc+1)); }
has() { # has <desc> <file> <grep-pattern>
	if grep -q -- "$3" "$2" 2>/dev/null; then ok "$1"; else nok "$1 (pattern [$3] missing in ${2#"$ROOT"/})"; fi; }

# --- opsx-workflow-schema.review-max-rounds-front-matter ---
has "review.md template documents review_max_rounds" "$TPL/review.md" "review_max_rounds"
has "review.md template states the default 5" "$TPL/review.md" "default 5"

# --- opsx-workflow-schema.convergence-template-support ---
has "review.md template has Scope Expansions section" "$TPL/review.md" "## Scope Expansions"
has "code-review template has round-ledger columns" "$TPL/code-review.md" "| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |"
has "follow-ups template exists with queue" "$TPL/follow-ups.md" "## Queue"

# --- opsx-review-convergence.baseline-bounded-verdict-contract ---
has "code-review template embeds the verdict contract" "$TPL/code-review.md" "Verdict contract"
has "contract restricts FAIL to baseline violation or objective defect" "$TPL/code-review.md" "objective correctness/security defect"

# --- opsx-review-convergence.severity-rubric-and-floor ---
has "code-review template carries the P0-P3 rubric" "$TPL/code-review.md" "P3  nit"
has "severity floor stated (pass iff no open P0/P1)" "$TPL/code-review.md" "no open P0/P1"

# --- opsx-review-convergence.orchestrator-round-ledger ---
has "ledger consolidation = MAX across reviewers" "$TPL/code-review.md" "Consolidated counts = MAX"
has "IX pass accepts disclosure-consensus with >=2 models" "$TPL/code-review.md" "disclosure-consensus when it consolidated"
has "apply ref IX accepts disclosure-consensus with >=2 models" "$APPLY_REF" "disclosure-consensus\` when the disclosure round consolidated"
has "blind prompts never carry the ledger" "$TPL/code-review.md" "NEVER include this ledger"
has "loop skill maintains the round ledger" "$LOOP_SKILL" "Round ledger"

# --- opsx-review-convergence.trajectory-stop-and-round-budget ---
has "loop skill has converged stop" "$LOOP_SKILL" "latest round P0+P1 = 0"
has "loop skill has treadmill stop" "$LOOP_SKILL" "flat or rising across the two most recent rounds"
has "loop skill has review_max_rounds budget stop" "$LOOP_SKILL" "review_max_rounds"

# --- opsx-review-convergence.disclosure-round ---
has "loop skill defines the single disclosure round" "$LOOP_SKILL" "Disclosure round (max 1 per change)"
has "disclosure mode marker in code-review template" "$TPL/code-review.md" "disclosure-consensus"

# --- opsx-review-convergence.decision-audit-landing ---
has "loop skill defines the decision-audit landing" "$LOOP_SKILL" "Decision-audit landing"
has "landing prohibits model shopping" "$LOOP_SKILL" "NEVER dispatch reviewer models"

# --- opsx-review-convergence.scope-widening-protocol ---
has "loop skill defines evidence-gated widening" "$LOOP_SKILL" "Scope widening (evidence-gated)"
has "review.md template explains widening evidence entries" "$TPL/review.md" "evidence:"

# --- opsx-review-convergence.finding-routing-and-follow-ups ---
has "loop skill routes non-required findings to follow-ups" "$LOOP_SKILL" "follow-ups.md"
has "follow-ups template records routing reason" "$TPL/follow-ups.md" "Routing reason"

# --- opsx-review-convergence.advisory-surface-audit ---
has "loop skill defines the advisory surface audit" "$LOOP_SKILL" "Advisory surface audit"

# --- opsx-review-convergence.reviewer-model-stability ---
has "loop skill pins the reviewer model set" "$LOOP_SKILL" "Reviewer-model stability"

# --- opsx-review-convergence.prose-surface-fidelity ---
has "loop skill carries the ledger-repair red flag" "$LOOP_SKILL" "provenance defect: repair the ledger before archive"
has "apply ref carries the ledger-repair red flag" "$APPLY_REF" "provenance defect — repair the ledger before archive"
has "code-review template findings heading is neutral" "$TPL/code-review.md" "^## Findings"
if grep -q "^## Convergent findings" "$TPL/code-review.md" 2>/dev/null; then nok "legacy Convergent findings heading reintroduced"; else ok "no convergence-implying findings heading"; fi

# --- opsx-loop-orchestration.review-dispatch-bound-by-convergence-discipline ---
has "loop skill evaluates stops before re-dispatch" "$LOOP_SKILL" "evaluate BEFORE dispatching"

# --- opsx-loop-orchestration.pre-apply-surface-audit-dispatch ---
has "surface audit dispatched before first implementation task" "$LOOP_SKILL" "advisory blind surface-enumeration audit before the"

# --- opsx-loop-orchestration.scope-widening-handled-in-the-loop ---
has "widening logged BEFORE committing the fix" "$LOOP_SKILL" "BEFORE committing the fix"

# --- opsx-post-impl-review.verdict-under-the-severity-floor ---
has "apply ref computes Verdict under the floor" "$APPLY_REF" "no open P0/P1"

# --- opsx-post-impl-review.round-ledger-sealed-in-code-review ---
has "apply ref seals the Round tracker ledger" "$APPLY_REF" "Round tracker"

# --- opsx-post-impl-review.disclosure-consensus-review-mode ---
has "apply ref review_mode vocabulary includes disclosure-consensus" "$APPLY_REF" "disclosure-consensus"

# --- opsx-post-impl-review.waiver-sealed-pass ---
has "apply ref defines waived_by_user re-seal" "$APPLY_REF" "waived_by_user"
has "code-review template documents waived_by_user" "$TPL/code-review.md" "waived_by_user"

# --- opsx-post-impl-review.adversarial-review-with-degradation ---
has "degraded-single-model still does not satisfy gating" "$APPLY_REF" "degraded-single-model"

echo "-----"
echo "opsx-review-convergence surfaces: $pass passed, $failc failed"
[ "$failc" -eq 0 ]
