#!/bin/sh
# Linux checks for this repo, the same command the CI `tests` job runs: the four node tests, then every
# Linux Python suite through scripts/ci-par.py (tests/heavy-gate one test per process, the rest one
# discover process per suite), then tests/kgate alone.
#
# Installs nothing. It assumes these are on PATH: chezmoi (the render tests), zsh, lsof and rsync (the
# agent-scratch, zshenv and agent-docker tests), node, and python3 (3.14). CI installs chezmoi and the
# apt packages first. On another Linux host, install them yourself, then run this from the repo.
#
# Usage: scripts/ci-linux.sh   (from any directory; it cd's to the repo root). Exit 1 if any step fails.
set -eu

cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1

for tool in chezmoi zsh lsof rsync node python3; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "[ci-linux] ERROR: $tool is not on PATH" >&2
    exit 1
  fi
done

node --test tests/pi-patches/pi_select.test.mjs
node --test tests/pi-patches/apply_no_pi.test.mjs
node --test tests/pi-patches/patch_failure_chain.test.mjs
node --test tests/pi-patches/refresh_and_verify.test.mjs

status=0
python3 scripts/ci-par.py \
  --per-test tests/heavy-gate \
  tests/qmd \
  tests/pi-mcp-lazy \
  tests/pi-idle-rss \
  tests/pi-agents-render \
  tests/instructions-profile \
  tests/pi-settings-render \
  tests/release-skills \
  'dot_local/share/session-recap:test_*.py' \
  tests/pi-op-shim \
  tests/op-token \
  tests/zshenv-op-token \
  tests/agent-scratch \
  tests/run-and-wake \
  tests/worktree-reap \
  tests/workstream-rank \
  tests/agent-events \
  tests/instances \
  tests/launchd-reload \
  tests/profiles \
  tests/agent-kit \
  tests/sync-harness-skills \
  tests/codex-merge \
  tests/agent-browser \
  tests/dotfiles-update \
  tests/agent-kill-guard \
  tests/pi-settings-modify \
  tests/chromium-wrapper \
  tests/viz \
  tests/axon-playbook \
  tests/spotlight-workshop \
  tests/t3-hook \
  tests/t3-hub \
  tests/hub \
  tests/pnpm-store \
  tests/agent-docker \
  tests/ssh-probe \
  tests/ci-par \
  tests/ci-main-status || status=1

# tests/kgate runs alone, not in the pool: its test_a_quota_that_never_frees_is_69_at_the_deadline_with_the_message is timing-bound and fails under pool load.
python3 -m unittest discover -s tests/kgate -v || status=1
exit "$status"
