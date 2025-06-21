#!/bin/sh
# The leading . in .install-password-manager.sh is important because it tells chezmoi to ignore .install-password-manager.sh when declaring the state of files in your home directory.

. "$HOME"/.local/share/chezmoi/utils.sh

# Check if 'op' command already exists
if command -v op >/dev/null 2>&1; then
  echo "op command already exists"
  exit 0
fi

# Check if 'op.exe' command exists for WSL on Windows
if is_wsl; then
  if command -v op.exe >/dev/null 2>&1; then
    echo "Found op.exe, creating symlink..."

    # Ensure the target directory exists
    mkdir -p "$HOME/.local/bin"

    # Get the full path to op.exe
    OP_EXE_PATH=$(command -v op.exe)

    # Create symlink
    ln -sf "$OP_EXE_PATH" "$HOME/.local/bin/op"

    echo "Symlink created: $HOME/.local/bin/op -> $OP_EXE_PATH"
    exit 0
  else
    echo "In WSL and op.exe is not installed. Please manually install the op cli for windows and rerun this script"
    exit 1
  fi
fi

# Continue with the rest of the script if neither op nor op.exe exist
echo "op command not found and not in WSL, continuing with script..."

case "$(uname -s)" in
Darwin)
  brew install 1password-cli
  ;;
Linux)
  if is_ubuntu; then
    curl -sS https://downloads.1password.com/linux/keys/1password.asc |
      sudo gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg &&
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/$(dpkg --print-architecture) stable main" |
      sudo tee /etc/apt/sources.list.d/1password.list &&
      sudo mkdir -p /etc/debsig/policies/AC2D62742012EA22/ &&
      curl -sS https://downloads.1password.com/linux/debian/debsig/1password.pol |
      sudo tee /etc/debsig/policies/AC2D62742012EA22/1password.pol &&
      sudo mkdir -p /usr/share/debsig/keyrings/AC2D62742012EA22 &&
      curl -sS https://downloads.1password.com/linux/keys/1password.asc |
      sudo gpg --dearmor --output /usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg &&
      sudo apt update && sudo apt install 1password-cli
  else
    "unsupported linux distro"
    exit 1
  fi
  ;;
*)
  echo "unsupported OS"
  exit 1
  ;;
esac
