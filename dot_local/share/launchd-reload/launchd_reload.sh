# launchd_reload.sh: the one place that waits for a LaunchAgent to finish unloading and then loads it. Sourced, never run.
#
#   . "$HOME/.local/share/launchd-reload/launchd_reload.sh"
#   launchctl bootout "gui/$uid/$label" ...      # the caller boots the job out
#   launchd_wait_gone "$label"                   # 0 once launchd no longer has the job; 1 if it is still there after about 10 s
#   launchd_bootstrap "$label" "$plist"          # 0 once loaded; 1 after 4 failed tries, with one ERROR line
#
# Why: `launchctl bootstrap` straight after `launchctl bootout` fails (5, Input/output error) while launchd is still tearing the old job
# down, and the agent then stays unloaded after the apply. macOS only; the chezmoi source ignores this file elsewhere.
#
# Contract
#   * launchd_wait_gone LABEL: polls `launchctl print gui/<uid>/LABEL` every 0.5 s, at most 20 times, until it fails (the job is gone).
#   * launchd_bootstrap LABEL PLIST: `launchctl bootstrap gui/<uid> PLIST`; a failure is retried 3 times, 1 s apart. After the last
#     failure it logs one ERROR line (label, plist, launchctl's first line, the command to run by hand), sets LAUNCHD_ERR to that
#     first line, and returns 1. Callers turn the 1 into their own non-zero exit or status line.
#   * Log lines are `[$LAUNCHD_TAG] LEVEL: message` on stdout (LAUNCHD_TAG defaults to launchd_reload).
# Hooks: LAUNCHD_RUN (a command prefix for every launchctl call; the reconcile script sets a timeout), LAUNCHD_POLLS, LAUNCHD_POLL_SLEEP,
# LAUNCHD_RETRIES, LAUNCHD_RETRY_SLEEP (the numbers above; tests shorten them).

launchd_log() { printf '[%s] %s: %s\n' "${LAUNCHD_TAG:-launchd_reload}" "$1" "$2"; }
launchd_lc() { ${LAUNCHD_RUN:-} launchctl "$@"; }

launchd_wait_gone() { # launchd_wait_gone LABEL
  _lr_d=gui/$(id -u)
  _lr_n=0
  while launchd_lc print "$_lr_d/$1" >/dev/null 2>&1; do
    [ "$_lr_n" -lt "${LAUNCHD_POLLS:-20}" ] || return 1
    _lr_n=$((_lr_n + 1))
    sleep "${LAUNCHD_POLL_SLEEP:-0.5}"
  done
  return 0
}

launchd_bootstrap() { # launchd_bootstrap LABEL PLIST
  _lr_d=gui/$(id -u)
  _lr_t=0
  until LAUNCHD_ERR=$(launchd_lc bootstrap "$_lr_d" "$2" 2>&1 </dev/null); do
    LAUNCHD_ERR=$(printf '%s\n' "$LAUNCHD_ERR" | head -n 1 | cut -c1-200)
    if [ "$_lr_t" -ge "${LAUNCHD_RETRIES:-3}" ]; then
      launchd_log ERROR "could not load $1 from $2 after $((_lr_t + 1)) bootstrap tries (${LAUNCHD_ERR:-no output}); no GUI session, e.g. over ssh? log in and chezmoi apply again, or run: launchctl bootstrap $_lr_d $2"
      return 1
    fi
    _lr_t=$((_lr_t + 1))
    launchd_log WARN "bootstrap of $1 failed (${LAUNCHD_ERR:-no output}); retry $_lr_t of ${LAUNCHD_RETRIES:-3} in ${LAUNCHD_RETRY_SLEEP:-1} s"
    sleep "${LAUNCHD_RETRY_SLEEP:-1}"
  done
  return 0
}
