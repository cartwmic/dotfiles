#!/bin/sh
# Chezmoi run_once script to install mise
# This runs once when chezmoi init/apply is executed on a new machine

set -eu

SCRIPT_NAME="$(basename "$0")"
LOG_PREFIX="[${SCRIPT_NAME}]"

log_info() {
  echo "${LOG_PREFIX} INFO: $*" >&2
}

log_error() {
  echo "${LOG_PREFIX} ERROR: $*" >&2
}

# Check if mise is already installed
if command -v mise &> /dev/null; then
  log_info "mise is already installed ($(mise --version))"
  exit 0
fi

log_info "Installing mise..."

if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS installation via Homebrew
  if ! command -v brew &> /dev/null; then
    log_error "Homebrew is not installed. Please install Homebrew first: https://brew.sh"
    exit 1
  fi
  brew install mise
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
  # Linux installation via official installer
  curl https://mise.run | sh

  # Add mise to PATH for this session
  export PATH="$HOME/.local/bin:$PATH"
else
  log_error "Unsupported operating system: $OSTYPE"
  exit 1
fi

# Verify installation
if command -v mise &> /dev/null; then
  log_info "mise successfully installed: $(mise --version)"
  log_info "mise will be activated when you restart your shell (via ~/.zshrc)"
else
  log_error "mise installation failed"
  exit 1
fi
