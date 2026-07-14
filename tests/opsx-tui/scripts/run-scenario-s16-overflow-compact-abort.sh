#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=red
export FAKE_OPENAI_STATUS_SEQUENCE=200,400,200,200
export FAKE_OPENAI_ERROR_MESSAGE="context length exceeded"
export FAKE_OPENAI_DELAY_MS=3000
scn_setup "s16-overflow-compact-abort"
scn_make_change "overflow-abort-change"
scn_pi_start

scn_send "/opsx-loop overflow-abort-change"
# Request 1 succeeds and creates enough history; request 2 overflows; request 3
# is the delayed compaction summary call. Escape must cancel it without request 4.
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 3 45
scn_send_key Escape
scn_assert_pane "opsx-loop stopped \(aborted\): overflow-abort-change" "Escape during settled-overflow compaction wins" 30
scn_assert_log_count_stays "$PROVIDER_LOG" "/chat/completions" 3 5 "aborted compaction injects no recovery turn"
scn_assert_file "$FAKE_LOG_DIR/gate-count-overflow-abort-change" "^2$" "only kickoff and first clean worker gate before overflow"

scn_finish
