#!/bin/sh
# GitHub credential helper for git on personal Linux (.chezmoiignore): `gh auth git-credential`, by name, so it survives a gh update.
# Runs when this script changes. Dotfiles manage no git config file; this sets exactly three keys in the user's global git config and nothing else:
#   credential.https://github.com.helper       = ""  then  !gh auth git-credential
#   credential.https://gist.github.com.helper  = ""  then  !gh auth git-credential
#   credential.https://gitea.internal.cartwmic.com.helper = ""  then  gitea-op   (~/.local/bin/git-credential-gitea-op: the Gitea token from 1Password)
# The empty first entry clears any helper inherited from the system config. Anything already set for those keys is replaced, including
# the version-pinned path `gh auth setup-git` writes when gh comes from mise (.../mise/installs/gh/2.103.3/.../gh), which breaks at the next gh update.
# Idempotent: when each key already holds exactly its pair, git is not written to.
# Needs `gh` on the PATH of whatever runs git (mise shims are, for the coordinator and T3 units); `gh auth login` is still a manual step.
# Reproduce by hand:  for h in github.com gist.github.com; do git config --global --unset-all credential.https://$h.helper; git config --global --add credential.https://$h.helper ''; git config --global --add credential.https://$h.helper '!gh auth git-credential'; done
#                     git config --global --unset-all credential.https://gitea.internal.cartwmic.com.helper; git config --global --add credential.https://gitea.internal.cartwmic.com.helper ''; git config --global --add credential.https://gitea.internal.cartwmic.com.helper gitea-op
# Undo:               for h in github.com gist.github.com gitea.internal.cartwmic.com; do git config --global --unset-all credential.https://$h.helper; done
# macOS keeps its own setup (not touched); the work profile has no Linux machine, so it is left out (.chezmoiignore).
set -eu
log() { printf '[git_credential_linux] %s: %s\n' "$1" "$2"; }
# One JSON line per key set, in $XDG_STATE_HOME/agent-harness/git-credential-linux.jsonl: a time, the key and what it held before (a helper name or path, never a secret). Best effort.
record_set() {
  state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/agent-harness"
  (umask 077 && mkdir -p "$state_dir") 2>/dev/null || return 0
  esc() { printf '%s' "$1" | tr '\n' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g'; }
  printf '{"ts":"%s","event":"credential-helper-set","key":"%s","before":"%s","after":"%s","script":"76_git_credential_linux"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(esc "$1")" "$(esc "$2")" "$(esc "$3")" >> "$state_dir/git-credential-linux.jsonl" 2>/dev/null || true
}

[ "$(uname -s)" = Linux ] || exit 0
command -v git >/dev/null 2>&1 || { log INFO "git is not installed; nothing to set"; exit 0; }

set_pair() {   # $1 host, $2 the helper value: the pair is empty, then $2
  key="credential.https://$1.helper"
  have=$(git config --global --get-all "$key" 2>/dev/null || true)
  [ "$have" = "$(printf '\n%s' "$2")" ] && return 0
  git config --global --unset-all "$key" 2>/dev/null || true
  git config --global --add "$key" ''
  git config --global --add "$key" "$2"
  record_set "$key" "$have" "$2"
  log INFO "set $key"
}
for host in github.com gist.github.com; do set_pair "$host" '!gh auth git-credential'; done
set_pair gitea.internal.cartwmic.com gitea-op
