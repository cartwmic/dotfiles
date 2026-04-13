#!/bin/sh

set -eu

SCRIPT_NAME="sync_harness_skills"
CHEZMOI_SOURCE="${CHEZMOI_SOURCE_DIR:-$HOME/.local/share/chezmoi}"
CHEZMOI_SKILLS="$CHEZMOI_SOURCE/dot_local/share/agent-harness/canonical/skills"
DEPLOYED_SKILLS="${AGENT_HARNESS_CANONICAL_ROOT:-$HOME/.local/share/agent-harness/canonical}/skills"
HARNESS_SCRIPT="$HOME/.local/user_scripts/apply_harness_config.sh"

# --- helpers ----------------------------------------------------------------

log() {
  echo "[$SCRIPT_NAME] $1"
}

log_error() {
  echo "[$SCRIPT_NAME] ERROR: $1" >&2
}

bold()  { printf '\033[1m%s\033[0m' "$1"; }
green() { printf '\033[32m%s\033[0m' "$1"; }
red()   { printf '\033[31m%s\033[0m' "$1"; }
cyan()  { printf '\033[36m%s\033[0m' "$1"; }
dim()   { printf '\033[2m%s\033[0m' "$1"; }

# List skill directory names (excluding README and dotfiles)
list_skills() {
  dir="$1"
  if [ ! -d "$dir" ]; then
    return
  fi
  find "$dir" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort
}

# --- diff computation -------------------------------------------------------

compute_diff() {
  source_skills=$(list_skills "$CHEZMOI_SKILLS")
  deployed_skills=$(list_skills "$DEPLOYED_SKILLS")

  TO_ADD=""
  TO_REMOVE=""
  TO_UPDATE=""
  UNCHANGED=""

  # Skills in source but not deployed → add
  for skill in $source_skills; do
    if ! echo "$deployed_skills" | grep -qx "$skill"; then
      TO_ADD="${TO_ADD:+$TO_ADD }$skill"
    fi
  done

  # Skills deployed but not in source → remove
  for skill in $deployed_skills; do
    if ! echo "$source_skills" | grep -qx "$skill"; then
      TO_REMOVE="${TO_REMOVE:+$TO_REMOVE }$skill"
    fi
  done

  # Skills in both → check for content changes
  for skill in $source_skills; do
    if echo "$deployed_skills" | grep -qx "$skill"; then
      if ! diff -rq "$CHEZMOI_SKILLS/$skill" "$DEPLOYED_SKILLS/$skill" >/dev/null 2>&1; then
        TO_UPDATE="${TO_UPDATE:+$TO_UPDATE }$skill"
      else
        UNCHANGED="${UNCHANGED:+$UNCHANGED }$skill"
      fi
    fi
  done
}

# --- display ----------------------------------------------------------------

show_summary() {
  echo ""
  bold "Harness Skills Sync"; echo ""
  echo "  source:   $(dim "$CHEZMOI_SKILLS")"
  echo "  deployed: $(dim "$DEPLOYED_SKILLS")"
  echo ""

  has_changes=false

  if [ -n "$TO_ADD" ]; then
    has_changes=true
    bold "  Add"; echo " (in source, not yet deployed):"
    for skill in $TO_ADD; do
      echo "    $(green "+") $skill"
    done
    echo ""
  fi

  if [ -n "$TO_REMOVE" ]; then
    has_changes=true
    bold "  Remove"; echo " (deployed, not in source):"
    for skill in $TO_REMOVE; do
      echo "    $(red "−") $skill"
    done
    echo ""
  fi

  if [ -n "$TO_UPDATE" ]; then
    has_changes=true
    bold "  Update"; echo " (content differs):"
    for skill in $TO_UPDATE; do
      echo "    $(cyan "~") $skill"
    done
    echo ""
  fi

  if [ -n "$UNCHANGED" ]; then
    bold "  Unchanged"; echo ":"
    for skill in $UNCHANGED; do
      echo "    $(dim "· $skill")"
    done
    echo ""
  fi

  if [ "$has_changes" = false ]; then
    log "Everything is in sync. Nothing to do."
    return 1
  fi

  return 0
}

show_detailed_diff() {
  if [ -n "$TO_REMOVE" ]; then
    echo "$(bold "── Removals ──────────────────────────────────────────")"
    for skill in $TO_REMOVE; do
      echo ""
      echo "  $(red "−") $(bold "$skill")"
      # Show files that will be deleted
      find "$DEPLOYED_SKILLS/$skill" -type f | sort | while IFS= read -r f; do
        rel="${f#$DEPLOYED_SKILLS/$skill/}"
        echo "    $(red "delete") $rel"
      done
    done
    echo ""
  fi

  if [ -n "$TO_ADD" ]; then
    echo "$(bold "── Additions ─────────────────────────────────────────")"
    for skill in $TO_ADD; do
      echo ""
      echo "  $(green "+") $(bold "$skill")"
      find "$CHEZMOI_SKILLS/$skill" -type f | sort | while IFS= read -r f; do
        rel="${f#$CHEZMOI_SKILLS/$skill/}"
        echo "    $(green "add") $rel"
      done
    done
    echo ""
  fi

  if [ -n "$TO_UPDATE" ]; then
    echo "$(bold "── Updates ───────────────────────────────────────────")"
    for skill in $TO_UPDATE; do
      echo ""
      echo "  $(cyan "~") $(bold "$skill")"
      diff -ru "$DEPLOYED_SKILLS/$skill" "$CHEZMOI_SKILLS/$skill" 2>/dev/null \
        | tail -n +3 \
        | while IFS= read -r line; do
            case "$line" in
              +*) echo "    $(green "$line")" ;;
              -*) echo "    $(red "$line")" ;;
              @@*) echo "    $(cyan "$line")" ;;
              *)  echo "    $line" ;;
            esac
          done
    done
    echo ""
  fi
}

# --- apply ------------------------------------------------------------------

apply_sync() {
  # Remove orphaned skills
  for skill in $TO_REMOVE; do
    rm -rf "${DEPLOYED_SKILLS:?}/$skill"
    log "Removed: $skill"
  done

  # Add new skills (copy from chezmoi source)
  for skill in $TO_ADD; do
    cp -R "$CHEZMOI_SKILLS/$skill" "$DEPLOYED_SKILLS/$skill"
    log "Added: $skill"
  done

  # Update changed skills (replace with source copy)
  for skill in $TO_UPDATE; do
    rm -rf "${DEPLOYED_SKILLS:?}/$skill"
    cp -R "$CHEZMOI_SKILLS/$skill" "$DEPLOYED_SKILLS/$skill"
    log "Updated: $skill"
  done

  # Re-run harness apply to fix symlinks
  if [ -x "$HARNESS_SCRIPT" ]; then
    echo ""
    log "Running harness apply to sync symlinks..."
    "$HARNESS_SCRIPT"
  else
    log "Harness apply script not found at $HARNESS_SCRIPT — skipping symlink sync"
    log "Run 'chezmoi apply' or the harness script manually to update symlinks"
  fi
}

# --- main -------------------------------------------------------------------

usage() {
  cat <<EOF
Usage: $(basename "$0") [--dry-run | --yes]

Sync canonical skills from chezmoi source to deployed harness location,
then re-run the harness apply script to update symlinks for all agents.

Options:
  --dry-run   Show what would change without applying
  --yes       Apply without confirmation prompt
  -h, --help  Show this help
EOF
}

main() {
  mode="interactive"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run) mode="dry-run"; shift ;;
      --yes)     mode="yes"; shift ;;
      -h|--help) usage; exit 0 ;;
      *)         log_error "Unknown option: $1"; usage >&2; exit 1 ;;
    esac
  done

  if [ ! -d "$CHEZMOI_SKILLS" ]; then
    log_error "Chezmoi skills source not found: $CHEZMOI_SKILLS"
    exit 1
  fi

  mkdir -p "$DEPLOYED_SKILLS"

  compute_diff

  if ! show_summary; then
    exit 0
  fi

  show_detailed_diff

  case "$mode" in
    dry-run)
      log "Dry run — no changes applied."
      exit 0
      ;;
    yes)
      apply_sync
      ;;
    interactive)
      printf "Apply these changes? [y/N] "
      read -r answer
      case "$answer" in
        [yY]|[yY][eE][sS])
          apply_sync
          ;;
        *)
          log "Aborted."
          exit 0
          ;;
      esac
      ;;
  esac

  echo ""
  log "Done."
}

main "$@"
