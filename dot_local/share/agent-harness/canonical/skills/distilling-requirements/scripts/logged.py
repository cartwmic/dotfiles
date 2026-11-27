"""Run a script's CLI and leave one JSON line in the skill's log (runlog.py, design principle 14).

    sys.exit(logged("check_shape.py", "check-shape", cli, sys.argv))

`cli(argv, stats)` returns the exit code and may put the key figures of the run in `stats` (they go into the line as they are). A `reason` in `stats`
means the script refused to do the work. Outcome: ok on exit 0, refused on exit 2 or when `stats` has a reason, failed otherwise (a check found problems).
A script that raises leaves a line too: outcome crashed, exit 1, `error` the exception's class name; the exception then goes on.
Not a CLI of its own. Stdlib only.
"""
import sys

sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from runlog import log_run


def logged(script, action, cli, argv):
    stats = {}
    try:
        code = cli(argv, stats)
    except SystemExit as e:  # a bare sys.exit(n) inside cli is an exit code, not a crash
        code = e.code if isinstance(e.code, int) else 0 if e.code is None else 1
        log_run(script, action, outcome(code, stats), exit=code, **stats)
        raise
    except BaseException as e:
        log_run(script, action, "crashed", exit=1, error=type(e).__name__, **stats)
        raise
    log_run(script, action, outcome(code, stats), exit=code, **stats)
    return code


def outcome(code, stats):
    return "ok" if code == 0 else "refused" if code == 2 or "reason" in stats else "failed"
