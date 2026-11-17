#!/bin/sh
# Install T3 (https://t3.codes/install.sh puts `t3` in ~/.local/bin). Shared by the Linux T3 service script
# (run_onchange_after_74_t3_service_linux.sh.tmpl) and the container tools script (run_onchange_after_05_container_tools.sh.tmpl).
#
# Unpinned (T3_PIN_VERSION unset, the Linux service script): when `t3` is on PATH, do nothing; otherwise run the installer, which takes the latest
# stable release.
#
# Pinned (T3_PIN_VERSION set, the container tools script): install exactly that release, so a pod's T3 matches the other T3s it links to (T3
# refuses a link between two versions that differ). The pin is in .chezmoidata.toml ([t3Pin]), with the sha256 of the release's linux archive for
# each CPU (T3_PIN_SHA256_X64, T3_PIN_SHA256_ARM64). To install it: download the archive, check it against the pinned sha256 (a mismatch exits 1 and
# installs nothing), unpack that same file into the installer's own layout ($T3CODE_HOME/runtime/versions/<pin>, marked .install-complete), write a
# stamp into that folder ("<pin> <sha256 of its t3>"), then run the installer with T3CODE_VERSION set: it finds the version already downloaded and only
# writes the `t3` launcher (over the old one, which it replaces when it made it). The installer downloads nothing.
#
# One check, pin_verified, decides every pinned exit 0: the `t3` on PATH is a launcher that runs exactly versions/<pin>/t3, and that folder holds the
# stamp for the t3 it contains. The stamp is the proof that the folder is the checked copy: this script writes it only after the sha256 check, and the
# installer deletes the whole folder (stamp included) when it unpacks again. pin_verified gates the early exit (so a pod that is already on the pin
# stays quiet, and one that is not verified is installed again through the checked path, never trusted) and the end of an install. If the installer
# does not use the checked folder (its layout changed and it downloaded the release itself), the script exits 1 on that run and on every later one;
# it never exits 0 on bytes the sha256 did not cover. A pod on the pin from before the stamp existed has no stamp, so it is installed again once.
# Older versions stay on disk.
#
# Exit 0: t3 is on PATH (pinned: pin_verified). Exit 1: the download, the sha256 check or the installer failed, or (pinned) the install is not the
# checked copy (a message says which).
# Test hooks: T3_INSTALL_URL, and T3CODE_RELEASE_BASE_URL (the installer's own release mirror variable, used here for the archive download; it
# must be an http(s) URL for the real installer, which rejects file://).
set -eu
log() { printf '[install_t3] %s: %s\n' "$1" "$2"; }

export PATH="$HOME/.local/bin:$PATH"
pin=${T3_PIN_VERSION:-}

if [ -n "$pin" ]; then
  # The folder the installer unpacks into, written the way install.sh writes it (absolute, no trailing slash), so the launcher line below matches.
  t3_home=${T3CODE_HOME:-$HOME/.t3}
  case "$t3_home" in /*) ;; *) t3_home=$(pwd -P)/$t3_home ;; esac
  while [ "${t3_home%/}" != "$t3_home" ] && [ "$t3_home" != / ]; do t3_home=${t3_home%/}; done
  versions=$t3_home/runtime/versions
  stamp=$versions/$pin/.verified-by-install_t3

  # 0 when the pinned T3 is the checked one; otherwise 1, with the reason in $why.
  pin_verified() {
    launcher=$(command -v t3 2>/dev/null) || { why="t3 is not on PATH"; return 1; }
    grep -qxF "exec '$versions/$pin/t3' \"\$@\"" "$launcher" \
      || { why="$launcher does not run $versions/$pin/t3"; return 1; }
    [ -f "$versions/$pin/t3" ] && [ "$(cat "$stamp" 2>/dev/null)" = "$pin $(sha256sum "$versions/$pin/t3" | cut -d' ' -f1)" ] \
      || { why="$versions/$pin is not the checked copy (no stamp, or its t3 changed)"; return 1; }
  }
  why=
  if pin_verified; then exit 0; fi
  [ -z "$why" ] || log INFO "T3 at the pin is not verified ($why)"
else
  command -v t3 >/dev/null 2>&1 && exit 0
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
  mkdir -p "$versions"
  staging=$(mktemp -d "$versions/.staging-XXXXXX")
  tar -xzf "$workdir/$archive" -C "$staging" --strip-components=1 || { log ERROR "T3 install failed: could not unpack $archive"; exit 1; }
  "$staging/t3" --version >/dev/null 2>&1 || { log ERROR "T3 install failed: the unpacked t3 does not run"; exit 1; }
  printf '%s\n' "$pin" > "$staging/.install-complete"
  printf '%s %s\n' "$pin" "$(sha256sum "$staging/t3" | cut -d' ' -f1)" > "$staging/.verified-by-install_t3"
  rm -rf "${versions:?}/$pin"
  mv "$staging" "$versions/$pin"
  export T3CODE_VERSION=$pin
fi

log INFO "installing T3${pin:+ $pin} (https://t3.codes/install.sh)"
curl -fsSL "${T3_INSTALL_URL:-https://t3.codes/install.sh}" -o "$installer" || { log ERROR "T3 install failed: could not download the installer"; exit 1; }
sh "$installer" || { log ERROR "T3 install failed"; exit 1; }
command -v t3 >/dev/null 2>&1 || { log ERROR "t3 is still not on PATH after the install"; exit 1; }
if [ -n "$pin" ]; then
  pin_verified || { log ERROR "T3 install failed: $why (the installer did not use the checked copy)"; exit 1; }
fi
