#!/bin/bash
# Cua Driver trial on the personal Mac mini (macOS arm64). Reproduces the host changes of the
# 2026-11-15 trial (workstream read-agent-desktop, ask #1037). A trial, not adoption: nothing here
# is wired into chezmoi apply. Run by hand on the mini:  cua-driver-mac-mini-trial.sh install|grant|status|undo
# Needs: curl, shasum, tar, codesign, ditto (all stock macOS).
set -euo pipefail

VERSION="0.51.5"
TAG="cua-driver-rs-v${VERSION}"
TARBALL="cua-driver-rs-${VERSION}-darwin-arm64.tar.gz"
BASE="https://github.com/trycua/cua/releases/download/${TAG}"
APP="/Applications/CuaDriver.app"
BIN="${APP}/Contents/MacOS/cua-driver"
BUNDLE_ID="com.trycua.driver"
WORK="${HOME}/.cache/cua-poc"

cmd_install() {
  [ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo "arm64 macOS only" >&2; exit 1; }
  mkdir -p "$WORK/dl" && cd "$WORK/dl"
  curl -fsSL -o "$TARBALL" "${BASE}/${TARBALL}"
  curl -fsSL -o SHA256SUMS "${BASE}/SHA256SUMS"
  grep " ${TARBALL}\$" SHA256SUMS | shasum -a 256 -c -
  rm -rf x && mkdir x && tar -xzf "$TARBALL" -C x
  src="$(find x -name CuaDriver.app -maxdepth 3 | head -1)"
  codesign --verify --deep --strict "$src"
  # The app must sit at /Applications/CuaDriver.app: `permissions grant` launches that exact path and
  # macOS attaches the grants to the bundle id. A scratch location is refused. No symlink, nothing on PATH.
  rm -rf "$APP" && ditto "$src" "$APP"
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
  "$BIN" telemetry disable || true
  "$BIN" --version
}

cmd_grant() {
  # Opens the tool's own guide. Manual part (Michael's admin password comes from 1Password, never from here):
  #  1. System Settings > Privacy & Security > "Device Control and Data Access" (Accessibility): switch CuaDriver on.
  #  2. Screen & System Audio Recording: drag the CuaDriver tile from the guide into the list, switch it on,
  #     answer the "Quit & Reopen" prompt with Later.
  #  3. Re-run this command until it prints "All set" (it also clears direct_capture_consent_required).
  "$BIN" permissions grant
  "$BIN" permissions status
}

cmd_status() { "$BIN" --version; "$BIN" status; "$BIN" permissions status; }

cmd_undo() {
  "$BIN" stop 2>/dev/null || true
  tccutil reset All "$BUNDLE_ID" || true      # resets only this app's own grants; run 2026-11-15, ask #1077
  rm -rf "$APP" "$HOME/.cua-driver" "$HOME/Library/Caches/cua-driver" "$WORK"
  /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$APP" 2>/dev/null || true
}

case "${1:-}" in
  install) cmd_install ;; grant) cmd_grant ;; status) cmd_status ;; undo) cmd_undo ;;
  *) echo "usage: $0 install|grant|status|undo" >&2; exit 2 ;;
esac
