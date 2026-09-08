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
if value="$(op read "$ref" --no-newline 2>/dev/null)" && [ -n "$value" ]; then
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
