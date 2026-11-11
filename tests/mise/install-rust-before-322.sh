set -euo pipefail

# rustup, not mise, manages Rust here. mise's rust backend exports
# RUSTUP_TOOLCHAIN, which overrides any repo-level rust-toolchain.toml.
if ! command -v rustup >/dev/null 2>&1 && [ ! -x "$HOME/.cargo/bin/rustup" ]; then
  echo "Installing rustup..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --no-modify-path --default-toolchain stable --profile default
fi

# dot_zshenv sources this for interactive shells; needed here for the task itself
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"

rustup default stable
# rust-analyzer: rustaceanvim (Neovim) runs the rustup proxy in ~/.cargo/bin,
# which fails until the component is installed.
rustup component add rust-analyzer
# wasm32-wasip1 is required to build the harpoon Zellij plugin from source
rustup target add wasm32-wasip1

echo "✅ rustup $(rustup --version 2>/dev/null | head -1)"
