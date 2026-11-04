#!/usr/bin/env python3
"""cache_ref.py: Python's cache gauges over a given database, as JSON (traces stage 2: the oracle of G5 check (k), and G1(f)).

    cache_ref.py --scratch DIR --db DIR/events.sqlite --now 1790000000 [--now 1790000120 ...]

For each `now` it prints what the frozen collector's `cache_gauges(con, now)` and `miss_streaks(con, now)` return, with
points sorted by label. The database is opened read-only. Project labels depend on AGENT_EVENTS_PROJECT_ROOTS and
AGENT_EVENTS_PROJECTS, so run it with the same values as the sender it checks.

It refuses a --db that is not inside --scratch, and a --scratch that is a live directory (exit 64), and, like shadow_py_run.py, exits 2 unless the frozen
modules it imports match reference.sha256.
"""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import shadow_py_run  # noqa: E402  (the frozen-file check lives there)


def points(pts):
    out = [{"labels": labels, "value": value} for labels, value in pts]
    return sorted(out, key=lambda p: json.dumps(p["labels"], sort_keys=True))


def inside(path, parent):
    path, parent = Path(path).resolve(), Path(parent).resolve()
    return path == parent or parent in path.parents


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--scratch", required=True, help="the directory the database was built in; --db must be inside it")
    ap.add_argument("--now", type=float, nargs="+", required=True, help="epoch seconds; one or many")
    args = ap.parse_args(argv)
    live = shadow_py_run.inside_live(args.scratch)
    if live:
        print(f"cache_ref: --scratch {args.scratch} is the live directory {live}; refusing", file=sys.stderr)
        return 64
    if not inside(args.db, args.scratch):
        print(f"cache_ref: --db {args.db} is not inside --scratch {args.scratch}; refusing", file=sys.stderr)
        return 64
    if not Path(args.db).is_file():
        print(f"cache_ref: no database at {args.db}", file=sys.stderr)
        return 64
    try:
        ae, metrics = shadow_py_run.load_frozen(HERE)
    except shadow_py_run.Refused as exc:
        print(f"cache_ref: refusing to run: {exc}", file=sys.stderr)
        return 2
    con = ae.connect(args.db, readonly=True)
    try:
        results = []
        for now in args.now:
            families = metrics.cache_gauges(con, now)
            streaks = metrics.miss_streaks(con, now)
            results.append({"now": now,
                            "gauges": [{"name": m["name"], "type": m["type"], "points": points(m["points"])} for m in families],
                            "miss_streaks": points(streaks)})
    finally:
        con.close()
    print(json.dumps({"reference_sha256": shadow_py_run.sha256_file(HERE / shadow_py_run.MANIFEST),
                      "results": results}, sort_keys=True, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
