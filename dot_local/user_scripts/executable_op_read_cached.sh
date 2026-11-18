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
#   OP_READ_TIMEOUT_SECONDS    how long `op read` may run on a miss. Default: 5 when a stale value can be served
#                              (half of pi's 10s, so the stale value still reaches pi in time under load; the same
#                              budget as claude-compat-guard), 20 when nothing is cached (waiting is the only way
#                              to get a value, and callers other than pi have no 10s limit)
#
# A fresh cache hit is the hot path (pi runs this on every model request), so it
# runs first and does as little as it can: no `op` lookup, no token read, no
# hashing. The entry lives at $cache_dir/ref/<vault>/<item>/<field>.v (or
# .../<item>/<section>/<field>.v), a path built from the reference with shell
# expansion only, and the hit costs one `find` (the age check) and one `cat`. The
# `.v` suffix keeps a field and a section of the same name apart; the one clash
# left is a section literally named "<field>.v" next to a field "<field>".
# References with an empty, absolute or `.` segment, or any `..`, are refused. Entries
# from the older layout ($cache_dir/<sha256 of the reference>) are copied to the
# new path, with their age, on first use; the old file is kept, so rolling this
# script back still finds its cache.
#
# Exit 69 when a read would need `op` and there is no service-account token (OP_SERVICE_ACCOUNT_TOKEN, else the token
# file): `op` is not run, because without the token it would fall back to the desktop app.
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

# One line per refusal, stale serve, failed read, slow hit or kill by the caller, in $XDG_STATE_HOME/agent-harness/op-read-cached.jsonl: a time, the event and the
# reference, and for a failed read why (timeout or error) and how long `op` ran. Never a value. Best effort: a write that fails
# does not change the outcome. $3, when given, is extra JSON fields (no leading comma).
record_event() {
	state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/agent-harness"
	(umask 077 && mkdir -p "$state_dir") 2>/dev/null || return 0
	escaped_ref=$(printf '%s' "$2" | sed 's/\\/\\\\/g; s/"/\\"/g')
	printf '{"ts":"%s","event":"%s","ref":"%s",%s"script":"op_read_cached.sh"}\n' \
		"$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$escaped_ref" "${3:+$3,}" >> "$state_dir/op-read-cached.jsonl" 2>/dev/null || true
}

# Pi runs this through execSync with a hard 10 s timeout and throws away stderr, so a kill must leave its own record.
# Every phase records a SIGTERM/INT/HUP from the caller with the phase it reached and how long the script ran
# ($SECONDS: bash's counter, no subprocess on the hot path; dash has none, so the field is null there). A script the
# system never schedules (seen 2026-11-18: 35-74 s whole-Mac stalls under memory pressure) cannot record anything; the
# coordinator's load.log lag column shows those.
phase=start
on_kill() {
	record_event caller-killed "${ref:-}" "$(printf '"phase":"%s","seconds":%s' "$phase" "${SECONDS:-null}")"
	exit 143
}
trap on_kill TERM INT HUP

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

ref_path="${ref#op://}"
case "$ref_path" in
"" | /* | */ | *//* | *..* | . | ./* | */./* | */. | *"
"*)
	log "ERROR: secret reference has an empty or unsafe path: $ref"
	exit 2
	;;
esac

cache_dir="${OP_READ_CACHE_DIR:-$HOME/.cache/agent-harness/secrets}"
ttl_minutes="${OP_READ_CACHE_TTL_MINUTES:-720}"
cache_file="$cache_dir/ref/$ref_path.v"

# `find -mmin` is portable across BSD and GNU find; `stat` format flags are not.
cache_is_fresh() {
	[ -s "$cache_file" ] || return 1
	[ -n "$(find "$cache_file" -prune -mmin -"$ttl_minutes" 2>/dev/null)" ]
}

emit_cache() {
	cat "$cache_file"
}

# The hot path: a fresh hit, before anything else.
phase=hit
if [ "$refresh" = false ] && cache_is_fresh; then
	emit_cache
	# A hit normally takes milliseconds; one that took seconds is the machine stalling, and pi's 10 s limit is near.
	if [ -n "${SECONDS:-}" ] && [ "$SECONDS" -ge 3 ]; then
		record_event slow-hit "$ref" "$(printf '"seconds":%s' "$SECONDS")"
	fi
	exit 0
fi
phase=miss

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

# Portable sha256 across macOS (shasum) and Ubuntu (sha256sum). Only used to find an entry in the older layout.
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

(umask 077 && mkdir -p "${cache_file%/*}")

# Older layout: copy the entry, keeping its age, so the TTL still counts from when it was read.
if [ ! -e "$cache_file" ]; then
	legacy_file="$cache_dir/$(hash_ref "$ref")"
	if [ -s "$legacy_file" ]; then
		# Copy to a temporary name, then rename: a concurrent caller never sees a half-written file.
		if ! (umask 077 && cp -p "$legacy_file" "$cache_file.$$" && mv -f "$cache_file.$$" "$cache_file"); then
			# The copy failed (a full disk, say): read the old file where it is rather than fail.
			rm -f "$cache_file.$$"
			log "WARN: could not copy the cached value for $ref to the new layout; using the old file"
			cache_file="$legacy_file"
		fi
		if [ "$refresh" = false ] && cache_is_fresh; then
			emit_cache
			exit 0
		fi
	fi
fi


# Without a service-account token `op` would fall back to the desktop app, so never run it (playbook 78819cbd). A fresh
# cache hit above needs no `op`. A stale entry is still served, as on any other op failure, so a caller is not broken.
if [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
	if [ -s "$cache_file" ]; then
		log "WARN: 1Password service account token not set; refusing to use the desktop app (playbook 78819cbd); serving stale cached value for $ref"
		record_event stale-served "$ref"
		emit_cache
		exit 0
	fi
	log "ERROR: 1Password service account token not set; refusing to use the desktop app (playbook 78819cbd)"
	record_event refused "$ref"
	exit 69
fi

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
if [ -s "$cache_file" ]; then
	op_timeout_seconds="${OP_READ_TIMEOUT_SECONDS:-5}"
else
	op_timeout_seconds="${OP_READ_TIMEOUT_SECONDS:-20}"
fi
cmd_pid=""
watchdog_pid=""
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

op_started=$(date +%s)
op_rc=0
# The read runs in this shell (not in a $(...)), its output in a private file, so a signal from the caller interrupts
# `wait` at once. The caller may kill this script before the bound: pi's execSync sends SIGTERM at 10 s, inside the
# 20 s no-cache bound. Record that read as failed, stop `op` and the watchdog, and exit, so the log still shows it.
op_out="$cache_file.out.$$"
on_caller_kill() {
	[ -n "$cmd_pid" ] && kill -9 "$cmd_pid" 2>/dev/null || true
	[ -n "$watchdog_pid" ] && kill "$watchdog_pid" 2>/dev/null || true
	rm -f "$op_out"
	record_event op-failed "$ref" "$(printf '"reason":"caller-killed","op_exit":null,"op_seconds":%s' "$(($(date +%s) - op_started))")"
	exit 143
}
trap on_caller_kill TERM INT HUP
trap 'rm -f "$op_out"' EXIT
(umask 077 && : >"$op_out")
run_bounded op_sa read "$ref" --no-newline >"$op_out" 2>/dev/null || op_rc=$?
phase=after-op
trap on_kill TERM INT HUP
value="$(cat "$op_out")"
rm -f "$op_out"
trap - EXIT
if [ "$op_rc" -eq 0 ] && [ -n "$value" ]; then
	tmp_file="$cache_file.$$"
	trap 'rm -f "$tmp_file"' EXIT
	(umask 077 && printf '%s' "$value" >"$tmp_file")
	mv -f "$tmp_file" "$cache_file"
	trap - EXIT
	printf '%s' "$value"
	exit 0
fi

# 137 is the watchdog's kill -9. A zero exit with no output counts as an error.
case "$op_rc" in
137) op_failure=timeout ;;
*) op_failure=error ;;
esac
op_detail=$(printf '"reason":"%s","op_exit":%s,"op_seconds":%s' "$op_failure" "$op_rc" "$(($(date +%s) - op_started))")

if [ -s "$cache_file" ]; then
	log "WARN: op read failed ($op_failure) for $ref; serving stale cached value"
	record_event op-failed-stale-served "$ref" "$op_detail"
	emit_cache
	exit 0
fi

log "ERROR: op read failed ($op_failure) for $ref and no cached value is available"
record_event op-failed "$ref" "$op_detail"
exit 1
