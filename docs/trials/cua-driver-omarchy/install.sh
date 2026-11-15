#!/bin/sh
# Cua Driver trial on Omarchy (aarch64 or x86_64): install the driver and BUILD the Hyprland plugin into a scratch
# directory. Touches nothing under ~/.local/bin and does not load anything into the live compositor.
#   usage: install.sh [VERSION]      default 0.51.5 (release tag cua-driver-rs-v<VERSION>)
# Needs: gh, cmake, ninja, gcc, hyprland (its headers ship in the package). Personal Linux profile only.
set -eu
V="${1:-0.51.5}"; T="cua-driver-rs-v$V"
ROOT="${CUA_TRIAL_DIR:-$HOME/.cache/cua-driver-trial}"
case "$(uname -m)" in aarch64) ARCH=arm64 ;; x86_64) ARCH=x86_64 ;; *) echo "unsupported arch" >&2; exit 2 ;; esac
mkdir -p "$ROOT/dl" "$ROOT/src" "$ROOT/home"
cd "$ROOT/dl"
gh release download "$T" -R trycua/cua -p "cua-driver-rs-$V-linux-$ARCH.tar.gz" -p SHA256SUMS -p "cua-hyprland-plugin-$V-*.tar.gz" --clobber
sha256sum -c SHA256SUMS --ignore-missing          # fails the script on a bad hash
tar xzf "cua-driver-rs-$V-linux-$ARCH.tar.gz" -C "$ROOT/src"
mkdir -p "$ROOT/src/plugin"; tar xzf cua-hyprland-plugin-"$V"-*.tar.gz -C "$ROOT/src/plugin"
"$ROOT/src/cua-driver-rs-$V-linux-$ARCH/cua-driver" --version
cd "$ROOT"/src/plugin/cua-hyprland-plugin-*/
HV=$(pkg-config --modversion hyprland)             # must equal the running Hyprland
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCUA_HYPRLAND_INPUT=ON -DCUA_HYPRLAND_EXPECTED_VERSION="$HV"
cmake --build build
ctest --test-dir build --output-on-failure
echo "plugin: $(pwd)/build/cua-hyprland-plugin.so"
"$ROOT/src/cua-driver-rs-$V-linux-$ARCH/cua-driver" telemetry disable
