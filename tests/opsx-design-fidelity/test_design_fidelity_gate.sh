#!/usr/bin/env bash
# Hermetic tests for the opsx gate DESIGN-FIDELITY verdict check.
# Cites the acceptance criterion by canonical ID so the verify gate's forward
# AC<->test mapping finds a literal match:
#   opsx-gate-enforcement.design-fidelity-verdict-enforcement
#
# The check is COMMITTED-READ (design D1): every field + digest input is read from
# the integration-checkout (main-worktree) HEAD via `git show`, never the live
# working tree. So each fixture COMMITS its design-bearing change (intent.md,
# design.md, specs/**/spec.md, design-fidelity.md) before the gate runs; an
# uncommitted edit can flip nothing in either direction. The check fires WHENEVER
# the committed change carries a non-empty design.md and is skipped entirely
# otherwise. Fixtures are Scale S (design-bearing but sub-M): design.md triggers
# fidelity without pulling in doneness / worktree-mandatory machinery, so the sole
# variable under test is the design-fidelity verdict itself.
set -uo pipefail

OPSX="$(cd "$(dirname "$0")/../.." && pwd)/dot_local/bin/executable_opsx"
pass=0; failc=0
ok()   { printf 'ok   - %s\n' "$1"; pass=$((pass+1)); }
nok()  { printf 'NOT OK - %s\n' "$1"; failc=$((failc+1)); }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else nok "$1 (want rc=$2 got rc=$3)"; fi; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FAKEBIN="$TMP/fakebin"; mkdir -p "$FAKEBIN"
# Deterministic stub: openspec validate always succeeds in fixtures.
printf '#!/usr/bin/env bash\nexit 0\n' >"$FAKEBIN/openspec"; chmod +x "$FAKEBIN/openspec"
export PATH="$FAKEBIN:$PATH"

git -C "$TMP" init -q
git -C "$TMP" config user.email t@t; git -C "$TMP" config user.name t
printf seed > "$TMP/seed"; git -C "$TMP" add seed; git -C "$TMP" commit -qm seed
export OPSX_ROOT="$TMP"
mkdir -p "$TMP/openspec"
printf '# Constitution\n' >"$TMP/openspec/constitution.md"
printf '# Domain\n' >"$TMP/openspec/domain.md"

dgst() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'; else sha256sum "$1" | awk '{print $1}'; fi; }
commit_all() { git -C "$TMP" add -A >/dev/null 2>&1; git -C "$TMP" commit -qm "${1:-c}" >/dev/null 2>&1 || true; }
gate() { "$OPSX" gate "$1" 2>"$TMP/err"; }   # NEVER commits — committed-read is the whole point

# seed_change <name> : a complete Scale-S design-bearing change (NO design-fidelity.md yet).
seed_change() {
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
  echo "# intent" >"$d/intent.md"
  echo "# design mechanism" >"$d/design.md"
  echo "# spec cap" >"$d/specs/cap/spec.md"
  printf '# tasks\n- [x] 1.1 done\n' >"$d/tasks.md"
}

# std_digests <name> : emit the standard bound-file digest block (intent, design,
# every spec) over the CURRENT working-tree content (== committed after commit_all).
std_digests() {
  local d="$TMP/openspec/changes/$1" f rel
  echo "**Digest sha256 (intent.md):** $(dgst "$d/intent.md")"
  echo "**Digest sha256 (design.md):** $(dgst "$d/design.md")"
  for f in "$d"/specs/*/spec.md; do [ -f "$f" ] || continue; rel="${f#"$d"/}"; echo "**Digest sha256 ($rel):** $(dgst "$f")"; done
}

# A valid 40-hex attestation literal (any committed sha — provenance only, never range-compared).
ATT="$(git -C "$TMP" rev-parse HEAD)"
PROV='**Judge Provenance:** claude-bridge/claude-opus-4-8; review_mode: blind-single-judge'

# ---------------------------------------------------------------------------
# 1. design-bearing change, design-fidelity.md ABSENT => GATE-FAIL design-fidelity
# ---------------------------------------------------------------------------
seed_change c1
commit_all c1
gate c1; rc=$?
check "1: design-bearing change without design-fidelity.md fails" 1 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && ok "1: reports design-fidelity absent" || nok "1: reports design-fidelity absent"

# ---------------------------------------------------------------------------
# 2. delivered + correct digests + valid provenance/attestation => check passes
# ---------------------------------------------------------------------------
seed_change c2
{
  echo '# Design Fidelity'; echo
  echo '**Fidelity:** delivered'; echo
  echo "$PROV"
  echo "**Attested HEAD:** $ATT"
  std_digests c2
} >"$TMP/openspec/changes/c2/design-fidelity.md"
commit_all c2
gate c2; rc=$?
check "2: delivered + correct digests + valid provenance passes" 0 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && nok "2: no design-fidelity fail line" || ok "2: no design-fidelity fail line"

# ---------------------------------------------------------------------------
# 3. digest mismatch (edit design.md AFTER seal, commit) => stale fail
# ---------------------------------------------------------------------------
seed_change c3
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** delivered'; echo; echo "$PROV"; echo "**Attested HEAD:** $ATT"; std_digests c3; } >"$TMP/openspec/changes/c3/design-fidelity.md"
commit_all c3-seal
echo "# design mechanism EDITED after seal" >"$TMP/openspec/changes/c3/design.md"
commit_all c3-edit
gate c3; rc=$?
check "3: post-seal design.md edit stales the digest" 1 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && grep -qi 'stale' "$TMP/err" && ok "3: reports stale digest" || nok "3: reports stale digest"

# ---------------------------------------------------------------------------
# 4. violated, no waiver => fail
# ---------------------------------------------------------------------------
seed_change c4
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** violated'; echo; echo "$PROV"; echo "**Attested HEAD:** $ATT"; std_digests c4; } >"$TMP/openspec/changes/c4/design-fidelity.md"
commit_all c4
gate c4; rc=$?
check "4: violated without a Human Waiver fails" 1 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && ok "4: reports violated-without-waiver" || nok "4: reports violated-without-waiver"

# ---------------------------------------------------------------------------
# 5. violated + non-empty Human Waiver + digests match => passes
# ---------------------------------------------------------------------------
seed_change c5
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** violated'; echo; echo "$PROV"; echo "**Attested HEAD:** $ATT"; std_digests c5; echo '**Human Waiver:** ADR-0009 decision-audit ruling waives the violated verdict'; } >"$TMP/openspec/changes/c5/design-fidelity.md"
commit_all c5
gate c5; rc=$?
check "5: violated + non-empty Human Waiver + fresh digests passes" 0 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && nok "5: waived violated does not fail" || ok "5: waived violated does not fail"

# ---------------------------------------------------------------------------
# 6. violated + whitespace-only waiver => fail (an empty field never waives)
# ---------------------------------------------------------------------------
seed_change c6
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** violated'; echo; echo "$PROV"; echo "**Attested HEAD:** $ATT"; std_digests c6; echo '**Human Waiver:**    '; } >"$TMP/openspec/changes/c6/design-fidelity.md"
commit_all c6
gate c6; rc=$?
check "6: whitespace-only Human Waiver still fails" 1 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && ok "6: reports whitespace waiver as no waiver" || nok "6: reports whitespace waiver as no waiver"

# ---------------------------------------------------------------------------
# 7. NEW delta spec committed AFTER seal (no digest line) => set-difference fail
# ---------------------------------------------------------------------------
seed_change c7
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** delivered'; echo; echo "$PROV"; echo "**Attested HEAD:** $ATT"; std_digests c7; } >"$TMP/openspec/changes/c7/design-fidelity.md"
commit_all c7-seal
mkdir -p "$TMP/openspec/changes/c7/specs/added"
echo "# added spec" >"$TMP/openspec/changes/c7/specs/added/spec.md"
commit_all c7-newspec
gate c7; rc=$?
check "7: a delta spec added after seal (no digest) fails set-equality" 1 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && grep -q 'missing digest' "$TMP/err" && ok "7: reports missing digest for the new spec" || nok "7: reports missing digest for the new spec"

# ---------------------------------------------------------------------------
# 8. recorded digest line for a REMOVED/ghost spec => set-difference fail
# ---------------------------------------------------------------------------
seed_change c8
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** delivered'; echo; echo "$PROV"; echo "**Attested HEAD:** $ATT"; std_digests c8; echo "**Digest sha256 (specs/ghost/spec.md):** $(printf '%064d' 0)"; } >"$TMP/openspec/changes/c8/design-fidelity.md"
commit_all c8
gate c8; rc=$?
check "8: a recorded digest for a ghost spec fails set-equality" 1 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && grep -q 'specs/ghost/spec.md' "$TMP/err" && ok "8: names the ghost bound-file digest" || nok "8: names the ghost bound-file digest"

# ---------------------------------------------------------------------------
# 9. provenance review_mode: degraded-single-model => fail; review_mode absent => fail
# ---------------------------------------------------------------------------
seed_change c9
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** delivered'; echo; echo '**Judge Provenance:** inline-self; review_mode: degraded-single-model'; echo "**Attested HEAD:** $ATT"; std_digests c9; } >"$TMP/openspec/changes/c9/design-fidelity.md"
commit_all c9
gate c9; rc=$?
check "9a: degraded-single-model provenance fails" 1 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && ok "9a: reports degraded provenance" || nok "9a: reports degraded provenance"

seed_change c9b
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** delivered'; echo; echo '**Judge Provenance:** claude-bridge/claude-opus-4-8 (no mode token)'; echo "**Attested HEAD:** $ATT"; std_digests c9b; } >"$TMP/openspec/changes/c9b/design-fidelity.md"
commit_all c9b
gate c9b; rc=$?
check "9b: absent review_mode provenance fails" 1 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && ok "9b: reports missing provenance mode" || nok "9b: reports missing provenance mode"

# ---------------------------------------------------------------------------
# 10. Attested HEAD short / symbolic => fail (40-hex literal required)
# ---------------------------------------------------------------------------
seed_change c10
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** delivered'; echo; echo "$PROV"; echo '**Attested HEAD:** HEAD'; std_digests c10; } >"$TMP/openspec/changes/c10/design-fidelity.md"
commit_all c10
gate c10; rc=$?
check "10a: symbolic Attested HEAD fails closed" 1 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && ok "10a: reports symbolic attestation" || nok "10a: reports symbolic attestation"

seed_change c10b
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** delivered'; echo; echo "$PROV"; echo "**Attested HEAD:** $(printf '%.12s' "$ATT")"; std_digests c10b; } >"$TMP/openspec/changes/c10b/design-fidelity.md"
commit_all c10b
gate c10b; rc=$?
check "10b: short-SHA Attested HEAD fails closed" 1 $rc

# ---------------------------------------------------------------------------
# 11. UNCOMMITTED Fidelity flip => gate reads committed value (invisible both directions)
# ---------------------------------------------------------------------------
# 11a: committed delivered (green), working-tree flipped to violated (no commit) => still passes.
seed_change c11
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** delivered'; echo; echo "$PROV"; echo "**Attested HEAD:** $ATT"; std_digests c11; } >"$TMP/openspec/changes/c11/design-fidelity.md"
commit_all c11
sed -i.bak 's/^\*\*Fidelity:\*\* delivered/**Fidelity:** violated/' "$TMP/openspec/changes/c11/design-fidelity.md" && rm -f "$TMP/openspec/changes/c11/design-fidelity.md.bak"
gate c11; rc=$?
check "11a: uncommitted delivered->violated flip is invisible (committed delivered governs)" 0 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && nok "11a: committed-read ignored the working-tree flip" || ok "11a: committed-read ignored the working-tree flip"

# 11b: committed violated (red), working-tree flipped to delivered (no commit) => still fails.
seed_change c11b
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** violated'; echo; echo "$PROV"; echo "**Attested HEAD:** $ATT"; std_digests c11b; } >"$TMP/openspec/changes/c11b/design-fidelity.md"
commit_all c11b
sed -i.bak 's/^\*\*Fidelity:\*\* violated/**Fidelity:** delivered/' "$TMP/openspec/changes/c11b/design-fidelity.md" && rm -f "$TMP/openspec/changes/c11b/design-fidelity.md.bak"
gate c11b; rc=$?
check "11b: uncommitted violated->delivered flip is invisible (committed violated governs)" 1 $rc

# ---------------------------------------------------------------------------
# 12. UNCOMMITTED review.md mode edit => committed value governs
# ---------------------------------------------------------------------------
# committed review.md is advisory (green); working-tree flip to gating-required must
# NOT take effect (would otherwise demand a code-review.md and fail).
seed_change c12
{ echo '# Design Fidelity'; echo; echo '**Fidelity:** delivered'; echo; echo "$PROV"; echo "**Attested HEAD:** $ATT"; std_digests c12; } >"$TMP/openspec/changes/c12/design-fidelity.md"
commit_all c12
sed -i.bak 's/^code_review_mode: advisory/code_review_mode: gating-required/' "$TMP/openspec/changes/c12/review.md" && rm -f "$TMP/openspec/changes/c12/review.md.bak"
gate c12; rc=$?
check "12: uncommitted review.md mode edit is invisible (committed advisory governs)" 0 $rc
grep -q 'GATE-FAIL code-review' "$TMP/err" && nok "12: committed-read ignored the working-tree mode flip" || ok "12: committed-read ignored the working-tree mode flip"

# ---------------------------------------------------------------------------
# 13. guidance order: missing design-fidelity.md AND an unchecked tasks.md =>
#     the design-fidelity failure line is emitted BEFORE the tasks failure line.
# (The ordering guarantee is between the design-fidelity check and the tasks-COMPLETE
#  check; tasks.md is present-but-unchecked so the tasks-complete failure fires — an
#  ABSENT tasks.md would instead trip the earlier required-artifact check.)
# ---------------------------------------------------------------------------
seed_change c13
printf '# tasks\n- [ ] 1.1 not done\n' >"$TMP/openspec/changes/c13/tasks.md"   # unchecked
commit_all c13
gate c13; rc=$?
check "13: design-bearing change missing design-fidelity + unchecked tasks fails" 1 $rc
df_ln="$(grep -n 'GATE-FAIL design-fidelity' "$TMP/err" | head -1 | cut -d: -f1)"
tk_ln="$(grep -n 'GATE-FAIL tasks' "$TMP/err" | head -1 | cut -d: -f1)"
if [ -n "$df_ln" ] && [ -n "$tk_ln" ] && [ "$df_ln" -lt "$tk_ln" ]; then
  ok "13: design-fidelity failure precedes the tasks failure (guidance order)"
else
  nok "13: guidance order (design-fidelity@${df_ln:-?} tasks@${tk_ln:-?})"
fi

# ---------------------------------------------------------------------------
# 14. no design.md => no design-fidelity requirement (no fail line)
# ---------------------------------------------------------------------------
seed_change c14
rm -f "$TMP/openspec/changes/c14/design.md"     # NOT design-bearing
commit_all c14
gate c14; rc=$?
check "14: a change without design.md passes with no fidelity requirement" 0 $rc
grep -q 'GATE-FAIL design-fidelity' "$TMP/err" && nok "14: fidelity wrongly demanded without design.md" || ok "14: no design-fidelity line without design.md"

echo "----"
echo "passed=$pass failed=$failc"
[ "$failc" -eq 0 ]
