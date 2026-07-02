#!/usr/bin/env bash
# Hermetic tests for the unified `opsx` multitool: dispatch + model write surface.
# Cites acceptance criteria by canonical ID for the verify gate's AC<->test map:
#   opsx-cli.unified-subcommand-dispatch
#   opsx-cli.model-config-write-surface
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

# set review replaces list with a warning
printf 'review:\n  - a/m1\n  - b/m2\n' > "$OPSX_MODELS_USER_CONFIG"
warn="$("$OPSX" models set review c/m3 2>&1 >/dev/null)"
[ "$(yq -r '.review' "$OPSX_MODELS_USER_CONFIG")" = "c/m3" ] && printf '%s' "$warn" | grep -qi 'replac' \
  && ok "set review replaces list and warns" || nok "set review warn"

# project layer via OPSX_ROOT; reject when no root
PROOT="$TMP/proj"; mkdir -p "$PROOT/openspec"
OPSX_ROOT="$PROOT" "$OPSX" models set impl x/y --layer project >/dev/null 2>&1
[ "$(yq -r '.impl' "$PROOT/openspec/opsx-models.yaml")" = "x/y" ] \
  && ok "project layer targets openspec/opsx-models.yaml" || nok "project layer write"
NOROOT="$(mktemp -d)"; ( cd "$NOROOT"; OPSX_ROOT="" "$OPSX" models set impl x --layer project >/dev/null 2>&1 ); [ $? -ne 0 ] \
  && ok "project layer with no root rejected" || nok "project no-root"; rm -rf "$NOROOT"

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

echo "opsx-cli: $pass passed, $failc failed"
[ "$failc" -eq 0 ]
