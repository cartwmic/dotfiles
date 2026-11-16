#!/bin/sh
# Retires the weekly mistakes-report systemd timer (retired 2026-11-16): the coordinator's Retro lead keeper now runs `mistakes-report` on the
# schedule "mistakes-weekly". Stops and disables mistakes-report.timer and removes both units on a host that still has them. The command
# (~/.local/bin/mistakes-report), its code, ~/.local/state/mistakes-report and the published page stay. .chezmoiignore skips this script on
# a host with no mistakes-report.timer left, so it does nothing there. Prune this script, its ignore line and its test once every machine has applied.
#
# Fails (and so fails the apply) when the timer will not stop: chezmoi records a run_onchange script only when it succeeds, so the next apply
# tries again. A host with no systemd user manager (a container, WSL without systemd) has nothing loaded, and WSL is left alone: both are a
# notice and a clean exit. Test hook: MISTAKES_REPORT_WSL_MARKER (the WSL interop file).
set -eu
log() { printf '[retire_mistakes_report_timer] %s: %s\n' "$1" "$2"; }

[ "$(uname -s)" = Linux ] || exit 0
if [ -f "${MISTAKES_REPORT_WSL_MARKER:-/proc/sys/fs/binfmt_misc/WSLInterop}" ]; then log INFO "WSL: not touched"; exit 0; fi
if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user show-environment >/dev/null 2>&1; then
  log INFO "no systemd user manager here; mistakes-report.timer not changed"
  exit 0
fi
dir="$HOME/.config/systemd/user"
systemctl --user disable --now mistakes-report.timer >/dev/null 2>&1 || :
if systemctl --user is-active --quiet mistakes-report.timer; then
  log ERROR "could not stop mistakes-report.timer; try: systemctl --user disable --now mistakes-report.timer, then chezmoi apply again"
  exit 1
fi
rm -f "$dir/mistakes-report.service" "$dir/mistakes-report.timer"
systemctl --user daemon-reload
log INFO "mistakes-report.timer is stopped and its units removed; the Retro keeper runs mistakes-report now"
