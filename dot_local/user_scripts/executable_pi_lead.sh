#!/bin/sh
# Binary of the T3 provider instance pi-lead (dot_t3/private_userdata/modify_settings.json.tmpl): runs the real `pi` for a durable
# coordinator lead, with the coordinator's pane-bin first on PATH and COORDINATOR_STATE_DIR set, so the lead can run `ledger` and the
# other pane-bin commands. T3 calls it as it would call pi (`--version`, `--mode rpc ...`); every argument goes through unchanged.
# The real pi is the first `pi` on the PATH T3 gave this script, the same lookup the plain `pi` instance does. Resolved before the
# pane-bin prefix is added, so a pane-bin command can never shadow it. State dir: the personal coordinator's (~/.local/share/coordinator).
set -eu
state=$HOME/.local/share/coordinator
pi=$(command -v pi) || { echo "pi_lead.sh: pi not found on PATH" >&2; exit 127; }
exec env PATH="$state/pane-bin:$PATH" COORDINATOR_STATE_DIR="$state" "$pi" "$@"
