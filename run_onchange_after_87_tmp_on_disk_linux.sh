#!/bin/sh
# /tmp on the root disk instead of RAM, on personal Linux (.chezmoiignore). Masks systemd's tmp.mount so /tmp is a plain directory after the next boot.
# Runs when this script changes. tmp.mount is a static unit (no fstab entry), which is why a mask is the way to turn it off.
# The live /tmp is never unmounted or touched: it stays a tmpfs until the host reboots. This script never reboots.
# Cleanup still happens: systemd-tmpfiles-clean.timer applies /usr/lib/tmpfiles.d/tmp.conf ("q /tmp 1777 root root 10d"), which deletes /tmp files older than 10 days on any filesystem.
# Idempotent: when tmp.mount is already masked, nothing is run.
# Reproduce by hand:  sudo systemctl mask tmp.mount     (then reboot; check with: findmnt /tmp  -> no tmpfs line)
# Undo:               sudo systemctl unmask tmp.mount   (then reboot; /tmp is a tmpfs again)
# A host with no running systemd, or no tmp.mount unit, gets a notice and a clean exit. A failed mask fails the script, so the next apply retries it
# (chezmoi records a run_onchange script only when it succeeds). The work profile is a Mac with no systemd, so it is left out (.chezmoiignore).
# Test hook: TMP_ON_DISK_SYSTEMD_DIR (stands in for /run/systemd/system, the "systemd is running" marker), TMP_ON_DISK_WSL_MARKER.
set -eu
log() { printf '[tmp_on_disk_linux] %s: %s\n' "$1" "$2"; }

[ "$(uname -s)" = Linux ] || exit 0
if [ -f "${TMP_ON_DISK_WSL_MARKER:-/proc/sys/fs/binfmt_misc/WSLInterop}" ]; then log INFO "WSL: nothing to set up"; exit 0; fi
if [ ! -d "${TMP_ON_DISK_SYSTEMD_DIR:-/run/systemd/system}" ] || ! command -v systemctl >/dev/null 2>&1; then
  log INFO "systemd is not running here; /tmp left as it is"
  exit 0
fi
if ! systemctl cat tmp.mount >/dev/null 2>&1; then
  log INFO "no tmp.mount unit on this host; /tmp left as it is"
  exit 0
fi
if [ "$(systemctl is-enabled tmp.mount 2>/dev/null || true)" = masked ]; then
  log INFO "tmp.mount is already masked; nothing to do"
  exit 0
fi
as_root=""
[ "$(id -u)" = 0 ] || as_root="sudo -n"
log INFO "running: ${as_root:+$as_root }systemctl mask tmp.mount"
# shellcheck disable=SC2086
$as_root systemctl mask tmp.mount >/dev/null 2>&1 || { log ERROR "could not mask tmp.mount (needs root or passwordless sudo); run: sudo systemctl mask tmp.mount"; exit 1; }
[ "$(systemctl is-enabled tmp.mount 2>/dev/null || true)" = masked ] || { log ERROR "tmp.mount is not masked after the mask"; exit 1; }
log INFO "tmp.mount masked: /tmp is on disk from the next reboot (the live /tmp is untouched; undo: sudo systemctl unmask tmp.mount)"
