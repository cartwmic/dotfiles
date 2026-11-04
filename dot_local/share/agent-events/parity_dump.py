#!/usr/bin/env python3
"""parity_dump.py: the canonical dump of the frozen Python collector for one corpus (traces stage 2, plan 3.0).

    parity_dump.py dump --sessions-dir DIR --out OUT [--now EPOCH ...] [--replay-ticks N --replay-start EPOCH]
    parity_dump.py fp   --roots DIR --machine LABEL         # approved-project list and fingerprint, as JSON

`dump` builds a scratch database from DIR with the frozen collector (the three reference files, checked against
reference.sha256 first) and writes, into the empty directory OUT:

    tables/<table>.jsonl      every table, rows sorted by primary key; path columns relative to DIR, mtime_ns zeroed
    meta.json                 schema version, reference file hashes, approved-project list, fingerprint, row counts
    collect.json              collect(con): families and points sorted by Unicode code point
    gauges-<now>.json         cache_gauges(con, now), one file for each --now
    project-map.json          every distinct cwd -> project_of, export_project
    tick-<k>/state.json       with --replay-ticks: the accounting state after tick k ...
    tick-<k>/payload.json     ... and the OTLP body that tick would send (points sorted; the value of
                              pi_agent_events_database_bytes zeroed, like mtime_ns: the size of the SQLite file depends
                              on the length of the corpus path stored in it and on the SQLite build)

A second run over the same corpus gives byte-identical files: the clock is pinned to the tick's `now`, and nothing
else in a dump depends on the machine. The scratch state directory and database are made fresh in a temporary
directory; nothing is read from or written to the live agent-events directories.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reference_common as rc  # noqa: E402
import shadow_py_run  # noqa: E402


def key_of(value):
    """A total order over SQLite values: NULL, then numbers, then text."""
    if value is None:
        return (0, 0, "")
    if isinstance(value, (int, float)):
        return (1, value, "")
    return (2, 0, str(value))


def table_rows(con, table, root):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    pk = [r[1] for r in sorted(con.execute(f"PRAGMA table_info({table})"), key=lambda r: r[5]) if r[5]] or cols
    rows = []
    for raw in con.execute(f"SELECT {', '.join(cols)} FROM {table}"):
        row = dict(zip(cols, raw))
        for c, v in row.items():  # the corpus root can sit inside a value too (the fallback dedupe_key), so cut it everywhere
            if isinstance(v, str) and root in v:
                row[c] = v.replace(root + "/", "").replace(root, "")
        if "mtime_ns" in row:
            row["mtime_ns"] = 0
        rows.append(row)
    rows.sort(key=lambda r: tuple(key_of(r[c]) for c in pk))
    return rows


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rc.dumps(obj) + "\n")


def family_json(m):
    pts = []
    for labels, value in m["points"]:
        if m["type"] == "histogram":
            counts, total, n = value
            value = {"counts": list(counts), "n": n, "sum": total}
        pts.append({"labels": labels, "value": value})
    pts.sort(key=lambda p: rc.dumps(p["labels"]))
    out = {"name": m["name"], "type": m["type"], "points": pts}
    if m["type"] == "histogram":
        out["bounds"] = list(m["bounds"])
    return out


def families_json(metrics):
    return sorted((family_json(m) for m in metrics), key=lambda f: f["name"])


DB_BYTES = "pi_agent_events_database_bytes"


def payload_json(payload):
    """The OTLP body with metrics sorted by name and points by attributes; timeUnixNano is kept. The database-size gauge is zeroed."""
    body = json.loads(json.dumps(payload))
    for rm in body["resourceMetrics"]:
        for sm in rm["scopeMetrics"]:
            sm["metrics"].sort(key=lambda m: m["name"])
            for m in sm["metrics"]:
                if m["name"] == DB_BYTES:
                    for p in m["gauge"]["dataPoints"]:
                        p["asDouble"] = 0.0
                for kind in ("gauge", "sum", "histogram"):
                    if kind in m:
                        m[kind]["dataPoints"].sort(key=lambda p: rc.dumps(p["attributes"]))
    return body


class Clock(types.SimpleNamespace):
    """Stands in for the `time` module inside agent_events_metrics so self_metrics sees the tick's now."""

    def __init__(self):
        import time as real
        super().__init__(now=0.0, real=real)

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(self.real, name)


def setup_env(args, scratch):
    """Everything the collector reads from the environment, set before it is imported."""
    for var in ("AGENT_EVENTS_OTLP_ENDPOINT", "AGENT_EVENTS_PROJECTS", "AGENT_EVENTS_CACHE_GAUGES"):
        os.environ.pop(var, None)
    live = os.environ.get("AGENT_EVENTS_STATE_DIR")
    if live:
        rc.refuse_live(live, "AGENT_EVENTS_STATE_DIR")
    state = scratch / "state"
    state.mkdir()
    roots = args.roots
    if not roots:
        roots = str(scratch / "roots")
        Path(roots).mkdir()
    traces = Path(args.traces_dir) if args.traces_dir else scratch / "no-traces"
    os.environ.update(AGENT_EVENTS_STATE_DIR=str(state), AGENT_EVENTS_PROJECT_ROOTS=roots,
                      AGENT_TRACES_DIR=str(traces), AGENT_EVENTS_MACHINE=args.machine, TZ="UTC")
    if args.home:
        os.environ["HOME"] = args.home
    if args.projects:
        os.environ["AGENT_EVENTS_PROJECTS"] = args.projects


def cmd_dump(args):
    sessions = Path(args.sessions_dir).resolve()
    if not sessions.is_dir():
        raise SystemExit(f"no sessions directory at {sessions}")
    out = rc.empty_dir(args.out, "--out")
    if out.resolve() == sessions or sessions in out.resolve().parents:
        raise SystemExit("refusing: --out is inside the sessions directory")
    scratch = Path(tempfile.mkdtemp(prefix="parity-dump-"))
    try:
        setup_env(args, scratch)
        ae, metrics = shadow_py_run.load_frozen(HERE)
        db = scratch / "events.sqlite"
        res = ae.build(sessions, db)
        clock = Clock()
        metrics.time = clock
        con = ae.connect(db, readonly=True)
        root = str(sessions)
        counts = {}
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        for t in tables:
            rows = table_rows(con, t, root)
            counts[t] = len(rows)
            path = out / "tables" / f"{t}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("".join(rc.dumps(r) + "\n" for r in rows))
        write(out / "collect.json", families_json(metrics.collect(con)))
        for now in args.now:
            write(out / f"gauges-{int(now) if now == int(now) else now}.json", {"now": now, "families": families_json(metrics.cache_gauges(con, now))})
        cwds = sorted({r[0] for r in con.execute("SELECT DISTINCT cwd FROM sessions") if r[0] is not None})
        write(out / "project-map.json", {c: {"project_of": ae.project_of(c), "export_project": ae.export_project(c)} for c in cwds})
        if args.replay_ticks:
            replay(args, ae, metrics, con, db, out, clock)
        manifest = shadow_py_run.read_manifest(HERE)
        write(out / "meta.json", {
            "schema_version": ae.SCHEMA_VERSION, "meta_table": dict(con.execute("SELECT key, value FROM meta")),
            "reference": manifest, "approved_projects": sorted(ae.approved_projects()),
            "fp": metrics.fingerprint(), "machine": args.machine, "row_counts": counts, "now": args.now,
            "parsed": res["parsed"], "malformed_lines": res["malformed_lines"]})
        con.close()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"dump written to {out}: {sum(counts.values())} rows in {len(counts)} tables, "
          f"{len(args.now)} gauge file(s), {args.replay_ticks} replay tick(s)")
    return 0


def replay(args, ae, metrics, con, db, out, clock):
    """Run the real export() K times at now = start + k * step with persist=True, capturing each body instead of sending it."""
    state = {}
    if args.state_in:
        state = json.loads(Path(args.state_in).read_text())
        if not metrics._valid_state(state):
            raise SystemExit(f"{args.state_in} is not a state file the collector accepts")
    status = {"epoch_ns": int(args.replay_start * 1e9), "last_build_ok_ts": args.replay_start,
              "last_build_seconds": 0, "consecutive_build_failures": 0}
    bodies = []
    metrics.post = lambda url, payload, timeout=30: bodies.append(payload_json(payload)) or 0
    for k in range(args.replay_ticks):
        now = args.replay_start + k * args.replay_step
        clock.now = now
        bodies.clear()
        metrics.export(con, str(db), status, "http://replay.invalid/", now=now, state=state, business=True, persist=True)
        write(out / f"tick-{k}" / "payload.json", bodies[0])
        write(out / f"tick-{k}" / "state.json", state)


def cmd_fp(args):
    scratch = Path(tempfile.mkdtemp(prefix="parity-fp-"))
    try:
        setup_env(args, scratch)
        _, metrics = shadow_py_run.load_frozen(HERE)
        import agent_events as ae
        print(json.dumps({"approved_projects": sorted(ae.approved_projects()), "fp": metrics.fingerprint(),
                          "machine": args.machine}))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("dump", "fp"):
        p = sub.add_parser(name)
        p.add_argument("--roots", help="AGENT_EVENTS_PROJECT_ROOTS (default: an empty scratch directory)", required=name == "fp")
        p.add_argument("--projects", help="AGENT_EVENTS_PROJECTS")
        p.add_argument("--machine", default="personal")
        p.add_argument("--traces-dir", help="AGENT_TRACES_DIR for the review logs (default: none)")
        p.add_argument("--home", help="HOME for the run, so project labels do not depend on this machine")
    d = sub.choices["dump"]
    d.add_argument("--sessions-dir", required=True)
    d.add_argument("--out", required=True, help="an empty or missing directory")
    d.add_argument("--now", type=float, nargs="*", default=[], help="epoch seconds for gauges-<now>.json")
    d.add_argument("--replay-ticks", type=int, default=0)
    d.add_argument("--replay-start", type=float, default=1_790_000_600.0)
    d.add_argument("--replay-step", type=float, default=120.0)
    d.add_argument("--state-in", help="start the replay from this state file (a copy), not from nothing")
    args = ap.parse_args(argv)
    try:
        return {"dump": cmd_dump, "fp": cmd_fp}[args.cmd](args)
    except shadow_py_run.Refused as exc:
        print(f"parity_dump: refusing to run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
