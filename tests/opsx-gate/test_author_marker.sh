#!/usr/bin/env bash
# Hermetic tests for opsx gate's In-Session Authoring Marker check.
# Cites acceptance criteria by canonical ID for the verify gate's forward
# AC<->test mapping (check 5):
#   opsx-gate-enforcement.in-session-authoring-marker-check
#   opsx-model-config.author-in-session-by-default
set -uo pipefail

# Hermetic: scrub inherited OPSX_* env so the env layer never shadows the
# per-test project/front-matter config the resolver is meant to read.
unset OPSX_AUTHOR_MODEL OPSX_REVIEW_MODELS OPSX_IMPL_MODEL OPSX_AUTHOR_IN_SESSION \
      OPSX_PROVIDER OPSX_AUTHOR_PROVIDER OPSX_REVIEW_PROVIDER OPSX_IMPL_PROVIDER OPSX_ROOT

ROOT_REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OPSX="$ROOT_REPO/dot_local/bin/executable_opsx"
pass=0; failc=0
ok()  { printf 'ok   - %s\n' "$1"; pass=$((pass+1)); }
nok() { printf 'NOT OK - %s\n' "$1"; failc=$((failc+1)); }

command -v jq >/dev/null 2>&1 || { echo "jq required for these tests"; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FAKEBIN="$TMP/fakebin"; mkdir -p "$FAKEBIN"
printf '#!/usr/bin/env bash\nexit 0\n' >"$FAKEBIN/openspec"; chmod +x "$FAKEBIN/openspec"

CH=demo
# Build a fresh fixture project. $1 = author yaml line(s); $2 = "marked"|"unmarked";
# $3 = optional review.md extra front-matter line (e.g. author_in_session: false)
build() {
	rm -rf "$TMP/proj"; local P="$TMP/proj"
	mkdir -p "$P/openspec/changes/$CH/specs/cap"
	( cd "$P"; git init -q; git config user.email t@t; git config user.name t )
	printf '%s\n' "$1" >"$P/openspec/opsx-models.yaml"
	{ echo '---'; echo 'scale: L'; echo 'worktree_mode: same-tree'; [ -n "${3:-}" ] && echo "$3"; echo '---'; echo '# Review'; } >"$P/openspec/changes/$CH/review.md"
	local marker=""; [ "$2" = marked ] && marker='<!-- authored: in-session -->'
	for a in proposal intent design clarify tasks plan; do
		printf '# %s\n%s\n' "$a" "$marker" >"$P/openspec/changes/$CH/$a.md"
	done
	printf '# spec\n%s\n' "$marker" >"$P/openspec/changes/$CH/specs/cap/spec.md"
	echo "$P"
}
run_gate() { # cwd=proj
	( cd "$1"; PATH="$FAKEBIN:$PATH" "$OPSX" gate "$CH" 2>&1 ) || true
}

# 1. author configured + missing marker => GATE-FAIL author-marker
P="$(build 'author: claude-bridge/claude-opus-4-8' unmarked)"
if run_gate "$P" | grep -q 'GATE-FAIL author-marker'; then ok "configured author + missing marker fails (in-session-authoring-marker-check)"; else nok "configured+missing should fail"; fi

# 2. author configured + marker present in all artifacts => no author-marker failure
P="$(build 'author: claude-bridge/claude-opus-4-8' marked)"
if run_gate "$P" | grep -q 'author-marker'; then nok "configured+marked should not fail marker"; else ok "configured author + marker present passes marker check (author-in-session-by-default)"; fi

# 3. author UNCONFIGURED => marker check skipped
P="$(build '# no roles configured' unmarked)"
if run_gate "$P" | grep -q 'author-marker'; then nok "unconfigured author should skip"; else ok "unconfigured author skips marker check (in-session-authoring-marker-check)"; fi

# 4. author configured but author_in_session=false => skipped
P="$(build 'author: claude-bridge/claude-opus-4-8' unmarked 'author_in_session: false')"
if run_gate "$P" | grep -q 'author-marker'; then nok "author_in_session:false should skip"; else ok "author_in_session false skips marker check (author-in-session-by-default)"; fi

echo "-----"
echo "author-marker: $pass passed, $failc failed"
[ "$failc" -eq 0 ]
