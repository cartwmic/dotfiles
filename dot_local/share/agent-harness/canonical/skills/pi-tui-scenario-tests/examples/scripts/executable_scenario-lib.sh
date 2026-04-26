#!/usr/bin/env bash
# scenario-lib.sh — shared helpers for tmux-driven Pi TUI scenario validation.
# Source from any scenario script: `source "$(dirname "$0")/scenario-lib.sh"`.
#
# Conventions:
#   - tmux session name is exported as $SESSION
#   - tmux pane is always 0 (single-pane sessions)
#   - per-scenario captures + logs go to $OUT_DIR/<scenario>.{pane,bridge}.log
#
# Defaults read from environment:
#   SCENARIO_PROVIDER  default: claude-bridge
#   SCENARIO_MODEL     default: claude-bridge/claude-haiku-4-5
#   SCENARIO_CWD       default: $(pwd)
#   SCENARIO_PI_ARGS   default: ""    (extra flags to pi, e.g. "--no-session -ne")
#   SCENARIO_OUT_DIR   default: <repo>/.test-output/scenarios
#
# Completion-signal selection (for scn_send waits):
#   SCN_PROVIDER_DEBUG_LOG    if set, watch this file for SCN_COMPLETION_SIGNAL_REGEX
#   SCN_COMPLETION_SIGNAL_REGEX  default: "caching session="  (claude-bridge)
#   SCN_IDLE_REGEX            default: "esc to interrupt"     (Pi footer; absence = idle)
#                              When SCN_PROVIDER_DEBUG_LOG is unset, scn_send waits for
#                              this regex to DISAPPEAR from the pane capture.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd 2>/dev/null || echo "$PWD")"
OUT_DIR="${SCENARIO_OUT_DIR:-$REPO_DIR/.test-output/scenarios}"
mkdir -p "$OUT_DIR"

: "${SCENARIO_PROVIDER:=claude-bridge}"
: "${SCENARIO_MODEL:=claude-bridge/claude-haiku-4-5}"
: "${SCENARIO_CWD:=$(pwd)}"
: "${SCENARIO_PI_ARGS:=}"
: "${SCN_PROVIDER_DEBUG_LOG:=}"
: "${SCN_COMPLETION_SIGNAL_REGEX:=caching session=}"
: "${SCN_IDLE_REGEX:=esc to interrupt}"

# Pi's interrupt key is Escape, not Ctrl-C. (See SKILL.md for full key table.)
PI_INTERRUPT_KEY="Escape"

# ─── Setup / teardown ────────────────────────────────────────────────────────

scn_setup() {
	local name="$1"
	export SESSION="pi-scn-${name}-$$"
	export BRIDGE_LOG="$OUT_DIR/${name}.bridge.log"
	export PANE_LOG="$OUT_DIR/${name}.pane.log"
	rm -f "$BRIDGE_LOG" "$PANE_LOG"
	# Honor user-set debug log path if explicitly given.
	if [[ -n "$SCN_PROVIDER_DEBUG_LOG" ]]; then
		BRIDGE_LOG="$SCN_PROVIDER_DEBUG_LOG"
	fi
	# Default opt-in: enable claude-bridge debug logs unless caller already set them.
	if [[ "$SCENARIO_PROVIDER" == "claude-bridge" ]]; then
		export CLAUDE_BRIDGE_DEBUG="${CLAUDE_BRIDGE_DEBUG:-1}"
		export CLAUDE_BRIDGE_DEBUG_PATH="${CLAUDE_BRIDGE_DEBUG_PATH:-$BRIDGE_LOG}"
	fi
}

scn_pi_start() {
	# Start pi in a fresh tmux session. Background; returns after pi renders.
	# Caller can pass extra args; SCENARIO_PI_ARGS gives a stable per-project default.
	local extra_args="${SCENARIO_PI_ARGS}"
	if (( $# > 0 )); then extra_args="$extra_args $*"; fi

	local provider_env=""
	if [[ "$SCENARIO_PROVIDER" == "claude-bridge" ]]; then
		provider_env="CLAUDE_BRIDGE_DEBUG=1 CLAUDE_BRIDGE_DEBUG_PATH='$BRIDGE_LOG'"
	fi

	tmux new-session -d -s "$SESSION" -x 200 -y 50 \
		"cd '$SCENARIO_CWD' && $provider_env \
		 pi --provider '$SCENARIO_PROVIDER' --model '$SCENARIO_MODEL' $extra_args"
	# Give pi time to render its prompt
	sleep 3
}

scn_pi_stop() {
	tmux kill-session -t "$SESSION" 2>/dev/null || true
}

# ─── Input ───────────────────────────────────────────────────────────────────

scn_send() {
	# scn_send "<text>"
	# Sends text + Enter, then waits for the next-turn completion signal.
	# Pass --no-wait as the first arg to skip the wait (e.g. before a steer).
	#
	# Completion signal:
	#   - If SCN_PROVIDER_DEBUG_LOG is set OR claude-bridge is the provider:
	#     watch BRIDGE_LOG for new occurrences of SCN_COMPLETION_SIGNAL_REGEX.
	#   - Else: poll capture-pane until SCN_IDLE_REGEX is ABSENT (idle indicator).
	local wait_for_completion=1
	if [[ "${1:-}" == "--no-wait" ]]; then wait_for_completion=0; shift; fi

	local pre_count=0
	if [[ -f "$BRIDGE_LOG" ]]; then
		pre_count=$(scn_grep_count "$SCN_COMPLETION_SIGNAL_REGEX" "$BRIDGE_LOG")
	fi

	tmux send-keys -t "$SESSION:0" -- "$1"
	tmux send-keys -t "$SESSION:0" Enter

	(( wait_for_completion )) || return 0

	local timeout=120
	local start=$SECONDS
	# First, give pi a beat to start generating (so the idle marker is briefly present).
	sleep 0.5
	while (( SECONDS - start < timeout )); do
		# Strategy 1: provider debug log signal
		if [[ -f "$BRIDGE_LOG" ]] && [[ "$BRIDGE_LOG" != "/dev/null" ]]; then
			local cur
			cur=$(scn_grep_count "$SCN_COMPLETION_SIGNAL_REGEX" "$BRIDGE_LOG")
			if (( cur > pre_count )); then
				sleep 0.5
				return 0
			fi
		fi
		# Strategy 2: pane idle (idle-regex absent)
		tmux capture-pane -t "$SESSION:0" -p -S -200 > "$PANE_LOG" 2>/dev/null || true
		if ! grep -qE "$SCN_IDLE_REGEX" "$PANE_LOG" 2>/dev/null; then
			# Once-idle confirmation: ensure it stays idle for 1s
			sleep 1
			tmux capture-pane -t "$SESSION:0" -p -S -200 > "$PANE_LOG" 2>/dev/null || true
			if ! grep -qE "$SCN_IDLE_REGEX" "$PANE_LOG" 2>/dev/null; then
				return 0
			fi
		fi
		sleep 0.5
	done
	echo "WARN: scn_send timed out waiting for turn completion ('$1')" >&2
}

scn_send_no_enter() {
	# scn_send_no_enter "<text>"
	# Type text WITHOUT submitting. Use for pre-submit assertions
	# (extension transformations like autocorrect happen in the editor before Enter).
	tmux send-keys -t "$SESSION:0" -- "$1"
}

scn_send_keys() {
	# scn_send_keys Escape   (raw tmux key names, no Enter appended)
	tmux send-keys -t "$SESSION:0" "$@"
}

# ─── Capture ─────────────────────────────────────────────────────────────────

scn_capture() {
	# Save the entire scrollback to PANE_LOG, then stream to stdout.
	tmux capture-pane -t "$SESSION:0" -p -S -2000 > "$PANE_LOG"
	cat "$PANE_LOG"
}

scn_wait_for() {
	# scn_wait_for "regex" [timeout_seconds]
	# Polls capture-pane until regex matches OR timeout.
	local pat="$1"
	local timeout="${2:-30}"
	local start=$SECONDS
	while ((SECONDS - start < timeout)); do
		tmux capture-pane -t "$SESSION:0" -p -S -2000 > "$PANE_LOG" 2>/dev/null || true
		if grep -qE "$pat" "$PANE_LOG"; then return 0; fi
		sleep 0.5
	done
	echo "TIMEOUT waiting for: $pat" >&2
	return 1
}

scn_wait_for_absent() {
	# scn_wait_for_absent "regex" [timeout_seconds]
	# Polls capture-pane until regex is GONE from the buffer (e.g. status flash cleared).
	local pat="$1"
	local timeout="${2:-5}"
	local start=$SECONDS
	while ((SECONDS - start < timeout)); do
		tmux capture-pane -t "$SESSION:0" -p -S -200 > "$PANE_LOG" 2>/dev/null || true
		if ! grep -qE "$pat" "$PANE_LOG"; then return 0; fi
		sleep 0.2
	done
	echo "TIMEOUT waiting for absence of: $pat" >&2
	return 1
}

# ─── Assertions ──────────────────────────────────────────────────────────────

scn_pass() { echo "  PASS: $1"; }
scn_fail() { echo "  FAIL: $1"; SCN_FAILED=1; }

scn_assert_pane_contains() {
	# scn_assert_pane_contains "<regex>" "<descr>"
	tmux capture-pane -t "$SESSION:0" -p -S -2000 > "$PANE_LOG"
	if grep -qE "$1" "$PANE_LOG"; then
		scn_pass "$2"
	else
		scn_fail "$2 — pattern not in pane: $1"
	fi
}

scn_assert_pane_not_contains() {
	# scn_assert_pane_not_contains "<regex>" "<descr>"
	tmux capture-pane -t "$SESSION:0" -p -S -2000 > "$PANE_LOG"
	if grep -qE "$1" "$PANE_LOG"; then
		scn_fail "$2 — pattern unexpectedly in pane: $1"
	else
		scn_pass "$2"
	fi
}

scn_assert_file_contains() {
	# scn_assert_file_contains "<file>" "<regex>" "<descr>"
	if [[ ! -f "$1" ]]; then
		scn_fail "$3 — file does not exist: $1"
		return
	fi
	if grep -qE "$2" "$1"; then
		scn_pass "$3"
	else
		scn_fail "$3 — pattern not in file: $2 (file: $1)"
	fi
}

# Helper: count regex matches, sanitizing output to a single integer.
scn_grep_count() {
	# scn_grep_count "<regex>" "<file>"
	local n
	n=$(grep -cE "$1" "$2" 2>/dev/null | head -1 | tr -d ' \n' || echo 0)
	echo "${n:-0}"
}

# Extract the model's response text after a specific user prompt by looking at
# the pane log for the prompt line, then capturing lines that follow until
# the next visual separator or a new prompt line.
scn_probe_response() {
	# scn_probe_response "<prompt-substring>"  -> writes response text to stdout
	local prompt_marker="$1"
	tmux capture-pane -t "$SESSION:0" -p -S -3000 > "$PANE_LOG"
	awk -v pat="$prompt_marker" '
		BEGIN { capture = 0 }
		index($0, pat) > 0 { buf = ""; capture = 1; next }
		capture && /^─{20,}/ { capture = 0 }
		capture { buf = buf "\n" $0 }
		END { print buf }
	' "$PANE_LOG"
}

scn_assert_response() {
	# scn_assert_response "<prompt-substring>" "<positive-regex>" "<negative-regex>" "<descr>"
	# A response must AFFIRM (positive matches) and NOT DENY (negative absent).
	# The negative is critical: without it, "I don't recall X" passes a "X" check.
	local prompt="$1"; shift
	local positive="$1"; shift
	local negative="$1"; shift
	local descr="$1"
	local resp
	resp=$(scn_probe_response "$prompt")
	if [[ -z "$resp" ]]; then
		scn_fail "$descr — no response captured for prompt"
		return
	fi
	if echo "$resp" | grep -qiE "$negative"; then
		scn_fail "$descr — model gave a NEGATIVE response: '$(echo "$resp" | grep -iE "$negative" | head -1 | tr -d '\n' | cut -c1-120)'"
		return
	fi
	if echo "$resp" | grep -qiE "$positive"; then
		scn_pass "$descr — model affirmed: '$(echo "$resp" | grep -iE "$positive" | head -1 | tr -d '\n' | cut -c1-120)'"
		return
	fi
	scn_fail "$descr — neither positive nor negative pattern matched"
}

# ─── Bridge-specific helpers (claude-bridge debug log) ───────────────────────
# Optional. Call from scenarios that explicitly test provider/bridge behavior.
# No-op (or empty output) when SCENARIO_PROVIDER != claude-bridge.

scn_cache_profile() {
	# Print (creation, read) tuple per usage line in the bridge log.
	[[ -f "$BRIDGE_LOG" ]] || { echo "  (no bridge log)"; return; }
	grep -E "\"msg\":\"usage:" "$BRIDGE_LOG" 2>/dev/null | awk '{
		for (i = 1; i <= NF; i++) {
			if ($i ~ /^cacheRead=/)  { gsub(/^cacheRead=/,  "", $i); read = $i  }
			if ($i ~ /^cacheWrite=/) { gsub(/^cacheWrite=/, "", $i); write = $i }
		}
		printf "  creation=%s read=%s\n", write, read
	}'
}

scn_session_count() {
	# How many distinct CC session_ids did the bridge cache during this run?
	[[ -f "$BRIDGE_LOG" ]] || { echo 0; return; }
	grep -oE "caching session=[a-f0-9]+" "$BRIDGE_LOG" 2>/dev/null \
		| sort -u | wc -l | tr -d ' \n' || echo 0
}

# Each scenario script begins with `SCN_FAILED=0` and ends with
# `exit $SCN_FAILED`. scn_pass/scn_fail collect into that.
