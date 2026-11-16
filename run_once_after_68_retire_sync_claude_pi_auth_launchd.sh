#!/bin/sh
# Unload the retired LaunchAgent com.cartwmic.sync-claude-pi-auth (retired 2026-10-02, .chezmoiremove). macOS only.
# .chezmoiremove deletes the plist and the script, but nothing unloads a job that launchd already has loaded; it kept running
# and exiting 2 on the Mac mini. This script unloads it and removes the plist if it is still there. It does nothing once the job is gone.
# A failed unload fails the apply, so the next apply runs this again (chezmoi records a run_once script only when it succeeds).
set -eu
log() { printf '[retire_sync_claude_pi_auth_launchd] %s: %s\n' "$1" "$2"; }

[ "$(uname -s)" = Darwin ] || exit 0
label=com.cartwmic.sync-claude-pi-auth
plist="$HOME/Library/LaunchAgents/$label.plist"
uid=$(id -u)
launchctl bootout "gui/$uid/$label" >/dev/null 2>&1 || :
if launchctl print "gui/$uid/$label" >/dev/null 2>&1; then
  log ERROR "could not unload $label; try: launchctl bootout gui/$uid/$label, then chezmoi apply again"
  exit 1
fi
rm -f "$plist"
log INFO "$label is unloaded and its plist removed"
