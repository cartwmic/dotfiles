#!/usr/bin/env bash
# Hermetic tests for opsx models.
# Cites acceptance criteria by canonical ID so the verify gate's forward
# AC<->test mapping (check 5) finds literal matches:
#   opsx-model-config.role-model-resolver
#   opsx-model-config.layered-resolution-order
#   opsx-model-config.config-conventions
#   opsx-model-config.thinking-suffix-passthrough
#   opsx-cli.interactive-models-set
#   opsx-cli.model-config-write-surface
set -uo pipefail

OPSX="$(cd "$(dirname "$0")/../.." && pwd)/dot_local/bin/executable_opsx"
pass=0; failc=0
ok()  { printf 'ok   - %s\n' "$1"; pass=$((pass+1)); }
nok() { printf 'NOT OK - %s\n' "$1"; failc=$((failc+1)); }
eq()  { # eq <desc> <expected> <actual>
	if [ "$2" = "$3" ]; then ok "$1"; else nok "$1 (want [$2] got [$3])"; fi; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
ROOT="$TMP/proj"; mkdir -p "$ROOT/openspec/changes/demo"
USERCFG="$TMP/user-models.yaml"
export OPSX_ROOT="$ROOT" OPSX_MODELS_USER_CONFIG="$USERCFG"
# Neutralize ambient env between cases.
clear_env() { unset OPSX_AUTHOR_MODEL OPSX_REVIEW_MODELS OPSX_IMPL_MODEL \
	OPSX_AUTHOR_PROVIDER OPSX_REVIEW_PROVIDER OPSX_IMPL_PROVIDER OPSX_PROVIDER OPSX_AUTHOR_IN_SESSION; }
run() { ( cd "$ROOT"; "$OPSX" models "$@" ); }

# --- opsx-model-config.role-model-resolver: unset -> empty -------------------
clear_env; rm -f "$ROOT/openspec/opsx-models.yaml"
eq "role-model-resolver: unconfigured author prints nothing" "" "$(run author)"
eq "role-model-resolver: unconfigured exit 0" "0" "$(run author >/dev/null; echo $?)"
eq "role-model-resolver: --with-default prints session sentinel" "session" "$(run author --with-default)"
eq "role-model-resolver: --json unset" '{"value":null,"source":"unset"}' "$(run author --json)"
eq "role-model-resolver: --json with-default" '{"value":"session","source":"default"}' "$(run author --json --with-default)"

# --- unknown role -----------------------------------------------------------
clear_env
eq "role-model-resolver: unknown role exits non-zero" "2" "$(run bogus 2>/dev/null; echo $?)"

# --- layered-resolution-order: env wins -------------------------------------
clear_env; OPSX_AUTHOR_MODEL="claude-bridge/claude-opus-4-8" \
	eq "layered-resolution-order: env overrides files" "claude-bridge/claude-opus-4-8" "$(OPSX_AUTHOR_MODEL=claude-bridge/claude-opus-4-8 run author)"
clear_env
eq "layered-resolution-order: empty env treated as unset" "" "$(OPSX_AUTHOR_MODEL= run author)"

# --- config-conventions + provider verbatim/qualify (user layer) ------------
clear_env; rm -f "$ROOT/openspec/opsx-models.yaml"
cat >"$USERCFG" <<EOF
author: claude-bridge/claude-opus-4-8
impl: claude-haiku-4-5
impl_provider: claude-bridge
review:
  - claude-bridge/claude-opus-4-8
  - openai-codex/gpt-5.5
provider: claude-bridge
EOF
eq "config-conventions: user value (slash) verbatim" "claude-bridge/claude-opus-4-8" "$(run author)"
eq "role-model-resolver: bare id qualified by role provider" "claude-bridge/claude-haiku-4-5" "$(run impl)"
eq "role-model-resolver: review list newline-delimited" "claude-bridge/claude-opus-4-8
openai-codex/gpt-5.5" "$(run review)"
eq "layered-resolution-order: --json source=user" '{"value":"claude-bridge/claude-opus-4-8","source":"user"}' "$(run author --json)"

# --- default provider applies only to a bare id -----------------------------
clear_env; rm -f "$ROOT/openspec/opsx-models.yaml"
cat >"$USERCFG" <<EOF
provider: claude-bridge
author: claude-opus-4-8
impl: openrouter/openai/gpt-5.5
EOF
eq "layered-resolution-order: default provider qualifies bare id" "claude-bridge/claude-opus-4-8" "$(run author)"
eq "role-model-resolver: multi-segment value verbatim" "openrouter/openai/gpt-5.5" "$(run impl)"

# --- explicit provider in value overrides configured provider ---------------
clear_env; rm -f "$ROOT/openspec/opsx-models.yaml"
cat >"$USERCFG" <<EOF
author_provider: openrouter
author: claude-bridge/claude-opus-4-8
EOF
eq "layered-resolution-order: slash value ignores configured provider" "claude-bridge/claude-opus-4-8" "$(run author)"

# --- front-matter beats user; highest layer replaces review list ------------
clear_env; rm -f "$ROOT/openspec/opsx-models.yaml"
cat >"$USERCFG" <<EOF
author: user/author
review: [a/x, b/y, c/z]
EOF
cat >"$ROOT/openspec/changes/demo/review.md" <<EOF
---
scale: M
author_model: fm/author
review_models: [only/one]
author_in_session: false
---
# Review
EOF
eq "layered-resolution-order: front-matter overrides user (author)" "fm/author" "$(run author --change demo)"
eq "layered-resolution-order: highest layer replaces review list" "only/one" "$(run review --change demo)"
eq "layered-resolution-order: --json source=change" '{"value":"fm/author","source":"change"}' "$(run author --change demo --json)"

# ============================================================================
# opsx-model-config.layered-resolution-order — PROJECT LAYER RETIRED (design D7)
# A lingering openspec/opsx-models.yaml is IGNORED in resolution, resolution
# falls through to user/default, and a one-time stderr warning is surfaced.
# ============================================================================
clear_env
cat >"$USERCFG" <<EOF
author: user/author
EOF
cat >"$ROOT/openspec/opsx-models.yaml" <<EOF
author: project/author
EOF
eq "layered-resolution-order: project yaml IGNORED, user wins" "user/author" "$(run author 2>/dev/null)"
eq "layered-resolution-order: --json source is user, never project" '{"value":"user/author","source":"user"}' "$(run author --json 2>/dev/null)"
# project yaml with NO user/default => unset (project contributes nothing)
: >"$USERCFG"
eq "layered-resolution-order: project-only role resolves unset (ignored)" '{"value":null,"source":"unset"}' "$(run author --json 2>/dev/null)"
# one-time warning: emitted exactly once per invocation, on stderr
warnlines="$(run author 2>&1 >/dev/null | grep -c 'project model layer removed')"
eq "layered-resolution-order: project-removed warning emitted exactly once" "1" "$warnlines"
# warning never contaminates stdout
eq "layered-resolution-order: warning is stderr-only (stdout clean)" "" "$(run author 2>/dev/null)"
# set --layer project is rejected with the removal message, no file written
rm -f "$ROOT/openspec/opsx-models.yaml"
setout="$( ( cd "$ROOT"; "$OPSX" models set author x/y --layer project ) 2>&1 >/dev/null )"; setrc=$?
[ "$setrc" -ne 0 ] && printf '%s' "$setout" | grep -qi 'project model layer removed' \
  && [ ! -f "$ROOT/openspec/opsx-models.yaml" ] \
  && ok "config-conventions: set --layer project rejected, no file written" \
  || nok "config-conventions: set --layer project rejected (rc=$setrc)"
# get --layer project is likewise rejected
( cd "$ROOT"; "$OPSX" models get author --layer project ) >/dev/null 2>&1; [ $? -ne 0 ] \
  && ok "config-conventions: get --layer project rejected" || nok "config-conventions: get --layer project rejected"
# --layer user still accepted (explicit spelling of the default)
cat >"$USERCFG" <<EOF
author: user/author
EOF
eq "config-conventions: --layer user still accepted" "user/author" "$(run get author --layer user 2>/dev/null)"

# --- review env comma/newline delimited -------------------------------------
clear_env; rm -f "$ROOT/openspec/opsx-models.yaml"
eq "layered-resolution-order: OPSX_REVIEW_MODELS comma-delimited" "a/x
b/y" "$(OPSX_REVIEW_MODELS='a/x, b/y' run review)"

# --- author-in-session boolean surface --------------------------------------
clear_env; rm -f "$ROOT/openspec/opsx-models.yaml"; : >"$USERCFG"
eq "role-model-resolver: author-in-session default true" "true" "$(run author-in-session)"
eq "role-model-resolver: author-in-session --json default" '{"value":true,"source":"default"}' "$(run author-in-session --json)"
eq "role-model-resolver: author-in-session env false" "false" "$(OPSX_AUTHOR_IN_SESSION=false run author-in-session)"
eq "role-model-resolver: author-in-session front-matter false" '{"value":false,"source":"change"}' "$(run author-in-session --change demo --json)"

# --- option hygiene: missing option values exit 2 immediately ----------------
# (regression: `shift 2` with one arg left never shifts -> infinite parse loop)
clear_env
eq "role-model-resolver: missing --change value exits 2 (no hang)" "2" \
	"$( ( perl -e 'alarm 5; exec @ARGV or die' "$OPSX" models author --change ) >/dev/null 2>&1; echo $? )"
eq "config-conventions: missing --layer value exits 2 (no hang)" "2" \
	"$( ( perl -e 'alarm 5; exec @ARGV or die' "$OPSX" models set author x --layer ) >/dev/null 2>&1; echo $? )"
eq "config-conventions: verb-mode missing --change value exits 2 (no hang)" "2" \
	"$( ( perl -e 'alarm 5; exec @ARGV or die' "$OPSX" models get author --change ) >/dev/null 2>&1; echo $? )"

# --- opsx-cli.model-config-write-surface: multi-review list write ------------
# opsx-cli.model-config-write-surface
clear_env; : >"$USERCFG"
( cd "$ROOT"; "$OPSX" models set review 'claude-bridge/a,openai-codex/b' ) >/dev/null 2>&1
eq "model-config-write-surface: comma-separated review → list" "claude-bridge/a
openai-codex/b" "$(run review)"
clear_env; : >"$USERCFG"
( cd "$ROOT"; "$OPSX" models set review claude-bridge/a openai-codex/b ) >/dev/null 2>&1
eq "model-config-write-surface: multi-arg review → list" "claude-bridge/a
openai-codex/b" "$(run review)"
clear_env; : >"$USERCFG"
( cd "$ROOT"; "$OPSX" models set review only/one ) >/dev/null 2>&1
eq "model-config-write-surface: single review → one-element list" "only/one" "$(run review)"
eq "model-config-write-surface: review stored as YAML seq" "!!seq" "$(yq -r '.review | type' "$USERCFG")"

# --- opsx-model-config.thinking-suffix-passthrough ---------------------------
# opsx-model-config.thinking-suffix-passthrough
clear_env; : >"$USERCFG"
( cd "$ROOT"; "$OPSX" models set impl 'cursor/composer-2.5:high' ) >/dev/null 2>&1
eq "thinking-suffix-passthrough: slash id keeps :high" "cursor/composer-2.5:high" "$(run impl)"
eq "thinking-suffix-passthrough: get --layer user keeps suffix" "cursor/composer-2.5:high" "$(run get impl --layer user)"
clear_env; : >"$USERCFG"
cat >"$USERCFG" <<EOF
provider: claude-bridge
author: claude-opus-4-8:xhigh
EOF
eq "thinking-suffix-passthrough: bare id + suffix qualifies" "claude-bridge/claude-opus-4-8:xhigh" "$(run author)"
clear_env; : >"$USERCFG"
( cd "$ROOT"; "$OPSX" models set review 'anthropic/claude-sonnet-5:high' 'cursor/composer-2.5:low' ) >/dev/null 2>&1
eq "thinking-suffix-passthrough: review list keeps per-entry suffixes" "anthropic/claude-sonnet-5:high
cursor/composer-2.5:low" "$(run review)"

# --- opsx-cli.interactive-models-set (stubbed catalog / no fzf) --------------
# opsx-cli.interactive-models-set
clear_env; : >"$USERCFG"
FAKE_PI="$(mktemp)"; chmod +x "$FAKE_PI"
cat >"$FAKE_PI" <<'PI'
#!/bin/sh
cat <<'OUT'
provider      model                                                          context  max-out  thinking  images
cursor        composer-2.5                                                   200K     16.4K    no        yes
anthropic     claude-sonnet-5                                                1M       128K     yes       yes
OUT
PI
run_interactive() {
	# Usage: run_interactive <stdin-answers> <role>
	local answers="$1" role="$2"
	printf '%s' "$answers" | env OPSX_MODELS_FORCE_INTERACTIVE=1 OPSX_MODELS_NO_FZF=1 \
		OPSX_MODELS_PI_CMD="$FAKE_PI" "$OPSX" models set "$role" >/dev/null 2>&1
}
printf '1\nhigh\n' >"$TMP/answers-impl"
( cd "$ROOT"; OPSX_MODELS_FORCE_INTERACTIVE=1 OPSX_MODELS_NO_FZF=1 OPSX_MODELS_PI_CMD="$FAKE_PI" \
	"$OPSX" models set impl <"$TMP/answers-impl" ) >/dev/null 2>&1
eq "interactive-models-set: role-only stub picks + suffix" "cursor/composer-2.5:high" "$(run impl)"
: >"$USERCFG"
printf '1 2\nskip\n' >"$TMP/answers-review"
( cd "$ROOT"; OPSX_MODELS_FORCE_INTERACTIVE=1 OPSX_MODELS_NO_FZF=1 OPSX_MODELS_PI_CMD="$FAKE_PI" \
	"$OPSX" models set review <"$TMP/answers-review" ) >/dev/null 2>&1
eq "interactive-models-set: review multi-select list" "cursor/composer-2.5
anthropic/claude-sonnet-5" "$(run review)"
: >"$USERCFG"
printf '1\nskip\n' >"$TMP/answers-miss"
( cd "$ROOT"; OPSX_MODELS_FORCE_INTERACTIVE=1 OPSX_MODELS_NO_FZF=1 OPSX_MODELS_PI_CMD=/nonexistent/pi-binary \
	"$OPSX" models set impl <"$TMP/answers-miss" ) >/dev/null 2>&1
irc=$?
eq "interactive-models-set: missing pi exits non-zero" "1" "$irc"
rm -f "$FAKE_PI"

# fzf multi path: sequential picks preserve selection order (not catalog order)
# opsx-cli.interactive-models-set
clear_env; : >"$USERCFG"
FAKE_PI="$(mktemp)"; chmod +x "$FAKE_PI"
cat >"$FAKE_PI" <<'PI'
#!/bin/sh
cat <<'OUT'
provider      model                                                          context  max-out  thinking  images
cursor        composer-2.5                                                   200K     16.4K    no        yes
anthropic     claude-sonnet-5                                                1M       128K     yes       yes
OUT
PI
FAKE_FZF="$(mktemp)"; chmod +x "$FAKE_FZF"
FZF_SEQ="$(mktemp)"
# selection order opposite catalog: sonnet first, then composer, then cancel
printf '%s\n' 'anthropic/claude-sonnet-5' 'cursor/composer-2.5' >"$FZF_SEQ"
cat >"$FAKE_FZF" <<'FZF'
#!/bin/sh
# Pop one line from OPSX_MODELS_FZF_SEQ_FILE per invocation; empty/fail ends multi loop.
seqf="${OPSX_MODELS_FZF_SEQ_FILE:-}"
[ -n "$seqf" ] && [ -f "$seqf" ] || exit 1
line="$(head -n1 "$seqf" 2>/dev/null || true)"
if [ -z "$line" ]; then exit 1; fi
tail -n +2 "$seqf" >"$seqf.tmp" && mv "$seqf.tmp" "$seqf"
printf '%s\n' "$line"
FZF
printf 'skip\n' >"$TMP/answers-fzf-order"
( cd "$ROOT"; OPSX_MODELS_FORCE_INTERACTIVE=1 OPSX_MODELS_PI_CMD="$FAKE_PI" \
	OPSX_MODELS_FZF_CMD="$FAKE_FZF" OPSX_MODELS_FZF_SEQ_FILE="$FZF_SEQ" \
	"$OPSX" models set review <"$TMP/answers-fzf-order" ) >/dev/null 2>&1
eq "interactive-models-set: fzf sequential picks keep selection order" "anthropic/claude-sonnet-5
cursor/composer-2.5" "$(run review)"
rm -f "$FAKE_PI" "$FAKE_FZF" "$FZF_SEQ"

echo "-----"
echo "opsx models: $pass passed, $failc failed"
[ "$failc" -eq 0 ]
