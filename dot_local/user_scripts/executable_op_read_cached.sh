#!/bin/sh
#
# op_read_cached.sh
#
# Read a 1Password secret reference, caching the value on local disk so that
# repeated reads do not hit the network.
#
# Why this exists: pi resolves a provider's `apiKey` shell command on EVERY
# model request and deliberately bypasses its own command cache
# (dist/core/provider-composer.js -> resolveConfigValueOrThrow ->
# resolveConfigValueUncached). It runs the command through execSync with a
# hard 10s timeout and discards stderr. A bare `!op read ...` therefore costs
# one 1Password round trip per request, measured at 1.0-9.5s via a service
# account and ~7.8s via desktop-app fallback. Whenever that crosses 10s pi
# fails the turn with:
#
#   API key auth failed for provider <id>: Failed to resolve API key for
#   provider "<id>" from shell command: op read 'op://...' --no-newline
#
# It also burns one of the service account's 1000 reads/hour per request, and
# exhausting that makes the failure persistent until the window resets.
#
# Usage:
#   op_read_cached.sh op://vault/item/field
#
# In ~/.pi/agent/models.json (source: dot_pi/private_agent/private_models.json.tmpl,
# or the pi-provider field of the relevant 1Password item):
#   "apiKey": "!$HOME/.local/user_scripts/op_read_cached.sh op://vault/item/field"
#
# An absolute $HOME path is used rather than relying on PATH because pi may be
# launched from contexts that do not source the interactive shell profile.
#
# Environment:
#   OP_READ_CACHE_TTL_MINUTES  cache lifetime in minutes (default 720 = 12h)
#   OP_READ_CACHE_DIR          cache location (default ~/.cache/agent-harness/secrets)
#
# Cache entries are plaintext secrets in a 0700 directory with 0600 files,
# outside any git tree. They are NOT in this repository.
#
# If `op` fails on a cache miss but a stale entry exists, the stale value is
# served rather than failing the caller. That is the whole point: a transient
# 1Password outage, a slow network, or an exhausted rate limit must not break
# an in-flight pi session. Rotate deliberately with --refresh.

set -eu

SCRIPT_NAME="op_read_cached.sh"

log() {
	printf '[%s] %s\n' "$SCRIPT_NAME" "$*" >&2
}

usage() {
	cat >&2 <<EOF
Usage: $SCRIPT_NAME [--refresh] op://vault/item/field

  --refresh   ignore any cached value and re-read from 1Password
EOF
}

refresh=false
ref=""

while [ $# -gt 0 ]; do
	case "$1" in
	--refresh)
		refresh=true
		;;
	--no-newline)
		# Accepted and ignored: output never has a trailing newline. Present so
		# an existing `op read ... --no-newline` invocation can be swapped in place.
		;;
	-h | --help)
		usage
		exit 0
		;;
	-*)
		log "ERROR: unknown option: $1"
		usage
		exit 2
		;;
	*)
		if [ -n "$ref" ]; then
			log "ERROR: only one secret reference may be given"
			exit 2
		fi
		ref="$1"
		;;
	esac
	shift
done

if [ -z "$ref" ]; then
	log "ERROR: missing secret reference"
	usage
	exit 2
fi

case "$ref" in
op://*) ;;
*)
	log "ERROR: not a 1Password secret reference: $ref"
	exit 2
	;;
esac

if ! command -v op >/dev/null 2>&1; then
	log "ERROR: 1Password CLI (op) not found on PATH"
	exit 1
fi

# Rotation-proof: the file always wins when the env var is absent. Some callers
# (e.g. loop-engine fan-out workers spawned through dagu) run with a curated
# environment that drops OP_SERVICE_ACCOUNT_TOKEN; without this fallback `op`
# falls back to desktop-app integration and pops a Touch ID unlock prompt
# whenever 1Password is locked. Same convention as apply_harness_config.sh and
# the zshrc block, which only cover shells and their children.
if [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ] && [ -r "$HOME/.config/agent-harness/op-service-token" ]; then
	OP_SERVICE_ACCOUNT_TOKEN="$(cat "$HOME/.config/agent-harness/op-service-token")"
	export OP_SERVICE_ACCOUNT_TOKEN
fi

cache_dir="${OP_READ_CACHE_DIR:-$HOME/.cache/agent-harness/secrets}"
ttl_minutes="${OP_READ_CACHE_TTL_MINUTES:-720}"

# Portable sha256 across macOS (shasum) and Ubuntu (sha256sum).
hash_ref() {
	if command -v shasum >/dev/null 2>&1; then
		printf '%s' "$1" | shasum -a 256 | cut -d' ' -f1
	elif command -v sha256sum >/dev/null 2>&1; then
		printf '%s' "$1" | sha256sum | cut -d' ' -f1
	else
		log "ERROR: neither shasum nor sha256sum available"
		exit 1
	fi
}

cache_file="$cache_dir/$(hash_ref "$ref")"

# `find -mmin` is portable across BSD and GNU find; `stat` format flags are not.
cache_is_fresh() {
	[ -s "$cache_file" ] || return 1
	[ -n "$(find "$cache_dir" -name "${cache_file##*/}" -mmin -"$ttl_minutes" 2>/dev/null)" ]
}

emit_cache() {
	cat "$cache_file"
}

if [ "$refresh" = false ] && cache_is_fresh; then
	emit_cache
	exit 0
fi

(umask 077 && mkdir -p "$cache_dir")

value=""
# Pure service-account mode. With OP_SERVICE_ACCOUNT_TOKEN set, `op` should
# never touch the 1Password desktop app, but on macOS it still discovers the app
# through $HOME (~/Library/Group Containers/...1password, ~/.config/op) and can
# block forever on desktop-app integration when the app is locked or the caller
# isn't in the GUI session (seen 2026-10-18 after a Herdr relaunch: every `op`
# call hung with no network activity, while the same token under an empty HOME
# answered instantly). Run `op` under a dedicated empty HOME so the service
# account is the only auth path. Without a token, fall back to the normal HOME.
op_sa() {
	if [ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
		sa_home="${OP_SA_HOME:-$HOME/.cache/agent-harness/op-sa-home}"
		(umask 077 && mkdir -p "$sa_home")
		HOME="$sa_home" XDG_CONFIG_HOME="$sa_home/.config" exec op "$@"
	else
		exec op "$@"
	fi
}

# Never let a wedged `op` hang the caller: kill it after a bound and fall
# through to the stale-cache path below.
op_timeout_seconds="${OP_READ_TIMEOUT_SECONDS:-20}"
run_bounded() {
	"$@" &
	cmd_pid=$!
	( sleep "$op_timeout_seconds"; kill -9 "$cmd_pid" 2>/dev/null ) >/dev/null 2>&1 &
	watchdog_pid=$!
	cmd_rc=0; wait "$cmd_pid" || cmd_rc=$?
	kill "$watchdog_pid" 2>/dev/null || true
	wait "$watchdog_pid" 2>/dev/null || true
	return "$cmd_rc"
}

if value="$(run_bounded op_sa read "$ref" --no-newline 2>/dev/null)" && [ -n "$value" ]; then
	tmp_file="$cache_file.$$"
	trap 'rm -f "$tmp_file"' EXIT
	(umask 077 && printf '%s' "$value" >"$tmp_file")
	mv -f "$tmp_file" "$cache_file"
	trap - EXIT
	printf '%s' "$value"
	exit 0
fi

if [ -s "$cache_file" ]; then
	log "WARN: op read failed for $ref; serving stale cached value"
	emit_cache
	exit 0
fi

log "ERROR: op read failed for $ref and no cached value is available"
exit 1
