#!/bin/sh
#
# sync_harness_skills.sh: deploy the canonical skills through chezmoi, then
# re-run the harness apply so every agent's skill links follow.
#
# chezmoi does the comparing and the writing (status, diff, apply on the skills
# path), so deployed files get their target names and rendered contents
# (executable_run.sh deploys as run.sh, *.tmpl is rendered). Never copy source
# files by hand: a raw copy leaves files named executable_* behind.
#
# chezmoi does not delete files it does not manage. Under the skills path those
# are whole skill directories that left the source (orphans) and leftover files
# inside a managed skill (a renamed file, an old raw copy). The preview always
# lists them; they are deleted only with --prune.
#
# CHEZMOI_SOURCE_DIR picks the source checkout (set it to a worktree). The
# destination is chezmoi's own ($HOME).

set -eu
# Lists below are newline-separated: paths may contain spaces. No globbing.
NL='
'
IFS=$NL
set -f

SCRIPT_NAME="sync_harness_skills"
CHEZMOI_SOURCE="${CHEZMOI_SOURCE_DIR:-$HOME/.local/share/chezmoi}"
SKILLS_REL=".local/share/agent-harness/canonical/skills"
DEPLOYED_SKILLS="$HOME/$SKILLS_REL"
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

cz() {
  chezmoi --source "$CHEZMOI_SOURCE" --no-tty "$@"
}

# Read relative chezmoi paths on stdin; print the part below the skills path.
below_skills() {
  awk -v p="$SKILLS_REL/" 'index($0, p) == 1 { print substr($0, length(p) + 1) }'
}

in_list() { # in_list WORD NEWLINE-LIST
  case "$NL$2$NL" in *"$NL$1$NL"*) return 0 ;; esac
  return 1
}

add() { # add VAR WORD: append WORD to the newline-separated list in VAR
  eval "_cur=\${$1}"
  if [ -n "$_cur" ]; then eval "$1=\$_cur\$NL\$2"; else eval "$1=\$2"; fi
}

# --- diff computation -------------------------------------------------------

compute_diff() {
  TO_ADD=""
  TO_UPDATE=""
  UNCHANGED=""
  ORPHANS=""
  LEFTOVERS=""
  TO_DELETE=""

  # Skills chezmoi manages (top-level directories below the skills path).
  managed=$(cz managed -i dirs "$DEPLOYED_SKILLS" | below_skills | grep -v / || true)

  # Skills with any pending change, by chezmoi's own comparison of the
  # rendered target with the deployed file.
  PENDING=$(cz status -x scripts "$DEPLOYED_SKILLS")
  changed=$(printf '%s\n' "$PENDING" | cut -c4- | below_skills | cut -d/ -f1 | sort -u)

  for skill in $managed; do
    if in_list "$skill" "$changed"; then
      if [ -d "$DEPLOYED_SKILLS/$skill" ]; then add TO_UPDATE "$skill"; else add TO_ADD "$skill"; fi
    else
      add UNCHANGED "$skill"
    fi
  done
  # Changed but not managed: chezmoi will delete it (.chezmoiremove).
  for skill in $changed; do
    in_list "$skill" "$managed" || add TO_DELETE "$skill"
  done

  # Entries chezmoi does not manage. A top-level one is an orphan skill (or
  # stray file); anything deeper is a leftover inside a managed skill.
  for rel in $(cz unmanaged "$DEPLOYED_SKILLS" | below_skills); do
    case "$rel" in
      '') continue ;;
      /*|*/../*|../*|*/..|..) continue ;;
      */*) add LEFTOVERS "$rel" ;;
      *)   add ORPHANS "$rel" ;;
    esac
  done
}

# --- display ----------------------------------------------------------------

show_summary() {
  echo ""
  bold "Harness Skills Sync"; echo ""
  echo "  source:   $(dim "$CHEZMOI_SOURCE")"
  echo "  deployed: $(dim "$DEPLOYED_SKILLS")"
  echo ""

  if [ -n "$TO_ADD" ]; then
    bold "  Add"; echo " (in source, not yet deployed):"
    for skill in $TO_ADD; do echo "    $(green "+") $skill"; done
    echo ""
  fi

  if [ -n "$TO_UPDATE" ]; then
    bold "  Update"; echo " (rendered source differs from deployed):"
    for skill in $TO_UPDATE; do echo "    $(cyan "~") $skill"; done
    echo ""
  fi

  if [ -n "$TO_DELETE" ]; then
    bold "  Delete"; echo " (chezmoi removes these, .chezmoiremove):"
    for skill in $TO_DELETE; do echo "    $(red "−") $skill"; done
    echo ""
  fi

  if [ -n "$UNCHANGED" ]; then
    bold "  Unchanged"; echo ":"
    for skill in $UNCHANGED; do echo "    $(dim "· $skill")"; done
    echo ""
  fi

  if [ -n "$ORPHANS$LEFTOVERS" ]; then
    if [ "$prune" = true ]; then
      bold "  Remove"; echo " (not managed by chezmoi; --prune deletes them):"
    else
      bold "  Not managed"; echo " (chezmoi leaves these; run with --prune to delete them):"
    fi
    for skill in $ORPHANS; do echo "    $(red "−") $skill/ (orphan skill)"; done
    for rel in $LEFTOVERS; do echo "    $(red "−") $rel"; done
    echo ""
  fi
}

show_detailed_diff() {
  if [ -n "$PENDING" ]; then
    bold "── chezmoi diff ──────────────────────────────────────"; echo ""
    cz diff --no-pager --recursive -x scripts "$DEPLOYED_SKILLS" || true
    echo ""
  fi
  if [ "$prune" = true ] && [ -n "$ORPHANS" ]; then
    bold "── Orphan files to delete ────────────────────────────"; echo ""
    for skill in $ORPHANS; do
      find "$DEPLOYED_SKILLS/$skill" -type f | sort | while IFS= read -r f; do
        echo "    $(red "delete") ${f#"$DEPLOYED_SKILLS"/}"
      done
    done
    echo ""
  fi
}

# --- apply ------------------------------------------------------------------

apply_sync() {
  if [ -n "$PENDING" ]; then
    # --force: the diff above is what was approved; do not stop at chezmoi's
    # "changed since chezmoi last wrote it" prompt.
    cz apply --force -x scripts "$DEPLOYED_SKILLS"
    for skill in $TO_ADD; do log "Added: $skill"; done
    for skill in $TO_UPDATE; do log "Updated: $skill"; done
    for skill in $TO_DELETE; do log "Deleted: $skill"; done
  fi

  if [ "$prune" = true ]; then
    for skill in $ORPHANS; do
      rm -rf "${DEPLOYED_SKILLS:?}/$skill"
      log "Removed orphan: $skill"
    done
    for rel in $LEFTOVERS; do
      rm -rf "${DEPLOYED_SKILLS:?}/$rel"
      log "Removed leftover: $rel"
    done
  fi

  left=$(cz status -x scripts "$DEPLOYED_SKILLS")
  if [ -n "$left" ]; then
    log_error "chezmoi still reports changes under $DEPLOYED_SKILLS:"
    echo "$left" >&2
    exit 1
  fi

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
Usage: $(basename "$0") [--dry-run | --yes] [--prune]

Deploy canonical skills from the chezmoi source with chezmoi (rendered names
and contents), then re-run the harness apply script to update symlinks for all
agents.

Options:
  --dry-run   Show what would change without applying
  --yes       Apply without confirmation prompt
  --prune     Also delete what chezmoi does not manage under the skills path:
              orphan skill directories and leftover files (always previewed)
  -h, --help  Show this help

Environment:
  CHEZMOI_SOURCE_DIR  chezmoi source checkout (default ~/.local/share/chezmoi)
EOF
}

main() {
  mode="interactive"
  prune=false
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run) mode="dry-run"; shift ;;
      --yes)     mode="yes"; shift ;;
      --prune)   prune=true; shift ;;
      -h|--help) usage; exit 0 ;;
      *)         log_error "Unknown option: $1"; usage >&2; exit 1 ;;
    esac
  done

  if [ ! -d "$CHEZMOI_SOURCE/dot_local/share/agent-harness/canonical/skills" ]; then
    log_error "Chezmoi skills source not found: $CHEZMOI_SOURCE/dot_local/share/agent-harness/canonical/skills"
    exit 1
  fi
  if ! command -v chezmoi >/dev/null 2>&1; then
    log_error "chezmoi not found on PATH"
    exit 1
  fi

  mkdir -p "$DEPLOYED_SKILLS"

  compute_diff
  show_summary

  if [ -z "$PENDING" ] && { [ "$prune" = false ] || [ -z "$ORPHANS$LEFTOVERS" ]; }; then
    log "Everything is in sync. Nothing to do."
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
