#!/usr/bin/env bash
# Deterministic assertions that the review-convergence discipline is present
# in its prose surfaces (schema templates + canonical skills). Guards against
# silent regression of the discipline text during future template/skill edits.
#
# Cites acceptance criteria by canonical ID so the verify gate's forward
# AC<->test mapping (check 5) finds literal matches:
#   opsx-adversarial-review.baseline-bounded-verdict-contract
#   opsx-adversarial-review.severity-rubric-and-floor
#   opsx-adversarial-review.finding-routing-and-follow-ups
#   opsx-adversarial-review.orchestrator-round-ledger
#   opsx-adversarial-review.trajectory-stop-and-round-budget
#   opsx-adversarial-review.disclosure-round
#   opsx-adversarial-review.decision-audit-landing
#   opsx-adversarial-review.scope-widening-protocol
#   opsx-adversarial-review.advisory-surface-audit
#   opsx-adversarial-review.reviewer-model-stability
#   opsx-loop.review-dispatch-bound-by-convergence-discipline
#   opsx-loop.pre-apply-surface-audit-dispatch
#   opsx-loop.scope-widening-handled-in-the-loop
#   opsx-adversarial-review.verdict-under-the-severity-floor
#   opsx-adversarial-review.round-ledger-sealed-in-code-review
#   opsx-adversarial-review.disclosure-consensus-review-mode
#   opsx-adversarial-review.waiver-sealed-pass
#   opsx-adversarial-review.adversarial-review-with-degradation
#   opsx-workflow-schema.review-max-rounds-front-matter
#   opsx-workflow-schema.convergence-template-support
#   opsx-loop.terminal-landings-set-the-loop-hold
#   opsx-workflow-schema.loop-hold-front-matter-keys
# Intentional: no `set -e` — assertions drive explicit pass/fail counters and
# the final exit is `[ "$failc" -eq 0 ]`; -e would abort on the first failed
# grep instead of reporting every failed assertion.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TPL="$ROOT/dot_local/share/openspec/schemas/opsx-superpowers/templates"
LOOP_SKILL="$ROOT/dot_local/share/agent-harness/canonical/skills/openspec-loop/SKILL.md"
APPLY_REF="$ROOT/dot_local/share/agent-harness/canonical/skills/openspec-apply-change/references/opsx-superpowers-mode.md"
PROPOSE_REF="$ROOT/dot_local/share/agent-harness/canonical/skills/openspec-propose/references/opsx-superpowers-mode.md"
PROPOSE_SKILL="$ROOT/dot_local/share/agent-harness/canonical/skills/openspec-propose/SKILL.md"
EXPLORE_SKILL="$ROOT/dot_local/share/agent-harness/canonical/skills/openspec-explore/SKILL.md"
ARCHIVE_REF="$ROOT/dot_local/share/agent-harness/canonical/skills/openspec-archive-change/references/opsx-superpowers-mode.md"
ARCHIVE_SKILL="$ROOT/dot_local/share/agent-harness/canonical/skills/openspec-archive-change/SKILL.md"
README="$ROOT/dot_local/share/openspec/schemas/opsx-superpowers/README.md"
SCHEMA="$ROOT/dot_local/share/openspec/schemas/opsx-superpowers/schema.yaml"
TEMPLATE_REVIEW="$ROOT/dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md"

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

# --- opsx-adversarial-review.baseline-bounded-verdict-contract ---
has "code-review template embeds the verdict contract" "$TPL/code-review.md" "Verdict contract"
has "contract restricts FAIL to baseline violation or objective defect" "$TPL/code-review.md" "objective correctness/security defect"

# --- opsx-adversarial-review.severity-rubric-and-floor ---
has "code-review template carries the P0-P3 rubric" "$TPL/code-review.md" "P3  nit"
has "severity floor stated (pass iff no open P0/P1)" "$TPL/code-review.md" "no open P0/P1"

# --- opsx-adversarial-review.orchestrator-round-ledger ---
has "ledger consolidation = MAX across reviewers" "$TPL/code-review.md" "Consolidated counts = MAX"
has "IX pass accepts disclosure-consensus with >=2 models" "$TPL/code-review.md" "disclosure-consensus when it consolidated"
has "apply ref IX accepts disclosure-consensus with >=2 models" "$APPLY_REF" "disclosure-consensus\` when the disclosure round consolidated"
has "blind prompts never carry the ledger" "$TPL/code-review.md" "NEVER include this ledger"
has "loop skill maintains the round ledger" "$LOOP_SKILL" "Round ledger"

# --- opsx-adversarial-review.trajectory-stop-and-round-budget ---
has "loop skill has converged stop" "$LOOP_SKILL" "latest round P0+P1 = 0"
has "loop skill has treadmill stop" "$LOOP_SKILL" "flat-or-rising P0+P1 across the two most recent rounds"
has "loop skill has review_max_rounds budget stop" "$LOOP_SKILL" "review_max_rounds"

# --- opsx-adversarial-review.disclosure-round ---
has "loop skill defines the single disclosure round" "$LOOP_SKILL" "Disclosure round (max 1 per change)"
has "disclosure mode marker in code-review template" "$TPL/code-review.md" "disclosure-consensus"

# --- opsx-adversarial-review.decision-audit-landing ---
has "loop skill defines the decision-audit landing" "$LOOP_SKILL" "Decision-audit landing"
has "landing prohibits model shopping" "$LOOP_SKILL" "NEVER dispatch reviewer models"

# --- opsx-adversarial-review.scope-widening-protocol ---
has "loop skill defines evidence-gated widening" "$LOOP_SKILL" "Scope widening (evidence-gated)"
has "review.md template explains widening evidence entries" "$TPL/review.md" "evidence:"

# --- opsx-adversarial-review.finding-routing-and-follow-ups ---
has "loop skill routes non-required findings to follow-ups" "$LOOP_SKILL" "follow-ups.md"
has "follow-ups template records routing reason" "$TPL/follow-ups.md" "Routing reason"

# --- opsx-adversarial-review.advisory-surface-audit ---
has "loop skill defines the advisory surface audit" "$LOOP_SKILL" "Advisory surface audit"

# --- opsx-adversarial-review.reviewer-model-stability ---
has "loop skill pins the reviewer model set" "$LOOP_SKILL" "Reviewer-model stability"

# --- opsx-adversarial-review.prose-surface-fidelity ---
has "loop skill carries the ledger-repair red flag" "$LOOP_SKILL" "provenance defect: repair the ledger before archive"
has "apply ref carries the ledger-repair red flag" "$APPLY_REF" "provenance defect — repair the ledger before archive"
has "code-review template findings heading is neutral" "$TPL/code-review.md" "^## Findings"
if grep -q "^## Convergent findings" "$TPL/code-review.md" 2>/dev/null; then nok "legacy Convergent findings heading reintroduced"; else ok "no convergence-implying findings heading"; fi

# --- opsx-loop.review-dispatch-bound-by-convergence-discipline ---
has "loop skill evaluates stops before re-dispatch" "$LOOP_SKILL" "THEN evaluate IN ORDER"

# --- opsx-loop.pre-apply-surface-audit-dispatch ---
has "surface audit dispatched before first implementation task" "$LOOP_SKILL" "advisory blind surface-enumeration audit before the"

# --- opsx-loop.scope-widening-handled-in-the-loop ---
has "widening logged BEFORE committing the fix" "$LOOP_SKILL" "BEFORE committing the fix"

# --- opsx-adversarial-review.verdict-under-the-severity-floor ---
has "apply ref computes Verdict under the floor" "$APPLY_REF" "no open P0/P1"

# --- opsx-adversarial-review.round-ledger-sealed-in-code-review ---
has "apply ref seals the Round tracker ledger" "$APPLY_REF" "Round tracker"

# --- opsx-adversarial-review.disclosure-consensus-review-mode ---
has "apply ref review_mode vocabulary includes disclosure-consensus" "$APPLY_REF" "disclosure-consensus"

# --- opsx-adversarial-review.waiver-sealed-pass ---
has "apply ref defines waived_by_user re-seal" "$APPLY_REF" "waived_by_user"
has "code-review template documents waived_by_user" "$TPL/code-review.md" "waived_by_user"

# --- opsx-adversarial-review.adversarial-review-with-degradation ---
has "degraded-single-model still does not satisfy gating" "$APPLY_REF" "degraded-single-model"

# --- opsx-loop.terminal-landings-set-the-loop-hold ---
has "loop skill lands via loop_hold, not stall burn" "$LOOP_SKILL" "loop_hold: true"
has "loop skill pins the hold to the integration checkout" "$LOOP_SKILL" "INTEGRATION checkout"
has "loop skill forbids self-clearing the hold" "$LOOP_SKILL" "NEVER clear a loop_hold"
has "stall burn demoted to no-hold-support fallback" "$LOOP_SKILL" "loop_hold support, stop committing"

# --- opsx-workflow-schema.loop-hold-front-matter-keys ---
has "review template documents loop_hold" "$TPL/review.md" "loop_hold: true"
has "review template documents loop_hold_reason" "$TPL/review.md" "loop_hold_reason"
has "review template states the gate ignores hold state" "$TPL/review.md" "NOT by opsx gate"
has "review template states cleared-by-named-re-arm-only" "$TPL/review.md" "named"

# --- opsx-gate-enforcement.worktree-locator-published-to-the-integration-checkout ---
has "apply ref mandates locator publication to the integration branch" "$APPLY_REF" "COMMIT that edit ON THE INTEGRATION BRANCH"
has "apply ref frames the fallback as backstop, not substitute" "$APPLY_REF" "a backstop, not a substitute"

# =====================================================================
# simplify-and-parallelize-opsx-workflow: 3-tier + full_rigor surfaces
# (Phase 3/2 prose rules; grep-level regression pins per task 4.4)
# =====================================================================

# --- tier vocabulary present (XS|S|M + full_rigor) ---
has "review.md template Scale row uses the XS|S|M vocabulary" "$TPL/review.md" "skills author per Scale"
has "review.md template documents the full_rigor key" "$TPL/review.md" "full_rigor"
has "loop skill states the XS | S | M tier vocabulary" "$LOOP_SKILL" "XS | S | M"
has "apply ref reads Scale as XS | S | M" "$APPLY_REF" "<XS | S | M>"
has "apply ref reads the full_rigor front-matter key" "$APPLY_REF" "full_rigor"
has "propose ref mode picker uses XS / S / M" "$PROPOSE_REF" "XS / S / M"
has "propose skill drops Scale >= L for full_rigor" "$PROPOSE_SKILL" "full_rigor"
has "README maps former L/XL to M + full_rigor" "$README" "Migration note"
# guard against reintroduced 5-tier vocabulary in the live surfaces
if grep -q -- "Scale . L" "$PROPOSE_SKILL" 2>/dev/null; then nok "propose skill reintroduced a Scale>=L tier"; else ok "propose skill has no legacy L tier"; fi

# --- schema.yaml + templates fully migrated off the L/XL scale vocabulary ---
has "schema.yaml Scale enum is the 3-tier XS | S | M" "$SCHEMA" "XS | S | M  (default: S)"
if grep -qE '\| L \| XL|Scale . L|Scale >= L|L~80|Scale = XL|Scale = L' "$SCHEMA" 2>/dev/null; then nok "schema.yaml still carries a live L/XL scale enumeration"; else ok "schema.yaml has no live L/XL scale enumeration"; fi
has "schema.yaml keys adversarial-on-analyze on full_rigor" "$SCHEMA" "when full_rigor is set, invoke"
has "schema.yaml keys the loop budget defaults on the 3 tiers + full_rigor" "$SCHEMA" "XS~10 / S~20 / M~40 /"
has "design template keys ADR promotion on full_rigor" "$TPL/design.md" "mandatory at full_rigor"
has "analyze template Check 4 keyed on full_rigor" "$TPL/analyze.md" "promotion candidates (full_rigor)"
has "retrospective template keyed on full_rigor" "$TPL/retrospective.md" "Required when full_rigor is set"
if grep -qE 'Scale = XL|Scale = L|optional at L' "$TPL/retrospective.md" 2>/dev/null; then nok "retrospective template still keys on a Scale=L/XL label"; else ok "retrospective template dropped L/XL keying"; fi

# --- F3: review.md is never skipped; skipped artifacts get no placeholder ---
has "propose ref states review.md is NEVER skipped at any Scale" "$PROPOSE_REF" "review.md is NEVER skipped"
has "propose ref writes NO placeholder for skipped artifacts" "$PROPOSE_REF" "write NO placeholder"
# R7-F1: the schema.yaml review-artifact instruction and the propose Scale
# prompt must not tell agents to skip review.md at XS (ungateable change).
has "schema.yaml review instruction forbids skipping review.md at any Scale" "$SCHEMA" "review.md is NEVER skipped at ANY Scale"
if grep -qF "Scale = XS: skip (defaults assumed)" "$SCHEMA" 2>/dev/null; then nok "schema.yaml review instruction still says XS skip"; else ok "schema.yaml review instruction no longer says XS skip"; fi
has "propose Scale prompt includes review.md at XS" "$PROPOSE_REF" "review.md (switchboard) + proposal + tasks"
# R7-F2: template must not hard-code an advisory code_review_mode that survives
# a scale: M edit — the key ships commented so the fail-closed derivation governs.
if grep -qE "^code_review_mode: " "$TEMPLATE_REVIEW" 2>/dev/null; then nok "review.md template still hard-codes code_review_mode"; else ok "review.md template ships code_review_mode commented (derived default governs)"; fi
has "review.md template documents the code_review_mode derivation" "$TEMPLATE_REVIEW" "derived when absent: M"

# --- F4: integration-checkout commits are path-scoped (git commit -- <paths>) ---
has "apply ref pre-flight commit is path-scoped, -m before --" "$APPLY_REF" "git commit -m \"chore(opsx): pre-flight commit for apply of <name>\" -- openspec/changes"
has "archive ref ADR commit is path-scoped, -m before --" "$ARCHIVE_REF" "git commit -m \"docs(adr): ADR-NNNN <title>\" -- <repo>/adr"
has "archive ref gates ADR promotion on full_rigor" "$ARCHIVE_REF" "full_rigor only"
has "archive ref gates retrospective refusal on full_rigor" "$ARCHIVE_REF" "requires retrospective.md before archive"

# --- authoring-time budget defaults + worktree-mode derivation (template) ---
has "review.md template carries the tier budget defaults" "$TPL/review.md" "XS=10, S=20, M=40, full_rigor=80"
has "review.md template carries the worktree-mode derivation comment" "$TPL/review.md" "DERIVED by tier when ABSENT"

# --- plain-M combined doneness dispatch (loop skill + doneness template) ---
has "loop skill defines the plain-M combined doneness dispatch" "$LOOP_SKILL" "COMBINED dispatch"
has "loop skill designates the first review model as doneness judge" "$LOOP_SKILL" "designated reviewer is the FIRST"
has "loop skill keeps full_rigor independent doneness dispatch" "$LOOP_SKILL" "INDEPENDENT dispatch"
has "doneness template documents the combined dispatch" "$TPL/doneness.md" "COMBINED dispatch"
has "doneness template seals a separate blind-single-judge verdict" "$TPL/doneness.md" "blind-single-judge"

# --- A2 path-scoped commit rule (loop skill) ---
has "loop skill mandates path-scoped integration commits" "$LOOP_SKILL" "path-scoped to the change"
has "loop skill forbids bare git add -A in loop commits" "$LOOP_SKILL" "git commit -m \"<msg>\" -- openspec/changes"

# --- archive-check invocation + refusal + D8 cleanup (archive surfaces) ---
has "archive ref runs opsx archive-check pre-archive" "$ARCHIVE_REF" "opsx archive-check"
has "archive ref refuses archive on non-zero archive-check" "$ARCHIVE_REF" "exits NON-ZERO, REFUSE archive"
has "archive ref deletes now-empty spec dirs post-archive (D8)" "$ARCHIVE_REF" "type d -empty -delete"
has "archive ref re-validates specs before the archive commit" "$ARCHIVE_REF" "openspec validate --specs --strict"
has "archive skill branch names the archive-check refusal" "$ARCHIVE_SKILL" "opsx archive-check"

# --- clarify-in-proposal + deterministic analyze at plain M (propose ref) ---
has "propose ref folds clarify into the proposal at plain M" "$PROPOSE_REF" "clarify-in-proposal"
has "propose ref places open questions in the proposal" "$PROPOSE_REF" "## Open Questions"
has "propose ref keeps the 2-option self-resolution discipline" "$PROPOSE_REF" "2-option self-resolution"
has "propose ref runs analyze deterministic-only at plain M" "$PROPOSE_REF" "deterministic-only analyze"

# --- R4-A: explore skill recommends XS|S|M + full_rigor, NO live L/XL recommendation ---
has "explore skill recommends the XS | S | M Scale vocabulary" "$EXPLORE_SKILL" "RECOMMEND a Scale tier (\`XS | S | M\`)"
has "explore skill recommends full_rigor for the former L/XL heuristics" "$EXPLORE_SKILL" "full_rigor"
if grep -qE '\| S \| M \| L \| XL|new capability, migration, multi-week' "$EXPLORE_SKILL" 2>/dev/null; then nok "explore skill still live-recommends an L/XL Scale tier"; else ok "explore skill has no live L/XL Scale recommendation"; fi

# --- R4-B: review.md template ships NO explicit worktree_mode (key commented out) ---
if grep -qE '^worktree_mode:' "$TPL/review.md" 2>/dev/null; then nok "review.md template ships an explicit worktree_mode value (defeats D6 derivation)"; else ok "review.md template ships no explicit worktree_mode value"; fi
has "review.md template comments out the worktree_mode key with the derivation note" "$TPL/review.md" "# worktree_mode: (derived when absent"

# --- R4-C: schema.yaml doneness dispatch is tier-conditioned (plain-M rides code-review, full_rigor independent) ---
has "schema.yaml plain-M doneness rides the code-review dispatch via the designated reviewer" "$SCHEMA" "DESIGNATED reviewer (the FIRST model"
has "schema.yaml plain-M doneness sealed as blind-single-judge" "$SCHEMA" "review_mode: blind-single-judge"
has "schema.yaml keeps the full_rigor INDEPENDENTLY dispatched blind doneness judge" "$SCHEMA" "INDEPENDENTLY dispatched blind"

# --- R4-D2: README required-artifact table includes review.md at EVERY tier ---
has "README states review.md is required at every tier" "$README" "review.md is required at EVERY tier"
has "README plain-M row marks design.md as decision-gated (not required)" "$README" "design.md is NOT required at plain M"

# --- models template without the project layer ---
has "models template retires the project layer" "$TPL/opsx-models.yaml" "project model layer"
has "models template resolution order omits the project file" "$TPL/opsx-models.yaml" "front-matter > user file > built-in default"
if grep -q -- "project scope" "$TPL/opsx-models.yaml" 2>/dev/null; then nok "models template still presents a project-scope location"; else ok "models template drops the project-scope location"; fi

# --- opsx-workflow-schema.review-budget-mode-front-matter ---
SCHEMA_DIR="$ROOT/dot_local/share/openspec/schemas/opsx-superpowers"
has "review.md template documents review_budget_mode" "$TPL/review.md" "review_budget_mode: quiet-round | land-on-stop"
has "review.md template states quiet-round is the absent default" "$TPL/review.md" "ABSENT ⇒ quiet-round"
has "review.md template states unknown values fail stricter" "$TPL/review.md" "stricter human-in-the-loop"
has "review.md template keeps the never-seal invariant beside the key" "$TPL/review.md" "NEVER"
has "README mode table carries review_budget_mode" "$SCHEMA_DIR/README.md" "review_budget_mode"
has "schema.yaml documents review_budget_mode" "$SCHEMA_DIR/schema.yaml" "review_budget_mode (optional front-matter key"

# --- opsx-workflow-schema.template-mode-table-mirrors-derived-defaults ---
has "Code Review Mode row presents derived value" "$TPL/review.md" "| Code Review Mode | derived (absent) |"
if grep -q '^| Code Review Mode | advisory |' "$TPL/review.md" 2>/dev/null; then
  nok "Code Review Mode row no longer hard-codes literal advisory"
else ok "Code Review Mode row no longer hard-codes literal advisory"; fi

# --- opsx-workflow-schema.migration-sweep-declaration ---
has "README documents sweep.txt declaration" "$SCHEMA_DIR/README.md" "sweep.txt"
has "README states the swept-surface exclusions" "$SCHEMA_DIR/README.md" "openspec/\*\*"
has "schema.yaml documents sweep.txt (non-artifact rationale)" "$SCHEMA_DIR/schema.yaml" "sweep.txt (optional, change-dir)"
has "schema.yaml states empty declaration is clean" "$SCHEMA_DIR/schema.yaml" "zero effective patterns = clean pass"

# --- opsx-skill-integration.openspec-loop-orchestrator-skill-exists (Q1/Q2/Q3 prose) ---
has "loop skill: quiet-round ordered table present" "$LOOP_SKILL" "| a | quiet round |"
has "loop skill: converging row continues without ruling" "$LOOP_SKILL" "NO human ruling"
has "loop skill: thrash guard row present" "$LOOP_SKILL" "| c | thrash guard |"
has "loop skill: hard cap regardless of trajectory" "$LOOP_SKILL" "regardless of trajectory"
has "loop skill: fix-before-evaluate ordering stated" "$LOOP_SKILL" "FIRST attempt and land the fixes"
has "loop skill: post-apply bookkeeping-off-branch invariant" "$LOOP_SKILL" "NEVER committed on the"
has "loop skill: analyze fix-surface progress signal" "$LOOP_SKILL" "AUTHORED fix"
has "loop skill: land-on-stop opt-in documented" "$LOOP_SKILL" "review_budget_mode: land-on-stop"
has "loop skill: continue-not-seal invariant" "$LOOP_SKILL" "only automates CONTINUE, never SEAL"
has "loop skill: sweep-before-round-1 directive" "$LOOP_SKILL" "resolve ALL hits BEFORE"
has "loop skill: sweep command named" "$LOOP_SKILL" "opsx sweep <change>"
has "loop skill: verdicts are filled templates" "$LOOP_SKILL" "FILLING the schema's shipped"
has "loop skill: template paths named" "$LOOP_SKILL" "templates/code-review.md"
if grep -q 'authors the verdict artifact (body, Verdict' "$LOOP_SKILL" 2>/dev/null; then
  nok "loop skill: free-write verdict instruction removed"
else ok "loop skill: free-write verdict instruction removed"; fi

# --- CR R1: sibling prose homes track the quiet-round default (opsx-adversarial-review.trajectory-stop-and-round-budget) ---
has "code-review template ledger comment states quiet-round order" "$TPL/code-review.md" "a quiet round"
has "code-review template converging row continues without ruling" "$TPL/code-review.md" "NO human ruling"
has "code-review template names land-on-stop opt-in" "$TPL/code-review.md" "review_budget_mode: land-on-stop"
if grep -q 'treadmill  — P0+P1 flat or rising' "$TPL/code-review.md" 2>/dev/null; then
  nok "code-review template treadmill-as-default removed"
else ok "code-review template treadmill-as-default removed"; fi
has "apply ref states fix-first quiet-round evaluation" "$APPLY_REF" "land the fixes FIRST, then evaluate IN ORDER"
has "apply ref names the thrash guard" "$APPLY_REF" "thrash guard"
has "apply ref names land-on-stop opt-in" "$APPLY_REF" "review_budget_mode: land-on-stop"
if grep -q 'treadmill (P0+P1 flat/rising' "$APPLY_REF" 2>/dev/null; then
  nok "apply ref treadmill-as-default removed"
else ok "apply ref treadmill-as-default removed"; fi

# --- opsx-adversarial-review.m-tier-review-stack-thinning (rigor uniform across tiers) ---
has "loop skill keeps 2-model code review gating at every tier" "$LOOP_SKILL" "gating-required at every tier"

# --- Q4 rider: stray .tmp removed and stays removed ---
if [ -e "$ROOT/tests/opsx-review-convergence/test_review_convergence_surfaces.sh.tmp" ]; then
  nok "stray surfaces .tmp stays deleted"
else ok "stray surfaces .tmp stays deleted"; fi

# --- opsx-workflow-schema.integration-branch-locator-default-detected ---
has "review.md template ships the <detected-at-capture> locator sentinel, not a branch literal" "$TEMPLATE_REVIEW" "\*\*Integration Branch:\*\* <detected-at-capture>"
has "review.md template documents capture-time detection via the resolver" "$TEMPLATE_REVIEW" "integration-branch-locator-default-detected"
if grep -q '^\*\*Integration Branch:\*\* main$' "$TEMPLATE_REVIEW" 2>/dev/null; then
  nok "review.md template no longer hardcodes Integration Branch: main"
else ok "review.md template no longer hardcodes Integration Branch: main"; fi

# --- opsx-gate-enforcement.land-base-currency (resolved-branch prose) ---
has "archive ref describes base-currency against the RESOLVED integration branch" "$ARCHIVE_REF" "integration-branch-resolution"
if grep -q 'merge-base opsx/<name> main' "$ARCHIVE_REF" 2>/dev/null; then
  nok "archive ref dropped the literal-main merge-base assertion"
else ok "archive ref dropped the literal-main merge-base assertion"; fi

# --- opsx-gate-enforcement.project-artifact-preflight (propose ref mirrors gate) ---
has "propose ref option B warns the gate fails closed at EVERY Scale" "$PROPOSE_REF" "project-artifact preflight"
if grep -q 'only safe for Scale=XS' "$PROPOSE_REF" 2>/dev/null; then
  nok "propose ref dropped the stale XS-safe skip claim"
else ok "propose ref dropped the stale XS-safe skip claim"; fi

# --- opsx-adversarial-review.reviewer-tree-identity-attestation +
#     opsx-adversarial-review.read-only-reviewer-dispatch +
#     opsx-workflow-schema.convergence-template-support (Attested HEAD surfaces) ---
has "code-review template carries the Attested HEAD field" "$TPL/code-review.md" '^\*\*Attested HEAD:\*\*'
has "code-review template documents the 40-hex fail-closed contract" "$TPL/code-review.md" "full 40-hex"
has "code-review template dispatch contract carries the attestation preamble" "$TPL/code-review.md" "git rev-parse --show-toplevel"
has "code-review template names INVALID (not fail) semantics" "$TPL/code-review.md" "INVALID"
has "doneness template carries the Attested HEAD field" "$TPL/doneness.md" '^\*\*Attested HEAD:\*\*'
has "doneness template scopes attestation to the full_rigor judge" "$TPL/doneness.md" "full_rigor"
has "loop skill requires the attestation preamble" "$LOOP_SKILL" "Attested Path"
has "loop skill pins dispatch cwd to the reviewed tree" "$LOOP_SKILL" "pin the"
has "loop skill defines INVALID as excluded from gating/ledger/budget" "$LOOP_SKILL" "INVALID — not fail"
has "loop skill bounds all-invalid re-dispatch at two attempts" "$LOOP_SKILL" "dispatch-integrity"
has "loop skill defines the read-only round window snapshot" "$LOOP_SKILL" "porcelain=v1"
has "loop skill forbids blanket git clean on restore" "$LOOP_SKILL" "NEVER blanket"
has "apply ref requires the attestation preamble" "$APPLY_REF" "Attested Path"
has "apply ref defines INVALID verdict semantics" "$APPLY_REF" "INVALID, not fail"
has "apply ref defines the read-only round window" "$APPLY_REF" "read-only-reviewer-dispatch"
has "apply ref keeps restore surgical" "$APPLY_REF" "never blanket"

echo "-----"
echo "opsx-review-convergence surfaces: $pass passed, $failc failed"
[ "$failc" -eq 0 ]
