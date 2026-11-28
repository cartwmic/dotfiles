#!/bin/sh
# 50 runs of every suite that ran chezmoi on the real source tree, each alone, with the Linux job's chezmoi (every connection refused) first on PATH.
# usage: tests/support/repeat-offline.sh RUNS JOBS   (from the repository root; SUITES="qmd shx" runs only those)
set -u
RUNS=$1; JOBS=$2
SUITES=${SUITES:-"agent-host agent-kit qmd session-cost coordinator-helper-gate agent-kill-guard agent-desktop tmp-on-disk chromium-wrapper container-mode session-keepalive homelab-chat lead-turn-end schedules-check shx initramfs-ssh-unlock computer-use-seat support"}
OUT=${TMPDIR:-/tmp}/repeat-offline
rm -rf "$OUT"; mkdir -p "$OUT"
CI_OFFLINE_REAL_CHEZMOI=$(command -v chezmoi)
export CI_OFFLINE_REAL_CHEZMOI
export PATH="$PWD/scripts/ci-offline:$PATH"
export OUT
i=1
while [ "$i" -le "$RUNS" ]; do
  for s in $SUITES; do echo "$i $s"; done
  i=$((i+1))
done | xargs -P "$JOBS" -L1 sh -c 'd="$OUT/$0-$1"; mkdir -p "$d/cache" "$d/tmp"; XDG_CACHE_HOME="$d/cache" TMPDIR="$d/tmp" python3 -m unittest discover -s "tests/$1" >"$d/log" 2>&1; echo "$? $0 $1" >>"$OUT/results"; rm -rf "$d/cache" "$d/tmp"'
total=$(wc -l <"$OUT/results")
failed=$(grep -vc '^0 ' "$OUT/results")
echo "suite-runs: $total  failed: $failed"
echo "failures by suite:"; grep -v '^0 ' "$OUT/results" | awk '{print $3}' | sort | uniq -c
echo "failed runs naming an archive address or a refused connection:"; grep -lE 'proxyconnect|\.tar\.gz' "$OUT"/*/log 2>/dev/null | wc -l
echo "failing tests (count over all runs):"
for l in $(grep -v '^0 ' "$OUT/results" | awk '{print $2"-"$3}'); do grep -hE '^(FAIL|ERROR):' "$OUT/$l/log" | sed "s/^/$l /"; done | sed 's/^[0-9]*-//' | sort | uniq -c | sort -rn
echo "the first failing log of each failing suite:"
for l in $(grep -v '^0 ' "$OUT/results" | awk '{print $2"-"$3}' | sort -u); do echo "== $l"; grep -hE -A12 '^(FAIL|ERROR):' "$OUT/$l/log" | head -30; done 2>/dev/null | head -80
