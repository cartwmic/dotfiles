#!/bin/sh
# Install xterm-kitty terminfo into ~/.terminfo.
#
# Local kitty windows set TERMINFO to the app bundle, so this is invisible
# until something SSHs in with TERM=xterm-kitty. Without the compiled
# database, zsh ZLE cannot move the cursor: the prompt reprints and typed
# text looks wrong while the input buffer is fine.

set -eu

SCRIPT_NAME="$(basename "$0")"
LOG_PREFIX="[${SCRIPT_NAME}]"

log_info() {
  echo "${LOG_PREFIX} INFO: $*" >&2
}

src=""
for candidate in \
  /Applications/kitty.app/Contents/Resources/kitty/terminfo/kitty.terminfo \
  /Applications/kitty.app/Contents/Resources/terminfo/kitty.terminfo
do
  if [ -f "$candidate" ]; then
    src="$candidate"
    break
  fi
done

if [ -z "$src" ]; then
  if infocmp xterm-kitty >/dev/null 2>&1; then
    log_info "xterm-kitty already available; nothing to install"
    exit 0
  fi
  log_info "no kitty terminfo source on this host, skipping"
  exit 0
fi

mkdir -p "$HOME/.terminfo"
tic -x -o "$HOME/.terminfo" "$src"
log_info "installed xterm-kitty from $src into $HOME/.terminfo"
