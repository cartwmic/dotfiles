#!/bin/sh
# Install T3 (https://t3.codes/install.sh puts `t3` in ~/.local/bin). Shared by the Linux T3 service script
# (run_onchange_after_74_t3_service_linux.sh.tmpl) and the container tools script (run_onchange_after_05_container_tools.sh.tmpl).
#
# Unpinned (T3_PIN_VERSION unset, the Linux service script): when `t3` is on PATH, do nothing; otherwise run the installer, which takes the latest
# stable release.
#
# Pinned (T3_PIN_VERSION set, the container tools script): install exactly that release, so a pod's T3 matches the other T3s it links to (T3
# refuses a link between two versions that differ). The pin is in .chezmoidata.toml ([t3Pin]), with the sha256 of the release's linux archive for
# each CPU (T3_PIN_SHA256_X64, T3_PIN_SHA256_ARM64). When `t3 --version` already prints the pin, do nothing. Otherwise download the archive, check it
# against the pinned sha256 (a mismatch exits 1 and installs nothing), unpack that same file into the installer's own layout
# ($T3CODE_HOME/runtime/versions/<pin>, marked .install-complete), then run the installer with T3CODE_VERSION set: it finds the version already
# downloaded and only writes the `t3` launcher (over the old one, which it replaces when it made it). So the bytes that run are the bytes the pinned
# sha256 covers; the installer downloads nothing. If the installer does not use the checked folder (its layout changed and it downloaded the
# release itself), the script exits 1: after it, the launcher must run exactly versions/<pin>/t3, the t3 binary must be unchanged, and a marker file
# written into the folder before the installer ran must still be there (the installer deletes the whole folder when it unpacks again). Older versions
# stay on disk.
#
# Exit 0: t3 is on PATH (pinned: at the pin). Exit 1: the download, the sha256 check or the installer failed, or (pinned) the installer did not leave
# the checked copy in place (a message says which).
# Test hooks: T3_INSTALL_URL, and T3CODE_RELEASE_BASE_URL (the installer's own release mirror variable, used here for the archive download; it
# must be an http(s) URL for the real installer, which rejects file://).
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
staging=
trap 'rm -rf "$workdir" "$staging"' EXIT
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
  versions=${T3CODE_HOME:-$HOME/.t3}/runtime/versions
  mkdir -p "$versions"
  staging=$(mktemp -d "$versions/.staging-XXXXXX")
  tar -xzf "$workdir/$archive" -C "$staging" --strip-components=1 || { log ERROR "T3 install failed: could not unpack $archive"; exit 1; }
  "$staging/t3" --version >/dev/null 2>&1 || { log ERROR "T3 install failed: the unpacked t3 does not run"; exit 1; }
  printf '%s\n' "$pin" > "$staging/.install-complete"
  rm -rf "${versions:?}/$pin"
  mv "$staging" "$versions/$pin"
  checked=$(sha256sum "$versions/$pin/t3")
  : > "$versions/$pin/.checked-by-install_t3"
fi

[ -z "$pin" ] || export T3CODE_VERSION=$pin
log INFO "installing T3${pin:+ $pin} (https://t3.codes/install.sh)"
curl -fsSL "${T3_INSTALL_URL:-https://t3.codes/install.sh}" -o "$installer" || { log ERROR "T3 install failed: could not download the installer"; exit 1; }
sh "$installer" || { log ERROR "T3 install failed"; exit 1; }
command -v t3 >/dev/null 2>&1 || { log ERROR "t3 is still not on PATH after the install"; exit 1; }
if [ -n "$pin" ]; then
  launcher=$(command -v t3)
  grep -qxF "exec '$versions/$pin/t3' \"\$@\"" "$launcher" \
    || { log ERROR "T3 install failed: $launcher does not run the checked $versions/$pin/t3 (the installer put T3 somewhere else)"; exit 1; }
  [ "$(sha256sum "$versions/$pin/t3")" = "$checked" ] && [ -e "$versions/$pin/.checked-by-install_t3" ] \
    || { log ERROR "T3 install failed: the installer replaced the checked files in $versions/$pin"; exit 1; }
  rm -f "$versions/$pin/.checked-by-install_t3"
fi
