#!/usr/bin/env bash
# Shared helpers for opsx-loop TUI scenarios.
# AC: opsx-loop.scenario-harness-is-isolated-and-signal-driven

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUITE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_DIR="$(cd "$SUITE_DIR/../.." && pwd)"
FIXTURE_DIR="$SUITE_DIR/fixtures"
OUT_DIR="$SUITE_DIR/.test-output"
mkdir -p "$OUT_DIR"

: "${SCN_TMUX_SOCKET:=opsx-tui-$$}"
TMUX_CMD=(tmux -L "$SCN_TMUX_SOCKET")

SCN_FAILED=0
SESSION=""
TMP_DIR=""
SCENARIO_CWD=""
FAKE_LOG_DIR=""
PANE_LOG=""
PROVIDER_LOG=""
SERVER_PID=""

scn_setup() {
  local name="$1"
  export SCENARIO_NAME="$name"
  SESSION="opsx-tui-${name}-$$"
  TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/opsx-tui-${name}.XXXXXX")"
  SCENARIO_CWD="$TMP_DIR/repo"
  FAKE_LOG_DIR="$TMP_DIR/logs"
  PANE_LOG="$OUT_DIR/${name}.pane.log"
  PROVIDER_LOG="$OUT_DIR/${name}.provider.log"
  mkdir -p "$SCENARIO_CWD/openspec/changes" "$TMP_DIR/bin" "$FAKE_LOG_DIR"
  rm -f "$PANE_LOG" "$PROVIDER_LOG"
  git -C "$SCENARIO_CWD" init -q
  git -C "$SCENARIO_CWD" config user.email opsx-tui@example.invalid
  git -C "$SCENARIO_CWD" config user.name "opsx TUI Test"
  echo '# temp repo' > "$SCENARIO_CWD/README.md"
  git -C "$SCENARIO_CWD" add README.md
  git -C "$SCENARIO_CWD" commit -q -m init
  cp "$FIXTURE_DIR/fake-opsx.sh" "$TMP_DIR/bin/opsx"
  chmod +x "$TMP_DIR/bin/opsx"
}

scn_cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then kill "$SERVER_PID" 2>/dev/null || true; fi
  "${TMUX_CMD[@]}" kill-server 2>/dev/null || true
  if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" && "${KEEP_OPSX_TUI_TMP:-0}" != "1" ]]; then
    rm -rf "$TMP_DIR"
  fi
}
trap scn_cleanup EXIT

scn_start_fake_provider() {
  local ready="$TMP_DIR/provider.port"
  rm -f "$ready"
  node "$FIXTURE_DIR/fake-openai-server.mjs" "$ready" "$PROVIDER_LOG" &
  SERVER_PID=$!
  local deadline=$((SECONDS + 15))
  while (( SECONDS < deadline )); do
    [[ -s "$ready" ]] && break
    sleep 0.1
  done
  [[ -s "$ready" ]] || { echo "fake provider did not start" >&2; return 1; }
  export OPSX_TUI_FAKE_BASE_URL="http://127.0.0.1:$(cat "$ready")/v1"
}

scn_pi_start() {
  scn_start_fake_provider
  local pi_cmd
  printf -v pi_cmd '%q ' \
    env \
    "PATH=$TMP_DIR/bin:$PATH" \
    "FAKE_OPSX_LOG_DIR=$FAKE_LOG_DIR" \
    "FAKE_OPSX_GATE_MODE=${FAKE_OPSX_GATE_MODE:-red}" \
    "FAKE_OPSX_GATE_SEQUENCE=${FAKE_OPSX_GATE_SEQUENCE:-1,0}" \
    "FAKE_OPSX_WORKTREE_PATH=$SCENARIO_CWD" \
    "OPSX_TUI_FAKE_BASE_URL=$OPSX_TUI_FAKE_BASE_URL" \
    pi --no-session -ne \
    -e "$REPO_DIR/dot_pi/agent/extensions/opsx-loop" \
    -e "$FIXTURE_DIR/fake-provider.ts" \
    --provider opsx-tui-fake --model smoke

  "${TMUX_CMD[@]}" new-session -d -s "$SESSION" -x 180 -y 45 "cd '$SCENARIO_CWD' && $pi_cmd"
  scn_wait_for "opsx-tui-fake|smoke|Type|/help" 40
  sleep 0.3
}

scn_send() {
  # Clear any stale editor text before sending. Without this, consecutive slash
  # commands can append to the previous editor buffer and become e.g.
  # `/opsx-loop status/opsx-loop clear`.
  "${TMUX_CMD[@]}" send-keys -t "$SESSION:0" C-u
  "${TMUX_CMD[@]}" send-keys -t "$SESSION:0" -l -- "$1"
  sleep 0.1
  "${TMUX_CMD[@]}" send-keys -t "$SESSION:0" Enter
  # Exact argument-completion entries consume the first Enter as selection.
  # Send one more Enter for these known exact-keyword commands to submit them.
  case "$1" in
    "/opsx-loop status"|"/opsx-loop clear"|"/opsx-loop models")
      sleep 0.1
      "${TMUX_CMD[@]}" send-keys -t "$SESSION:0" Enter
      ;;
  esac
}

scn_send_key() {
  "${TMUX_CMD[@]}" send-keys -t "$SESSION:0" "$@"
}

scn_capture() {
  "${TMUX_CMD[@]}" capture-pane -t "$SESSION:0" -p -S -2000 > "$PANE_LOG" 2>/dev/null || true
  cat "$PANE_LOG"
}

scn_wait_for() {
  local pat="$1"
  local timeout="${2:-30}"
  local start=$SECONDS
  while (( SECONDS - start < timeout )); do
    scn_capture >/dev/null || true
    if grep -qE "$pat" "$PANE_LOG" 2>/dev/null; then return 0; fi
    sleep 0.25
  done
  echo "TIMEOUT waiting for pane regex: $pat" >&2
  scn_capture >&2 || true
  return 1
}

scn_wait_log_count() {
  local file="$1"
  local pat="$2"
  local want="$3"
  local timeout="${4:-30}"
  local start=$SECONDS
  while (( SECONDS - start < timeout )); do
    local got=0
    [[ -f "$file" ]] && got=$(grep -cE "$pat" "$file" 2>/dev/null || true)
    if (( got >= want )); then return 0; fi
    sleep 0.25
  done
  echo "TIMEOUT waiting for $want matches of $pat in $file" >&2
  [[ -f "$file" ]] && cat "$file" >&2 || true
  return 1
}

scn_assert_pane() {
  local pat="$1"
  local msg="$2"
  if scn_wait_for "$pat" "${3:-20}"; then
    echo "PASS: $msg"
  else
    echo "FAIL: $msg" >&2
    SCN_FAILED=1
  fi
}

scn_assert_file() {
  local file="$1"
  local pat="$2"
  local msg="$3"
  if grep -qE "$pat" "$file" 2>/dev/null; then
    echo "PASS: $msg"
  else
    echo "FAIL: $msg" >&2
    [[ -f "$file" ]] && cat "$file" >&2 || true
    SCN_FAILED=1
  fi
}

scn_make_change() {
  local change="$1"
  mkdir -p "$SCENARIO_CWD/openspec/changes/$change"
  cat > "$SCENARIO_CWD/openspec/changes/$change/review.md" <<EOF_REVIEW
---
scale: M
loop_max_iterations: 5
---
# Review

**Diff Base SHA:** $(git -C "$SCENARIO_CWD" rev-parse HEAD)
**Worktree Path:** $SCENARIO_CWD
**Integration Branch:** main
EOF_REVIEW
  cat > "$SCENARIO_CWD/openspec/changes/$change/intent.md" <<EOF_INTENT
# Intent — $change
Status: explore-frozen
EOF_INTENT
  git -C "$SCENARIO_CWD" add "openspec/changes/$change"
  git -C "$SCENARIO_CWD" commit -q -m "add $change"
}

scn_finish() {
  scn_capture > "$PANE_LOG" || true
  exit "$SCN_FAILED"
}
