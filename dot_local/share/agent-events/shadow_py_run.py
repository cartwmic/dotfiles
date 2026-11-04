#!/usr/bin/env python3
"""shadow_py_run.py: the Python control arm's entry (traces stage 2, G3).

Runs the frozen collector exactly as `agent_events.py` would, with one change made in memory: `cache_gauges` returns [].
The frozen collector has no switch to leave the five pi_cache_* families out and always sends them on a business tick,
and editing it would break the reference SHA. So this file replaces the function after import and calls the unchanged
`agent_events.main`. It changes none of the frozen files.

It refuses to run (exit 2) unless the frozen files beside it hash to the lines in reference.sha256 and the modules it
loaded are those files. Its own directory is first on sys.path, so its imports resolve to nothing else.

    shadow_py_run.py run          # same arguments as agent_events.py
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = "reference.sha256"
MODULES = ("agent_events", "agent_events_metrics", "agent_events_review", "agent_events_show")
sys.dont_write_bytecode = True


class Refused(Exception):
    """The frozen files are not the reference. The message says which."""


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
    metrics.cache_gauges = lambda con, now: []  # export() looks the name up when it runs, so this reaches it
    return ae.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
