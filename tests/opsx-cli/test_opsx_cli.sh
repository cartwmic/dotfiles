#!/usr/bin/env bash
# Hermetic tests for the unified `opsx` multitool: dispatch + model write surface.
# Cites acceptance criteria by canonical ID for the verify gate's AC<->test map:
#   opsx-cli.unified-subcommand-dispatch
#   opsx-cli.model-config-write-surface
#   opsx-loop.worktree-resolution-convention-fallback
set -uo pipefail

unset OPSX_AUTHOR_MODEL OPSX_REVIEW_MODELS OPSX_IMPL_MODEL OPSX_AUTHOR_IN_SESSION \
      OPSX_PROVIDER OPSX_AUTHOR_PROVIDER OPSX_REVIEW_PROVIDER OPSX_IMPL_PROVIDER OPSX_ROOT

OPSX="$(cd "$(dirname "$0")/../.." && pwd)/dot_local/bin/executable_opsx"
pass=0; failc=0
ok()  { printf 'ok   - %s\n' "$1"; pass=$((pass+1)); }
nok() { printf 'NOT OK - %s\n' "$1"; failc=$((failc+1)); }
command -v jq >/dev/null 2>&1 || { echo "jq required"; exit 1; }
command -v yq >/dev/null 2>&1 || { echo "yq required"; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export OPSX_MODELS_USER_CONFIG="$TMP/user.yaml"

# ---- opsx-cli.unified-subcommand-dispatch ----
"$OPSX" >/dev/null 2>&1; [ $? -eq 2 ] && ok "missing subcommand exits non-zero" || nok "missing subcommand"
"$OPSX" bogus >/dev/null 2>&1; [ $? -eq 2 ] && ok "unknown subcommand exits non-zero" || nok "unknown subcommand"
"$OPSX" --help >/dev/null 2>&1; [ $? -eq 0 ] && ok "help exits 0" || nok "help"
# exit-code passthrough: `models <bad>` exits 2 through the dispatcher
"$OPSX" models 2>/dev/null; [ $? -eq 2 ] && ok "models missing-arg exit propagates" || nok "exit passthrough"
# gate dispatch reaches gate (unknown change → non-zero, gate-style). Isolated dir
# so the openspec/ it creates does not pollute later project-root discovery tests.
GATEREPO="$TMP/gaterepo"; mkdir -p "$GATEREPO"
( cd "$GATEREPO"; git init -q . 2>/dev/null; mkdir -p openspec/changes; "$OPSX" gate nope >/dev/null 2>&1 ); \
  [ $? -ne 0 ] && ok "gate subcommand dispatches" || nok "gate dispatch"

# ---- opsx-cli.model-config-write-surface ----
rm -f "$OPSX_MODELS_USER_CONFIG"
"$OPSX" models set author claude-bridge/claude-opus-4-8 >/dev/null 2>&1
[ "$("$OPSX" models get author --layer user)" = "claude-bridge/claude-opus-4-8" ] \
  && ok "set author -> user layer (create-if-absent)" || nok "set author user"
[ -f "$OPSX_MODELS_USER_CONFIG" ] && ok "set creates the target file" || nok "create file"

# comment + key-order preservation
printf '# header comment\nauthor: old\nimpl: keep  # inline\n' > "$OPSX_MODELS_USER_CONFIG"
"$OPSX" models set author NEW >/dev/null 2>&1
grep -q '# header comment' "$OPSX_MODELS_USER_CONFIG" && grep -q 'inline' "$OPSX_MODELS_USER_CONFIG" \
  && [ "$("$OPSX" models get author --layer user)" = "NEW" ] && [ "$("$OPSX" models get impl --layer user)" = "keep" ] \
  && ok "write preserves comments + other keys" || nok "comment preservation"

# author-in-session boolean coercion + reject
"$OPSX" models set author-in-session false >/dev/null 2>&1
[ "$(yq -r '.author_in_session' "$OPSX_MODELS_USER_CONFIG")" = "false" ] \
  && ok "author-in-session set as boolean (hyphen->underscore key)" || nok "ais boolean"
"$OPSX" models set author-in-session maybe >/dev/null 2>&1; [ $? -ne 0 ] \
  && ok "non-boolean author-in-session rejected" || nok "ais reject"

# invalid role / layer rejected without writing
cp "$OPSX_MODELS_USER_CONFIG" "$TMP/before.yaml"
"$OPSX" models set bogus x >/dev/null 2>&1; r1=$?
"$OPSX" models set author x --layer bogus >/dev/null 2>&1; r2=$?
[ $r1 -ne 0 ] && [ $r2 -ne 0 ] && diff -q "$TMP/before.yaml" "$OPSX_MODELS_USER_CONFIG" >/dev/null \
  && ok "invalid role/layer rejected, file untouched" || nok "invalid role/layer"

# set review replaces list with a warning (stores YAML seq — multi-review write)
printf 'review:\n  - a/m1\n  - b/m2\n' > "$OPSX_MODELS_USER_CONFIG"
warn="$("$OPSX" models set review c/m3 2>&1 >/dev/null)"
[ "$(yq -r '.review | type' "$OPSX_MODELS_USER_CONFIG")" = "!!seq" ] \
  && [ "$(yq -r '.review | length' "$OPSX_MODELS_USER_CONFIG")" = "1" ] \
  && [ "$(yq -r '.review[0]' "$OPSX_MODELS_USER_CONFIG")" = "c/m3" ] \
  && printf '%s' "$warn" | grep -qi 'replac' \
  && ok "set review replaces list and warns" || nok "set review warn"

# project layer RETIRED (design D7): set --layer project rejected, no file written
PROOT="$TMP/proj"; mkdir -p "$PROOT/openspec"
OPSX_ROOT="$PROOT" "$OPSX" models set impl x/y --layer project >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && [ ! -f "$PROOT/openspec/opsx-models.yaml" ] \
  && ok "set --layer project rejected, no openspec/opsx-models.yaml written" || nok "project layer rejected (rc=$rc)"

# list shows roles + sources
out="$("$OPSX" models list 2>/dev/null)"
printf '%s' "$out" | grep -q '^author:' && printf '%s' "$out" | grep -q '^author-in-session:' \
  && ok "list reports roles incl author-in-session" || nok "list"

# failed write (forced yq failure via a PATH stub) leaves the target intact / absent
FAKE="$TMP/fakebin"; mkdir -p "$FAKE"
printf '#!/usr/bin/env bash\nexit 3\n' > "$FAKE/yq"; chmod +x "$FAKE/yq"
UDIR="$(dirname "$OPSX_MODELS_USER_CONFIG")"
printf 'author: keepme\n' > "$OPSX_MODELS_USER_CONFIG"
cp "$OPSX_MODELS_USER_CONFIG" "$TMP/orig.yaml"
PATH="$FAKE:$PATH" "$OPSX" models set author NEW >/dev/null 2>&1; rc=$?
left=$(ls "$UDIR"/.opsx-cfg.* 2>/dev/null | wc -l | tr -d ' ')
[ $rc -ne 0 ] && diff -q "$TMP/orig.yaml" "$OPSX_MODELS_USER_CONFIG" >/dev/null && [ "$left" = "0" ] \
  && ok "failed write leaves existing target unchanged, no temp left" || nok "atomic existing"
ABSENT="$TMP/absent-dir/models.yaml"
OPSX_MODELS_USER_CONFIG="$ABSENT" PATH="$FAKE:$PATH" "$OPSX" models set author NEW >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && [ ! -f "$ABSENT" ] && ok "failed write to absent target creates no file" || nok "atomic absent"

# ---- opsx-cli.worktree-lifecycle-commands ----
# Runtime-owned lifecycle: create / reuse-with-base-check / halt / clean.
WTREPO="$TMP/wtrepo/repo"; mkdir -p "$WTREPO"
git -C "$WTREPO" init -q
git -C "$WTREPO" config user.email t@t; git -C "$WTREPO" config user.name t
mkdir -p "$WTREPO/openspec/changes/demo"
printf '# Review\n' >"$WTREPO/openspec/changes/demo/review.md"
git -C "$WTREPO" add -A; git -C "$WTREPO" commit -qm seed
WBASE="$(git -C "$WTREPO" rev-parse HEAD)"

out="$(cd "$WTREPO" && "$OPSX" worktree ensure demo 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q '^WORKTREE-OK created' \
  && ok "worktree ensure creates branch+worktree, prints locator" || nok "worktree ensure create (rc=$rc)"
printf '%s' "$out" | grep -q "Diff Base SHA: $WBASE" \
  && ok "worktree ensure records merge-base as Diff Base SHA" || nok "worktree ensure base"

# Reuse without a recorded base in review.md: HALT (exit 1)
( cd "$WTREPO" && "$OPSX" worktree ensure demo ) >/dev/null 2>&1; rc=$?
[ $rc -eq 1 ] && ok "reuse without recorded Diff Base SHA halts for human repair" || nok "reuse halt (rc=$rc)"

# Record the base -> reuse succeeds and preserves it
printf '\n**Diff Base SHA:** %s\n' "$WBASE" >>"$WTREPO/openspec/changes/demo/review.md"
out="$(cd "$WTREPO" && "$OPSX" worktree ensure demo 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q '^WORKTREE-OK reused' \
  && printf '%s' "$out" | grep -q "Diff Base SHA: $WBASE" \
  && ok "reuse preserves the recorded immutable base" || nok "reuse preserve (rc=$rc)"

# Creation failure aborts: path conflict (file where the worktree would go)
mkdir -p "$WTREPO/openspec/changes/demo2"; printf '# Review\n' >"$WTREPO/openspec/changes/demo2/review.md"
git -C "$WTREPO" add -A; git -C "$WTREPO" commit -qm demo2
touch "$TMP/wtrepo/repo--opsx-demo2"
( cd "$WTREPO" && "$OPSX" worktree ensure demo2 ) >/dev/null 2>&1; rc=$?
[ $rc -eq 1 ] && ok "worktree creation failure aborts with exit 1" || nok "creation failure abort (rc=$rc)"
rm -f "$TMP/wtrepo/repo--opsx-demo2"

# clean: dirty worktree refused without --force; --force removes worktree+branch
touch "$TMP/wtrepo/repo--opsx-demo/dirty"
( cd "$WTREPO" && "$OPSX" clean demo ) >/dev/null 2>&1; rc=$?
[ $rc -eq 1 ] && ok "clean refuses a dirty worktree without --force" || nok "clean dirty refuse (rc=$rc)"
( cd "$WTREPO" && "$OPSX" clean demo --force ) >/dev/null 2>&1; rc=$?
[ $rc -eq 0 ] && [ ! -d "$TMP/wtrepo/repo--opsx-demo" ] \
  && ! git -C "$WTREPO" show-ref --verify --quiet refs/heads/opsx/demo \
  && ok "clean --force removes worktree and branch" || nok "clean force (rc=$rc)"
( cd "$WTREPO" && "$OPSX" clean demo ) >/dev/null 2>&1; rc=$?
[ $rc -eq 0 ] && ok "clean is idempotent (nothing to clean exits 0)" || nok "clean idempotent (rc=$rc)"

# ---- opsx-cli.read-only-worktree-path-emit ----
# Single-source convention-path derivation: read-only, no side effects.
mkdir -p "$WTREPO/openspec/changes/demo3"; printf '# Review\n' >"$WTREPO/openspec/changes/demo3/review.md"
git -C "$WTREPO" add -A; git -C "$WTREPO" commit -qm demo3
out="$(cd "$WTREPO" && "$OPSX" worktree path demo3 2>&1)"; rc=$?
case "$out" in */wtrepo/repo--opsx-demo3) [ $rc -eq 0 ] && ok "worktree path emits the convention path when nothing exists" || nok "path convention emit (rc=$rc)" ;; *) nok "path convention emit (rc=$rc out=$out)" ;; esac
[ ! -e "$TMP/wtrepo/repo--opsx-demo3" ] \
  && ! git -C "$WTREPO" show-ref --verify --quiet refs/heads/opsx/demo3 \
  && ok "worktree path is read-only (no branch, no worktree, no file created)" || nok "path no side effects"
# Convention-ONLY emit: even after ensure with a --path override, path still
# prints the convention derivation — override worktrees are covered by the
# committed locator, NOT the fallback (by design).
( cd "$WTREPO" && "$OPSX" worktree ensure demo3 --path "$TMP/wtrepo/custom-demo3" ) >/dev/null 2>&1
out="$(cd "$WTREPO" && "$OPSX" worktree path demo3 2>&1)"; rc=$?
case "$out" in */wtrepo/repo--opsx-demo3) [ $rc -eq 0 ] && ok "worktree path stays convention-only despite a --path override worktree" || nok "path convention-only emit (rc=$rc)" ;; *) nok "path convention-only emit (rc=$rc out=$out)" ;; esac
# Main-root normalization: the emit is IDENTICAL from inside a linked worktree
out="$(cd "$TMP/wtrepo/custom-demo3" && "$OPSX" worktree path demo3 2>&1)"; rc=$?
case "$out" in */wtrepo/repo--opsx-demo3) [ $rc -eq 0 ] && ok "worktree path derivation identical from inside a linked worktree" || nok "path from-worktree emit (rc=$rc)" ;; *) nok "path from-worktree emit (rc=$rc out=$out)" ;; esac
( cd "$WTREPO" && "$OPSX" worktree path nope ) >/dev/null 2>&1; rc=$?
[ $rc -eq 1 ] && ok "worktree path unknown change exits 1" || nok "path unknown change (rc=$rc)"
( cd "$WTREPO" && "$OPSX" worktree path demo3 --path x ) >/dev/null 2>&1; rc=$?
[ $rc -eq 2 ] && ok "worktree path rejects options" || nok "path rejects options (rc=$rc)"

# ---- opsx-cli.status-fleet-view ----
# Read-only, model-free fleet view: one block per non-archive change, placeholders
# for a review.md-less change, exit 0 even with a red fleet, and NO side effects.
SREPO="$TMP/srepo"; mkdir -p "$SREPO"
git -C "$SREPO" init -q; git -C "$SREPO" config user.email t@t; git -C "$SREPO" config user.name t
mkdir -p "$SREPO/openspec/changes/alpha" "$SREPO/openspec/changes/beta" "$SREPO/openspec/changes/archive/old"
cat >"$SREPO/openspec/changes/alpha/review.md" <<EOF
---
scale: M
full_rigor: true
loop_hold: true
loop_hold_reason: "audit pending"
---
# Review
EOF
echo "# proposal" >"$SREPO/openspec/changes/beta/proposal.md"   # beta has NO review.md
echo "# archived" >"$SREPO/openspec/changes/archive/old/review.md"
printf seed >"$SREPO/seed"; git -C "$SREPO" add -A; git -C "$SREPO" commit -qm seed
git -C "$SREPO" branch -m main 2>/dev/null || true

before="$(cd "$SREPO" && { git status --porcelain; git branch; git worktree list; find openspec -type f | sort; })"
out="$(cd "$SREPO" && "$OPSX" status 2>/dev/null)"; rc=$?
[ $rc -eq 0 ] && ok "status exits 0 with a red fleet (view, not a gate)" || nok "status exit 0 (rc=$rc)"
printf '%s' "$out" | grep -q '^alpha$' && printf '%s' "$out" | grep -q '^beta$' \
  && ok "status prints a block per non-archive change" || nok "status per-change block"
printf '%s\n' "$out" | grep -q '^old$' && nok "status leaked an archived change" || ok "status excludes archive/"
printf '%s' "$out" | grep -q 'Scale: M +full_rigor' && ok "status shows Scale + full_rigor marker" || nok "status full_rigor marker"
printf '%s' "$out" | grep -q 'held — audit pending' && ok "status shows loop_hold + reason" || nok "status loop_hold reason"
printf '%s' "$out" | grep -q 'gate(cheap):' && ok "status labels the gate summary gate(cheap)" || nok "status gate(cheap) label"
betablock="$(printf '%s\n' "$out" | awk '/^beta$/{f=1;next} /^[^ ]/{f=0} f')"
printf '%s' "$betablock" | grep -q 'Scale: —' && ok "status placeholder Scale for a review.md-less change" || nok "status placeholder Scale"
printf '%s' "$betablock" | grep -q 'worktree: none' && ok "status placeholder worktree when no branch" || nok "status placeholder worktree"
after="$(cd "$SREPO" && { git status --porcelain; git branch; git worktree list; find openspec -type f | sort; })"
[ "$before" = "$after" ] && ok "status is read-only (no new files/branches/worktrees)" || nok "status read-only"

# ---- opsx-cli.archive-check (opsx-gate-enforcement.land-base-currency + ADR-dup + multi-dir advisory) ----
ACREPO="$TMP/acrepo"; mkdir -p "$ACREPO/openspec/changes/feat"
git -C "$ACREPO" init -q; git -C "$ACREPO" config user.email t@t; git -C "$ACREPO" config user.name t
printf '# Review\n' >"$ACREPO/openspec/changes/feat/review.md"
printf seed >"$ACREPO/seed"; git -C "$ACREPO" add -A; git -C "$ACREPO" commit -qm seed
git -C "$ACREPO" branch -m main 2>/dev/null || true

# branch-absent => worktree-mandatory model REFUSES (no same-tree exemption): the
# base-currency check fails loudly naming the `opsx worktree ensure` remedy.
out="$(cd "$ACREPO" && "$OPSX" archive-check feat 2>&1)"; rc=$?
[ $rc -ne 0 ] && printf '%s' "$out" | grep -q 'no opsx/feat branch' \
  && printf '%s' "$out" | grep -q 'opsx worktree ensure feat' \
  && ok "branchless archive-check REFUSES naming the ensure remedy (worktree-mandatory)" || nok "archive-check branchless refuse (rc=$rc)"

# opsx/feat forked at current main => base currency passes
git -C "$ACREPO" worktree add -q -b opsx/feat "$TMP/acwt-feat" main >/dev/null 2>&1
out="$(cd "$ACREPO" && "$OPSX" archive-check feat 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q 'base-currency OK' \
  && ok "archive-check current base permits landing" || nok "archive-check current base (rc=$rc)"

# advance main after the fork => stale base refuses + names the rebase remedy
printf x >"$ACREPO/newfile"; git -C "$ACREPO" add newfile; git -C "$ACREPO" commit -qm "advance main"
out="$(cd "$ACREPO" && "$OPSX" archive-check feat 2>&1)"; rc=$?
[ $rc -ne 0 ] && printf '%s' "$out" | grep -qi 'rebase' \
  && ok "archive-check stale base refuses + names rebase remedy" || nok "archive-check stale base (rc=$rc)"

# ADR-dup: two files claim ADR-0007 => fail naming BOTH paths (branch absent => base exempt)
ADREPO="$TMP/adrepo"; mkdir -p "$ADREPO/openspec/changes/c1" "$ADREPO/adr"
git -C "$ADREPO" init -q; git -C "$ADREPO" config user.email t@t; git -C "$ADREPO" config user.name t
printf '# Review\n' >"$ADREPO/openspec/changes/c1/review.md"
printf '# a\n' >"$ADREPO/adr/ADR-0007-first.md"; printf '# b\n' >"$ADREPO/adr/ADR-0007-second.md"
git -C "$ADREPO" add -A; git -C "$ADREPO" commit -qm seed; git -C "$ADREPO" branch -m main 2>/dev/null || true
out="$(cd "$ADREPO" && "$OPSX" archive-check c1 2>&1)"; rc=$?
[ $rc -ne 0 ] && printf '%s' "$out" | grep -q 'ADR-0007-first.md' && printf '%s' "$out" | grep -q 'ADR-0007-second.md' \
  && ok "archive-check ADR-dup fails naming both offending paths" || nok "archive-check ADR-dup (rc=$rc)"

# multi-dir advisory: a commit touching TWO change dirs is flagged, exit UNAFFECTED
MDREPO="$TMP/mdrepo"; mkdir -p "$MDREPO/openspec/changes/x" "$MDREPO/openspec/changes/y"
git -C "$MDREPO" init -q; git -C "$MDREPO" config user.email t@t; git -C "$MDREPO" config user.name t
printf '# x\n' >"$MDREPO/openspec/changes/x/review.md"
git -C "$MDREPO" add -A; git -C "$MDREPO" commit -qm seed; git -C "$MDREPO" branch -m main 2>/dev/null || true
MDBASE="$(git -C "$MDREPO" rev-parse main)"
printf '\n**Diff Base SHA:** %s\n' "$MDBASE" >>"$MDREPO/openspec/changes/x/review.md"
printf '# y\n' >"$MDREPO/openspec/changes/y/review.md"   # SAME commit touches x/ and y/
git -C "$MDREPO" add -A; git -C "$MDREPO" commit -qm "cross-dir commit"
# worktree-mandatory: opsx/x must exist + be base-current for a clean exit; fork it
# at the current main HEAD so base-currency passes and the advisory alone drives output.
git -C "$MDREPO" worktree add -q -b opsx/x "$TMP/mdwt" main >/dev/null 2>&1
out="$(cd "$MDREPO" && "$OPSX" archive-check x 2>&1)"; rc=$?
printf '%s' "$out" | grep -qi 'advisory' && ok "archive-check flags a multi-dir commit (advisory)" || nok "archive-check multi-dir advisory flag"
[ $rc -eq 0 ] && ok "archive-check multi-dir advisory does NOT affect the exit code" || nok "archive-check advisory exit unaffected (rc=$rc)"

# multi-dir advisory INCLUDES MERGE COMMITS: an "evil merge" whose net effect on
# main touches TWO change dirs must be flagged
# (opsx-cli.multi-dir-integration-commit-detector: ANY integration-checkout
# commit; R1 review SIMPAR-R1-001)
EMREPO="$TMP/emrepo"; mkdir -p "$EMREPO/openspec/changes/x"
git -C "$EMREPO" init -q; git -C "$EMREPO" config user.email t@t; git -C "$EMREPO" config user.name t
printf '# x\n' >"$EMREPO/openspec/changes/x/review.md"
git -C "$EMREPO" add -A; git -C "$EMREPO" commit -qm seed; git -C "$EMREPO" branch -m main 2>/dev/null || true
EMBASE="$(git -C "$EMREPO" rev-parse main)"
printf '\n**Diff Base SHA:** %s\n' "$EMBASE" >>"$EMREPO/openspec/changes/x/review.md"
git -C "$EMREPO" add -A; git -C "$EMREPO" commit -qm "pin base"
git -C "$EMREPO" checkout -qb side "$EMBASE"
printf 'side\n' >"$EMREPO/sidefile"; git -C "$EMREPO" add -A; git -C "$EMREPO" commit -qm "side work"
git -C "$EMREPO" checkout -q main
git -C "$EMREPO" merge -q --no-ff --no-commit side >/dev/null 2>&1
mkdir -p "$EMREPO/openspec/changes/y" "$EMREPO/openspec/changes/z"
printf '# y\n' >"$EMREPO/openspec/changes/y/review.md"   # evil merge: lands y/ and z/
printf '# z\n' >"$EMREPO/openspec/changes/z/review.md"
git -C "$EMREPO" add -A; git -C "$EMREPO" commit -qm "evil merge" >/dev/null
# worktree-mandatory: fork opsx/x at the current main HEAD (post evil-merge) so
# base-currency passes and the multi-dir advisory alone drives output.
git -C "$EMREPO" worktree add -q -b opsx/x "$TMP/emwt" main >/dev/null 2>&1
out="$(cd "$EMREPO" && "$OPSX" archive-check x 2>&1)"; rc=$?
printf '%s' "$out" | grep -qi 'advisory' && printf '%s' "$out" | grep -q 'openspec/changes/y' \
  && ok "archive-check flags an evil MERGE commit touching two change dirs" || nok "archive-check evil-merge advisory (rc=$rc)"
[ $rc -eq 0 ] && ok "archive-check evil-merge advisory keeps exit 0" || nok "archive-check evil-merge exit (rc=$rc)"

# ---- opsx-cli.integration-branch-resolution ----
# Deterministic resolver order: review.md **Integration Branch:** field (trimmed,
# `<detected-at-capture>` sentinel skipped) > origin/HEAD short name > local main
# > local master > loud named failure in blocking checks; opsx status degrades.

# (1) locator field wins + non-main repo (trunk) base-currency pass AND stale fail
IBREPO="$TMP/ibrepo"; mkdir -p "$IBREPO/openspec/changes/feat"
git -C "$IBREPO" init -q; git -C "$IBREPO" config user.email t@t; git -C "$IBREPO" config user.name t
printf '# Review\n\n**Integration Branch:** trunk\n' >"$IBREPO/openspec/changes/feat/review.md"
printf seed >"$IBREPO/seed"; git -C "$IBREPO" add -A; git -C "$IBREPO" commit -qm seed
git -C "$IBREPO" branch -m trunk 2>/dev/null || true
git -C "$IBREPO" worktree add -q -b opsx/feat "$TMP/ibwt-feat" trunk >/dev/null 2>&1
out="$(cd "$IBREPO" && "$OPSX" archive-check feat 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q 'merge-base(opsx/feat, trunk)' \
  && ok "resolver: locator field wins — trunk repo base-currency passes when current (integration-branch-resolution)" \
  || nok "resolver trunk current (rc=$rc)"
printf x >"$IBREPO/newfile"; git -C "$IBREPO" add newfile; git -C "$IBREPO" commit -qm "advance trunk"
out="$(cd "$IBREPO" && "$OPSX" archive-check feat 2>&1)"; rc=$?
[ $rc -ne 0 ] && printf '%s' "$out" | grep -q 'rebase opsx/feat onto trunk HEAD' \
  && ok "resolver: trunk stale base refuses naming the RESOLVED branch in the remedy" \
  || nok "resolver trunk stale (rc=$rc)"

# (2) sentinel is skipped; master-only repo falls through to master
MSREPO="$TMP/msrepo"; mkdir -p "$MSREPO/openspec/changes/feat"
git -C "$MSREPO" init -q; git -C "$MSREPO" config user.email t@t; git -C "$MSREPO" config user.name t
printf '# Review\n\n**Integration Branch:** <detected-at-capture>\n' >"$MSREPO/openspec/changes/feat/review.md"
printf seed >"$MSREPO/seed"; git -C "$MSREPO" add -A; git -C "$MSREPO" commit -qm seed
git -C "$MSREPO" branch -m master 2>/dev/null || true
git -C "$MSREPO" worktree add -q -b opsx/feat "$TMP/mswt-feat" master >/dev/null 2>&1
out="$(cd "$MSREPO" && "$OPSX" archive-check feat 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q 'merge-base(opsx/feat, master)' \
  && ok "resolver: <detected-at-capture> sentinel skipped, master-only repo resolves master" \
  || nok "resolver sentinel/master (rc=$rc)"

# (3) origin/HEAD symbolic-ref outranks local main
OHREPO="$TMP/ohrepo"; mkdir -p "$OHREPO/openspec/changes/feat"
git -C "$OHREPO" init -q; git -C "$OHREPO" config user.email t@t; git -C "$OHREPO" config user.name t
printf '# Review\n' >"$OHREPO/openspec/changes/feat/review.md"
printf seed >"$OHREPO/seed"; git -C "$OHREPO" add -A; git -C "$OHREPO" commit -qm seed
git -C "$OHREPO" branch -m main 2>/dev/null || true
git -C "$OHREPO" branch dev main
git -C "$OHREPO" update-ref refs/remotes/origin/dev "$(git -C "$OHREPO" rev-parse main)"
git -C "$OHREPO" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/dev
git -C "$OHREPO" worktree add -q -b opsx/feat "$TMP/ohwt-feat" main >/dev/null 2>&1
out="$(cd "$OHREPO" && "$OPSX" archive-check feat 2>&1)"; rc=$?
printf '%s' "$out" | grep -q 'merge-base(opsx/feat, dev)' \
  && ok "resolver: origin/HEAD short name outranks local main" \
  || nok "resolver origin/HEAD (rc=$rc out=$out)"

# (4) unresolvable branch: blocking check fails LOUD with a named error
UNREPO="$TMP/unrepo"; mkdir -p "$UNREPO/openspec/changes/feat"
git -C "$UNREPO" init -q; git -C "$UNREPO" config user.email t@t; git -C "$UNREPO" config user.name t
printf '# Review\n' >"$UNREPO/openspec/changes/feat/review.md"
printf seed >"$UNREPO/seed"; git -C "$UNREPO" add -A; git -C "$UNREPO" commit -qm seed
git -C "$UNREPO" branch -m trunk 2>/dev/null || true   # not main/master, no locator, no origin
git -C "$UNREPO" worktree add -q -b opsx/feat "$TMP/unwt-feat" trunk >/dev/null 2>&1
out="$(cd "$UNREPO" && "$OPSX" archive-check feat 2>&1)"; rc=$?
[ $rc -ne 0 ] && printf '%s' "$out" | grep -q 'integration branch unresolvable' \
  && ok "resolver: unresolvable branch fails loud in blocking archive-check" \
  || nok "resolver unresolvable loud (rc=$rc)"

# (5) opsx status: trunk staleness counted against resolved branch; unresolvable degrades
printf '\n**Diff Base SHA:** %s\n' "$(git -C "$IBREPO" rev-parse trunk~1)" >>"$IBREPO/openspec/changes/feat/review.md"
out="$(cd "$IBREPO" && "$OPSX" status 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q 'behind trunk' \
  && ok "status: staleness counted behind the RESOLVED branch (trunk), exit 0 (status-fleet-view)" \
  || nok "status behind trunk (rc=$rc)"
printf '\n**Diff Base SHA:** %s\n' "$(git -C "$UNREPO" rev-parse trunk)" >>"$UNREPO/openspec/changes/feat/review.md"
out="$(cd "$UNREPO" && "$OPSX" status 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q 'base: —' \
  && ok "status: unresolvable branch degrades to placeholder and still exits 0 (clarify C3)" \
  || nok "status unresolvable degrade (rc=$rc)"

# ---- opsx-cli.migration-completeness-sweep-command ----
SWREPO="$TMP/sweeprepo"; mkdir -p "$SWREPO"
git -C "$SWREPO" init -q
git -C "$SWREPO" config user.email t@t; git -C "$SWREPO" config user.name t
mkdir -p "$SWREPO/openspec/changes/swc" "$SWREPO/adr" "$SWREPO/lib"
printf 'RETIRED_CLI_TOKEN in shipped lib\n' > "$SWREPO/lib/mod.sh"
printf 'RETIRED_CLI_TOKEN in adr history\n' > "$SWREPO/adr/ADR-0001.md"
printf 'RETIRED_CLI_TOKEN in openspec workspace\n' > "$SWREPO/openspec/changes/swc/proposal.md"
git -C "$SWREPO" add -A; git -C "$SWREPO" commit -qm seed

# missing declaration: soft pass with notice
out="$(cd "$SWREPO" && "$OPSX" sweep swc 2>&1)"; rc=$?
[ $rc -eq 0 ] && printf '%s' "$out" | grep -q 'no sweep.txt' \
  && ok "sweep: missing declaration is a soft pass with notice" || nok "sweep missing-decl (rc=$rc)"

# usage: no change arg
( cd "$SWREPO" && "$OPSX" sweep ) >/dev/null 2>&1; [ $? -eq 2 ] \
  && ok "sweep: missing change arg exits 2" || nok "sweep usage exit"

# hit on shipped surface → SWEEP-HIT + exit 1; history surfaces excluded
printf '# retired vocabulary\nRETIRED_CLI_TOKEN\n' > "$SWREPO/openspec/changes/swc/sweep.txt"
out="$(cd "$SWREPO" && "$OPSX" sweep swc 2>&1)"; rc=$?
[ $rc -eq 1 ] && printf '%s' "$out" | grep -q 'SWEEP-HIT RETIRED_CLI_TOKEN lib/mod.sh:1' \
  && ok "sweep: shipped-surface hit → SWEEP-HIT + exit 1" || nok "sweep hit (rc=$rc)"
printf '%s' "$out" | grep -qE 'SWEEP-HIT.*(adr/|openspec/)' \
  && nok "sweep: history surfaces excluded" || ok "sweep: history surfaces excluded (adr/**, openspec/**)"

# clean after fix
printf 'cleaned\n' > "$SWREPO/lib/mod.sh"; git -C "$SWREPO" add -A; git -C "$SWREPO" commit -qm fix
( cd "$SWREPO" && "$OPSX" sweep swc ) >/dev/null 2>&1; [ $? -eq 0 ] \
  && ok "sweep: clean pass after cleanup" || nok "sweep clean pass"

# empty declaration (comments/blanks only) = clean pass
printf '# nothing declared\n\n' > "$SWREPO/openspec/changes/swc/sweep.txt"
( cd "$SWREPO" && "$OPSX" sweep swc ) >/dev/null 2>&1; [ $? -eq 0 ] \
  && ok "sweep: empty declaration is a clean pass" || nok "sweep empty decl"

# whitespace-only lines are blank (CR R1: a lone space must NOT become an ERE)
printf ' \n\t\n  # indented comment after trim\n' > "$SWREPO/openspec/changes/swc/sweep.txt"
( cd "$SWREPO" && "$OPSX" sweep swc ) >/dev/null 2>&1; [ $? -eq 0 ] \
  && ok "sweep: whitespace-only lines ignored (no false-positive flood)" || nok "sweep whitespace lines"

# malformed ERE → SWEEP-ERROR + non-zero (loud, never silent)
printf '*bad(regex\n' > "$SWREPO/openspec/changes/swc/sweep.txt"
out="$(cd "$SWREPO" && "$OPSX" sweep swc 2>&1)"; rc=$?
[ $rc -ne 0 ] && printf '%s' "$out" | grep -q 'SWEEP-ERROR' \
  && ok "sweep: malformed ERE → SWEEP-ERROR + non-zero" || nok "sweep bad regex (rc=$rc)"

# explicit --worktree validated loudly (invalid path → hard fail, no fallback)
( cd "$SWREPO" && "$OPSX" sweep swc --worktree /nonexistent ) >/dev/null 2>&1; [ $? -eq 2 ] \
  && ok "sweep: invalid explicit --worktree fails loudly" || nok "sweep --worktree loud"

# worktree resolution: fix landed only in the worktree is seen via --worktree
printf 'RETIRED_CLI_TOKEN back\n' > "$SWREPO/lib/mod.sh"
printf 'RETIRED_CLI_TOKEN\n' > "$SWREPO/openspec/changes/swc/sweep.txt"
git -C "$SWREPO" add -A; git -C "$SWREPO" commit -qm replant
SWWT="$TMP/swc-wt"
git -C "$SWREPO" worktree add -q -b opsx/swc "$SWWT" >/dev/null 2>&1
( cd "$SWWT" && printf 'cleaned\n' > lib/mod.sh && git add lib/mod.sh && git commit -qm fix )
( cd "$SWREPO" && "$OPSX" sweep swc --worktree "$SWWT" ) >/dev/null 2>&1; [ $? -eq 0 ] \
  && ok "sweep: worktree-side fix passes via --worktree (resolved checkout)" || nok "sweep worktree resolution"
( cd "$SWREPO" && "$OPSX" sweep swc ) >/dev/null 2>&1; [ $? -eq 1 ] \
  && ok "sweep: integration copy still hits without worktree resolution" || nok "sweep integration stale hit"

# ---- opsx-cli.unified-subcommand-dispatch: usage carries consolidated gate forms + sweep ----
usage_out="$("$OPSX" --help 2>&1)"
printf '%s' "$usage_out" | grep -q 'sweep    <change>' \
  && ok "usage lists sweep subcommand" || nok "usage sweep line"
g1="$(printf '%s\n' "$usage_out" | grep -n 'gate     <change> \[--worktree' | head -1 | cut -d: -f1)"
g2="$(printf '%s\n' "$usage_out" | grep -n 'gate     <change> --cheap' | head -1 | cut -d: -f1)"
[ -n "$g1" ] && [ -n "$g2" ] && [ "$g2" -eq $((g1+1)) ] \
  && ok "usage gate forms consolidated adjacent (both preserved, R3-A2)" || nok "usage gate forms adjacency (g1=$g1 g2=$g2)"

echo "opsx-cli: $pass passed, $failc failed"
[ "$failc" -eq 0 ]
