"""Import this first in every test module. The scripts log each run (runlog.py, design principle 14), so a test run must never touch the owner's real log.
On import (once per run) it points HOME and XDG_STATE_HOME at a scratch folder and stops bytecode writes (this process and the subprocesses).
It also records the real log's size and mtime, and when the run ends it fails the run if either changed."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

_state_home = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
REAL_LOG = Path(_state_home, "distilling-requirements", "log.jsonl")


def _stat(path):
    try:
        s = path.stat()
        return (s.st_size, s.st_mtime_ns)
    except OSError:
        return None


_before = _stat(REAL_LOG)
SCRATCH = tempfile.mkdtemp(prefix="runlog-support-")
STATE = os.path.join(SCRATCH, "state")
os.environ["HOME"] = SCRATCH
os.environ["XDG_STATE_HOME"] = STATE
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
atexit.register(shutil.rmtree, SCRATCH, True)


def _tripwire():
    after = _stat(REAL_LOG)
    if after != _before:
        sys.stderr.write("FAILED: the test run changed the real log %s (size, mtime: %s -> %s)\n" % (REAL_LOG, _before, after))
        sys.stderr.flush()
        os._exit(1)


atexit.register(_tripwire)  # registered last, so it runs first
