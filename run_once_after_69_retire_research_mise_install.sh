#!/bin/sh
# Remove the mise install of the retired `research` program (Loop Engine's research workflow; its alias and pin are gone from the mise
# config). Dropping the pin stops new installs, but nothing deletes the versions mise already put on a machine: they sit in the data
# directory, and an agent host that captured its PATH while they were pinned keeps naming them. This removes the tool's install
# directory (each version and mise's links to it), its download cache and its shim.
# It touches nothing but `research`, and does nothing, quietly, when there is no such install (a new machine, Termux, no mise).
# chezmoi records a run_once script only when it succeeds, so a failed removal fails the apply and the next apply runs this again.
set -eu
log() { printf '[retire_research_mise_install] %s: %s\n' "$1" "$2"; }

data="${MISE_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/mise}"
installs="$data/installs/research"
downloads="$data/downloads/research"
shim="$data/shims/research"

# -L as well as -e: after `mise uninstall` the directory can hold only links whose targets are gone.
found=
for path in "$installs" "$downloads" "$shim"; do
  if [ -e "$path" ] || [ -L "$path" ]; then found=1; fi
done
[ -n "$found" ] || exit 0

versions=
if [ -d "$installs" ]; then
  for dir in "$installs"/*; do
    [ -d "$dir" ] && [ ! -L "$dir" ] || continue
    versions="$versions ${dir##*/}"
  done
fi

rm -rf "$installs" "$downloads"
rm -f "$shim"
log INFO "removed the retired research install${versions:+ (versions:$versions)} from $data"
