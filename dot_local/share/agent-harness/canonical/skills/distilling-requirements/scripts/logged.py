"""Run a script's CLI and leave one JSON line in the skill's log (runlog.py, design principle 14).

    sys.exit(logged("check_shape.py", "check-shape", cli, sys.argv))

`cli(argv, stats)` returns the exit code and may put the key figures of the run in `stats` (they go into the line as they are). A `reason` in `stats`
means the script refused to do the work. Outcome: ok on exit 0, refused on exit 2 or when `stats` has a reason, failed otherwise (a check found problems).
Not a CLI of its own. Stdlib only.
"""
from runlog import log_run


def logged(script, action, cli, argv):
    stats = {}
    code = cli(argv, stats)
    outcome = "ok" if code == 0 else "refused" if code == 2 or "reason" in stats else "failed"
    log_run(script, action, outcome, exit=code, **stats)
    return code
