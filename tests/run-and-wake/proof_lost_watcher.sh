#!/bin/sh
# Proof, on any host, with no real T3 and no real thread: a job's watcher and the job are killed together, as the kernel does when a container's
# pid 1 exits (the agent host pod restarting: everything in the container dies, detached sessions included). Then run-and-wake is called again
# the way an agent would. The old script leaves a `start` with no `end` and sends nothing; the fixed one writes an `end` (error "lost") and wakes the thread.
# State, the fake `t3` and the thread id are all scratch, so no live log or thread is touched. Never signals anything but the two pids it started.
# Usage: proof_lost_watcher.sh /path/to/run-and-wake   (run it with the old script and the fixed one and compare)
set -eu
script=${1:?path to run-and-wake}
dir=$(mktemp -d /tmp/rw-lost.XXXXXX)
trap 'rm -rf "$dir"' EXIT
mkdir -p "$dir/bin" "$dir/state"
cat > "$dir/bin/t3" <<EOT
#!/bin/sh
cat >> "$dir/delivered"
EOT
chmod +x "$dir/bin/t3"
env_run() { env -u HERDR_PANE_ID -u PI_SESSION_FILE XDG_STATE_HOME="$dir/state" T3CODE_THREAD_ID=proof-thread T3CODE_CLI_PATH="$dir/bin/t3" RUN_AND_WAKE_COALESCE=0 "$@"; }
env_run python3 "$script" -- sleep 300 >/dev/null
log=$dir/state/run-and-wake/log.jsonl
job=$(python3 -c "import json,sys; print(next(json.loads(l)['job'] for l in open('$log')))")
jobpid=$(python3 -c "import json; print(json.loads(open('$log').readline())['pid'])")
pids="$(ps -o ppid= -p "$jobpid" | tr -d ' ') $jobpid"   # the watcher is the job's parent
echo "job $job started; killing its watcher and the job together (pids: $pids)"
# shellcheck disable=SC2086
kill -KILL $pids
sleep 1
env_run python3 "$script" -- true >/dev/null   # any later call: the next agent that starts a job
sleep 1
python3 - "$log" "$job" <<'PY'
import json, sys
for line in open(sys.argv[1]):
    r = json.loads(line)
    if r["job"] == sys.argv[2]:
        print("  log:", {k: r[k] for k in ("event", "exit", "signal", "error", "lost", "result") if k in r})
PY
echo "thread received: $(grep -c "k:$job" "$dir/delivered" 2>/dev/null || true) message(s) naming the job"
