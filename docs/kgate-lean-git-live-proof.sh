#!/bin/sh
# Live proof for the lean shared git folder (dotfiles PR "kgate-lean-git"). Run after the PR is merged and chezmoi has applied ~/.local/bin/kgate.
# Makes a fresh linked worktree of the coordinator, with a second linked worktree beside it (so there is metadata to leave out; the real rr-cache is already there),
# runs one real homelab job from it, and checks: the `kgate:` line says under 100 MB shipped (a coordinator worktree was 258 MB), `git status --short` in
# the pod has 0 lines, `git log -1` in the pod is this worktree's head, and the pod's shared git folder has no rr-cache, logs or other worktrees.
# Prints PASS and exits 0, or says what is wrong and exits 1. Removes the worktrees after. Run it from anywhere.
set -eu
repo=${KGATE_PROOF_REPO:-$HOME/git/coordinator}
a=/tmp/lean-git-live-a; b=/tmp/lean-git-live-b
cleanup() { git -C "$repo" worktree remove --force "$a" 2>/dev/null || true; git -C "$repo" worktree remove --force "$b" 2>/dev/null || true; git -C "$repo" branch -D lean-git-live-a lean-git-live-b >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
git -C "$repo" fetch -q origin
git -C "$repo" worktree add -q -b lean-git-live-a "$a" origin/main
git -C "$repo" worktree add -q -b lean-git-live-b "$b" origin/main
want=$(git -C "$a" rev-parse HEAD)
out=$(mktemp)
cd "$a"
kgate -- sh -c 'echo "STATUS=$(git status --short | wc -l)"; echo "HEAD=$(git log -1 --format=%H)"; d=$(git rev-parse --git-common-dir); echo "GITDIR=$d"; for n in rr-cache logs; do [ -e "$d/$n" ] && echo "FOUND=$n"; done; echo "OTHERS=$(ls "$d/worktrees" | wc -l)"; echo "SIZE=$(du -sm "$d" | cut -f1)"' > "$out" 2>&1 || { cat "$out"; echo "FAIL: the job did not finish (not a result about the change)"; exit 1; }
cat "$out"
mb=$(sed -n 's/^kgate: .* \([0-9.]*\) MB$/\1/p' "$out" | head -1)
fail=0
[ -n "$mb" ] && [ "${mb%.*}" -lt 100 ] || { echo "FAIL: shipped ${mb:-?} MB, want under 100"; fail=1; }
grep -qx 'STATUS=0' "$out" || { echo "FAIL: git status not clean in the pod"; fail=1; }
grep -qx "HEAD=$want" "$out" || { echo "FAIL: pod head is not $want"; fail=1; }
grep -q '^FOUND=' "$out" && { echo "FAIL: rr-cache or logs shipped"; fail=1; }
grep -qx 'OTHERS=1' "$out" || { echo "FAIL: pod has other worktrees' metadata"; fail=1; }
[ "$fail" = 0 ] && echo "PASS: shipped ${mb} MB, status clean, head $want, no rr-cache, no logs, own worktree only"
rm -f "$out"
exit "$fail"
