#!/usr/bin/env bash
# Hermetic tests for opsx-models.
# Cites acceptance criteria by canonical ID so the verify gate's forward
# AC<->test mapping (check 5) finds literal matches:
#   opsx-model-config.role-model-resolver
#   opsx-model-config.layered-resolution-order
#   opsx-model-config.config-conventions
set -uo pipefail

BIN="$(cd "$(dirname "$0")/../.." && pwd)/dot_local/bin/executable_opsx-models"
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
run() { ( cd "$ROOT"; "$BIN" "$@" ); }

# --- opsx-model-config.role-model-resolver: unset -> empty -------------------
clear_env; : >"$ROOT/openspec/opsx-models.yaml"
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

# --- config-conventions + provider verbatim/qualify -------------------------
clear_env
cat >"$ROOT/openspec/opsx-models.yaml" <<EOF
author: claude-bridge/claude-opus-4-8
impl: claude-haiku-4-5
impl_provider: claude-bridge
review:
  - claude-bridge/claude-opus-4-8
  - openai-codex/gpt-5.5
provider: claude-bridge
EOF
eq "config-conventions: project value (slash) verbatim" "claude-bridge/claude-opus-4-8" "$(run author)"
eq "role-model-resolver: bare id qualified by role provider" "claude-bridge/claude-haiku-4-5" "$(run impl)"
eq "role-model-resolver: review list newline-delimited" "claude-bridge/claude-opus-4-8
openai-codex/gpt-5.5" "$(run review)"
eq "layered-resolution-order: --json source=project" '{"value":"claude-bridge/claude-opus-4-8","source":"project"}' "$(run author --json)"

# --- default provider applies only to a bare id -----------------------------
clear_env
cat >"$ROOT/openspec/opsx-models.yaml" <<EOF
provider: claude-bridge
author: claude-opus-4-8
impl: openrouter/openai/gpt-5.5
EOF
eq "layered-resolution-order: default provider qualifies bare id" "claude-bridge/claude-opus-4-8" "$(run author)"
eq "role-model-resolver: multi-segment value verbatim" "openrouter/openai/gpt-5.5" "$(run impl)"

# --- explicit provider in value overrides configured provider ---------------
clear_env
cat >"$ROOT/openspec/opsx-models.yaml" <<EOF
author_provider: openrouter
author: claude-bridge/claude-opus-4-8
EOF
eq "layered-resolution-order: slash value ignores configured provider" "claude-bridge/claude-opus-4-8" "$(run author)"

# --- front-matter beats project; highest layer replaces review list ---------
clear_env
cat >"$ROOT/openspec/opsx-models.yaml" <<EOF
author: project/author
review: [a/x, b/y, c/z]
EOF
cat >"$ROOT/openspec/changes/demo/review.md" <<EOF
---
scale: L
author_model: fm/author
review_models: [only/one]
author_in_session: false
---
# Review
EOF
eq "layered-resolution-order: front-matter overrides project (author)" "fm/author" "$(run author --change demo)"
eq "layered-resolution-order: highest layer replaces review list" "only/one" "$(run review --change demo)"
eq "layered-resolution-order: --json source=change" '{"value":"fm/author","source":"change"}' "$(run author --change demo --json)"

# --- project beats user -----------------------------------------------------
clear_env
cat >"$USERCFG" <<EOF
author: user/author
EOF
cat >"$ROOT/openspec/opsx-models.yaml" <<EOF
author: project/author
EOF
eq "layered-resolution-order: project overrides user" "project/author" "$(run author)"
: >"$ROOT/openspec/opsx-models.yaml"
eq "layered-resolution-order: user layer used when project empty" "user/author" "$(run author)"

# --- review env comma/newline delimited -------------------------------------
clear_env; : >"$ROOT/openspec/opsx-models.yaml"
eq "layered-resolution-order: OPSX_REVIEW_MODELS comma-delimited" "a/x
b/y" "$(OPSX_REVIEW_MODELS='a/x, b/y' run review)"

# --- author-in-session boolean surface --------------------------------------
clear_env; : >"$ROOT/openspec/opsx-models.yaml"; : >"$USERCFG"
eq "role-model-resolver: author-in-session default true" "true" "$(run author-in-session)"
eq "role-model-resolver: author-in-session --json default" '{"value":true,"source":"default"}' "$(run author-in-session --json)"
eq "role-model-resolver: author-in-session env false" "false" "$(OPSX_AUTHOR_IN_SESSION=false run author-in-session)"
eq "role-model-resolver: author-in-session front-matter false" '{"value":false,"source":"change"}' "$(run author-in-session --change demo --json)"

echo "-----"
echo "opsx-models: $pass passed, $failc failed"
[ "$failc" -eq 0 ]
