#!/usr/bin/env python3
"""Check a saved live run of agent-desktop on one device (criteria c12, c13, c14).

usage: check_record.py --device omarchy|mac-mini|work-mac|g14 --record FILE

Exit 0 and one stable line on stdout when the record is complete and was made against the source files that are in this
tree now:
    device=D score=N/14 pass=ROWS fail=ROW:ERROR;... [not_offered=ROWS]
Exit 1 with one reason on stderr (nothing on stdout) otherwise. Exit 2 for a bad command line.

A record (schema 1) is written by tests/agent-desktop/live_run.py. All files it names are relative to the folder that
holds record.json. See live_run.py (build_record) for the shape.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # importing proof_sources must not leave a __pycache__ in the tree
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ROWS = ["J0", "J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8", "N1", "N2", "N3", "N4", "N5"]
STATUSES = ("pass", "fail", "not_offered")
REQUIRED = {  # rows that must pass
    "omarchy": ROWS[:9],
    "mac-mini": ROWS[:9] + ["N1", "N2"],
    "work-mac": ROWS[:9] + ["N1", "N2"],  # judged like a Mac: the same rows as the Mac mini
    "g14": ROWS[:9] + ["N1", "N2"],
}
OMARCHY_NOT_OFFERED = ["N1", "N2", "N3", "N4"]
SETTINGS_MUST_HOLD = ("Console lock display off timeout", "Require a password on wakeup")


class Reject(Exception):
    pass


def reject_unless(cond, msg):
    if not cond:
        raise Reject(msg)


def load_sources():
    spec = importlib.util.spec_from_file_location("proof_sources", HERE / "proof_sources.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def one_line(text, limit=200):
    t = re.sub(r"\s+", " ", str(text)).strip()
    return t if len(t) <= limit else t[: limit - 3] + "..."


def is_dict(x):
    return isinstance(x, dict)


def file_in(base, rel, what):
    reject_unless(isinstance(rel, str) and rel, "%s names no file" % what)
    p = (base / rel).resolve()
    reject_unless(base.resolve() in p.parents, "%s: %s is outside the record folder" % (what, rel))
    reject_unless(p.is_file(), "%s: file %s is missing" % (what, rel))
    return p


def check_command(base, c, what):
    reject_unless(is_dict(c), "%s: a command entry is not an object" % what)
    reject_unless(isinstance(c.get("command"), str) and c["command"].strip(), "%s: a command entry has no command text" % what)
    reject_unless(isinstance(c.get("exit"), int) and not isinstance(c.get("exit"), bool), "%s: command %r has no exit code" % (what, c["command"]))
    file_in(base, c.get("output_file"), what)


def check_png(base, rel, what):
    p = file_in(base, rel, what)
    with open(p, "rb") as f:
        reject_unless(f.read(8) == PNG_SIGNATURE, "%s: %s is not a PNG (bad signature)" % (what, rel))


def check_install(base, device, install):
    reject_unless(is_dict(install), "install steps are missing")
    fresh = install.get("fresh")
    reject_unless(is_dict(fresh), "install: the fresh install step is missing")
    check_command(base, fresh, "install fresh")
    reject_unless(fresh["exit"] == 0, "install: the fresh install step exited %s" % fresh["exit"])
    if device == "g14":
        second = install.get("second")
        reject_unless(is_dict(second), "install: the second install run is missing")
        check_command(base, second, "install second")
        reject_unless(second["exit"] == 0, "install: the second install run exited %s" % second["exit"])
        reject_unless(second.get("changed") is False, "install: the second install run changed something (changed != false)")


def check_rows(base, device, rows):
    reject_unless(isinstance(rows, list), "rows are missing")
    by_id = {}
    for r in rows:
        reject_unless(is_dict(r) and isinstance(r.get("id"), str), "a row entry has no id")
        reject_unless(r["id"] in ROWS, "unknown row %s" % r["id"])
        reject_unless(r["id"] not in by_id, "row %s appears twice" % r["id"])
        by_id[r["id"]] = r
    for rid in ROWS:
        reject_unless(rid in by_id, "missing row %s" % rid)
    for rid in ROWS:
        r = by_id[rid]
        st = r.get("status")
        reject_unless(st in STATUSES, "row %s has status %r (one of pass, fail, not_offered)" % (rid, st))
        cmds = r.get("commands", [])
        reject_unless(isinstance(cmds, list), "row %s: commands is not a list" % rid)
        for c in cmds:
            check_command(base, c, "row %s" % rid)
        shots = r.get("screenshots", [])
        reject_unless(isinstance(shots, list), "row %s: screenshots is not a list" % rid)
        for s in shots:
            check_png(base, s, "row %s screenshot" % rid)
        if st == "fail":
            reject_unless(isinstance(r.get("error"), str) and r["error"].strip(), "row %s failed with no error text" % rid)
        if rid in REQUIRED[device]:
            reject_unless(st == "pass", "required row %s is %s%s" % (rid, st, (": " + one_line(r.get("error", ""))) if r.get("error") else ""))
        if st == "pass":
            reject_unless(cmds, "row %s passed with no command saved" % rid)
        if device == "omarchy":
            if rid in OMARCHY_NOT_OFFERED:
                reject_unless(st == "not_offered", "row %s must be not_offered on omarchy (it is %s)" % (rid, st))
        elif rid not in REQUIRED[device]:
            reject_unless(st != "not_offered", "row %s is not_offered but %s offers it" % (rid, device))
    return by_id


def check_g14(base, rec):
    s = rec.get("settings")
    reject_unless(is_dict(s) and is_dict(s.get("before")) and is_dict(s.get("after")), "g14: settings before/after are missing")
    reject_unless(s["before"] and s["after"], "g14: settings before/after are empty")
    reject_unless(s["before"] == s["after"], "g14: settings changed between before and after")
    lines = s["before"].get("powercfg")
    reject_unless(isinstance(lines, list), "g14: settings hold no powercfg list")
    text = "\n".join(str(x) for x in lines)
    for needle in SETTINGS_MUST_HOLD:
        reject_unless(needle in text, "g14: settings do not hold the lock setting %r" % needle)
    checks = rec.get("checks")
    reject_unless(is_dict(checks), "g14: checks are missing")
    for name, want_exit in (("locked_screen", 1), ("ui_via_task", 0)):
        c = checks.get(name)
        reject_unless(is_dict(c), "g14: check %s is missing" % name)
        check_command(base, c, "check " + name)
        reject_unless(c.get("status") == "pass", "g14: check %s did not pass (%s)" % (name, c.get("status")))
        reject_unless(c["exit"] == want_exit, "g14: check %s exited %s, expected %s" % (name, c["exit"], want_exit))


def check(device, record_path):
    try:
        rec = json.loads(Path(record_path).read_text())
    except (OSError, ValueError) as e:
        raise Reject("record %s cannot be read: %s" % (record_path, one_line(e)))
    reject_unless(is_dict(rec), "record is not a JSON object")
    base = Path(record_path).resolve().parent
    reject_unless(rec.get("schema") == 1, "record schema is %r, expected 1" % rec.get("schema"))
    reject_unless(rec.get("device") == device, "record is for device %r, not %r" % (rec.get("device"), device))
    ps = load_sources()
    try:
        now, _files = ps.digest(device, ROOT)
    except ps.NoSources as e:
        raise Reject(str(e))
    reject_unless(rec.get("source_digest") == now, "source digest differs: the run was made against other %s files than the ones in this tree" % device)
    check_install(base, device, rec.get("install"))
    by_id = check_rows(base, device, rec.get("rows"))
    if device == "g14":
        check_g14(base, rec)
    passed = [r for r in ROWS if by_id[r]["status"] == "pass"]
    failed = [r for r in ROWS if by_id[r]["status"] == "fail"]
    notoff = [r for r in ROWS if by_id[r]["status"] == "not_offered"]
    line = "device=%s score=%d/14 pass=%s fail=%s" % (
        device, len(passed), ",".join(passed) or "-",
        ";".join("%s:%s" % (r, one_line(by_id[r]["error"])) for r in failed) or "-",
    )
    if notoff:
        line += " not_offered=" + ",".join(notoff)
    return line


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--device", required=True, choices=("omarchy", "mac-mini", "work-mac", "g14"))
    ap.add_argument("--record", required=True)
    a = ap.parse_args(argv)
    try:
        line = check(a.device, a.record)
    except Reject as e:
        sys.stderr.write("check_record: REJECTED (%s): %s\n" % (a.device, one_line(e, 400)))
        return 1
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
