#!/bin/sh
# Linux checks for this repo, the same command the CI `tests` job runs: the five node tests, then every
# Linux Python suite through scripts/ci-par.py (tests/heavy-gate one test per process, the rest one
# discover process per suite), then tests/kgate and tests/pi-mcp-lazy alone, as two processes at once.
#
# Installs nothing. It assumes these are on PATH: chezmoi (the render tests), zsh, lsof and rsync (the
# agent-scratch, zshenv and agent-docker tests), node, and python3 (3.14). tests/omarchy-remote-unlock also
# needs sshd (openssh-server) and skips without it; tests/le-verify-clean needs bwrap (bubblewrap) and skips without it. CI installs chezmoi and the
# apt packages first. On another Linux host, install them yourself, then run this from the repo.
#
# Usage: scripts/ci-linux.sh   (from any directory; it cd's to the repo root). Exit 1 if any step fails.
set -eu

cd "$(dirname "$0")/.."
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-${TMPDIR:-/tmp}/ci-pycache}"   # bytecode goes here, not into the checkout (kgate sets it already)

# systemd-analyze --user needs XDG_RUNTIME_DIR, or it exits 1 ("Failed to initialize manager") before it reads the unit, and the
# unit tests that only look at its stderr pass without checking anything. A login session sets it (GitHub's runner has one); a kgate
# pod has none. Leave an existing directory alone. Otherwise make a private one for this user.
if [ -z "${XDG_RUNTIME_DIR:-}" ] || [ ! -d "$XDG_RUNTIME_DIR" ]; then
  XDG_RUNTIME_DIR="${TMPDIR:-/tmp}/xdg-runtime-$(id -u)"
  mkdir -p "$XDG_RUNTIME_DIR"
  chmod 0700 "$XDG_RUNTIME_DIR"
  export XDG_RUNTIME_DIR
fi

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
# A Pi extension is TypeScript: node 22.6 or newer runs it by stripping the types (CI's setup-node step gives it).
node --experimental-strip-types --disable-warning=ExperimentalWarning --test dot_pi/private_agent/extensions/coordinator-helper-gate/index.test.ts

status=0
python3 scripts/ci-par.py \
  --per-test tests/heavy-gate \
  tests/qmd \
  tests/pi-idle-rss \
  tests/pi-agents-render \
  tests/coordinator-helper-gate \
  tests/instructions-profile \
  tests/pi-settings-render \
  tests/release-skills \
  tests/pr-body-check \
  tests/pr-open \
  tests/intent-review-check \
  tests/review-intent \
  tests/known-limits-check \
  tests/mcp-ticket-lookup \
  'dot_local/share/session-recap:test_*.py' \
  tests/pi-op-shim \
  tests/seed-op-connect-token \
  tests/op-token \
  tests/zshenv-op-token \
  tests/agent-scratch \
  tests/run-and-wake \
  tests/video-rename \
  tests/worktree-reap \
  tests/workstream-rank \
  tests/session-cost \
  tests/schedules-check \
  tests/agent-events \
  tests/session-keepalive \
  tests/mistakes-report \
  tests/le-verify-clean \
  tests/instances \
  tests/launchd-reload \
  tests/profiles \
  tests/container-mode \
  tests/design-principles \
  tests/agent-kit \
  tests/sync-harness-skills \
  tests/codex-merge \
  tests/rustdesk \
  tests/agent-browser \
  tests/dotfiles-update \
  tests/agent-kill-guard \
  tests/config-show \
  tests/disposition-check \
  tests/stop-running-jobs \
  tests/homelab-chat \
  tests/computer-use-seat \
  tests/pi-settings-modify \
  tests/chromium-wrapper \
  tests/shx \
  tests/axon-playbook \
  tests/spotlight-workshop \
  tests/t3-hook \
  tests/cursor \
  tests/agent-host \
  tests/t3-hub \
  tests/seat-context \
  tests/t3-pin \
  tests/t3-pin-check \
  tests/t3-service \
  tests/pi-lead \
  tests/hub \
  tests/pnpm-store \
  tests/workshop-enabled \
  tests/leak-guard \
  tests/agent-docker \
  tests/ssh-probe \
  tests/omarchy-remote-unlock \
  tests/hypr-screen-share \
  tests/agent-desktop \
  tests/hill-climb \
  tests/deriving-readable-docs \
  tests/designing-the-smallest-version \
  tests/distilling-requirements \
  tests/reviewing-prs \
  tests/triaging-automated-review \
  tests/git-credential \
  tests/tmp-on-disk \
  tests/initramfs-ssh-unlock \
  tests/ci-par \
  tests/mcp-pins \
  tests/release-pins \
  tests/ci-main-status \
  tests/ci-main-status-any-repo \
  tests/ci-main-status-gitea \
  tests/ci-main-status-threads \
  tests/kgate-split \
  tests/test-edit-check \
  tests/untested-hunks-check || status=1

# tests/kgate and tests/pi-mcp-lazy run after the pool, as two processes at once, and not in the pool: their
# timing-bound tests (test_a_quota_that_never_frees_is_69_at_the_deadline_with_the_message in kgate,
# test_second_stop_still_reaches_a_helper_reparented_by_the_first in pi-mcp-lazy) fail under pool load.
# Each suite streams into its own log file. The files stay on disk, so a hang or a cancel still leaves what
# each one printed. Both logs print in full, kgate's first, once both have finished.
logs=$(mktemp -d "${TMPDIR:-/tmp}/ci-linux-logs.XXXXXX")
echo "[ci-linux] per-suite logs: $logs"
python3 -m unittest discover -s tests/kgate -v >"$logs/kgate.log" 2>&1 &
kgate_pid=$!
python3 -m unittest discover -s tests/pi-mcp-lazy -v >"$logs/pi-mcp-lazy.log" 2>&1 &
lazy_pid=$!
wait "$kgate_pid" || status=1
wait "$lazy_pid" || status=1
cat "$logs/kgate.log" "$logs/pi-mcp-lazy.log"
exit "$status"
