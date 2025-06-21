#!/bin/sh

is_wsl() {
  # Check for WSL2-specific file
  if [ -f /proc/sys/fs/binfmt_misc/WSLInterop ]; then
    return 0
  fi

  return 1
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
