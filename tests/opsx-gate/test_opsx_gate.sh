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
#   opsx-gate-enforcement.doneness-verdict-enforcement
#   opsx-doneness-judge.sealed-doneness-verdict-artifact
#   opsx-doneness-judge.freshness-bound-verdict
#   opsx-doneness-judge.anti-self-forge-provenance
#   opsx-doneness-judge.scale-gated-with-waiver
set -uo pipefail

OPSX="$(cd "$(dirname "$0")/../.." && pwd)/dot_local/bin/executable_opsx"
pass=0; failc=0
ok()   { printf 'ok   - %s\n' "$1"; pass=$((pass+1)); }
nok()  { printf 'NOT OK - %s\n' "$1"; failc=$((failc+1)); }
check(){ # check <desc> <expected-rc> <actual-rc>
  if [ "$2" = "$3" ]; then ok "$1"; else nok "$1 (want rc=$2 got rc=$3)"; fi; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FAKEBIN="$TMP/fakebin"; mkdir -p "$FAKEBIN"
# Deterministic stub: openspec validate always succeeds in fixtures.
cat >"$FAKEBIN/openspec" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$FAKEBIN/openspec"
export PATH="$FAKEBIN:$PATH"

git -C "$TMP" init -q
git -C "$TMP" config user.email t@t; git -C "$TMP" config user.name t
printf seed > "$TMP/seed"; git -C "$TMP" add seed; git -C "$TMP" commit -qm seed
export OPSX_ROOT="$TMP"
HEAD_SHA="$(git -C "$TMP" rev-parse HEAD)"

mkchange() { # mkchange <name> ; creates a complete Scale-S change by default
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d/specs/cap"
  cat >"$d/review.md" <<'EOF'
---
scale: S
worktree_mode: same-tree
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

run() { "$OPSX" gate "$@" 2>"$TMP/err"; }

# --- opsx-gate-enforcement.gate-exit-code-contract ---
mkchange green-s
run green-s; check "complete Scale-S change passes (gate-exit-code-contract)" 0 $?
run nonexistent-change; check "unknown change fails (gate-exit-code-contract)" 1 $?

# --- opsx-gate-enforcement.required-artifact-by-scale ---
mkchange missing-plan; rm "$TMP/openspec/changes/missing-plan/plan.md"
run missing-plan; rc=$?
check "missing Scale-S artifact fails (required-artifact-by-scale)" 1 $rc
grep -q 'GATE-FAIL artifact-plan' "$TMP/err" && ok "reports artifact-plan" || nok "reports artifact-plan"

mkchange noscale
# break the scale value
sed -i.bak 's/^scale: S/scale: /' "$TMP/openspec/changes/noscale/review.md"
run noscale; check "absent Scale fails (required-artifact-by-scale)" 1 $?
grep -q 'GATE-FAIL scale' "$TMP/err" && ok "reports scale fail" || nok "reports scale fail"

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
mkchange fresh
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' \
  "$TMP/openspec/changes/fresh/review.md"
HEAD_SHA="$(git -C "$TMP" rev-parse HEAD 2>/dev/null || echo HEAD)"
cat >>"$TMP/openspec/changes/fresh/review.md" <<EOF

**Diff Base SHA:** base000
**Worktree Path:**
EOF
# stale: recorded range mentions a different head
cat >"$TMP/openspec/changes/fresh/code-review.md" <<EOF
Verdict: pass
review_mode: adversarial-multimodel
reviewer-provenance: subagent-x
Reviewed Range: base000..deadbeef
EOF
run fresh; check "stale reviewed range fails (verdict-freshness-and-provenance)" 1 $?
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
printf '\n**Diff Base SHA:** %s\n**Worktree Path:**\n' "$HEAD_SHA" \
  >>"$TMP/openspec/changes/cr-pass/review.md"
cat >"$TMP/openspec/changes/cr-pass/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $HEAD_SHA
**Reviewed Range:** $HEAD_SHA..$HEAD_SHA
EOF
run cr-pass; check "correct bold-field passing review reaches GATE-PASS (verdict-freshness-and-provenance)" 0 $?

# --- verdict-freshness-and-provenance: missing Reviewed Range is a failure, not a pass ---
mkchange cr-norange
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' \
  "$TMP/openspec/changes/cr-norange/review.md"
printf '\n**Diff Base SHA:** %s\n' "$HEAD_SHA" >>"$TMP/openspec/changes/cr-norange/review.md"
cat >"$TMP/openspec/changes/cr-norange/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
EOF
run cr-norange; check "missing Reviewed Range fails, not passes (verdict-freshness-and-provenance)" 1 $?

# --- worktree-required with no Worktree Path must fail, not fall back to ROOT ---
mkchange wt-required
sed -i.bak 's/^worktree_mode: same-tree/worktree_mode: worktree-required/' \
  "$TMP/openspec/changes/wt-required/review.md"
run wt-required; check "worktree-required + empty Worktree Path fails (required-artifact-by-scale)" 1 $?
grep -q 'GATE-FAIL worktree' "$TMP/err" && ok "locate-failure is a hard fail" || nok "locate-failure is a hard fail"

# --- freshness tolerates verdict-only sealing commits, rejects code drift ---
mkchange cr-seal
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' \
  "$TMP/openspec/changes/cr-seal/review.md"
printf '\n**Diff Base SHA:** %s\n' "$HEAD_SHA" >>"$TMP/openspec/changes/cr-seal/review.md"
git -C "$TMP" add -A; git -C "$TMP" commit -qm "cr-seal change"
C1="$(git -C "$TMP" rev-parse HEAD)"
cat >"$TMP/openspec/changes/cr-seal/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $HEAD_SHA
**Reviewed Range:** $HEAD_SHA..$C1
EOF
git -C "$TMP" add openspec/changes/cr-seal/code-review.md
git -C "$TMP" commit -qm "seal verdict (verdict-only commit)"
run cr-seal; check "freshness tolerates verdict-only sealing commit (verdict-freshness-and-provenance)" 0 $?
printf x >"$TMP/codefile"; git -C "$TMP" add codefile; git -C "$TMP" commit -qm "code change after review"
run cr-seal; check "freshness rejects non-verdict change after review (verdict-freshness-and-provenance)" 1 $?

# ============================================================================
# opsx-gate-enforcement.doneness-verdict-enforcement
# opsx-doneness-judge.{sealed-doneness-verdict-artifact,freshness-bound-verdict,
#                      anti-self-forge-provenance,scale-gated-with-waiver}
# ============================================================================
HEAD_SHA="$(git -C "$TMP" rev-parse HEAD)"
ihash() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'; else sha256sum "$1" | awk '{print $1}'; fi; }

mkMdone() { # complete Scale-M change that PASSES every check UP TO doneness
  local d="$TMP/openspec/changes/$1"; mkdir -p "$d/specs/cap"
  cat >"$d/review.md" <<EOF
---
scale: M
worktree_mode: same-tree
verification_mode: retained-recommended
code_review_mode: gating-required
loop_max_iterations: 40
validation_source_mode: waived
spec_level: spec-anchored
doneness_mode: required
---
# Review

**Diff Base SHA:** $HEAD_SHA
**Worktree Path:**
EOF
  for a in intent proposal clarify design analyze plan; do echo "# $a" >"$d/$a.md"; done
  echo "# spec" >"$d/specs/cap/spec.md"
  printf '# tasks\n- [x] 1.1 done\n' >"$d/tasks.md"
  cat >"$d/code-review.md" <<EOF
# Code Review
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** subagent-x
**Diff Base SHA:** $HEAD_SHA
**Reviewed Range:** $HEAD_SHA..$HEAD_SHA
EOF
}
donefile() { # <name> <verdict>
  local d="$TMP/openspec/changes/$1"; local ih; ih="$(ihash "$d/intent.md")"
  cat >"$d/doneness.md" <<EOF
# Doneness
**Doneness:** $2
**Judge:** claude-bridge/claude-opus-4-8
**review_mode:** adversarial-multimodel
**Frozen-Intent SHA:** $ih
**Diff Base SHA:** $HEAD_SHA
**Reviewed Range:** $HEAD_SHA..$HEAD_SHA
EOF
}

# satisfied + fresh + provenanced => PASS
mkMdone d-ok; donefile d-ok satisfied
run d-ok; check "satisfied fresh provenanced doneness passes (sealed-doneness-verdict-artifact / doneness-verdict-enforcement)" 0 $?

# absent doneness.md at Scale M required => FAIL
mkMdone d-absent
run d-absent; rc=$?
check "absent doneness.md fails at Scale>=M (doneness-verdict-enforcement)" 1 $rc
grep -q 'GATE-FAIL doneness' "$TMP/err" && ok "reports doneness absent" || nok "reports doneness absent"

# Doneness: not => FAIL
mkMdone d-not; donefile d-not not
run d-not; check "Doneness not fails (doneness-verdict-enforcement)" 1 $?

# mismatched intent hash => FAIL
mkMdone d-hash; donefile d-hash satisfied
sed -i.bak 's/^\*\*Frozen-Intent SHA:\*\*.*/**Frozen-Intent SHA:** deadbeefhash/' "$TMP/openspec/changes/d-hash/doneness.md"
run d-hash; check "mismatched intent hash fails (freshness-bound-verdict)" 1 $?

# mismatched diff base => FAIL
mkMdone d-base; donefile d-base satisfied
sed -i.bak 's/^\*\*Diff Base SHA:\*\*.*/**Diff Base SHA:** base999/' "$TMP/openspec/changes/d-base/doneness.md"
run d-base; check "mismatched diff base fails (freshness-bound-verdict)" 1 $?

# unprovenanced (no Judge) => FAIL
mkMdone d-prov; donefile d-prov satisfied
sed -i.bak '/^\*\*Judge:\*\*/d' "$TMP/openspec/changes/d-prov/doneness.md"
run d-prov; check "unprovenanced doneness fails (anti-self-forge-provenance)" 1 $?

# degraded-single-model => FAIL
mkMdone d-deg; donefile d-deg satisfied
sed -i.bak 's/^\*\*review_mode:\*\*.*/**review_mode:** degraded-single-model/' "$TMP/openspec/changes/d-deg/doneness.md"
run d-deg; check "degraded-single-model doneness fails (anti-self-forge-provenance)" 1 $?

# missing review_mode provenance => FAIL (not just literal degraded)
mkMdone d-nomode; donefile d-nomode satisfied
sed -i.bak '/^\*\*review_mode:\*\*/d' "$TMP/openspec/changes/d-nomode/doneness.md"
run d-nomode; rc=$?
check "missing review_mode provenance fails (anti-self-forge-provenance)" 1 $rc
grep -q 'GATE-FAIL doneness ' "$TMP/err" && ok "missing review_mode reported under doneness check" || nok "missing review_mode reported under doneness check"

# stale reviewed range => FAIL, reported under the 'doneness' check id
mkMdone d-stale; donefile d-stale satisfied
sed -i.bak 's/^\*\*Reviewed Range:\*\*.*/**Reviewed Range:** '"$HEAD_SHA"'..deadbeef/' "$TMP/openspec/changes/d-stale/doneness.md"
run d-stale; rc=$?
check "stale doneness reviewed range fails (freshness-bound-verdict)" 1 $rc
grep -q 'GATE-FAIL doneness ' "$TMP/err" && ok "stale doneness reported under doneness check id" || nok "stale doneness reported under doneness check id"

# waiver WITH rationale => PASS (no doneness.md needed)
mkMdone d-waive
cat >"$TMP/openspec/changes/d-waive/review.md" <<EOF
---
scale: M
worktree_mode: same-tree
verification_mode: retained-recommended
code_review_mode: gating-required
loop_max_iterations: 40
validation_source_mode: waived
spec_level: spec-anchored
doneness_mode: waived
doneness_waiver_rationale: bootstrap reason
---
# Review

**Diff Base SHA:** $HEAD_SHA
**Worktree Path:**
EOF
run d-waive; check "waiver with rationale passes without doneness.md (scale-gated-with-waiver)" 0 $?

# bare waiver (no rationale) => FAIL at Scale>=M
mkMdone d-bare
cat >"$TMP/openspec/changes/d-bare/review.md" <<EOF
---
scale: M
worktree_mode: same-tree
verification_mode: retained-recommended
code_review_mode: gating-required
loop_max_iterations: 40
validation_source_mode: waived
spec_level: spec-anchored
doneness_mode: waived
---
# Review

**Diff Base SHA:** $HEAD_SHA
**Worktree Path:**
EOF
run d-bare; rc=$?
check "bare waiver fails at Scale>=M (scale-gated-with-waiver)" 1 $rc
grep -q 'GATE-FAIL doneness' "$TMP/err" && ok "reports bare-waiver doneness fail" || nok "reports bare-waiver doneness fail"

# sub-M skip: Scale-S change with doneness_mode required must NOT evaluate doneness
mkchange d-subm
awk '1; /^spec_level:/{print "doneness_mode: required"}' "$TMP/openspec/changes/d-subm/review.md" >"$TMP/dsub.tmp" && mv "$TMP/dsub.tmp" "$TMP/openspec/changes/d-subm/review.md"
run d-subm; check "sub-M change skips doneness even when mode required (scale-gated-with-waiver)" 0 $?

# sole-remaining suppression: an upstream (code-review) failure suppresses the doneness line
mkMdone d-suppress; donefile d-suppress satisfied
sed -i.bak 's/^\*\*Verdict:\*\* pass/**Verdict:** fail/' "$TMP/openspec/changes/d-suppress/code-review.md"
run d-suppress; rc=$?
check "upstream code-review failure present (doneness-verdict-enforcement)" 1 $rc
grep -q 'GATE-FAIL code-review' "$TMP/err" && ok "code-review fail emitted" || nok "code-review fail emitted"
grep -q 'GATE-FAIL doneness' "$TMP/err" && nok "doneness suppressed while another check red" || ok "doneness suppressed while another check red"

echo "----"
echo "passed=$pass failed=$failc"
[ "$failc" -eq 0 ]
