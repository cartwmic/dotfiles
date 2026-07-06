#!/usr/bin/env bash
# Run opsx-loop TUI scenarios.
# AC: opsx-loop.scenario-harness-is-isolated-and-signal-driven

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/.test-output"
mkdir -p "$OUT_DIR"
SUMMARY="$OUT_DIR/SUMMARY.md"
TIMEOUT_SECS="${OPSX_TUI_SCENARIO_TIMEOUT:-180}"
FILTER="${OPSX_TUI_SCENARIO_FILTER:-}"

if command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN=gtimeout
elif command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN=timeout
else
  TIMEOUT_BIN=""
fi

printf '# opsx-loop TUI scenario run — %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SUMMARY"

pass=0
fail=0
timeout_count=0

for script in "$SCRIPT_DIR"/run-scenario-s*.sh; do
  [[ -x "$script" ]] || continue
  name="$(basename "$script" .sh | sed 's/^run-scenario-//')"
  if [[ -n "$FILTER" ]] && ! echo "$name" | grep -qE "$FILTER"; then
    continue
  fi
  log="$OUT_DIR/${name}.run.log"
  socket="opsx-tui-${name}-$$"
  printf '%-28s ' "$name"
  rc=0
  if [[ -n "$TIMEOUT_BIN" ]]; then
    SCN_TMUX_SOCKET="$socket" "$TIMEOUT_BIN" --kill-after=10 "$TIMEOUT_SECS" "$script" > "$log" 2>&1 || rc=$?
  else
    SCN_TMUX_SOCKET="$socket" "$script" > "$log" 2>&1 || rc=$?
  fi
  tmux -L "$socket" kill-server 2>/dev/null || true
  if [[ "$rc" -eq 0 ]]; then
    echo PASS
    pass=$((pass + 1))
    echo "## $name — PASS" >> "$SUMMARY"
  elif [[ "$rc" -eq 124 ]]; then
    echo TIMEOUT
    timeout_count=$((timeout_count + 1))
    echo "## $name — TIMEOUT" >> "$SUMMARY"
  else
    echo FAIL
    fail=$((fail + 1))
    echo "## $name — FAIL" >> "$SUMMARY"
  fi
  if [[ "$rc" -ne 0 ]]; then
    echo '```' >> "$SUMMARY"
    tail -80 "$log" >> "$SUMMARY" || true
    echo '```' >> "$SUMMARY"
  fi
  echo >> "$SUMMARY"
done

printf '\nPassed: %s  Failed: %s  Timeout: %s\n' "$pass" "$fail" "$timeout_count"
echo "Results: $SUMMARY"
[[ $((fail + timeout_count)) -eq 0 ]]
