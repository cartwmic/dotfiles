#!/bin/sh
# Chezmoi run_once script to install build essentials BEFORE mise installation
# This ensures C compiler and build tools are available for Rust/cargo builds
#
# The "run_once_before_" prefix ensures this runs before other run_once scripts

set -eu

SCRIPT_NAME="$(basename "$0")"
LOG_PREFIX="[${SCRIPT_NAME}]"

log_info() {
  echo "${LOG_PREFIX} INFO: $*" >&2
}

log_error() {
  echo "${LOG_PREFIX} ERROR: $*" >&2
}

is_ubuntu() {
  if [ -f /etc/os-release ]; then
    grep -q "^ID=ubuntu" /etc/os-release
    return $?
  fi
  return 1
}

is_macos() {
  [ "$(uname -s)" = "Darwin" ]
}

# macOS already has clang/build tools via Xcode Command Line Tools
if is_macos; then
  log_info "Running on macOS - build tools should be available via Xcode CLT"
  if ! command -v cc >/dev/null 2>&1; then
    log_error "No C compiler found. Please install Xcode Command Line Tools:"
    log_error "  xcode-select --install"
    exit 1
  fi
  exit 0
fi

# Ubuntu/Linux - install build-essential
if is_ubuntu || [ "$(uname -s)" = "Linux" ]; then
  if ! dpkg -l | grep -q "^ii  build-essential"; then
    log_info "Installing build-essential and essential packages..."
    sudo apt-get update
    sudo apt-get install -y build-essential software-properties-common \
      curl wget git zsh tar zip unzip
    log_info "Build essentials installed successfully"
  else
    log_info "build-essential already installed"
  fi
  exit 0
fi

log_info "Unknown platform - assuming build tools are available"
