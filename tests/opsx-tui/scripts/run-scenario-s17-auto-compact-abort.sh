#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPENAI_STATUS_SEQUENCE=200,400,200,200
export FAKE_OPENAI_ERROR_MESSAGE="context length exceeded"
export FAKE_OPENAI_DELAY_MS=3000
export SCN_PI_APPROVE=1
scn_setup "s17-auto-compact-abort"
scn_make_change "auto-overflow-abort-change"
mkdir -p "$SCENARIO_CWD/.pi"
cat > "$SCENARIO_CWD/.pi/settings.json" <<'EOF_SETTINGS'
{
  "compaction": {
    "enabled": true,
    "reserveTokens": 1000,
    "keepRecentTokens": 0
  }
}
EOF_SETTINGS
scn_pi_start

scn_send "/opsx-loop auto-overflow-abort-change"
# Request 1 creates history; request 2 overflows; request 3 is Pi's OWN delayed
# auto-compaction call. Escape must mark that host compaction cancelled so the
# extension does not start replacement compaction from agent_settled.
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 3 45
scn_send_key Escape
scn_assert_pane "opsx-loop stopped \(aborted\): auto-overflow-abort-change" "Escape during Pi auto-compaction wins" 30
scn_assert_log_count_stays "$PROVIDER_LOG" "/chat/completions" 3 5 "settlement does not restart cancelled host compaction"
scn_assert_file "$FAKE_LOG_DIR/gate-count-auto-overflow-abort-change" "^2$" "only kickoff and first clean gate before host overflow"

scn_finish
