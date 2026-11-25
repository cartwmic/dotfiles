"""One JSON line per script run, in a log that outlasts the terminal (design principle 14).

    from runlog import log_run
    log_run("score.py", "score", "refused", reason="...", claims=12)

The line holds ts (UTC), script, action, outcome, duration_s (seconds since this module loaded, which is the start of the run) and
the numbers the caller passes. It is appended to `${XDG_STATE_HOME:-~/.local/state}/<skill folder name>/log.jsonl`, so counting lines
answers how often each action ran and how often it was refused. A log that cannot be written never changes the script's exit code.
Stdlib only. A copy of this file sits in every skill whose scripts log; tests/deriving-readable-docs/test_runlog.py fails when they differ.
"""
import datetime
import json
import os
import time

SKILL = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # .../<skill>/scripts/runlog.py
STARTED = time.monotonic()


def log_path():
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, SKILL, "log.jsonl")


def log_run(script, action, outcome, **numbers):
    """Append one record. `outcome` is ok, failed (a check found problems) or refused (the script would not do the work); `numbers` are the key figures of the run."""
    record = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "script": script, "action": action,
              "outcome": outcome, "duration_s": round(time.monotonic() - STARTED, 3), **numbers}
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass  # the log is a record, not a dependency of the run
