#!/usr/bin/env bash
# Hermetic tests for opsx-gate.
# Cites acceptance criteria by canonical ID so the verify gate's forward
# AC<->test mapping (check 5) finds literal matches:
#   opsx-gate-enforcement.gate-exit-code-contract
#   opsx-gate-enforcement.required-artifact-by-scale
#   opsx-gate-enforcement.cheap-before-expensive-ordering
#   opsx-gate-enforcement.manifest-validation-execution
#   opsx-gate-enforcement.mode-aware-verdict-reading
#   opsx-gate-enforcement.verdict-freshness-and-provenance
set -uo pipefail

GATE="$(cd "$(dirname "$0")/../.." && pwd)/dot_local/bin/executable_opsx-gate"
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
export OPSX_ROOT="$TMP"

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

run() { "$GATE" "$@" 2>"$TMP/err"; }

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

echo "----"
echo "passed=$pass failed=$failc"
[ "$failc" -eq 0 ]
