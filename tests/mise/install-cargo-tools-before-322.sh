# Ensure cargo is available (install-rust should have installed rustup by now)
if ! command -v cargo >/dev/null 2>&1; then
  echo "ERROR: cargo not found. Run: mise run install-rust"
  exit 1
fi

# Install rage
if ! command -v rage >/dev/null 2>&1; then
  cargo install rage --locked
fi

# Install kickstart
if ! command -v kickstart >/dev/null 2>&1; then
  cargo install kickstart --features=cli
fi
