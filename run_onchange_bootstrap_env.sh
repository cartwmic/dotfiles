#!/bin/sh

# Exit on error and undefined variables
set -eu

. "$HOME"/.local/share/chezmoi/utils.sh

# Constants
SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_NAME
LOG_PREFIX="[${SCRIPT_NAME}]"
readonly LOG_PREFIX

# Manual installation reminders
MANUAL_GVM_MSG="INSTALL GVM MANUALLY\nREMEMBER TO INSTALL AND SET A GO VERSION"
MANUAL_XQUARTZ_MSG="REMEMBER TO ADD XQUARTZ AS A LOGIN ITEM"

# Globals
PACKAGE=""

# ============================================================================
# Utility functions
# ============================================================================

log_info() {
  echo "${LOG_PREFIX} INFO: $*" >&2
}

log_error() {
  echo "${LOG_PREFIX} ERROR: $*" >&2
}

# Fetch latest GitHub release tag
fetch_latest_github_tag() {
  repo="$1"
  curl -s "https://api.github.com/repos/${repo}/tags" | jq -r '.[0].name'
}

# Install GitHub release binary (generic pattern)
install_github_release() {
  repo="$1"
  asset_name="$2"
  binary_name="$3"

  version=$(fetch_latest_github_tag "$repo")
  if [ -z "$version" ]; then
    log_error "Failed to fetch latest version for ${repo}"
    return 1
  fi

  # Remove 'v' prefix if present
  version_num=$(echo "$version" | sed 's/^v//')

  # Create temp directory just for this installation
  temp_dir=$(mktemp -d)
  trap 'rm -rf "$temp_dir"' EXIT

  cd "$temp_dir"
  curl -Lo download "$asset_name"

  # Handle tar.gz or deb based on extension
  case "$asset_name" in
    *.tar.gz)
      tar xf download "$binary_name"
      sudo install "$binary_name" -D -t /usr/local/bin/
      ;;
    *.deb)
      sudo apt install -y ./download
      ;;
  esac

  cd - >/dev/null
  rm -rf "$temp_dir"
  trap - EXIT
}

# ============================================================================
# Package classification
# ============================================================================

is_cross_platform_package() {
  case "${PACKAGE}" in
    sdkman|just|uv|nvm|antidote|fzf|fzf-tab|rage|rust|helm|gvm|kitty|mmdc|vectorcode|claude|claude-code-acp|mistral-vibe)
      return 0 ;;
    *)
      return 1 ;;
  esac
}

is_special_ubuntu_package() {
  case "${PACKAGE}" in
    go-task|lazygit|starship|zellij|kustomize|kubeseal|k9s|yq)
      return 0 ;;
    *)
      return 1 ;;
  esac
}

# ============================================================================
# Installation functions - Cross-platform
# ============================================================================

install_cross_platform() {
  case "${PACKAGE}" in
    # Python tools via uv
    mistral-vibe|vectorcode)
      uv tool install "${PACKAGE}"
      ;;

    # Node.js global packages
    claude-code-acp)
      npm install -g @zed-industries/claude-code-acp
      ;;
    mmdc)
      npm install -g @mermaid-js/mermaid-cli
      ;;

    # Curl installers
    claude)
      curl -fsSL https://claude.ai/install.sh | bash
      ;;
    kitty)
      curl -L https://sw.kovidgoyal.net/kitty/installer.sh | sh /dev/stdin
      ;;
    sdkman)
      curl -s "https://get.sdkman.io" | bash
      ;;
    uv)
      curl -LsSf https://astral.sh/uv/install.sh | sh
      ;;
    helm)
      curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
      ;;
    rust)
      curl https://sh.rustup.rs -sSf | sh
      . "$HOME"/.cargo/env
      ;;

    # Git clones
    nvm)
      NVM_VERSION=$(fetch_latest_github_tag "nvm-sh/nvm")
      curl -o- "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_VERSION}/install.sh" | bash
      ;;
    antidote)
      git clone --depth=1 https://github.com/mattmc3/antidote.git "$HOME/.antidote"
      ;;
    fzf)
      git clone --depth 1 https://github.com/junegunn/fzf.git "$HOME/.fzf"
      "$HOME/.fzf/install"
      ;;
    fzf-tab)
      git clone https://github.com/Aloxaf/fzf-tab "$HOME/fzf-tab"
      ;;

    # Cargo packages
    just|rage)
      cargo install "${PACKAGE}"
      ;;

    # Manual installations
    gvm)
      echo "$MANUAL_GVM_MSG"
      ;;

    *)
      log_error "Unknown cross-platform package: ${PACKAGE}"
      return 1
      ;;
  esac
}

# ============================================================================
# Installation functions - macOS
# ============================================================================

install_macos() {
  case "${PACKAGE}" in
    imagemagick)
      brew install imagemagick xquartz
      echo "$MANUAL_XQUARTZ_MSG"
      ;;
    k9s)
      brew install derailed/k9s/k9s
      ;;
    terraform)
      brew tap hashicorp/tap
      brew install hashicorp/tap/terraform
      ;;
    *)
      brew install "${PACKAGE}"
      ;;
  esac
}

# ============================================================================
# Installation functions - Ubuntu
# ============================================================================

install_ubuntu_special() {
  case "${PACKAGE}" in
    go-task)
      sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b "${HOME}/.local/bin"
      ;;

    # GitHub releases with common pattern
    lazygit)
      version=$(fetch_latest_github_tag "jesseduffield/lazygit")
      version_num=$(echo "$version" | sed 's/^v//')
      install_github_release \
        "jesseduffield/lazygit" \
        "https://github.com/jesseduffield/lazygit/releases/download/${version}/lazygit_${version_num}_Linux_x86_64.tar.gz" \
        "lazygit"
      ;;

    k9s)
      wget https://github.com/derailed/k9s/releases/latest/download/k9s_linux_amd64.deb
      sudo apt install -y ./k9s_linux_amd64.deb
      rm -f k9s_linux_amd64.deb
      ;;

    kubeseal)
      version=$(fetch_latest_github_tag "bitnami-labs/sealed-secrets")
      version_num=$(echo "$version" | sed 's/^v//')
      install_github_release \
        "bitnami-labs/sealed-secrets" \
        "https://github.com/bitnami-labs/sealed-secrets/releases/download/${version}/kubeseal-${version_num}-linux-amd64.tar.gz" \
        "kubeseal"
      ;;

    # Cargo builds
    starship|zellij)
      cargo install --locked "${PACKAGE}"
      ;;

    # Special installations
    kustomize)
      mkdir -p "${HOME}/.local/bin"
      (cd "${HOME}/.local/bin" && curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash)
      ;;

    yq)
      sudo wget "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_$(dpkg --print-architecture)" -O /usr/local/bin/yq
      sudo chmod +x /usr/local/bin/yq
      ;;

    *)
      log_error "Unknown special Ubuntu package: ${PACKAGE}"
      return 1
      ;;
  esac
}

install_ubuntu_apt() {
  # Add repositories if needed
  case "${PACKAGE}" in
    kubectl)
      sudo apt-get update
      sudo apt-get install -y apt-transport-https ca-certificates curl
      curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key |
        sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
      echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' |
        sudo tee /etc/apt/sources.list.d/kubernetes.list
      sudo apt-get update
      ;;
    neovim)
      sudo add-apt-repository -y ppa:neovim-ppa/unstable
      sudo apt-get update
      ;;
    terraform)
      wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
      sudo apt update
      ;;
  esac

  sudo apt install -y "${PACKAGE}"
}

install_ubuntu() {
  if is_special_ubuntu_package; then
    install_ubuntu_special
  else
    install_ubuntu_apt
  fi
}

# ============================================================================
# Font installation
# ============================================================================

install_fonts() {
  log_info "Installing fonts"

  if is_macos; then
    brew install --cask font-sauce-code-pro-nerd-font
  elif is_ubuntu; then
    temp_dir=$(mktemp -d)
    trap 'rm -rf "$temp_dir"' EXIT

    cd "$temp_dir"
    VERSION=$(fetch_latest_github_tag "ryanoasis/nerd-fonts")
    curl -L -o SourceCodePro.zip "https://github.com/ryanoasis/nerd-fonts/releases/download/${VERSION}/SourceCodePro.zip"
    unzip -q SourceCodePro.zip
    mkdir -p "$HOME/.local/share/fonts"
    mv ./*.ttf "$HOME/.local/share/fonts"
    fc-cache -fv

    cd - >/dev/null
    rm -rf "$temp_dir"
    trap - EXIT
  else
    log_error "Unsupported operating system for font installation"
    return 1
  fi
}

# ============================================================================
# Package installation orchestration
# ============================================================================

install_package() {
  package_name="$1"
  PACKAGE="$package_name"

  log_info "Installing ${package_name}"

  if is_cross_platform_package; then
    install_cross_platform
  elif is_macos; then
    install_macos
  elif is_ubuntu; then
    install_ubuntu
  else
    log_error "Unsupported operating system"
    return 1
  fi

  log_info "Successfully installed ${package_name}"
}

# ============================================================================
# Main execution
# ============================================================================

main() {
  is_macos && IS_MACOS=true || IS_MACOS=false
  is_ubuntu && IS_UBUNTU=true || IS_UBUNTU=false

  # Ubuntu system dependencies
  if $IS_UBUNTU; then
    sudo apt-get update
    sudo apt-get install -y build-essential software-properties-common jq tar curl wget git sed gnupg zip zsh fontconfig util-linux bison mercurial
    sudo chsh "$USER" -s /usr/bin/zsh
  fi

  # Prerequisites (must be installed first)
  missing_prerequisites=""
  command -v uv >/dev/null 2>&1 || missing_prerequisites="$missing_prerequisites uv"
  command -v cargo >/dev/null 2>&1 || missing_prerequisites="$missing_prerequisites rust"

  for executable in $missing_prerequisites; do
    install_package "$executable"
  done

  [ -n "$missing_prerequisites" ] && log_info "Prerequisites installed"

  # Main package list with executable checks
  # Format: "command_to_check:package_name" or "path_check:package_name"
  PACKAGES="
    k9s:k9s
    just:just
    z:zoxide
    kubectl:kubectl
    kubeseal:kubeseal
    sdk:sdkman
    task:go-task
    rg:ripgrep
    lazygit:lazygit
    starship:starship
    kitty:kitty
    zellij:zellij
    nvim:neovim
    kustomize:kustomize
    helm:helm
    rage:rage
    terraform:terraform
    yq:yq
    gvm:gvm
    magick:imagemagick
    mmdc:mmdc
    vectorcode:vectorcode
    claude:claude
    claude-code-acp:claude-code-acp
    vibe:mistral-vibe
  "

  # Special path-based checks
  PATH_CHECKS="
    $HOME/.config/nvm:nvm
    $HOME/.antidote:antidote
    $HOME/.fzf:fzf
    $HOME/fzf-tab:fzf-tab
  "

  missing_executables=""

  # Check command-based packages
  for entry in $PACKAGES; do
    cmd=$(echo "$entry" | cut -d: -f1)
    pkg=$(echo "$entry" | cut -d: -f2)
    command -v "$cmd" >/dev/null 2>&1 || missing_executables="$missing_executables $pkg"
  done

  # Check path-based packages
  for entry in $PATH_CHECKS; do
    path=$(echo "$entry" | cut -d: -f1)
    pkg=$(echo "$entry" | cut -d: -f2)

    # Special handling for fzf (needs both path and command)
    if [ "$pkg" = "fzf" ]; then
      (test -e "$path" && command -v fzf >/dev/null 2>&1) || missing_executables="$missing_executables $pkg"
    else
      test -e "$path" || missing_executables="$missing_executables $pkg"
    fi
  done

  # Install missing packages
  for executable in $missing_executables; do
    install_package "$executable"
  done

  [ -n "$missing_executables" ] && log_info "Executables installed"

  # Install fonts
  install_fonts

  # Manual installation reminders
  echo "\n=== Manual Steps Required ==="
  echo "$MANUAL_GVM_MSG"
  $IS_MACOS && echo "$MANUAL_XQUARTZ_MSG"
}

# Run main function
main "$@"
