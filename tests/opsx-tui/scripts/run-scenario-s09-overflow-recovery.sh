#!/usr/bin/env bash
# AC: opsx-loop.interrupt-or-error-stops-the-loop

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

export FAKE_OPSX_GATE_MODE=sequence
export FAKE_OPSX_GATE_SEQUENCE=1,0
export FAKE_OPENAI_STATUS_SEQUENCE=400,200,200
export FAKE_OPENAI_ERROR_MESSAGE="context length exceeded"
scn_setup "s09-overflow-recovery"
scn_make_change "overflow-recovery-change"
scn_pi_start

scn_send "/opsx-loop overflow-recovery-change"
scn_assert_pane "context overflow; compacting and retrying once" "settled overflow triggers one bounded compaction" 30
# Tiny fixture sessions have nothing worth summarizing, so ctx.compact reports
# "Nothing to compact" and invokes the same bounded onError continuation.
scn_wait_log_count "$PROVIDER_LOG" "/chat/completions" 2 30
scn_assert_pane "gate green\. Ready to archive" "overflow recovery resumes under same loop" 30
scn_assert_file "$FAKE_LOG_DIR/gate-count-overflow-recovery-change" "^2$" "recovered worker reaches one post-success gate"

scn_finish
