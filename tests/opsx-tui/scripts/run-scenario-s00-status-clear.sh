#!/usr/bin/env bash
# AC: opsx-loop.tui-scenarios-exercise-user-visible-slash-commands

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

scn_setup "s00-status-clear"
scn_pi_start

scn_send "/opsx-loop"
scn_assert_pane "No active opsx-loop" "bare /opsx-loop reports no active loop"

scn_send "/opsx-loop status"
scn_assert_pane "No active opsx-loop" "status reports no active loop"

scn_send "/opsx-loop clear"
scn_assert_pane "No active opsx-loop to clear" "clear reports no active loop to clear"

scn_finish
