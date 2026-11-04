#!/usr/bin/env python3
"""shadow_py_run.py: the Python control arm's entry (traces stage 2, G3).

Runs the frozen collector exactly as `agent_events.py` would, with one change made in memory: `cache_gauges` returns [].
The frozen collector has no switch to leave the five pi_cache_* families out and always sends them on a business tick,
and editing it would break the reference SHA. So this file replaces the function after import and calls the unchanged
`agent_events.main`. It changes none of the frozen files.

It refuses to run (exit 2) unless the frozen files beside it hash to the lines in reference.sha256 and the modules it
loaded are those files. Its own directory is first on sys.path, so its imports resolve to nothing else.

The arm has its own state dir and its own database (plan 3.3, and section 3: no step points a collector at the live
ones). So, for every verb including `status`, it also refuses (exit 64, nothing written) when AGENT_EVENTS_STATE_DIR is
unset, when that resolves to the live state dir, or when the database it would open (--db, else the default) is the
live one. Paths are compared after symlinks are resolved.

    shadow_py_run.py run          # same arguments as agent_events.py
"""
import argparse
import hashlib
import os
import pwd
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = "reference.sha256"
MODULES = ("agent_events", "agent_events_metrics", "agent_events_review", "agent_events_show")
sys.dont_write_bytecode = True


class Refused(Exception):
    """The frozen files are not the reference. The message says which."""


class LiveTarget(Exception):
    """The state dir or the database is missing or is the live one. The message says which."""


def live_dirs():
    """Where the real collector keeps its state and data: the home defaults of this user, and of $HOME if it differs
    (symlinks resolved). The LaunchAgent sets no XDG_* variable, and the arm uses XDG_DATA_HOME for its own database,
    so XDG_* does not name a live directory."""
    homes = {Path(pwd.getpwuid(os.getuid()).pw_dir), Path.home()}
    out = set()
    for home in homes:
        out.add(home / ".local/state/agent-events")
        out.add(home / ".local/share/agent-events")
    return {p.resolve() for p in out}


def inside_live(path):
    """The live directory that `path` is, or is inside, after symlinks are resolved; else None."""
    p = Path(path).resolve()
    return next((live for live in sorted(live_dirs()) if p == live or live in p.parents), None)


def check_isolated(ae, argv):
    """Raise LiveTarget unless this run has its own state dir and its own database."""
    raw = os.environ.get("AGENT_EVENTS_STATE_DIR")
    if not raw or not raw.strip():
        raise LiveTarget("AGENT_EVENTS_STATE_DIR is not set; the collector would use the live state dir")
    state = Path(raw).resolve()
    if inside_live(state):
        raise LiveTarget(f"AGENT_EVENTS_STATE_DIR {state} is the live state dir ({inside_live(state)})")
    pre = argparse.ArgumentParser(add_help=False)  # only --db; the collector's own parser would exit 0 on --help before we looked
    pre.add_argument("--db")
    db_arg = pre.parse_known_args(argv)[0].db
    db = Path(db_arg) if db_arg else ae.default_db()
    if inside_live(db):
        raise LiveTarget(f"the database {Path(db).resolve()} is the live one ({inside_live(db)}); pass --db or set XDG_DATA_HOME")


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_manifest(directory):
    """{file name: sha256} from reference.sha256 (sha256sum format) beside the frozen files."""
    path = Path(directory) / MANIFEST
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise Refused(f"cannot read {path}: {exc.strerror or type(exc).__name__}") from None
    out = {}
    for line in lines:
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            raise Refused(f"{path}: not a sha256sum line: {line!r}")
        out[parts[1]] = parts[0]
    missing = [m + ".py" for m in MODULES if m + ".py" not in out]
    if missing:
        raise Refused(f"{path} has no line for {', '.join(missing)}")
    return out


def load_frozen(directory=HERE):
    """Hash every frozen file in `directory`, import the collector from there only, check the loaded files, and
    return (agent_events, agent_events_metrics). Raises Refused on any difference."""
    directory = Path(directory).resolve()
    manifest = read_manifest(directory)
    for name, want in sorted(manifest.items()):
        have = sha256_file(directory / name) if (directory / name).is_file() else "missing"
        if have != want:
            raise Refused(f"{directory / name} is {have}, reference.sha256 says {want}")
    sys.path.insert(0, str(directory))
    for name in MODULES:  # a module imported earlier from elsewhere would be reused below; drop it
        sys.modules.pop(name, None)
    import agent_events
    import agent_events_metrics
    for name in MODULES:
        mod = sys.modules.get(name)
        if mod is None:
            continue
        loaded = Path(mod.__file__).resolve()
        if loaded.parent != directory or sha256_file(loaded) != manifest[name + ".py"]:
            raise Refused(f"loaded {loaded}, not the reference {directory / (name + '.py')}")
    return agent_events, agent_events_metrics


def main(argv):
    try:
        ae, metrics = load_frozen()
    except Refused as exc:
        print(f"shadow_py_run: refusing to run: {exc}", file=sys.stderr)
        return 2
    try:
        check_isolated(ae, argv)
    except LiveTarget as exc:
        print(f"shadow_py_run: refusing to run: {exc}", file=sys.stderr)
        return 64
    metrics.cache_gauges = lambda con, now: []  # export() looks the name up when it runs, so this reaches it
    return ae.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
