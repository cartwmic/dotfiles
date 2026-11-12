#!/bin/sh
# Git author identity on personal Linux (.chezmoiignore): the global user.name and user.email, so a commit works with no -c overrides.
# Why a script and not a git config file: dotfiles manage no git config file (see 76_git_credential_linux.sh), and Omarchy writes
# ~/.config/git/config itself with no [user] section. This sets two keys and nothing else:
#   user.name  = Michael Cartwright
#   user.email = 45673987+cartwmic@users.noreply.github.com   (the GitHub noreply address Michael's commits already use)
# A key that is already set is left alone, so a machine-local identity wins. Idempotent: nothing is written when both keys are set.
# macOS keeps its own setup (not touched). The work profile has no Linux machine, so it is left out (.chezmoiignore); the work
# identity is not in this source and is not set from here.
# Reproduce by hand:  git config --global user.name 'Michael Cartwright'; git config --global user.email '45673987+cartwmic@users.noreply.github.com'
# Undo:               git config --global --unset user.name; git config --global --unset user.email
set -eu
log() { printf '[git_identity_linux] %s: %s\n' "$1" "$2"; }

[ "$(uname -s)" = Linux ] || exit 0
command -v git >/dev/null 2>&1 || { log INFO "git is not installed; nothing to set"; exit 0; }

set_if_unset() {
  if [ -z "$(git config --global --get "$1" 2>/dev/null || true)" ]; then
    git config --global "$1" "$2"
    log INFO "set $1"
  fi
}
set_if_unset user.name 'Michael Cartwright'
set_if_unset user.email '45673987+cartwmic@users.noreply.github.com'
