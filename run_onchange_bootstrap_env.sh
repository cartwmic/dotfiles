#!/bin/sh

# Exit on error and undefined variables
set -eu

. "$HOME"/.local/share/chezmoi/utils.sh

# Constants
SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_NAME
TEMP_DIR="/tmp/${SCRIPT_NAME}.$$"
readonly TEMP_DIR
LOG_PREFIX="[${SCRIPT_NAME}]"
readonly LOG_PREFIX

# Globals
PACKAGE=""

# Utility functions
log_info() {
  echo "${LOG_PREFIX} INFO: $*" >&2
}

log_error() {
  echo "${LOG_PREFIX} ERROR: $*" >&2
}

cleanup() {
  exit_code=$?
  if [ -d "${TEMP_DIR}" ]; then
    rm -rf "${TEMP_DIR}"
    log_info "Cleaned up temporary directory: ${TEMP_DIR}"
  fi
  exit $exit_code
}

is_cross_platform_package() {
  case "${PACKAGE}" in
  sdkman | just | uv | nvm | antidote | fzf | fzf-tab | rage | rust | helm | gvm | kitty | mmdc) return 0 ;;
  *) return 1 ;;
  esac
}

# Installation functions
install_cross_platform() {
  case "${PACKAGE}" in
  mmdc)
    npm install -g @mermaid-js/mermaid-cli
    ;;
  kitty)
    curl -L https://sw.kovidgoyal.net/kitty/installer.sh | sh /dev/stdin
    ;;
  gvm)
    # have to do the below manually
    # bash < <(curl -LSs 'https://raw.githubusercontent.com/moovweb/gvm/master/binscripts/gvm-installer')
    echo "INSTALL GVM MANUALLY"
    echo "REMEMBER TO INSTALL AND SET A GO VERSION"
    ;;
  sdkman)
    if [ -z "${USER}" ]; then
      log_error "User parameter required for sdkman installation"
      exit 1
    fi
    curl -s "https://get.sdkman.io" | bash
    ;;
  just)
    cargo install just
    ;;
  uv)
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ;;
  nvm)
    NVM_VERSION=$(curl -s https://api.github.com/repos/nvm-sh/nvm/tags | jq -r '.[0].name')
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/"$NVM_VERSION"/install.sh | bash
    ;;
  antidote)
    git clone --depth=1 https://github.com/mattmc3/antidote.git "$HOME"/.antidote
    ;;
  fzf)
    git clone --depth 1 https://github.com/junegunn/fzf.git "$HOME"/.fzf
    "$HOME"/.fzf/install
    ;;
  fzf-tab)
    git clone https://github.com/Aloxaf/fzf-tab "$HOME"/fzf-tab
    ;;
  helm)
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    ;;
  rage)
    cargo install rage
    ;;
  rust)
    curl https://sh.rustup.rs -sSf | sh
    . "$HOME"/.zshrc
    ;;
  *)
    log_error "Unknown cross-platform package: ${PACKAGE}"
    return 1
    ;;
  esac

  return $?
}

install_macos() {
  case "${PACKAGE}" in
  imagemagick)
    brew install imagemagick xquartz
    echo "REMEMBER TO ADD XQUARTZ AS A LOGIN ITEM"
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

  return $?
}

install_ubuntu_special() {
  case "${PACKAGE}" in
  go-task)
    if [ -z "${USER}" ]; then
      log_error "User parameter required for go-task installation"
      exit 1
    fi
    sudo -u "${USER}" sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b "${HOME}/.local/bin"
    ;;
  lazygit)
    version=$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" | \grep -Po '"tag_name": *"v\K[^"]*')
    if [ -z "${version}" ]; then
      log_error "Failed to fetch lazygit version"
      return 1
    fi

    curl -Lo lazygit.tar.gz "https://github.com/jesseduffield/lazygit/releases/download/v${version}/lazygit_${version}_Linux_x86_64.tar.gz"
    tar xf lazygit.tar.gz lazygit
    sudo install lazygit -D -t /usr/local/bin/
    ;;
  starship)
    cargo install starship --locked
    ;;
  zellij)
    cargo install --locked zellij
    ;;
  k9s)
    wget https://github.com/derailed/k9s/releases/latest/download/k9s_linux_amd64.deb
    sudo apt install ./k9s_linux_amd64.deb
    ;;
  kustomize)
    install_dir="${HOME}/.local/bin"
    mkdir -p "${install_dir}"
    (cd "${install_dir}" && curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash)
    ;;
  kubeseal)
    # Fetch the latest sealed-secrets version using GitHub API
    KUBESEAL_VERSION=$(curl -s https://api.github.com/repos/bitnami-labs/sealed-secrets/tags | jq -r '.[0].name' | cut -c 2-)

    # Check if the version was fetched successfully
    if [ -z "$KUBESEAL_VERSION" ]; then
      log_error "Failed to fetch the latest KUBESEAL_VERSION"
      exit 1
    fi

    wget "https://github.com/bitnami-labs/sealed-secrets/releases/download/v${KUBESEAL_VERSION}/kubeseal-${KUBESEAL_VERSION}-linux-amd64.tar.gz"
    tar -xvzf "kubeseal-${KUBESEAL_VERSION}-linux-amd64.tar.gz" kubeseal
    sudo install -m 755 kubeseal /usr/local/bin/kubeseal
    ;;
  yq)
    sudo wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_"$(dpkg --print-architecture)" -O /usr/local/bin/yq &&
      sudo chmod +x /usr/local/bin/yq
    ;;
  *)
    log_error "Unknown special Ubuntu package: ${PACKAGE}"
    return 1
    ;;
  esac

  return $?
}

install_ubuntu_apt() {
  case "${PACKAGE}" in
  kubectl)
    sudo apt-get update
    sudo apt-get install -y apt-transport-https ca-certificates curl
    # The same signing key is used for all repositories so you can disregard the version in the URL
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

  return $?
}

is_special_ubuntu_package() {
  case "${PACKAGE}" in
  go-task | lazygit | starship | zellij | kustomize | kubeseal | k9s | yq)
    return 0
    ;;
  *)
    return 1
    ;;
  esac
}

install_ubuntu() {
  if is_special_ubuntu_package; then
    install_ubuntu_special
  else
    install_ubuntu_apt
  fi

  return $?
}

install_fonts_macos() {
  brew install --cask font-sauce-code-pro-nerd-font
}

install_fonts_ubuntu() {
  VERSION=$(curl -s https://api.github.com/repos/ryanoasis/nerd-fonts/tags | jq -r '.[0].name')
  curl -L -o SourceCodePro.zip https://github.com/ryanoasis/nerd-fonts/releases/download/"$VERSION"/SourceCodePro.zip
  unzip SourceCodePro.zip
  mkdir -p "$HOME/.local/share/fonts"
  mv ./*ttf "$HOME/.local/share/fonts"
  fc-cache -fv

  return $?
}

main() {
  # Set up cleanup trap
  trap cleanup EXIT INT TERM

  mkdir -p "${TEMP_DIR}"
  cd "${TEMP_DIR}"

  is_macos && IS_MACOS=true || IS_MACOS=false
  is_ubuntu && IS_UBUNTU=true || IS_UBUNTU=false

  if $IS_UBUNTU; then
    # stuff to always install and is idempotent
    sudo apt-get update
    sudo apt-get install -y build-essential software-properties-common jq tar curl wget git sed gnupg zip zsh fontconfig sed util-linux bison mercurial
    sudo chsh "$USER" -s /usr/bin/zsh
  fi

  missing_prerequisites=""

  # check each prerequisite and add to array if missing
  command -v uv >/dev/null 2>&1 || missing_prerequisites="$missing_prerequisites uv"
  command -v cargo >/dev/null 2>&1 || missing_prerequisites="$missing_prerequisites rust"

  for executable in $missing_prerequisites; do
    log_info "Installing prerequisite ${executable}"
    PACKAGE=$executable

    if is_cross_platform_package; then
      install_cross_platform
    elif $IS_MACOS; then
      install_macos
    elif $IS_UBUNTU; then
      install_ubuntu
    else
      log_error "Unsupported operating system or distribution"
      exit 1
    fi

    log_info "Successfully installed prerequisite ${executable}"
  done

  log_info "Prerequisites installed"

  # Initialize array for missing executables
  missing_executables=""

  # Check each binary and add to array if missing
  command -v k9s >/dev/null 2>&1 || missing_executables="$missing_executables k9s"
  command -v just >/dev/null 2>&1 || missing_executables="$missing_executables just"
  command -v z >/dev/null 2>&1 || missing_executables="$missing_executables zoxide"
  command -v kubectl >/dev/null 2>&1 || missing_executables="$missing_executables kubectl"
  command -v kubeseal >/dev/null 2>&1 || missing_executables="$missing_executables kubeseal"
  command -v sdk >/dev/null 2>&1 || missing_executables="$missing_executables sdkman"
  command -v task >/dev/null 2>&1 || missing_executables="$missing_executables go-task"
  command -v rg >/dev/null 2>&1 || missing_executables="$missing_executables ripgrep"
  command -v lazygit >/dev/null 2>&1 || missing_executables="$missing_executables lazygit"
  command -v starship >/dev/null 2>&1 || missing_executables="$missing_executables starship"
  command -v kitty >/dev/null 2>&1 || missing_executables="$missing_executables kitty"
  test -e "$HOME/.config/nvm" || missing_executables="$missing_executables nvm"
  test -e "$HOME/.antidote" || missing_executables="$missing_executables antidote"
  (test -e "$HOME/.fzf" && command -v fzf) || missing_executables="$missing_executables fzf"
  test -e "$HOME/fzf-tab" || missing_executables="$missing_executables fzf-tab"
  command -v zellij >/dev/null 2>&1 || missing_executables="$missing_executables zellij"
  command -v nvim >/dev/null 2>&1 || missing_executables="$missing_executables neovim"
  command -v kustomize >/dev/null 2>&1 || missing_executables="$missing_executables kustomize"
  command -v helm >/dev/null 2>&1 || missing_executables="$missing_executables helm"
  command -v rage >/dev/null 2>&1 || missing_executables="$missing_executables rage"
  command -v terraform >/dev/null 2>&1 || missing_executables="$missing_executables terraform"
  command -v yq >/dev/null 2>&1 || missing_executables="$missing_executables yq"
  command -v gvm >/dev/null 2>&1 || missing_executables="$missing_executables gvm"
  command -v magick >/dev/null 2>&1 || missing_executables="$missing_executables imagemagick"
  command -v mmdc >/dev/null 2>&1 || missing_executables="$missing_executables mmdc"

  for executable in $missing_executables; do
    log_info "Installing ${executable}"
    PACKAGE=$executable

    if is_cross_platform_package; then
      install_cross_platform
    elif $IS_MACOS; then
      install_macos
    elif $IS_UBUNTU; then
      install_ubuntu
    else
      log_error "Unsupported operating system or distribution"
      exit 1
    fi

    log_info "Successfully installed ${executable}"
  done

  log_info "Executables installed"

  log_info "Installing fonts"
  if $IS_MACOS; then
    install_fonts_macos
  elif $IS_UBUNTU; then
    install_fonts_ubuntu
  else
    log_error "Unsupported operating system or distribution"
    exit 1
  fi

  echo "INSTALL GVM MANUALLY"
  echo "REMEMBER TO INSTALL AND SET A GO VERSION"
  if $IS_MACOS; then
    echo "REMEMBER TO ADD XQUARTZ AS A LOGIN ITEM"
  fi

}

# Run main function
main "$@"
