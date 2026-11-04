#!/usr/bin/env python3
"""rollback_drill.py: can the frozen Python collector still load a state file the TS port wrote? (traces stage 2, G4, plan 3.4)

    rollback_drill.py --state COPY --status COPY --original-status FILE --machine LABEL --py-db DB \\
                      --sessions-dir CLONE --scratch EMPTYDIR --out RESULT.json

Everything runs on copies, in --scratch. --state and --status must be copies, not the live files; --py-db is only read
(through `VACUUM INTO` over a read-only connection). The drill:

  0. copies the Python database, then runs Python's build over a clone of the current corpus into the copy, and times
     it. That is the catch-up a real rollback pays. Over --catchup-limit (600 s) the drill exits 1.
  1. load_state() must not report the state lost.
  2. runs Python's export() once against a loopback receiver (the real post path), then the build and export() again.
  3. after tick 1: the key set is unchanged, fp and seeded are equal, seeded_families are kept, every exported value
     is at least the state's `sent`, and status.json loads with epoch_ns exact: the same integer, digit for digit, as in
     --original-status (read only), a status.json that Python wrote and nothing has rounded (the frozen copy from freeze.sh in G2,
     the T0 backup at cutover). A value that went through a JS Number (…456768 became …456800) is a different integer
     and fails; so does a float or a missing value.
  4. after tick 2: each series moved by exactly seen - last (1e-9 relative), so no history lands as activity.

--machine must be the label the state was written under (`test-personal-ts` for a shadow state, `personal` for a copy
of the live state): the fingerprint includes it, and any other label starts a baseline for a reason that is not the port.
Exit 0: every step held. 1: a step failed (the result file says which). 2: the frozen files are not the reference.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import reference_common as rc  # noqa: E402
import shadow_py_run  # noqa: E402


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(a, b):
    return abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1e-300) or a == b


def series_key(name, labels):
    return name + "|" + json.dumps(sorted(labels.items()))


def sent_vectors(body):
    """{series key: exported vector} from an OTLP body; a histogram vector is bucketCounts + [sum, count], as in the state."""
    out = {}
    for rm in body["resourceMetrics"]:
        for sm in rm["scopeMetrics"]:
            for m in sm["metrics"]:
                kind = "sum" if "sum" in m else "histogram" if "histogram" in m else None
                if kind is None:
                    continue
                for p in m[kind]["dataPoints"]:
                    labels = {a["key"]: a["value"]["stringValue"] for a in p["attributes"]}
                    vec = [float(p["asDouble"])] if kind == "sum" else \
                        [float(c) for c in p["bucketCounts"]] + [float(p["sum"]), float(p["count"])]
                    out[series_key(m["name"], labels)] = vec
    return out


def read_epoch(path):
    """epoch_ns from a status.json as written: a plain JSON integer or None (a float, a string or a missing key is None)."""
    raw = Path(path).read_text()
    value = json.loads(raw).get("epoch_ns")
    if isinstance(value, int) and not isinstance(value, bool) and re.search(r'"epoch_ns"\s*:\s*%d\b(?![.eE])' % value, raw):
        return value
    return None


def epoch_is_exact(path, expected):
    """True when epoch_ns in `path` is the integer `expected`, digit for digit. Returns (ok, the value found).
    Python wrote `expected` as int(time.time() * 1e9), an exact double; a Number round trip prints it as another integer."""
    value = read_epoch(path)
    return value is not None and value == expected, value


def step(result, name, ok, detail=""):
    result["steps"][name] = {"ok": bool(ok), "detail": detail}
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""))
    return ok


def drill(args, between=None):
    """Run the four steps; return the result dict. `between` is called after tick 1 so a caller can add activity."""
    for label, path in (("--state", args.state), ("--status", args.status)):
        rc.refuse_live(path, label)
    expected = read_epoch(args.original_status)
    if expected is None:
        raise SystemExit(f"refusing: --original-status {args.original_status} has no integer epoch_ns to compare with")
    scratch = rc.empty_dir(args.scratch, "--scratch")
    state_dir, db = scratch / "state", scratch / "python.sqlite"
    state_dir.mkdir()
    traces = scratch / "no-traces"
    os.environ.pop("AGENT_EVENTS_OTLP_ENDPOINT", None)
    os.environ.update(AGENT_EVENTS_STATE_DIR=str(state_dir), AGENT_EVENTS_MACHINE=args.machine,
                      AGENT_EVENTS_PROJECT_ROOTS=args.roots or str(scratch / "roots"), AGENT_TRACES_DIR=str(traces))
    if not args.roots:
        (scratch / "roots").mkdir()
    if args.projects:
        os.environ["AGENT_EVENTS_PROJECTS"] = args.projects
    if args.home:
        os.environ["HOME"] = args.home
    ae, metrics = shadow_py_run.load_frozen(HERE)
    result = {"ok": False, "machine": args.machine, "input_state_sha256": sha256(args.state),
              "reference_sha256": sha256(HERE / shadow_py_run.MANIFEST), "steps": {}}

    # 0. a current Python database
    src = sqlite3.connect(f"file:{args.py_db}?mode=ro", uri=True)
    try:
        src.execute("VACUUM INTO ?", (str(db),))
    finally:
        src.close()
    started = time.time()
    built = ae.build(Path(args.sessions_dir), db)
    result["catchup_seconds"] = round(time.time() - started, 2)
    result["catchup_parsed"] = built["parsed"]
    shutil.copyfile(args.state, state_dir / "export_state.json")
    shutil.copyfile(args.status, state_dir / "status.json")
    if not step(result, "0 catch-up within limit", result["catchup_seconds"] <= args.catchup_limit,
                f"{result['catchup_seconds']} s, {built['parsed']} files parsed, limit {args.catchup_limit} s"):
        return result

    # 1. the state loads
    state, lost = metrics.load_state()
    if not step(result, "1 load_state is not lost", not lost, "the state file was rejected" if lost else ""):
        return result
    before = copy.deepcopy(state)
    status = metrics.load_status()

    # 2. one export at tick 1
    with rc.Receiver() as receiver:
        con = ae.connect(db, readonly=True)
        now1 = args.now or time.time()
        metrics.export(con, str(db), status, receiver.url, now=now1, state=state, business=True, persist=True)
        after1 = copy.deepcopy(state)
        con.close()
        sent1 = sent_vectors(receiver.bodies[0])
        status["last_export_ok_ts"] = now1
        metrics.save_status(status)

        # 3. what tick 1 must show
        problems = []
        created = sorted(set(state["series"]) - set(before["series"]))
        gone = sorted(set(before["series"]) - set(state["series"]))
        if created or gone:
            problems.append(f"key set changed: {len(created)} new, {len(gone)} gone"
                            + (f" (e.g. {created[0][:80]})" if created else ""))
        if before.get("fp") != state.get("fp") or before.get("seeded") != state.get("seeded"):
            problems.append(f"fp/seeded changed: {before.get('fp')}/{before.get('seeded')} -> {state.get('fp')}/{state.get('seeded')}")
        if not set(before.get("seeded_families") or []) <= set(state.get("seeded_families") or []):
            problems.append("seeded_families lost")
        low = [k for k, e in before["series"].items()
               if k not in sent1 or len(sent1[k]) != len(e["sent"]) or any(v < s - 1e-9 * max(abs(s), 1) for v, s in zip(sent1[k], e["sent"]))]
        if low:
            problems.append(f"{len(low)} exported value(s) below the state's sent (e.g. {low[0][:80]})")
        exact, epoch = epoch_is_exact(state_dir / "status.json", expected)
        if not exact:
            problems.append(f"status.json epoch_ns is {epoch!r}, not the original {expected}")
        if not step(result, "2-3 tick 1 keeps keys, fp, seeded, sent, epoch_ns", not problems, "; ".join(problems)):
            return result

        # 4. tick 2 adds only the increment
        if between:
            between()
        built = ae.build(Path(args.sessions_dir), db)
        con = ae.connect(db, readonly=True)
        status = metrics.load_status()
        now2 = max(now1 + 120, args.now2 or 0)
        metrics.export(con, str(db), status, receiver.url, now=now2, state=state, business=True, persist=True)
        con.close()
        sent2 = sent_vectors(receiver.bodies[1])
        problems, moved = [], 0
        for key, e in state["series"].items():
            old = after1["series"].get(key)
            if old is None:
                if key in sent2 and any(v != 0 for v in sent2[key]):
                    problems.append(f"new series sent nonzero: {key[:80]}")
                continue
            ok1 = old["ok"]
            rise = [c - l if (all(c2 >= l2 for c2, l2 in zip(e["seen"], old["last"])) and ok1) else 0
                    for c, l in zip(e["seen"], old["last"])]
            got = [b - a for a, b in zip(sent1[key], sent2[key])]
            moved += any(r for r in rise)
            if not all(close(g, r) for g, r in zip(got, rise)):
                problems.append(f"{key[:80]} moved {got[:3]}, expected {rise[:3]}")
        if not step(result, "4 tick 2 adds only seen - last", not problems,
                    "; ".join(problems[:3]) if problems else f"{len(state['series'])} series, {moved} moved"):
            return result
    result["ok"] = True
    return result


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True, help="a COPY of the TS-written export_state.json")
    ap.add_argument("--status", required=True, help="a COPY of the matching status.json")
    ap.add_argument("--original-status", required=True,
                    help="a status.json Python wrote, never rounded (frozen copy / T0 backup): its epoch_ns is the one to match exactly")
    ap.add_argument("--machine", required=True, help="the label the state was written under")
    ap.add_argument("--py-db", required=True, help="the Python database to copy (read only)")
    ap.add_argument("--sessions-dir", required=True, help="a clone of the current corpus")
    ap.add_argument("--scratch", required=True, help="an empty directory")
    ap.add_argument("--out", required=True)
    ap.add_argument("--roots", help="AGENT_EVENTS_PROJECT_ROOTS (the frozen roots fixture)")
    ap.add_argument("--projects", help="AGENT_EVENTS_PROJECTS")
    ap.add_argument("--home")
    ap.add_argument("--catchup-limit", type=float, default=600.0)
    ap.add_argument("--now", type=float, help="epoch seconds for tick 1 (default: the clock)")
    ap.add_argument("--now2", type=float)
    args = ap.parse_args(argv)
    try:
        result = drill(args)
    except shadow_py_run.Refused as exc:
        print(f"rollback_drill: refusing to run: {exc}", file=sys.stderr)
        return 2
    Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print("drill " + ("passed" if result["ok"] else "FAILED") + f"; result in {args.out}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
