#!/bin/sh

set -eu

SCRIPT_NAME="setup_openspec"
TOOLS="claude,codex,pi"
PROFILE="core"
FORCE="--force"

log() {
  echo "[$SCRIPT_NAME] $1"
}

log_error() {
  echo "[$SCRIPT_NAME] ERROR: $1" >&2
}

usage() {
  cat <<EOF
Usage: setup_openspec.sh <repo-path>

Bootstraps OpenSpec for Claude Code, Codex CLI, and Pi using the core profile.
EOF
}

require_dir() {
  if [ ! -d "$1" ]; then
    log_error "Directory not found: $1"
    exit 1
  fi
}

# Skills that the agent-harness canonical pipeline owns; openspec init/update
# would otherwise write per-repo copies of these and collide with the
# canonical symlinks in ~/.pi/agent/skills, ~/.claude/skills, ~/.codex/skills.
# Keep this list in sync with dot_local/share/agent-harness/canonical/skills/
# entries that openspec emits on init.
CANONICAL_OPENSPEC_SKILLS="openspec-explore openspec-propose openspec-apply-change openspec-archive-change clarify-spec"

strip_canonical_skill_copies() {
  repo_path="$1"

  for tool_dir in .pi .claude .codex; do
    skills_dir="$repo_path/$tool_dir/skills"
    [ -d "$skills_dir" ] || continue

    for skill_name in $CANONICAL_OPENSPEC_SKILLS; do
      target="$skills_dir/$skill_name"
      if [ -e "$target" ] || [ -L "$target" ]; then
        rm -rf "$target"
        log "Stripped per-repo skill copy: $target (canonical-owned)"
      fi
    done

    # Remove now-empty skills dir to avoid leaving a stub.
    if [ -d "$skills_dir" ] && [ -z "$(ls -A "$skills_dir" 2>/dev/null)" ]; then
      rmdir "$skills_dir"
      log "Removed empty skills dir: $skills_dir"
    fi
  done
}

summarize_repo_outputs() {
  repo_path="$1"

  log "Repo outputs under $repo_path"
  for path in \
    "$repo_path/openspec" \
    "$repo_path/.claude/skills" \
    "$repo_path/.claude/commands/opsx" \
    "$repo_path/.pi/skills" \
    "$repo_path/.pi/prompts"
  do
    if [ -e "$path" ]; then
      log "  ✓ $path"
    else
      log "  - $path (not present)"
    fi
  done
}

summarize_codex_outputs() {
  codex_home="${CODEX_HOME:-$HOME/.codex}"
  codex_prompts="$codex_home/prompts"

  if [ -d "$codex_prompts" ]; then
    log "Codex prompt files in $codex_prompts"
    find "$codex_prompts" -maxdepth 1 -type f -name 'opsx-*' | sort | while IFS= read -r prompt; do
      log "  ✓ $prompt"
    done
  else
    log "Codex prompts directory not present: $codex_prompts"
  fi
}

main() {
  if [ "$#" -ne 1 ]; then
    usage >&2
    exit 1
  fi

  repo_path="$1"
  require_dir "$repo_path"

  if ! command -v openspec >/dev/null 2>&1; then
    log_error "openspec not found in PATH. Run: mise run install-openspec"
    exit 1
  fi

  repo_path=$(cd "$repo_path" && pwd)

  log "Bootstrapping OpenSpec in $repo_path"
  log "Using tools=$TOOLS profile=$PROFILE"

  openspec config profile "$PROFILE"
  openspec init "$repo_path" --tools "$TOOLS" --profile "$PROFILE" $FORCE
  openspec update "$repo_path" --force

  strip_canonical_skill_copies "$repo_path"

  summarize_repo_outputs "$repo_path"
  summarize_codex_outputs

  log "Done"
}

main "$@"
