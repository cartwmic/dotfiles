#!/bin/sh
# Remove the mise install of the retired `research` program (Loop Engine's research workflow; its alias and pin are gone from the mise
# config). Dropping the pin stops new installs, but nothing deletes the versions mise already put on a machine: they sit in the data
# directory, and an agent host that captured its PATH while they were pinned keeps naming them. This removes the tool's install
# directory (each version and mise's links to it), its download cache and its shim.
# It touches nothing but `research`, and does nothing, quietly, when there is no such install (a new machine, Termux, no mise).
# chezmoi records a run_once script only when it succeeds, so a failed removal fails the apply and the next apply runs this again.
set -eu
log() { printf '[retire_research_mise_install] %s: %s\n' "$1" "$2"; }
# One JSON line per removal attempt, in $XDG_STATE_HOME/agent-harness/retire-research-mise-install.jsonl: a time, the outcome (exit status), the data
# directory and the versions that were installed. Nothing secret. Best effort: a failed write never changes the script's exit status.
record_outcome() {
  state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/agent-harness"
  (umask 077 && mkdir -p "$state_dir") 2>/dev/null || return 0
  esc() { printf '%s' "$1" | tr '\n' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g'; }
  if [ "$1" -eq 0 ]; then event=research-install-removed; else event=research-install-remove-failed; fi
  printf '{"ts":"%s","event":"%s","exit":%s,"data_dir":"%s","versions":"%s","script":"69_retire_research_mise_install"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$event" "$1" "$(esc "$data")" "$(esc "${versions# }")" >> "$state_dir/retire-research-mise-install.jsonl" 2>/dev/null || true
}

data="${MISE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mise}"
installs="$data/installs/research"
downloads="$data/downloads/research"
shim="$data/shims/research"

# -L as well as -e: a dangling link (a shim whose target is gone, or a link at the install path) is not "there" to -e but is still to be removed.
found=
for path in "$installs" "$downloads" "$shim"; do
  if [ -e "$path" ] || [ -L "$path" ]; then found=1; fi
done
[ -n "$found" ] || exit 0

versions=
if [ -d "$installs" ] && [ ! -L "$installs" ]; then
  for dir in "$installs"/*; do
    [ -d "$dir" ] && [ ! -L "$dir" ] || continue
    versions="$versions ${dir##*/}"
  done
fi

# From here a failure is recorded too: the trap runs on the exit that `set -e` forces, with that exit's status.
trap 'status=$?; record_outcome "$status"; [ "$status" -eq 0 ] || log ERROR "could not remove the research install from $data"' EXIT
rm -rf "$installs" "$downloads"
rm -f "$shim"
log INFO "removed the retired research install${versions:+ (versions:$versions)} from $data"
