#!/bin/sh
# Proof, on any host, with no real T3 and no real thread: a job's watcher and the job are killed together, as the kernel does when a container's
# pid 1 exits (the agent host pod restarting: everything in the container dies, detached sessions included). Then run-and-wake is called again
# the way an agent would. The old script leaves a `start` with no `end` and sends nothing; the fixed one writes an `end` (error "lost") and wakes the thread.
# State, the fake `t3` and the thread id are all scratch, so no live log or thread is touched. Never signals anything but the two pids it started.
# Usage: proof_lost_watcher.sh /path/to/run-and-wake [fixed|old]   (run it with the old script and the fixed one and compare)
# Exits 1 when the result is not the expected one: "fixed" (default) wants an `end` (lost) and one wake; "old" wants the silent loss.
set -eu
script=${1:?path to run-and-wake}
expect=${2:-fixed}
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
python3 - "$log" "$job" "$dir/delivered" "$expect" <<'PY'
import json, sys
log, job, delivered, expect = sys.argv[1:5]
events = []
for line in open(log):
    r = json.loads(line)
    if r["job"] == job:
        events.append(r)
        print("  log:", {k: r[k] for k in ("event", "exit", "signal", "error", "lost", "result") if k in r})
try:
    sent = sum(1 for line in open(delivered) if f"k:{job}" in line)
except OSError:
    sent = 0
print(f"thread received: {sent} message(s) naming the job")
names = [r["event"] for r in events]
end = next((r for r in events if r["event"] == "end"), {})
if expect == "fixed":
    ok = names == ["start", "end", "wake"] and end.get("error") == "lost" and end.get("exit") is None and sent == 1
else:
    ok = names == ["start"] and sent == 0
print("RESULT:", "as expected (" + expect + ")" if ok else "NOT as expected (" + expect + ")")
sys.exit(0 if ok else 1)
PY
