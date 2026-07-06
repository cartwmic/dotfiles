#!/usr/bin/env bash
# Hermetic tests for opsx gate.
# Cites acceptance criteria by canonical ID so the verify gate's forward
# AC<->test mapping (check 5) finds literal matches:
#   opsx-gate-enforcement.gate-exit-code-contract
#   opsx-gate-enforcement.required-artifact-by-scale
#   opsx-gate-enforcement.cheap-before-expensive-ordering
#   opsx-gate-enforcement.manifest-validation-execution
#   opsx-gate-enforcement.mode-aware-verdict-reading
#   opsx-gate-enforcement.verdict-freshness-and-provenance
#   opsx-gate-enforcement.worktree-locator-published-to-the-integration-checkout
#   opsx-gate-enforcement.worktree-mandatory-gate-enforcement
#   opsx-gate-enforcement.design-fidelity-verdict-enforcement
#   opsx-gate-enforcement.doneness-verdict-enforcement
#   opsx-adversarial-review.sealed-doneness-verdict-artifact
#   opsx-adversarial-review.freshness-bound-verdict
#   opsx-adversarial-review.anti-self-forge-provenance
#   opsx-adversarial-review.scale-gated-with-waiver
#
# WORKTREE-ALWAYS + COMMITTED-READ MODEL (design D7 + D8): the gate reads every
# orchestration input — review.md front-matter switchboard fields, the Diff Base /
# Worktree Path locators, and design-fidelity.md — from the COMMITTED integration
# checkout (main-worktree HEAD), never the live working tree; and a change PAST
# Diff Base capture MUST resolve a real opsx/<change> worktree. So fixtures here
# COMMIT their review.md (via run()'s auto-commit or an explicit seal) and, for any
# gating/freshness/doneness scenario carrying a Diff Base, create a genuine
# opsx/<change> worktree whose working tree holds the implementation-coupled verdict
# artifacts (tasks/code-review/doneness). The abolished `worktree_mode` key is
# rejected outright.
set -uo pipefail

OPSX="$(cd "$(dirname "$0")/../.." && pwd)/dot_local/bin/executable_opsx"
pass=0; failc=0
ok()   { printf 'ok   - %s\n' "$1"; pass=$((pass+1)); }
nok()  { printf 'NOT OK - %s\n' "$1"; failc=$((failc+1)); }
check(){ # check <desc> <expected-rc> <actual-rc>
  if [ "$2" = "$3" ]; then ok "$1"; else nok "$1 (want rc=$2 got rc=$3)"; fi; }

TMP="$(mktemp -d)"
WTBASE="$(mktemp -d)"                       # linked worktrees live OUTSIDE $TMP so
                                            # `git -C $TMP add -A` never scans them
trap 'git -C "$TMP" worktree prune 2>/dev/null; rm -rf "$TMP" "$WTBASE"' EXIT
FAKEBIN="$TMP/fakebin"; mkdir -p "$FAKEBIN"
# Deterministic stub: openspec validate always succeeds in fixtures.
cat >"$FAKEBIN/openspec" <<'EOF'
#!/usr/bin/env bash
# Record invocations so tests can assert WHEN the gate runs structural
# validation (R6-F1: skipped iff specs/ absent), then succeed.
[ -n "$OPSX_TEST_OPENSPEC_LOG" ] && printf '%s\n' "$*" >>"$OPSX_TEST_OPENSPEC_LOG"
exit 0
EOF
chmod +x "$FAKEBIN/openspec"
export PATH="$FAKEBIN:$PATH"

git -C "$TMP" init -q
git -C "$TMP" config user.email t@t; git -C "$TMP" config user.name t
printf seed > "$TMP/seed"; git -C "$TMP" add seed; git -C "$TMP" commit -qm seed
export OPSX_ROOT="$TMP"
# Project-artifact preflight fixtures (opsx-gate-enforcement.project-artifact-preflight):
# every gate run requires non-empty constitution.md + domain.md at every Scale.
mkdir -p "$TMP/openspec"
printf '# Constitution\n' >"$TMP/openspec/constitution.md"
printf '# Domain\n' >"$TMP/openspec/domain.md"

# ---------------------------------------------------------------------------
# HELPERS (worktree-always / committed-read)
# ---------------------------------------------------------------------------
dgst() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'; else sha256sum "$1" | awk '{print $1}'; fi; }
ihash() { dgst "$1"; }
wtp() { echo "$WTBASE/wt-$1"; }

# Commit the whole integration working tree (orchestration must be committed for
# the gate's committed-read to see it). No-op when nothing changed.
commit_all() { git -C "$TMP" add -A >/dev/null 2>&1; git -C "$TMP" commit -qm "${1:-auto}" >/dev/null 2>&1 || true; }

# run <change> [gate args...] : commit integration, then run the gate. stderr -> $TMP/err.
run() { commit_all; "$OPSX" gate "$@" 2>"$TMP/err"; }

# make_wt <change> : commit the fixture, create a real opsx/<change> worktree at that
# HEAD. Exports WT (worktree path) and WTHEAD (its HEAD sha). Implementation-coupled
# verdict artifacts are then written into $WT (uncommitted) so IMPL_HEAD == WTHEAD.
make_wt() {
  commit_all "seal $1"
  WT="$(wtp "$1")"; rm -rf "$WT"
  git -C "$TMP" worktree add -q -b "opsx/$1" "$WT" >/dev/null 2>&1
  WTHEAD="$(git -C "$WT" rev-parse HEAD)"
}

# df_seal <change> : write a DELIVERED design-fidelity.md into the integration change
# dir with correct committed-content digests (intent.md, design.md, each spec.md).
df_seal() {
  local d="$TMP/openspec/changes/$1" f rel
  {
    echo '# Design Fidelity'; echo
    echo '**Fidelity:** delivered'; echo
    echo '**Judge Provenance:** judge-x; review_mode: blind-single-judge'
    echo "**Attested HEAD:** $(git -C "$TMP" rev-parse HEAD)"
    echo "**Digest sha256 (intent.md):** $(dgst "$d/intent.md")"
    echo "**Digest sha256 (design.md):** $(dgst "$d/design.md")"
    for f in "$d"/specs/*/spec.md; do [ -f "$f" ] || continue; rel="${f#"$d"/}"; echo "**Digest sha256 ($rel):** $(dgst "$f")"; done
  } >"$d/design-fidelity.md"
}

mkchange() { # mkchange <name> ; creates a complete Scale-S change by default
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d/specs/cap"
  cat >"$d/review.md" <<'EOF'
---
scale: S
verification_mode: retained-recommended
code_review_mode: advisory
loop_max_iterations: 20
validation_source_mode: required
spec_level: spec-anchored
---
# Review
EOF
  echo "# proposal" >"$d/proposal.md"
  echo "# spec" >"$d/specs/cap/spec.md"
  echo "# plan" >"$d/plan.md"
  printf '# tasks\n- [x] 1.1 done\n' >"$d/tasks.md"
}

# --- opsx-gate-enforcement.gate-exit-code-contract ---
mkchange green-s
run green-s; check "complete Scale-S change passes (gate-exit-code-contract)" 0 $?
run nonexistent-change; check "unknown change fails (gate-exit-code-contract)" 1 $?

# --- opsx-gate-enforcement.required-artifact-by-scale ---
# D3: at S the required set is review+proposal+tasks (specs/plan are NOT required
# below M). Removing a genuinely-required S artifact (tasks.md) must fail.
mkchange missing-tasks; rm "$TMP/openspec/changes/missing-tasks/tasks.md"
run missing-tasks; rc=$?
check "missing Scale-S required artifact fails (required-artifact-by-scale)" 1 $rc
grep -q 'GATE-FAIL artifact-tasks' "$TMP/err" && ok "reports artifact-tasks" || nok "reports artifact-tasks"

# D3 matrix (reviewer probes): XS requires review.md ONLY; S requires
# review+proposal+tasks and must NOT demand specs/ or plan.
mkXSonly() { # XS change carrying ONLY review.md
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d"
  cat >"$d/review.md" <<'EOF'
---
scale: XS
verification_mode: retained-recommended
code_review_mode: advisory
loop_max_iterations: 10
validation_source_mode: required
spec_level: spec-anchored
---
# Review
EOF
}
mkXSonly xs-only
run xs-only; check "XS with only review.md passes artifact checks (required-artifact-by-scale)" 0 $?
grep -q 'GATE-FAIL artifact-' "$TMP/err" && nok "XS demanded an artifact beyond review.md" || ok "XS demands no artifact beyond review.md"

mkSminimal() { # S change carrying review + proposal + tasks ONLY (no specs/, no plan)
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d"
  cat >"$d/review.md" <<'EOF'
---
scale: S
verification_mode: retained-recommended
code_review_mode: advisory
loop_max_iterations: 20
validation_source_mode: required
spec_level: spec-anchored
---
# Review
EOF
  echo "# proposal" >"$d/proposal.md"
  printf '# tasks\n- [x] 1.1 done\n' >"$d/tasks.md"
}
mkSminimal s-min
run s-min; check "S with review+proposal+tasks passes, no specs/plan demanded (required-artifact-by-scale)" 0 $?
grep -qE 'GATE-FAIL artifact-(specs|plan)' "$TMP/err" && nok "S wrongly demanded specs/ or plan" || ok "S demands no specs/ or plan"

mkchange noscale
# break the scale value
sed -i.bak 's/^scale: S/scale: /' "$TMP/openspec/changes/noscale/review.md"
run noscale; check "absent Scale fails (required-artifact-by-scale)" 1 $?
grep -q 'GATE-FAIL scale' "$TMP/err" && ok "reports scale fail" || nok "reports scale fail"

# --- opsx-gate-enforcement.worktree-mandatory-gate-enforcement ---
# The abolished worktree_mode KEY (any value, empty included) is a failed check
# naming the delete-the-key remedy. A YAML COMMENT merely mentioning it does NOT
# trip the check. A change PAST Diff Base capture with no valid opsx/<change>
# worktree fails loudly (key-less migration shape).
mkchange wtmode-key
sed -i.bak 's/^scale: S/scale: S\nworktree_mode: same-tree/' "$TMP/openspec/changes/wtmode-key/review.md"
run wtmode-key; rc=$?
check "worktree_mode key (any value) rejected (worktree-mandatory-gate-enforcement)" 1 $rc
grep -q 'GATE-FAIL worktree-mode' "$TMP/err" && ok "reports worktree-mode key rejection" || nok "reports worktree-mode key rejection"

mkchange wtmode-empty
sed -i.bak 's/^scale: S/scale: S\nworktree_mode:/' "$TMP/openspec/changes/wtmode-empty/review.md"
run wtmode-empty; rc=$?
check "empty-valued worktree_mode key still rejected (worktree-mandatory-gate-enforcement)" 1 $rc
grep -q 'GATE-FAIL worktree-mode' "$TMP/err" && ok "empty worktree_mode value still trips key rejection" || nok "empty worktree_mode value still trips key rejection"

mkchange wtmode-comment
sed -i.bak 's/^scale: S/scale: S\n# worktree_mode: same-tree (historical note)/' "$TMP/openspec/changes/wtmode-comment/review.md"
run wtmode-comment; rc=$?
check "front-matter COMMENT mentioning worktree_mode passes (worktree-mandatory-gate-enforcement)" 0 $rc
grep -q 'GATE-FAIL worktree-mode' "$TMP/err" && nok "comment-only worktree_mode wrongly rejected" || ok "comment-only worktree_mode not rejected"

# key-less migration shape: Diff Base captured, empty Worktree Path, no branch => LOUD worktree fail.
mkchange wt-required
BASE_WR="$(git -C "$TMP" rev-parse HEAD)"
printf '\n**Diff Base SHA:** %s\n**Worktree Path:**\n' "$BASE_WR" >>"$TMP/openspec/changes/wt-required/review.md"
run wt-required; check "past-capture change without a worktree fails (worktree-mandatory-gate-enforcement)" 1 $?
grep -q 'GATE-FAIL worktree ' "$TMP/err" && ok "no-worktree past capture is a hard fail" || nok "no-worktree past capture is a hard fail"

# --- opsx-gate-enforcement.cheap-before-expensive-ordering ---
mkchange cheapfirst; rm "$TMP/openspec/changes/cheapfirst/proposal.md"
cat >"$TMP/openspec/opsx-gates.yaml" <<'EOF'
gates:
  - id: boom
    run: 'exit 7'
    required: true
EOF
run cheapfirst; rc=$?
check "cheap failure short-circuits (cheap-before-expensive-ordering)" 1 $rc
grep -q 'validations skipped' "$TMP/err" && ok "validations skipped on cheap fail" || nok "validations skipped on cheap fail"
grep -q 'GATE-FAIL validation-boom' "$TMP/err" && nok "should NOT run boom" || ok "expensive gate not run"
rm -f "$TMP/openspec/opsx-gates.yaml"

# --- opsx-gate-enforcement.manifest-validation-execution ---
mkchange manifest-fail
cat >"$TMP/openspec/opsx-gates.yaml" <<'EOF'
gates:
  - id: req
    run: 'exit 3'
    required: true
EOF
run manifest-fail; check "required manifest non-zero fails (manifest-validation-execution)" 1 $?
grep -q 'GATE-FAIL validation-req' "$TMP/err" && ok "reports validation-req" || nok "reports validation-req"

cat >"$TMP/openspec/opsx-gates.yaml" <<'EOF'
gates:
  - id: adv
    run: 'exit 3'
    required: false
  - id: okreq
    run: 'true'
    required: true
EOF
mkchange manifest-warn
run manifest-warn; rc=$?
check "advisory manifest non-zero only warns (manifest-validation-execution)" 0 $rc
grep -q 'GATE-WARN validation-adv' "$TMP/err" && ok "advisory warns not fails" || nok "advisory warns not fails"
rm -f "$TMP/openspec/opsx-gates.yaml"

# --- opsx-gate-enforcement.mode-aware-verdict-reading ---
mkchange cr-gating
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' \
  "$TMP/openspec/changes/cr-gating/review.md"
run cr-gating; check "gating-required + absent code-review fails (mode-aware-verdict-reading)" 1 $?
grep -q 'GATE-FAIL code-review' "$TMP/err" && ok "reports code-review fail" || nok "reports code-review fail"

mkchange cr-advisory   # advisory: absent code-review must NOT fail
run cr-advisory; check "advisory code-review absent does not block (mode-aware-verdict-reading)" 0 $?

# --- opsx-gate-enforcement.verdict-freshness-and-provenance ---
# stale reviewed range under a real worktree (Diff Base captured => worktree resolved).
mkchange fresh
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' \
  "$TMP/openspec/changes/fresh/review.md"
BASE_F="$(git -C "$TMP" rev-parse HEAD)"
printf '\n**Diff Base SHA:** %s\n**Worktree Path:**\n' "$BASE_F" >>"$TMP/openspec/changes/fresh/review.md"
make_wt fresh
# stale: recorded range head is a bogus/non-ancestor sha
cat >"$WT/openspec/changes/fresh/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $BASE_F
**Reviewed Range:** $BASE_F..deadbeef
**Attested HEAD:** $BASE_F
EOF
run fresh --worktree "$WT"; check "stale reviewed range fails (verdict-freshness-and-provenance)" 1 $?
grep -q 'GATE-FAIL code-review-stale' "$TMP/err" && ok "reports stale verdict" || nok "reports stale verdict"

# --- P0-1: a template HTML comment must NOT satisfy verdict/provenance ---
mkchange tmpl-comment
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' \
  "$TMP/openspec/changes/tmpl-comment/review.md"
cat >"$TMP/openspec/changes/tmpl-comment/code-review.md" <<'EOF'
# Code Review
<!--
  - Verdict             pass | fail
  - reviewer-provenance adapter-stamped reviewer identity
-->
**Verdict:** fail
EOF
run tmpl-comment; check "template comment does not satisfy verdict, fail review fails (mode-aware-verdict-reading)" 1 $?
grep -q 'GATE-FAIL code-review' "$TMP/err" && ok "comment-only fail review is rejected" || nok "comment-only fail review is rejected"

# --- verdict-freshness-and-provenance: correct bold-field review reaches PASS ---
mkchange cr-pass
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' \
  "$TMP/openspec/changes/cr-pass/review.md"
BASE_CP="$(git -C "$TMP" rev-parse HEAD)"
printf '\n**Diff Base SHA:** %s\n**Worktree Path:**\n' "$BASE_CP" >>"$TMP/openspec/changes/cr-pass/review.md"
make_wt cr-pass
cat >"$WT/openspec/changes/cr-pass/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $BASE_CP
**Reviewed Range:** $BASE_CP..$WTHEAD
**Attested HEAD:** $WTHEAD
EOF
run cr-pass --worktree "$WT"; check "correct bold-field passing review reaches GATE-PASS (verdict-freshness-and-provenance)" 0 $?

# --- verdict-freshness-and-provenance: missing Reviewed Range is a failure, not a pass ---
mkchange cr-norange
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' \
  "$TMP/openspec/changes/cr-norange/review.md"
BASE_NR="$(git -C "$TMP" rev-parse HEAD)"
printf '\n**Diff Base SHA:** %s\n**Worktree Path:**\n' "$BASE_NR" >>"$TMP/openspec/changes/cr-norange/review.md"
make_wt cr-norange
cat >"$WT/openspec/changes/cr-norange/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $BASE_NR
**Attested HEAD:** $WTHEAD
EOF
run cr-norange --worktree "$WT"; check "missing Reviewed Range fails, not passes (verdict-freshness-and-provenance)" 1 $?

# --- convention fallback: empty locator + real opsx/<change> worktree resolves, no split-brain
# (opsx-gate-enforcement.worktree-locator-published-to-the-integration-checkout)
# The convention path is dirname(main)/basename(main)--opsx-<change>; a Diff Base
# capture forces worktree resolution, so the convention fallback is what makes the
# change gateable without --worktree.
mkchange wt-fallback
BASE_WF="$(git -C "$TMP" rev-parse HEAD)"
printf '\n**Diff Base SHA:** %s\n**Worktree Path:**\n' "$BASE_WF" >>"$TMP/openspec/changes/wt-fallback/review.md"
commit_all "wt-fallback change"
RROOT="$(git -C "$TMP" rev-parse --show-toplevel)"
CONVWT="$(dirname "$RROOT")/$(basename "$RROOT")--opsx-wt-fallback"
rm -rf "$CONVWT"
git -C "$TMP" worktree add "$CONVWT" -b opsx/wt-fallback >/dev/null 2>&1
run wt-fallback; check "empty locator + convention-path opsx/<change> worktree resolves via fallback (verdict-freshness-and-provenance)" 0 $?
grep -q 'GATE-FAIL worktree ' "$TMP/err" && nok "fallback avoided the locate hard-fail" || ok "fallback avoided the locate hard-fail"
# Gate-view equality: the SAME command from INSIDE the convention worktree must
# agree (convention derivation is normalized to the repo's main worktree root)
( cd "$CONVWT" && OPSX_ROOT="$CONVWT" "$OPSX" gate wt-fallback ) >/dev/null 2>"$TMP/err"; rc=$?
check "gate from inside the convention worktree agrees with the integration view" 0 $rc
# explicit --worktree that fails validation stays loud — never silently re-probed
( cd "$TMP" && "$OPSX" gate wt-fallback --worktree "$TMP/nonexistent" ) >/dev/null 2>"$TMP/err"; rc=$?
[ $rc -ne 0 ] && grep -q 'GATE-FAIL worktree ' "$TMP/err" \
  && ok "explicit invalid --worktree fails loud, no silent fallback" || nok "explicit invalid --worktree fails loud (rc=$rc)"
# a NON-convention (custom-path) worktree is out of the fallback's reach BY DESIGN
git -C "$TMP" worktree remove --force "$CONVWT" >/dev/null 2>&1
git -C "$TMP" worktree add "$WTBASE/wtfb-custom" opsx/wt-fallback >/dev/null 2>&1
run wt-fallback; check "custom-path worktree NOT resolved by fallback (locator publication covers it)" 1 $?
git -C "$TMP" worktree remove --force "$WTBASE/wtfb-custom" >/dev/null 2>&1; git -C "$TMP" branch -D opsx/wt-fallback >/dev/null 2>&1

# --- freshness tolerates verdict-only sealing commits, rejects code drift ---
mkchange cr-seal
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' \
  "$TMP/openspec/changes/cr-seal/review.md"
BASE_CS="$(git -C "$TMP" rev-parse HEAD)"
printf '\n**Diff Base SHA:** %s\n**Worktree Path:**\n' "$BASE_CS" >>"$TMP/openspec/changes/cr-seal/review.md"
make_wt cr-seal
cat >"$WT/openspec/changes/cr-seal/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $BASE_CS
**Reviewed Range:** $BASE_CS..$WTHEAD
**Attested HEAD:** $WTHEAD
EOF
# seal the verdict as a verdict-only trailing commit in the worktree
git -C "$WT" add openspec/changes/cr-seal/code-review.md
git -C "$WT" commit -qm "seal verdict (verdict-only commit)"
run cr-seal --worktree "$WT"; check "freshness tolerates verdict-only sealing commit (verdict-freshness-and-provenance)" 0 $?
# a code change after review (non-verdict trailing commit) => stale
printf x >"$WT/codefile"; git -C "$WT" add codefile; git -C "$WT" commit -qm "code change after review"
run cr-seal --worktree "$WT"; check "freshness rejects non-verdict change after review (verdict-freshness-and-provenance)" 1 $?

# ============================================================================
# opsx-gate-enforcement.verdict-freshness-and-provenance — Attested HEAD binding
# ============================================================================
mkatt() { # <name> ; builds a gating Scale-S fixture + worktree + base code-review
          # WITHOUT an Attested HEAD line. Caller appends the Attested line using $WTHEAD.
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d/specs/cap"
  cat >"$d/review.md" <<'EOF'
---
scale: S
verification_mode: retained-recommended
code_review_mode: gating-required
loop_max_iterations: 20
validation_source_mode: required
spec_level: spec-anchored
---
# Review
EOF
  echo "# proposal" >"$d/proposal.md"; echo "# spec" >"$d/specs/cap/spec.md"
  printf '# tasks\n- [x] 1.1 done\n' >"$d/tasks.md"
  MATT_BASE="$(git -C "$TMP" rev-parse HEAD)"
  printf '\n**Diff Base SHA:** %s\n**Worktree Path:**\n' "$MATT_BASE" >>"$d/review.md"
  make_wt "$1"
  cat >"$WT/openspec/changes/$1/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $MATT_BASE
**Reviewed Range:** $MATT_BASE..$WTHEAD
EOF
  ATTCR="$WT/openspec/changes/$1/code-review.md"
}

# absent Attested HEAD under gating-required => FAIL (fail-closed)
mkatt att-absent
run att-absent --worktree "$WT"; check "absent Attested HEAD fails under gating-required (verdict-freshness-and-provenance)" 1 $?
grep -q 'Attested HEAD' "$TMP/err" && ok "names the Attested HEAD remedy" || nok "names the Attested HEAD remedy"

# matching full 40-hex => PASS
mkatt att-match; printf '**Attested HEAD:** %s\n' "$WTHEAD" >>"$ATTCR"
run att-match --worktree "$WT"; check "matching 40-hex Attested HEAD passes (verdict-freshness-and-provenance)" 0 $?

# symbolic ref is UNPARSEABLE — never resolved in the located worktree
mkatt att-symbolic; printf '**Attested HEAD:** HEAD\n' >>"$ATTCR"
run att-symbolic --worktree "$WT"; check "symbolic Attested HEAD fails closed, never resolved (verdict-freshness-and-provenance)" 1 $?
grep -q 'Attested HEAD' "$TMP/err" && ok "symbolic form reported as attestation failure" || nok "symbolic form reported as attestation failure"

# short SHA is UNPARSEABLE
mkatt att-short; printf '**Attested HEAD:** %.12s\n' "$WTHEAD" >>"$ATTCR"
run att-short --worktree "$WT"; check "short-SHA Attested HEAD fails closed (verdict-freshness-and-provenance)" 1 $?

# mismatched full 40-hex (valid form, wrong tree) => FAIL
mkatt att-mismatch; printf '**Attested HEAD:** %040d\n' 1 >>"$ATTCR"
run att-mismatch --worktree "$WT"; check "mismatched 40-hex Attested HEAD fails — wrong-tree verdict (verdict-freshness-and-provenance)" 1 $?
grep -q 'wrong-tree' "$TMP/err" && ok "mismatch names wrong-tree" || nok "mismatch names wrong-tree"

# advisory (derived, Scale S) => Attested HEAD never demanded, even with a CR file present
mkchange att-advisory
cat >"$TMP/openspec/changes/att-advisory/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
EOF
run att-advisory; check "advisory code review never demands Attested HEAD (verdict-freshness-and-provenance)" 0 $?

# ============================================================================
# opsx-gate-enforcement.doneness-verdict-enforcement
# opsx-adversarial-review.{sealed-doneness-verdict-artifact,freshness-bound-verdict,
#                      anti-self-forge-provenance,scale-gated-with-waiver}
# ============================================================================
mkMdone() { # <name> [fr]  complete Scale-M change PASSING every check UP TO doneness,
            # with a real opsx/<change> worktree. Exports BASE/WT/WTHEAD.
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d/specs/cap"
  BASE="$(git -C "$TMP" rev-parse HEAD)"
  {
    echo '---'; echo 'scale: M'; [ "${2:-}" = fr ] && echo 'full_rigor: true'
    echo 'verification_mode: retained-recommended'; echo 'code_review_mode: gating-required'
    echo 'loop_max_iterations: 40'; echo 'validation_source_mode: waived'
    echo 'spec_level: spec-anchored'; echo 'doneness_mode: required'; echo '---'
    echo '# Review'; echo; echo "**Diff Base SHA:** $BASE"; echo '**Worktree Path:**'
  } >"$d/review.md"
  for a in intent proposal plan; do echo "# $a" >"$d/$a.md"; done
  echo "# spec" >"$d/specs/cap/spec.md"
  printf '# tasks\n- [x] 1.1 done\n' >"$d/tasks.md"
  if [ "${2:-}" = fr ]; then
    for a in clarify analyze design; do echo "# $a" >"$d/$a.md"; done
    df_seal "$1"
  fi
  make_wt "$1"
  cat >"$WT/openspec/changes/$1/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $BASE
**Reviewed Range:** $BASE..$WTHEAD
**Attested HEAD:** $WTHEAD
EOF
}
donefile() { # <name> <verdict> [review_mode] [attested]  -> writes doneness.md into the worktree
  local d="$WT/openspec/changes/$1"; local ih; ih="$(ihash "$d/intent.md")"
  cat >"$d/doneness.md" <<EOF
# Doneness
**Doneness:** $2
**Judge:** claude-bridge/claude-opus-4-8
**review_mode:** ${3:-blind-single-judge}
**Frozen-Intent SHA:** $ih
**Diff Base SHA:** $BASE
**Reviewed Range:** $BASE..$WTHEAD
${4:+**Attested HEAD:** $4}
EOF
}

# satisfied + fresh + provenanced => PASS (blind-single-judge, the normal case)
mkMdone d-ok; donefile d-ok satisfied
run d-ok --worktree "$WT"; check "satisfied fresh provenanced doneness passes (sealed-doneness-verdict-artifact / doneness-verdict-enforcement)" 0 $?

# adversarial-multimodel is the stronger, equally-valid review_mode
mkMdone d-multi; donefile d-multi satisfied adversarial-multimodel
run d-multi --worktree "$WT"; check "adversarial-multimodel doneness review_mode passes (anti-self-forge-provenance)" 0 $?

# --- Attested HEAD on doneness: full_rigor-only binding (verdict-freshness-and-provenance) ---
# full_rigor independent judge WITHOUT attestation => FAIL under the doneness check
mkMdone d-fr-noatt fr; donefile d-fr-noatt satisfied
run d-fr-noatt --worktree "$WT"; rc=$?
check "full_rigor judge without Attested HEAD fails (verdict-freshness-and-provenance)" 1 $rc
grep -q 'GATE-FAIL doneness' "$TMP/err" && grep -q 'Attested HEAD' "$TMP/err" \
  && ok "full_rigor doneness attestation named" || nok "full_rigor doneness attestation named"
# full_rigor judge WITH matching attestation => PASS
mkMdone d-fr-att fr; donefile d-fr-att satisfied blind-single-judge "$WTHEAD"
run d-fr-att --worktree "$WT"; check "full_rigor judge with matching Attested HEAD passes (verdict-freshness-and-provenance)" 0 $?

# --- attestation survives the doneness-only verdict-sealing trailing commit ---
mkMdone d-fr-seal fr; donefile d-fr-seal satisfied blind-single-judge "$WTHEAD"
git -C "$WT" add openspec/changes/d-fr-seal/code-review.md openspec/changes/d-fr-seal/doneness.md
git -C "$WT" commit -qm "seal verdicts (verdict-only trailing commit)"
run d-fr-seal --worktree "$WT"; check "full_rigor Attested HEAD survives doneness-only sealing commit (verdict-freshness-and-provenance)" 0 $?

# unknown review_mode fails CLOSED
mkMdone d-unknownmode; donefile d-unknownmode satisfied something-else
run d-unknownmode --worktree "$WT"; rc=$?
check "unknown doneness review_mode fails closed (anti-self-forge-provenance)" 1 $rc
grep -q 'GATE-FAIL doneness' "$TMP/err" && ok "reports doneness fail for unknown review_mode" || nok "reports doneness fail for unknown review_mode"

# absent doneness.md at Scale M required => FAIL
mkMdone d-absent
run d-absent --worktree "$WT"; rc=$?
check "absent doneness.md fails at Scale>=M (doneness-verdict-enforcement)" 1 $rc
grep -q 'GATE-FAIL doneness' "$TMP/err" && ok "reports doneness absent" || nok "reports doneness absent"

# Doneness: not => FAIL
mkMdone d-not; donefile d-not not
run d-not --worktree "$WT"; check "Doneness not fails (doneness-verdict-enforcement)" 1 $?

# mismatched intent hash => FAIL
mkMdone d-hash; donefile d-hash satisfied
sed -i.bak 's/^\*\*Frozen-Intent SHA:\*\*.*/**Frozen-Intent SHA:** deadbeefhash/' "$WT/openspec/changes/d-hash/doneness.md"
run d-hash --worktree "$WT"; check "mismatched intent hash fails (freshness-bound-verdict)" 1 $?

# mismatched diff base => FAIL
mkMdone d-base; donefile d-base satisfied
sed -i.bak 's/^\*\*Diff Base SHA:\*\*.*/**Diff Base SHA:** base999/' "$WT/openspec/changes/d-base/doneness.md"
run d-base --worktree "$WT"; check "mismatched diff base fails (freshness-bound-verdict)" 1 $?

# unprovenanced (no Judge) => FAIL
mkMdone d-prov; donefile d-prov satisfied
sed -i.bak '/^\*\*Judge:\*\*/d' "$WT/openspec/changes/d-prov/doneness.md"
run d-prov --worktree "$WT"; check "unprovenanced doneness fails (anti-self-forge-provenance)" 1 $?

# degraded-single-model => FAIL
mkMdone d-deg; donefile d-deg satisfied
sed -i.bak 's/^\*\*review_mode:\*\*.*/**review_mode:** degraded-single-model/' "$WT/openspec/changes/d-deg/doneness.md"
run d-deg --worktree "$WT"; check "degraded-single-model doneness fails (anti-self-forge-provenance)" 1 $?

# missing review_mode provenance => FAIL (not just literal degraded)
mkMdone d-nomode; donefile d-nomode satisfied
sed -i.bak '/^\*\*review_mode:\*\*/d' "$WT/openspec/changes/d-nomode/doneness.md"
run d-nomode --worktree "$WT"; rc=$?
check "missing review_mode provenance fails (anti-self-forge-provenance)" 1 $rc
grep -q 'GATE-FAIL doneness ' "$TMP/err" && ok "missing review_mode reported under doneness check" || nok "missing review_mode reported under doneness check"

# stale reviewed range => FAIL, reported under the 'doneness' check id
mkMdone d-stale; donefile d-stale satisfied
sed -i.bak 's/^\*\*Reviewed Range:\*\*.*/**Reviewed Range:** '"$BASE"'..deadbeef/' "$WT/openspec/changes/d-stale/doneness.md"
run d-stale --worktree "$WT"; rc=$?
check "stale doneness reviewed range fails (freshness-bound-verdict)" 1 $rc
grep -q 'GATE-FAIL doneness ' "$TMP/err" && ok "stale doneness reported under doneness check id" || nok "stale doneness reported under doneness check id"

# ---- waiver path (doneness_mode: waived) ----
mkMwaive() { # <name> [fm_line] ; fm_line = one extra front-matter line (e.g. a
             # doneness_waiver_rationale). NOTE: never invoked via a pipe — a piped
             # function runs in a subshell and would lose the exported WT/WTHEAD.
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d/specs/cap"
  BASE="$(git -C "$TMP" rev-parse HEAD)"
  {
    echo '---'; echo 'scale: M'; echo 'verification_mode: retained-recommended'
    echo 'code_review_mode: gating-required'; echo 'loop_max_iterations: 40'
    echo 'validation_source_mode: waived'; echo 'spec_level: spec-anchored'
    echo 'doneness_mode: waived'; [ -n "${2:-}" ] && printf '%s\n' "$2"; echo '---'
    echo '# Review'; echo; echo "**Diff Base SHA:** $BASE"; echo '**Worktree Path:**'
  } >"$d/review.md"
  for a in intent proposal plan; do echo "# $a" >"$d/$a.md"; done
  echo "# spec" >"$d/specs/cap/spec.md"; printf '# tasks\n- [x] 1.1 done\n' >"$d/tasks.md"
  make_wt "$1"
  cat >"$WT/openspec/changes/$1/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $BASE
**Reviewed Range:** $BASE..$WTHEAD
**Attested HEAD:** $WTHEAD
EOF
}

# waiver WITH rationale => PASS (no doneness.md needed)
mkMwaive d-waive 'doneness_waiver_rationale: bootstrap reason'
run d-waive --worktree "$WT"; check "waiver with rationale passes without doneness.md (scale-gated-with-waiver)" 0 $?

# bare waiver (no rationale) => FAIL at Scale>=M
mkMwaive d-bare
run d-bare --worktree "$WT"; rc=$?
check "bare waiver fails at Scale>=M (scale-gated-with-waiver)" 1 $rc
grep -q 'GATE-FAIL doneness' "$TMP/err" && ok "reports bare-waiver doneness fail" || nok "reports bare-waiver doneness fail"

# empty block-scalar rationale => FAIL
mkMwaive d-emptyblock 'doneness_waiver_rationale: >'
run d-emptyblock --worktree "$WT"; rc=$?
check "empty block-scalar rationale fails, not passes (scale-gated-with-waiver)" 1 $rc
grep -q 'GATE-FAIL doneness' "$TMP/err" && ok "content-less block-scalar rationale rejected" || nok "content-less block-scalar rationale rejected"

# block-scalar rationale WITH indented content => PASS
# (build the block scalar directly: the indented content line must land inside
#  the front-matter, so append it after mkMwaive lays the fence-less body.)
mkMwaive d-blockok 'doneness_waiver_rationale: >'
# insert the indented content line right below the block-scalar marker, still in FM
awk '1; /^doneness_waiver_rationale: >$/{print "  a real multi-line rationale explaining the waiver"}' \
  "$TMP/openspec/changes/d-blockok/review.md" >"$TMP/dblk.tmp" && mv "$TMP/dblk.tmp" "$TMP/openspec/changes/d-blockok/review.md"
cp "$TMP/openspec/changes/d-blockok/review.md" "$WT/openspec/changes/d-blockok/review.md" 2>/dev/null || true
run d-blockok --worktree "$WT"; check "block-scalar rationale with content passes (scale-gated-with-waiver)" 0 $?

# content-less rationale variants (comment-only, block+trailing-comment, quoted-whitespace) => FAIL
for variant in 'doneness_waiver_rationale: # only a comment' 'doneness_waiver_rationale: > # comment, no content' 'doneness_waiver_rationale: "   "'; do
  nm="d-empty-$(echo "$variant" | tr -cd 'a-z' | cut -c1-8)$RANDOM"
  mkMwaive "$nm" "$variant"
  run "$nm" --worktree "$WT"; check "content-less rationale variant fails: [$variant] (scale-gated-with-waiver)" 1 $?
done

# inline quoted rationale WITH content => PASS
mkMwaive d-inlineok 'doneness_waiver_rationale: "a real inline rationale for the waiver"'
run d-inlineok --worktree "$WT"; check "inline quoted rationale with content passes (scale-gated-with-waiver)" 0 $?

# sub-M skip: Scale-S change with doneness_mode required must NOT evaluate doneness
mkchange d-subm
awk '1; /^spec_level:/{print "doneness_mode: required"}' "$TMP/openspec/changes/d-subm/review.md" >"$TMP/dsub.tmp" && mv "$TMP/dsub.tmp" "$TMP/openspec/changes/d-subm/review.md"
run d-subm; check "sub-M change skips doneness even when mode required (scale-gated-with-waiver)" 0 $?

# sole-remaining suppression: an upstream (code-review) failure suppresses the doneness line
mkMdone d-suppress; donefile d-suppress satisfied
sed -i.bak 's/^\*\*Verdict:\*\* pass/**Verdict:** fail/' "$WT/openspec/changes/d-suppress/code-review.md"
run d-suppress --worktree "$WT"; rc=$?
check "upstream code-review failure present (doneness-verdict-enforcement)" 1 $rc
grep -q 'GATE-FAIL code-review' "$TMP/err" && ok "code-review fail emitted" || nok "code-review fail emitted"
grep -q 'GATE-FAIL doneness' "$TMP/err" && nok "doneness suppressed while another check red" || ok "doneness suppressed while another check red"

# ============================================================================
# Audit-remediation (bundle A) tests
# ============================================================================

# --- option hygiene: a missing --worktree value exits 2 immediately ---------
# (regression: `shift 2` with one arg left never shifts -> infinite parse loop)
( perl -e 'alarm 5; exec @ARGV or die' "$OPSX" gate green-s --worktree ) >/dev/null 2>&1
check "missing --worktree value exits 2, no hang (gate-exit-code-contract)" 2 $?

# --- fail-closed mode validation (mode-aware-verdict-reading) ----------------
mkchange badmode2
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-requred/' "$TMP/openspec/changes/badmode2/review.md"
run badmode2; rc=$?
check "malformed code_review_mode fails closed (mode-aware-verdict-reading)" 1 $rc
grep -q 'GATE-FAIL mode' "$TMP/err" && ok "reports mode fail (code_review_mode)" || nok "reports mode fail (code_review_mode)"

# --- hung required validator is bounded by OPSX_GATE_CMD_TIMEOUT ------------
mkchange hangy
cat >"$TMP/openspec/opsx-gates.yaml" <<'EOF'
gates:
  - id: hang
    run: sleep 30
    required: true
EOF
if command -v yq >/dev/null 2>&1 && command -v perl >/dev/null 2>&1; then
  t0="$(date +%s)"
  OPSX_GATE_CMD_TIMEOUT=1 run hangy; rc=$?
  t1="$(date +%s)"
  check "hung validator fails via timeout (manifest-validation-execution)" 1 $rc
  grep -q 'GATE-FAIL validation-hang' "$TMP/err" && ok "reports validation-hang" || nok "reports validation-hang"
  [ $((t1 - t0)) -lt 15 ] && ok "timeout bounded (<15s, not 30s sleep)" || nok "timeout bounded (took $((t1 - t0))s)"
fi
rm -f "$TMP/openspec/opsx-gates.yaml"

# --- worktree artifact source: gate reads artifacts from the WORKTREE -------
# (split-brain regression: validation cwd was the worktree but tasks/verdicts
#  were read from the integration checkout)
WTD="$TMP/openspec/changes/wt-div"; mkdir -p "$WTD/specs/cap"
BASE_WD="$(git -C "$TMP" rev-parse HEAD)"
cat >"$WTD/review.md" <<EOF
---
scale: S
verification_mode: retained-recommended
code_review_mode: advisory
loop_max_iterations: 20
validation_source_mode: required
spec_level: spec-anchored
---
# Review

**Diff Base SHA:** $BASE_WD
**Worktree Path:** $WTBASE/wt-div
EOF
echo "# proposal" >"$WTD/proposal.md"
echo "# spec" >"$WTD/specs/cap/spec.md"
echo "# plan" >"$WTD/plan.md"
printf '# tasks\n- [ ] 1.1 todo\n' >"$WTD/tasks.md"
commit_all "wt-div fixture"
git -C "$TMP" worktree add -q -b "opsx/wt-div" "$WTBASE/wt-div" >/dev/null 2>&1

# Worktree copy: tasks complete. Root copy: still unchecked (stale).
printf '# tasks\n- [x] 1.1 todo\n' >"$WTBASE/wt-div/openspec/changes/wt-div/tasks.md"
run wt-div --worktree "$WTBASE/wt-div"
check "worktree tasks.md is the artifact source, stale root ignored (mode-aware-verdict-reading)" 0 $?

# Reverse: worktree copy unchecked must FAIL even when root copy is checked.
printf '# tasks\n- [ ] 1.1 todo\n' >"$WTBASE/wt-div/openspec/changes/wt-div/tasks.md"
printf '# tasks\n- [x] 1.1 todo\n' >"$WTD/tasks.md"
run wt-div --worktree "$WTBASE/wt-div"; rc=$?
check "unchecked worktree tasks.md fails despite checked root copy (mode-aware-verdict-reading)" 1 $rc
grep -q 'GATE-FAIL tasks' "$TMP/err" && ok "reports tasks fail from worktree copy" || nok "reports tasks fail from worktree copy"

# Recorded Worktree Path (no --worktree flag) resolves the same artifact source.
printf '# tasks\n- [x] 1.1 todo\n' >"$WTBASE/wt-div/openspec/changes/wt-div/tasks.md"
printf '# tasks\n- [ ] 1.1 todo\n' >"$WTD/tasks.md"
# publish the recorded Worktree Path locator (committed integration content)
sed -i.bak 's#^\*\*Worktree Path:\*\*.*#**Worktree Path:** '"$WTBASE"'/wt-div#' "$WTD/review.md" && rm -f "$WTD/review.md.bak"
run wt-div
check "recorded Worktree Path resolves worktree artifact source without --worktree (mode-aware-verdict-reading)" 0 $?

# ============================================================================
# Tier collapse (opsx-workflow-schema.scale-adaptive-gating,
# opsx-gate-enforcement.required-artifact-by-scale): XS|S|M vocabulary +
# full_rigor flag; L/XL fail closed with the relabel remedy; plain-M drops
# clarify.md/analyze.md; M+full_rigor restores them; and --cheap skips
# validation-command execution while verdict-state checks still report.
# ============================================================================

# 3-tier vocabulary ACCEPTED: XS resolves without a scale failure ------------
mkchange xs-ok
sed -i.bak 's/^scale: S/scale: XS/' "$TMP/openspec/changes/xs-ok/review.md"
run xs-ok; check "Scale XS accepted (scale-adaptive-gating)" 0 $?
grep -q 'GATE-FAIL scale' "$TMP/err" && nok "XS wrongly scale-failed" || ok "XS is a known Scale"

# L and XL FAIL CLOSED with the relabel remedy ------------------------------
mkchange lscale
sed -i.bak 's/^scale: S/scale: L/' "$TMP/openspec/changes/lscale/review.md"
run lscale; rc=$?
check "Scale L fails closed (scale-adaptive-gating)" 1 $rc
grep -q 'GATE-FAIL scale' "$TMP/err" && grep -qi 'relabel' "$TMP/err" && grep -q "full_rigor: true" "$TMP/err" \
  && ok "L names the relabel-to-M+full_rigor remedy" || nok "L relabel remedy text"
mkchange xlscale
sed -i.bak 's/^scale: S/scale: XL/' "$TMP/openspec/changes/xlscale/review.md"
run xlscale; rc=$?
check "Scale XL fails closed (scale-adaptive-gating)" 1 $rc
grep -q 'GATE-FAIL scale' "$TMP/err" && grep -qi 'relabel' "$TMP/err" && ok "XL names the relabel remedy" || nok "XL relabel remedy text"

# non-boolean full_rigor FAILS CLOSED --------------------------------------
mkchange badfr
awk '1; /^scale: S/{print "full_rigor: maybe"}' "$TMP/openspec/changes/badfr/review.md" >"$TMP/badfr.tmp" \
  && mv "$TMP/badfr.tmp" "$TMP/openspec/changes/badfr/review.md"
run badfr; rc=$?
check "non-boolean full_rigor fails closed (scale-adaptive-gating)" 1 $rc
grep -q 'GATE-FAIL full_rigor' "$TMP/err" && ok "reports full_rigor fail" || nok "reports full_rigor fail"

# plain-M change PASSES artifact checks WITHOUT clarify.md / analyze.md ------
# (plain M does NOT carry design.md — design is decision-gated per D5 — so no
#  design-fidelity verdict is demanded either.)
mkPlainM() { # complete plain-M (no full_rigor) fixture: NO clarify.md, analyze.md, design.md
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d/specs/cap"
  cat >"$d/review.md" <<EOF
---
scale: M
verification_mode: retained-recommended
code_review_mode: advisory
loop_max_iterations: 40
validation_source_mode: waived
spec_level: spec-anchored
doneness_mode: waived
doneness_waiver_rationale: "test fixture waiver"
---
# Review
EOF
  for a in intent proposal plan; do echo "# $a" >"$d/$a.md"; done
  echo "# spec" >"$d/specs/cap/spec.md"
  printf '# tasks\n- [x] 1.1 done\n' >"$d/tasks.md"
}
mkPlainM plain-m
run plain-m; check "plain-M passes WITHOUT clarify.md/analyze.md (required-artifact-by-scale)" 0 $?
[ ! -f "$TMP/openspec/changes/plain-m/clarify.md" ] && [ ! -f "$TMP/openspec/changes/plain-m/analyze.md" ] \
  && ok "plain-M fixture genuinely omits clarify/analyze" || nok "plain-M fixture omits clarify/analyze"

# ---- R5-F1: ABSENT code_review_mode derives the fail-closed default ----
# (opsx-gate-enforcement.mode-aware-verdict-reading): at Scale M an omitted
# code_review_mode key derives gating-required — missing code-review.md FAILS.
mkPlainM m-no-crmode
sed -i.bak '/^code_review_mode: advisory$/d' "$TMP/openspec/changes/m-no-crmode/review.md" && rm -f "$TMP/openspec/changes/m-no-crmode/review.md.bak"
run m-no-crmode; rc=$?
[ $rc -ne 0 ] && grep -q 'code-review' "$TMP/err" \
  && ok "absent code_review_mode at M derives gating-required (missing code-review.md fails)" || nok "absent code_review_mode at M fail-closed (rc=$rc)"
# Below M: absent key derives advisory — missing code-review.md does NOT block.
mkchange xs-no-crmode
sed -i.bak -e 's/^scale: .*/scale: XS/' -e '/^code_review_mode:/d' "$TMP/openspec/changes/xs-no-crmode/review.md" && rm -f "$TMP/openspec/changes/xs-no-crmode/review.md.bak"
run xs-no-crmode; rc=$?
grep -q 'code-review' "$TMP/err" && nok "absent code_review_mode below M must stay advisory" || ok "absent code_review_mode below M derives advisory (no code-review block)"

# ---- R6-F1: whole-change openspec validate conditioned on specs/ presence ----
# The real openspec CLI demands >=1 spec delta; XS/S deliberately omit specs/.
# Gate must SKIP whole-change validation when specs/ is absent (XS/S usable in
# real workspaces) and RUN it whenever specs/ exists.
mkchange xs-nospecs
sed -i.bak 's/^scale: .*/scale: XS/' "$TMP/openspec/changes/xs-nospecs/review.md" && rm -f "$TMP/openspec/changes/xs-nospecs/review.md.bak"
rm -rf "$TMP/openspec/changes/xs-nospecs/specs"
export OPSX_TEST_OPENSPEC_LOG="$TMP/openspec-invocations"
: >"$OPSX_TEST_OPENSPEC_LOG"
run xs-nospecs; rc=$?
[ $rc -eq 0 ] && ok "XS without specs/ passes the gate (structure validation skipped)" || nok "XS without specs/ gateable (rc=$rc)"
grep -q 'validate xs-nospecs' "$OPSX_TEST_OPENSPEC_LOG" && nok "structure validation must be skipped when specs/ absent" || ok "whole-change openspec validate skipped when specs/ absent"
: >"$OPSX_TEST_OPENSPEC_LOG"
run green-s; rc=$?
grep -q 'validate green-s' "$OPSX_TEST_OPENSPEC_LOG" && ok "whole-change openspec validate still runs when specs/ present" || nok "structure validation must run when specs/ present"
unset OPSX_TEST_OPENSPEC_LOG

# plain-M does NOT require design.md (D3/D5: design is decision-gated at plain M) --
mkPlainM plain-m-nodesign
rm -f "$TMP/openspec/changes/plain-m-nodesign/design.md"
run plain-m-nodesign; check "plain-M passes WITHOUT design.md (required-artifact-by-scale)" 0 $?
grep -q 'GATE-FAIL artifact-design' "$TMP/err" && nok "plain-M wrongly demanded design.md" || ok "plain-M omits the design.md requirement"

# M + full_rigor REQUIRES clarify.md + analyze.md ---------------------------
# (full_rigor also carries design.md => a sealed design-fidelity verdict; df_seal
#  supplies it so the ONLY variable under test is the clarify/analyze requirement.)
mkFR() { # full_rigor M fixture WITHOUT clarify/analyze; design + design-fidelity sealed
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d/specs/cap"
  cat >"$d/review.md" <<EOF
---
scale: M
full_rigor: true
verification_mode: retained-recommended
code_review_mode: advisory
loop_max_iterations: 40
validation_source_mode: waived
spec_level: spec-anchored
doneness_mode: waived
doneness_waiver_rationale: "test fixture waiver"
---
# Review
EOF
  for a in intent proposal design plan; do echo "# $a" >"$d/$a.md"; done
  echo "# spec" >"$d/specs/cap/spec.md"
  printf '# tasks\n- [x] 1.1 done\n' >"$d/tasks.md"
  df_seal "$1"
}
mkFR fr-need
run fr-need; rc=$?
check "M+full_rigor requires clarify.md/analyze.md (required-artifact-by-scale)" 1 $rc
grep -q 'GATE-FAIL artifact-clarify' "$TMP/err" && ok "full_rigor demands clarify.md" || nok "full_rigor demands clarify.md"
grep -q 'GATE-FAIL artifact-analyze' "$TMP/err" && ok "full_rigor demands analyze.md" || nok "full_rigor demands analyze.md"
echo "# clarify" >"$TMP/openspec/changes/fr-need/clarify.md"
echo "# analyze" >"$TMP/openspec/changes/fr-need/analyze.md"
run fr-need; check "M+full_rigor passes once clarify.md+analyze.md exist (required-artifact-by-scale)" 0 $?

# M + full_rigor REQUIRES design.md (the former L/XL full set always carried design)
mkFR fr-nodesign
echo "# clarify" >"$TMP/openspec/changes/fr-nodesign/clarify.md"
echo "# analyze" >"$TMP/openspec/changes/fr-nodesign/analyze.md"
rm -f "$TMP/openspec/changes/fr-nodesign/design.md"
run fr-nodesign; rc=$?
check "M+full_rigor fails WITHOUT design.md (required-artifact-by-scale)" 1 $rc
grep -q 'GATE-FAIL artifact-design' "$TMP/err" && ok "full_rigor demands design.md" || nok "full_rigor demands design.md"

# --cheap: skips validation-command execution + validation-source; verdict-state
# checks STILL report; a full gate STILL runs validations (regression pin).
mkchange cheapv
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' "$TMP/openspec/changes/cheapv/review.md"
BASE_CV="$(git -C "$TMP" rev-parse HEAD)"
printf '\n**Diff Base SHA:** %s\n**Worktree Path:**\n' "$BASE_CV" >>"$TMP/openspec/changes/cheapv/review.md"
make_wt cheapv; WCV="$WT"
# stale code-review in the worktree
cat >"$WCV/openspec/changes/cheapv/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $BASE_CV
**Reviewed Range:** $BASE_CV..deadbeef
**Attested HEAD:** $BASE_CV
EOF
cat >"$TMP/openspec/opsx-gates.yaml" <<'EOF'
gates:
  - id: mustrun
    run: 'exit 5'
    required: true
EOF
# full gate: executes the (failing) validation AND reports the stale verdict.
run cheapv --worktree "$WCV"; rc=$?
check "full gate executes validation commands (regression pin)" 1 $rc
grep -q 'GATE-FAIL validation-mustrun' "$TMP/err" && ok "full gate ran the validation command" || nok "full gate ran the validation command"
# --cheap: the validation command is NOT executed, the stale verdict STILL reports.
commit_all
"$OPSX" gate cheapv --cheap --worktree "$WCV" >"$TMP/outc" 2>"$TMP/errc"; rcc=$?
check "cheap gate is red on the verdict-state check (opsx gate --cheap)" 1 $rcc
grep -q 'GATE-FAIL validation-mustrun' "$TMP/errc" && nok "cheap wrongly executed the validation command" || ok "cheap skipped the validation command"
grep -q 'GATE-FAIL code-review-stale' "$TMP/errc" && ok "cheap still reports the verdict-state (freshness) check" || nok "cheap still reports the verdict-state check"
grep -qi 'gate(cheap)' "$TMP/errc" "$TMP/outc" && ok "cheap run is label-visible as gate(cheap)" || nok "cheap label visible"

# --cheap GREEN never overclaims: a would-fail validation is skipped, a clean
# change reaches GATE-PASS(cheap) with the 'validations not run' caveat.
mkchange cheapg
run cheapg; check "full gate red when its required validation fails (manifest-validation-execution)" 1 $?
commit_all
"$OPSX" gate cheapg --cheap >"$TMP/outg" 2>"$TMP/errg"; rcg=$?
check "cheap gate green despite a failing validation (validation not executed)" 0 $rcg
grep -q 'GATE-PASS(cheap)' "$TMP/outg" && ok "cheap green labeled GATE-PASS(cheap)" || nok "cheap green labeled GATE-PASS(cheap)"
grep -qi 'validations not run' "$TMP/outg" && ok "cheap green does not overclaim validations ran" || nok "cheap green caveat present"
rm -f "$TMP/openspec/opsx-gates.yaml"

# --- opsx-gate-enforcement.migration-sweep-gate-check ---
# Tracked shipped surface carrying a retired token, outside openspec/**+adr/**.
printf 'clean line\nRETIRED_SWEEP_TOKEN lives here\n' > "$TMP/shipped_surface"
git -C "$TMP" add shipped_surface; git -C "$TMP" commit -qm shipped-surface

mkchange sweep-hit
printf '# declared retired tokens\nRETIRED_SWEEP_TOKEN\n' > "$TMP/openspec/changes/sweep-hit/sweep.txt"
run sweep-hit; rc=$?
check "declared pattern hit on shipped surface fails the gate (migration-sweep-gate-check)" 1 $rc
grep -q 'GATE-FAIL sweep' "$TMP/err" && ok "sweep failure emits GATE-FAIL sweep line" || nok "GATE-FAIL sweep line"
grep -q 'SWEEP-HIT RETIRED_SWEEP_TOKEN shipped_surface:2' "$TMP/err" \
  && ok "SWEEP-HIT names pattern + file:line" || nok "SWEEP-HIT detail line"

mkchange sweep-none   # NO sweep.txt: check absent, exit unaffected
run sweep-none; rc=$?
check "undeclared change unaffected by sweep (conditional check)" 0 $rc
grep -q 'sweep' "$TMP/err" && nok "no sweep output for undeclared change" || ok "no sweep output for undeclared change"

mkchange sweep-clean
printf 'TOKEN_THAT_MATCHES_NOTHING_ANYWHERE_ZZZ\n' > "$TMP/openspec/changes/sweep-clean/sweep.txt"
run sweep-clean; rc=$?
check "clean declared sweep passes the gate" 0 $rc

mkchange sweep-empty  # declaration with only comments/blanks = clean pass
printf '# only comments\n\n' > "$TMP/openspec/changes/sweep-empty/sweep.txt"
run sweep-empty; rc=$?
check "empty declaration (comments only) is a clean pass" 0 $rc

mkchange sweep-badre  # malformed ERE: loud SWEEP-ERROR failure, never silent pass
printf '*invalid(\n' > "$TMP/openspec/changes/sweep-badre/sweep.txt"
run sweep-badre; rc=$?
check "malformed ERE fails the gate loudly" 1 $rc
grep -q 'SWEEP-ERROR' "$TMP/err" && ok "malformed ERE emits SWEEP-ERROR" || nok "SWEEP-ERROR line"

# Worktree resolution: stale token on integration, FIXED in the worktree — the
# gate sweep greps the resolved ART_ROOT (worktree), so the fix counts.
mkchange sweep-wt
printf 'RETIRED_SWEEP_TOKEN\n' > "$TMP/openspec/changes/sweep-wt/sweep.txt"
commit_all sweep-wt-change
SWWT="$WTBASE/wt-sweep"
git -C "$TMP" worktree add -q -b opsx/sweep-wt "$SWWT" >/dev/null 2>&1
( cd "$SWWT" && sed -i.bak 's/RETIRED_SWEEP_TOKEN/cleaned/' shipped_surface && rm -f shipped_surface.bak \
  && git add shipped_surface && git commit -qm fix-token )
run sweep-wt --worktree "$SWWT"; rc=$?
grep -q 'GATE-FAIL sweep' "$TMP/err" && nok "worktree-fixed token does not sweep-fail" || ok "worktree-fixed token does not sweep-fail"
# and WITHOUT the worktree view the stale integration copy still fails:
git -C "$TMP" worktree remove --force "$SWWT" >/dev/null 2>&1
git -C "$TMP" branch -qD opsx/sweep-wt >/dev/null 2>&1
run sweep-wt; rc=$?
grep -q 'GATE-FAIL sweep' "$TMP/err" && ok "integration-stale token still sweep-fails without worktree" || nok "integration-stale sweep-fail"
# cleanup the planted surface so later suites/fixtures are unaffected
git -C "$TMP" rm -q shipped_surface; git -C "$TMP" commit -qm rm-shipped-surface

# --- opsx-gate-enforcement.project-artifact-preflight ---
# constitution.md + domain.md must exist NON-EMPTY at EVERY Scale; fail-closed,
# remedy names the shipped templates; no waiver key, no auto-scaffold.
mkchange preflight-s
mv "$TMP/openspec/constitution.md" "$TMP/openspec/constitution.md.bak"
run preflight-s; rc=$?
[ $rc -ne 0 ] && grep -q 'GATE-FAIL project-artifacts 1 openspec/constitution.md' "$TMP/err" \
  && grep -q 'constitution-template.md' "$TMP/err" \
  && ok "preflight: missing constitution reds naming the template remedy (project-artifact-preflight)" \
  || nok "preflight missing constitution (rc=$rc)"
mv "$TMP/openspec/constitution.md.bak" "$TMP/openspec/constitution.md"
: >"$TMP/openspec/domain.md"   # empty file counts as missing (test -s, clarify C2)
run preflight-s; rc=$?
[ $rc -ne 0 ] && grep -q 'GATE-FAIL project-artifacts 1 openspec/domain.md' "$TMP/err" \
  && grep -q 'domain-template.md' "$TMP/err" \
  && ok "preflight: EMPTY domain reds naming the template remedy (test -s semantics)" \
  || nok "preflight empty domain (rc=$rc)"
printf '# Domain\n' >"$TMP/openspec/domain.md"
run preflight-s; check "preflight: both artifacts present turn the check green" 0 $?
# fires at XS too (no Scale skips it)
mkchange preflight-xs
d="$TMP/openspec/changes/preflight-xs"; rm -rf "$d/specs" "$d/plan.md" 2>/dev/null
sed -i.bak 's/^scale: S/scale: XS/' "$d/review.md" && rm -f "$d/review.md.bak"
mv "$TMP/openspec/constitution.md" "$TMP/openspec/constitution.md.bak"
run preflight-xs; rc=$?
[ $rc -ne 0 ] && grep -q 'GATE-FAIL project-artifacts' "$TMP/err" \
  && ok "preflight fires at Scale XS alike (no Scale skips it)" || nok "preflight at XS (rc=$rc)"
mv "$TMP/openspec/constitution.md.bak" "$TMP/openspec/constitution.md"

echo "----"
echo "passed=$pass failed=$failc"
[ "$failc" -eq 0 ]
