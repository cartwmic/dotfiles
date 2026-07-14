#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop
set -euo pipefail

log_dir="${FAKE_OPSX_LOG_DIR:-}"
if [[ -n "$log_dir" ]]; then
  mkdir -p "$log_dir"
  printf '%s\tcwd=%s\tenv_FAKE_OPSX_WORKTREE_PATH=%s\tenv_OPSX_AUTHOR_MODEL=%s\tenv_OPSX_REVIEW_MODELS=%s\tenv_OPSX_IMPL_MODEL=%s\tenv_OPSX_AUTHOR_IN_SESSION=%s\targs=%q' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$(pwd)" \
    "${FAKE_OPSX_WORKTREE_PATH:-}" \
    "${OPSX_AUTHOR_MODEL:-}" \
    "${OPSX_REVIEW_MODELS:-}" \
    "${OPSX_IMPL_MODEL:-}" \
    "${OPSX_AUTHOR_IN_SESSION:-}" \
    "$0" >> "$log_dir/opsx.log"
  for arg in "$@"; do printf '\t%q' "$arg" >> "$log_dir/opsx.log"; done
  printf '\n' >> "$log_dir/opsx.log"
fi

cmd="${1:-}"
if [[ $# -gt 0 ]]; then shift; fi

case "$cmd" in
  models)
    sub="${1:-list}"
    case "$sub" in
      list)
        echo "fake-models: author=claude-bridge/claude-haiku-4-5 review=claude-bridge/claude-haiku-4-5 impl=claude-bridge/claude-haiku-4-5"
        ;;
      set)
        shift || true
        echo "fake-models-set: $*"
        ;;
      author|review|impl|author-in-session)
        role="$sub"
        json=0
        for a in "$@"; do [[ "$a" == "--json" ]] && json=1; done
        if [[ "$role" == "author-in-session" ]]; then
          [[ $json -eq 1 ]] && echo '{"value":true,"source":"change"}' || echo true
        else
          [[ $json -eq 1 ]] && echo '{"value":"opsx-tui-fake/smoke","source":"change"}' || echo 'opsx-tui-fake/smoke'
        fi
        ;;
      *)
        echo "fake-models: $sub $*"
        ;;
    esac
    ;;
  gate)
    change="${1:-unknown}"
    if [[ -n "${FAKE_OPSX_GATE_DELAY_SECONDS:-}" ]]; then
      sleep "$FAKE_OPSX_GATE_DELAY_SECONDS"
    fi
    safe_change="$(printf '%s' "$change" | tr '/[:space:]' '___')"
    count_file="${log_dir:-/tmp}/gate-count-${safe_change}"
    count=0
    [[ -f "$count_file" ]] && count=$(cat "$count_file")
    count=$((count + 1))
    echo "$count" > "$count_file"

    mode="${FAKE_OPSX_GATE_MODE:-red}"
    if [[ "$mode" == "sequence" ]]; then
      IFS=',' read -r -a seq <<< "${FAKE_OPSX_GATE_SEQUENCE:-1,0}"
      idx=$((count - 1))
      if (( idx >= ${#seq[@]} )); then idx=$((${#seq[@]} - 1)); fi
      code="${seq[$idx]}"
    elif [[ "$mode" == "green" ]]; then
      code=0
    else
      code=1
    fi
    if [[ "$code" == "0" ]]; then
      echo "fake gate green for $change"
      exit 0
    fi
    echo "GATE-FAIL fake-red 1 scripted red gate for $change"
    exit 1
    ;;
  worktree)
    sub="${1:-}"
    if [[ "$sub" == "path" ]]; then
      shift || true
      change="${1:-unknown}"
      echo "${FAKE_OPSX_WORKTREE_PATH:-$(pwd)}"
      exit 0
    fi
    echo "fake opsx worktree unsupported: $sub" >&2
    exit 2
    ;;
  *)
    echo "fake opsx unsupported command: $cmd" >&2
    exit 2
    ;;
esac
