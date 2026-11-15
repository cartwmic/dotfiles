#!/bin/sh
# Proof against the REAL T3: a job started from this T3 thread must survive a T3 restart and its wake must arrive in this thread. Nobody has to act during the outage:
# each job ends by itself the moment the T3 port stops answering, so it ends inside the restart.
#   1. proof_t3_restart.sh launch /path/to/old/run-and-wake /path/to/fixed/run-and-wake      (from the thread that should get the wakes)
#   2. restart T3 (this drops every running session): systemctl --user restart t3code
#   3. proof_t3_restart.sh check                                                              (after T3 is back)
# Expected: the old script's job: scope survived, end, wake "failed" (Could not reach the T3 Code server), nothing delivered. The fixed script's job: end,
# wake "sent" with attempts above 1, one message in the thread. Send back any wake `error` text that is not "Could not reach the T3 Code server" or "No running T3 Code server".
set -eu
state=${XDG_STATE_HOME:-$HOME/.local/state}/run-and-wake
keep=/tmp/rw-restart-proof.jobs
port=${T3_PORT:-3773}
case ${1:-} in
launch)
  : > "$keep"
  for which in old fixed; do
    script=$2; [ "$which" = fixed ] && script=$3
    out=$(python3 "$script" -- sh -c "while curl -s -o /dev/null -m 1 http://127.0.0.1:$port/; do sleep 0.3; done")
    job=$(echo "$out" | sed -n 's/.* job \([^ ]*\) started.*/\1/p')
    echo "$which $job" >> "$keep"
    echo "$which: job $job, scope $(systemctl --user is-active "run-and-wake-$job.scope")"
  done
  echo "now: systemctl --user restart t3code   (then: $0 check)"
  ;;
check)
  while read -r which job; do
    echo "== $which $job: scope $(systemctl --user is-active "run-and-wake-$job.scope" 2>&1 || true)"
    python3 - "$state/log.jsonl" "$job" <<'PY'
import json, sys
for line in open(sys.argv[1]):
    r = json.loads(line)
    if r["job"] == sys.argv[2]:
        print("  ", {k: r[k] for k in ("ts", "event", "exit", "signal", "stopped", "result", "attempts", "error") if k in r})
PY
  done < "$keep"
  ;;
*) echo "usage: $0 launch OLD FIXED | check" >&2; exit 2 ;;
esac
