#!/bin/sh
# Proof on a Linux host with a systemd user manager, without touching the real T3: a scratch unit stands in for t3code.service, and a fake `t3` says
# "Could not reach the T3 Code server" while that unit is stopped. A real run-and-wake job (in its own scope, in T3's agents slice) is started, the
# "T3" is stopped, the job ends while it is down, and "T3" comes back. Prints whether the thread got the wake.
# Usage: proof_t3_outage.sh /path/to/run-and-wake   (run it with the old script and the fixed one and compare)
set -eu
script=${1:?path to run-and-wake}
dir=$(mktemp -d /tmp/rw-proof.XXXXXX)
unit=rw-proof-t3-$$
trap 'systemctl --user stop "$unit.service" >/dev/null 2>&1 || :; rm -rf "$dir"' EXIT
mkdir -p "$dir/bin" "$dir/state"
cat > "$dir/bin/t3" <<EOF
#!/bin/sh
if ! systemctl --user is-active --quiet $unit.service; then
  echo "Could not reach the T3 Code server at http://127.0.0.1:3773. fetch failed" >&2
  exit 1
fi
cat >> "$dir/delivered"
EOF
chmod +x "$dir/bin/t3"
up() { systemd-run --user --quiet --unit="$unit" sleep 3600; }
env_run() { env -u HERDR_PANE_ID -u PI_SESSION_FILE XDG_STATE_HOME="$dir/state" T3CODE_THREAD_ID=proof-thread T3CODE_CLI_PATH="$dir/bin/t3" RUN_AND_WAKE_T3_RETRY=1:60 "$@"; }
up
out=$(env_run python3 "$script" -- sh -c "while [ ! -e $dir/go ]; do sleep 0.2; done; echo done")
job=$(echo "$out" | sed -n 's/.* job \([^ ]*\) started.*/\1/p')
echo "job $job started; scope: $(systemctl --user is-active "run-and-wake-$job.scope")"
systemctl --user stop "$unit.service"                       # T3 goes away (a restart)
echo "T3 stopped; job scope still: $(systemctl --user is-active "run-and-wake-$job.scope")"
touch "$dir/go"                                             # the job ends while T3 is down
sleep 3
echo "while T3 is down, delivered: $(cat "$dir/delivered" 2>/dev/null | grep -c . || true) message(s)"
up                                                          # T3 is back
sleep 4
echo "after T3 is back, delivered: $(cat "$dir/delivered" 2>/dev/null | grep -c . || true) message(s)"
python3 - "$dir/state/run-and-wake/log.jsonl" "$job" <<'PY'
import json, sys
for line in open(sys.argv[1]):
    r = json.loads(line)
    if r["job"] == sys.argv[2] and r["event"] in ("end", "wake"):
        print("  log:", {k: r[k] for k in ("event", "exit", "signal", "result", "attempts", "error") if k in r})
PY
