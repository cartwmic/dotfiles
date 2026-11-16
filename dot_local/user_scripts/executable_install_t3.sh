#!/bin/sh
# Install T3 (https://t3.codes/install.sh puts `t3` in ~/.local/bin) when `t3` is not on PATH. Shared by the Linux T3 service script
# (run_onchange_after_74_t3_service_linux.sh.tmpl) and the container tools script (run_onchange_after_05_container_tools.sh.tmpl).
# Exit 0: t3 is on PATH. Exit 1: the download or the installer failed, or t3 is still not on PATH after it (a message says which).
# Test hook: T3_INSTALL_URL.
set -eu
log() { printf '[install_t3] %s: %s\n' "$1" "$2"; }

export PATH="$HOME/.local/bin:$PATH"
command -v t3 >/dev/null 2>&1 && exit 0
log INFO "installing T3 (https://t3.codes/install.sh)"
installer=$(mktemp "${TMPDIR:-/tmp}/t3-install.XXXXXX")
trap 'rm -f "$installer"' EXIT
curl -fsSL "${T3_INSTALL_URL:-https://t3.codes/install.sh}" -o "$installer" || { log ERROR "T3 install failed: could not download the installer"; exit 1; }
sh "$installer" || { log ERROR "T3 install failed"; exit 1; }
command -v t3 >/dev/null 2>&1 || { log ERROR "t3 is still not on PATH after the install"; exit 1; }
