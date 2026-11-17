"""The call log of the gh wrapper: one JSON line per gh call at exit, and a start line first for a watch, so a watch killed before it exits still shows.
docs/gh-wrapper.md has the record.

A layer for lib/gh_layers.py. It writes the log and changes nothing else: a write that fails raises, the seam reports it on standard error and the call
goes on. The budget layer's facts (urgent, budget, budget_left) come from call.notes; with no budget layer they are null.

Never the arguments, the bodies or the tokens. `class` is the command's name (gh_classify masks the ids in an API path). A calling process is its program
name, plus the file name of its first argument when that argument is an existing file (a script it runs, with or without an extension), and nothing
else from its command line. A relative first argument is looked up in the calling process's own working directory (/proc/<pid>/cwd on Linux; on a Mac
there is no cheap equivalent, so it is looked up in this process's).
"""
import datetime
import json
import os
import subprocess
import sys
import time

LOG_NAME = "calls.jsonl"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
WATCH_CLASSES = ("run watch",)


def log_path(environ=os.environ):
    state = environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "gh-wrapper", LOG_NAME)


def max_bytes(environ=os.environ):
    try:
        return max(1, int(environ["GH_WRAPPER_LOG_MAX"]))
    except (KeyError, ValueError):
        return DEFAULT_MAX_BYTES


# ---- the record: reads the clock, the working directory, the environment and whether argv[1] is a file, and writes nothing; proc() reads the calling processes ----------------------------------------

def is_watch(call):
    return call.klass in WATCH_CLASSES or "--watch" in call.args


def interval_of(args):
    """The --interval (or -i) gh will get: an int when it is one, else the text as given; None when the call sets none."""
    for i, arg in enumerate(args):
        if arg.startswith("--interval="):
            value = arg.split("=", 1)[1]
        elif arg in ("--interval", "-i") and i + 1 < len(args):
            value = args[i + 1]
        else:
            continue
        return int(value) if value.isdigit() else value
    return None


def caller(argv, cwd=None):
    """A calling process as the log names it: its program, and the file name of its first argument when that argument is an existing file that is not an option. Never its other arguments.
    `cwd` is the process's working directory, where a relative first argument is looked up; None looks it up in this process's."""
    if not argv:
        return None
    names = [os.path.basename(argv[0])]
    if len(argv) > 1 and not argv[1].startswith("-") and os.path.isfile(os.path.join(cwd or "", argv[1])):
        names.append(os.path.basename(argv[1]))
    return " ".join(names)


def record(call, event, parent, grandparent):
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = None
    entry = {"event": event,
             "utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "id": call.id, "class": call.klass, "bucket": call.bucket,
             "urgent": call.notes.get("urgent"), "budget": call.notes.get("budget"), "budget_left": call.notes.get("budget_left"),
             "action": call.action, "rewrite": call.rewrite,
             "rc": call.rc if event == "exit" else None,
             "dur_s": round(time.time() - call.t0, 3) if event == "exit" else None,
             "who": os.environ.get("COORDINATOR_WHO") or os.environ.get("GH_CALLER") or None,
             "parent": parent, "grandparent": grandparent, "cwd": cwd}
    if is_watch(call):
        entry["interval"] = interval_of(call.args)
    return entry


# ---- the edges: the calling processes, and the file ---------------------------------------------------------------------------------------------------

def proc(pid):
    """(parent pid, argv) of a process: from /proc on Linux, from ps elsewhere. (None, []) when it cannot be read."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/%d/stat" % pid) as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                return ppid, [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        out = subprocess.run(["ps", "-o", "ppid=,command=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout.split(None, 1)
        return int(out[0]), out[1].split()
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, []


def proc_cwd(pid):
    """The working directory of a process, from /proc on Linux; None elsewhere or when it cannot be read."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        return os.readlink("/proc/%d/cwd" % pid)
    except OSError:
        return None


def named(pid):
    """(parent pid, caller() name) of a process, its relative script looked up in its own working directory."""
    ppid, argv = proc(pid)
    return ppid, caller(argv, proc_cwd(pid) if argv else None)


def ancestry():
    """(parent, grandparent) of this process, each as caller() names it."""
    grand_pid, parent = named(os.getppid())
    _, grandparent = named(grand_pid) if grand_pid else (None, None)
    return parent, grandparent


def append(entry, environ=os.environ):
    path = log_path(environ)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    try:
        if os.path.getsize(path) >= max_bytes(environ):
            os.replace(path, path + ".1")      # one old file is kept; the next rotation replaces it
    except FileNotFoundError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def write(call, event):
    parent, grandparent = ancestry()
    append(record(call, event, parent, grandparent))


# ---- the layer hooks ----------------------------------------------------------------------------------------------------------------------------------

def before(call):
    if is_watch(call):
        write(call, "start")


def after(call):
    write(call, "exit")
