#!/usr/bin/env bash
# AC: opsx-loop.tui-scenarios-exercise-user-visible-slash-commands

set -euo pipefail
source "$(dirname "$0")/scenario-lib.sh"

scn_setup "s01-models"
scn_pi_start

scn_send "/opsx-loop models"
scn_assert_pane "fake-models: author=" "models list output visible in pane"

scn_send "/opsx-loop models set author claude-bridge/claude-haiku-4-5"
scn_assert_pane "fake-models-set: author claude-bridge/claude-haiku-4-5" "models set output visible in pane"
scn_assert_file "$FAKE_LOG_DIR/opsx.log" "models[[:space:]]+set[[:space:]]+author[[:space:]]+claude-bridge/claude-haiku-4-5" "models argv preserved after leading keyword"

scn_finish
