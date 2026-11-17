#!/bin/sh
# Install T3 (https://t3.codes/install.sh puts `t3` in ~/.local/bin). Shared by the Linux T3 service script
# (run_onchange_after_74_t3_service_linux.sh.tmpl) and the container tools script (run_onchange_after_05_container_tools.sh.tmpl).
#
# Unpinned (T3_PIN_VERSION unset, the Linux service script): when `t3` is on PATH, do nothing; otherwise run the installer, which takes the latest
# stable release.
#
# Pinned (T3_PIN_VERSION set, the container tools script): install exactly that release, so a pod's T3 matches the other T3s it links to (T3
# refuses a link between two versions that differ). The pin is in .chezmoidata.toml ([t3Pin]), with the sha256 of the release's linux archive for
# each CPU (T3_PIN_SHA256_X64, T3_PIN_SHA256_ARM64). When `t3 --version` already prints the pin, do nothing. Otherwise download the archive the
# installer would fetch, check it against the pinned sha256 (a mismatch exits 1 and installs nothing), and only then run the installer with
# T3CODE_VERSION set. The installer fetches the archive itself, from the same URL, and checks it against the release's own SHA256SUMS; the pinned
# sha256 is the extra check that the release still holds the bytes the pin was made from. The installer then writes the `t3` launcher over the
# old one (it replaces a launcher of its own making) and leaves older versions on disk.
#
# Exit 0: t3 is on PATH (pinned: at the pin). Exit 1: the download, the sha256 check or the installer failed, or t3 is not at the expected version
# after it (a message says which).
# Test hooks: T3_INSTALL_URL, and T3CODE_RELEASE_BASE_URL (the installer's own release mirror variable, used for the sha256 download too).
set -eu
log() { printf '[install_t3] %s: %s\n' "$1" "$2"; }

export PATH="$HOME/.local/bin:$PATH"
pin=${T3_PIN_VERSION:-}
if [ -z "$pin" ]; then
  command -v t3 >/dev/null 2>&1 && exit 0
elif [ "$(t3 --version 2>/dev/null || true)" = "t3 v$pin" ]; then
  exit 0
fi

workdir=$(mktemp -d "${TMPDIR:-/tmp}/t3-install.XXXXXX")
trap 'rm -rf "$workdir"' EXIT
installer=$workdir/install.sh

if [ -n "$pin" ]; then
  case "$(uname -m)" in
    x86_64 | amd64) arch=x64; want=${T3_PIN_SHA256_X64:-} ;;
    aarch64 | arm64) arch=arm64; want=${T3_PIN_SHA256_ARM64:-} ;;
    *) log ERROR "T3 install failed: no pinned build for CPU $(uname -m)"; exit 1 ;;
  esac
  [ -n "$want" ] || { log ERROR "T3 install failed: no sha256 pinned for linux-$arch"; exit 1; }
  archive="t3-$pin-linux-$arch.tar.gz"
  log INFO "checking $archive against the pinned sha256"
  curl -fsSL "${T3CODE_RELEASE_BASE_URL:-https://github.com/pingdotgg/t3code/releases/download}/v$pin/$archive" -o "$workdir/$archive" \
    || { log ERROR "T3 install failed: could not download $archive"; exit 1; }
  echo "$want  $workdir/$archive" | sha256sum -c - >/dev/null 2>&1 \
    || { log ERROR "T3 install failed: $archive does not match the pinned sha256 $want (the release changed, or the pin is wrong)"; exit 1; }
  rm -f "$workdir/$archive"
fi

[ -z "$pin" ] || export T3CODE_VERSION=$pin
log INFO "installing T3${pin:+ $pin} (https://t3.codes/install.sh)"
curl -fsSL "${T3_INSTALL_URL:-https://t3.codes/install.sh}" -o "$installer" || { log ERROR "T3 install failed: could not download the installer"; exit 1; }
sh "$installer" || { log ERROR "T3 install failed"; exit 1; }
command -v t3 >/dev/null 2>&1 || { log ERROR "t3 is still not on PATH after the install"; exit 1; }
[ -z "$pin" ] || [ "$(t3 --version 2>/dev/null || true)" = "t3 v$pin" ] \
  || { log ERROR "t3 prints \"$(t3 --version 2>&1 | head -n 1)\" after the install, not \"t3 v$pin\""; exit 1; }
