#!/usr/bin/env bash
# DEPRECATED 2026-08-04.
#
# Termux is a first-class chezmoi profile. Do not ADB-push config from this
# staging directory anymore — set profile: "termux" on the phone and run
# `chezmoi apply`. See termux/README.md.

set -euo pipefail

cat >&2 <<'EOF'
error: termux/sync.sh is retired.

Termux config is managed by chezmoi with:

  data:
    profile: "termux"

On the phone:
  pkg install -y chezmoi git openssh
  mkdir -p ~/.config/chezmoi
  printf 'data:\n  profile: "termux"\n' > ~/.config/chezmoi/chezmoi.yaml
  chezmoi init --apply <dotfiles-git-remote>

Canonical sources:
  dot_termux/termux.properties   -> ~/.termux/termux.properties
  dot_termux/font.ttf            -> ~/.termux/font.ttf
  bin/executable_zellij-jump     -> ~/bin/zellij-jump
  bin/executable_herdr-jump      -> ~/bin/herdr-jump
  private_dot_ssh/modify_config.tmpl (termux block)
  run_once_after_05_provision_termux_ssh_keys.sh.tmpl

See termux/README.md.
EOF
exit 1
