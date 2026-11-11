#!/bin/sh
# GitHub credential helper for git on personal Linux (.chezmoiignore): `gh auth git-credential`, by name, so it survives a gh update.
# Runs when this script changes. Dotfiles manage no git config file; this sets exactly two keys in the user's global git config and nothing else:
#   credential.https://github.com.helper       = ""  then  !gh auth git-credential
#   credential.https://gist.github.com.helper  = ""  then  !gh auth git-credential
# The empty first entry clears any helper inherited from the system config. Anything already set for those two keys is replaced, including
# the version-pinned path `gh auth setup-git` writes when gh comes from mise (.../mise/installs/gh/2.103.3/.../gh), which breaks at the next gh update.
# Idempotent: when both keys already hold exactly that pair, git is not written to.
# Needs `gh` on the PATH of whatever runs git (mise shims are, for the coordinator and T3 units); `gh auth login` is still a manual step.
# Reproduce by hand:  for h in github.com gist.github.com; do git config --global --unset-all credential.https://$h.helper; git config --global --add credential.https://$h.helper ''; git config --global --add credential.https://$h.helper '!gh auth git-credential'; done
# Undo:               for h in github.com gist.github.com; do git config --global --unset-all credential.https://$h.helper; done
# macOS keeps its own setup (not touched); the work profile has no Linux machine, so it is left out (.chezmoiignore).
set -eu
log() { printf '[git_credential_linux] %s: %s\n' "$1" "$2"; }

[ "$(uname -s)" = Linux ] || exit 0
command -v git >/dev/null 2>&1 || { log INFO "git is not installed; nothing to set"; exit 0; }

want=$(printf '\n!gh auth git-credential')   # the two values, one per line: empty, then the helper
for host in github.com gist.github.com; do
  key="credential.https://$host.helper"
  have=$(git config --global --get-all "$key" 2>/dev/null || true)
  if [ "$have" = "$want" ]; then
    continue
  fi
  git config --global --unset-all "$key" 2>/dev/null || true
  git config --global --add "$key" ''
  git config --global --add "$key" '!gh auth git-credential'
  log INFO "set $key"
done
