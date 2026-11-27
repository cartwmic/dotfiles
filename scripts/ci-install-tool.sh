#!/bin/sh
# Install one pinned tool for CI from its GitHub release file: retried download, sha256 check against scripts/ci-tool-pins.txt, unpack into a bin folder.
# Usage: scripts/ci-install-tool.sh TOOL [BIN_DIR]   (BIN_DIR defaults to $HOME/.local/bin)
# Why not the tool's install script (get.chezmoi.io, mise.run): one bad answer from that site (HTTP 504, 2026-11-27) failed both CI jobs before any test ran.
# CI_TOOL_BASE_URL replaces https://github.com as the download host, CI_TOOL_PINS the pin file, CI_TOOL_RETRY_DELAY (seconds, default 5) the wait between
# tries; tests/ci-install-tool uses all three against a local server.
# Exit 0: the tool is in BIN_DIR and its file matched the pinned sha256. Exit 1: the download failed (the message names the file and the address), the
# sha256 differed, the pin is missing for this platform, or the unpack failed.
set -eu

here=$(dirname "$0")
pins=${CI_TOOL_PINS:-$here/ci-tool-pins.txt}
base=${CI_TOOL_BASE_URL:-https://github.com}
tool=${1:?usage: ci-install-tool.sh TOOL [BIN_DIR]}
bin=${2:-$HOME/.local/bin}

fail() { echo "ci-install-tool: $*" >&2; exit 1; }

case $(uname -s) in Linux) os=linux ;; Darwin) os=darwin ;; *) fail "unsupported OS $(uname -s)" ;; esac
case $(uname -m) in x86_64 | amd64) cpu=amd64 ;; arm64 | aarch64) cpu=arm64 ;; *) fail "unsupported CPU $(uname -m)" ;; esac
platform=$os-$cpu

line=$(awk -v t="$tool" -v p="$platform" '$1 == t && $3 == p { print; exit }' "$pins")
[ -n "$line" ] || fail "no pin for $tool on $platform in $pins"
set -- $line
version=$2 repo=$4 file=$5 want=$6 member=$7

url=$base/$repo/releases/download/$version/$file
scratch=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/ci-install-tool.XXXXXX")
trap 'rm -rf "$scratch"' EXIT

# --retry-all-errors retries a 5xx answer too (plain --retry stops at the first HTTP error status it does not count as transient).
if ! curl --fail --silent --show-error --location --retry 6 --retry-all-errors --retry-delay "${CI_TOOL_RETRY_DELAY:-5}" --connect-timeout 20 --max-time 180 \
  --output "$scratch/$file" "$url"; then
  fail "download failed: $file from $url"
fi

if command -v sha256sum >/dev/null 2>&1; then got=$(sha256sum "$scratch/$file" | cut -d' ' -f1); else got=$(shasum -a 256 "$scratch/$file" | cut -d' ' -f1); fi
[ "$got" = "$want" ] || fail "checksum mismatch for $file (from $url): pinned $want, got $got"

tar -xzf "$scratch/$file" -C "$scratch" "$member" || fail "cannot unpack $member from $file"
mkdir -p "$bin"
cp "$scratch/$member" "$bin/$tool"
chmod 755 "$bin/$tool"
echo "ci-install-tool: installed $tool $version to $bin/$tool (sha256 $got)"
