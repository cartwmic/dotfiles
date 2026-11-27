#!/usr/bin/env python3
"""Truth check for the register rows of a REQUIREMENTS.md: turn each R-row into a claim the deriving-readable-docs checker takes.

usage:
  check_truth.py prepare REQUIREMENTS.md --out DIR [--since PREVIOUS_DIR]
  check_truth.py verdicts DIR REPORTS_DIR

prepare writes DIR/register-claims.md, a doc in the shape slice.py, check_citations.py and score.py read (one `## R-n` heading, then the row's requirement
sentence and its evidence as backticked `path:line` citations), and DIR/rows.json (doc line -> R-id, and the rows it could not hand to a checker). It finds every
`path:line` or `path:start-end` in each `;` part of the evidence cell, whether backticked or followed by a remark. A row whose evidence is an `owner:`
source only is listed as not checked: there is nothing in the repo to read. A row with neither a citation nor an `owner:` part fails (prepare prints it and exits 1,
and verdicts counts it as a failure). A row whose evidence is a README or doc, or whose
note names a code comment, gets that source in its sentence ("(README)", "(doc)", "(code comment)"), because the check brief fails a claim that rests on one without saying so.
A row whose evidence includes `owner:interview` and a `path:line` states what the owner requires, not what the code does: the last sentence of its requirement ends "(owner requirement)", and its
note goes to DIR/owner-notes.txt (`N | R-id | note`, N the doc line of the row: every claim N.k of that line is judged with it), not into the sentence, so a date or a number in the note cannot fail check_citations.py.
The checker reads the note with the sentence under references/check-brief-owner-rows.md. prepare says how many such rows there are.
The checker then runs from the sibling skill, by path, unchanged: see references/truth-check.md.
--since PREVIOUS_DIR (a fix round after the first) is the work folder of the round before, where `verdicts` has run: a row whose requirement, evidence and note are
as they were, and that HOLDS there, is not written to the claims doc again (rows.json lists it under `carried`, and `verdicts` prints it HOLDS, unchanged). Every other row is
checked again: a row a fix round changed, a new row, and a row that did not hold and was left as it was.
verdicts also writes DIR/verdicts.json (each row's key and worst verdict) for the next round's --since.
verdicts reads the checker reports in REPORTS_DIR (the `read | N.k | VERDICT | path:line` rows) and prints one verdict per R-row, the worst of its claims. A row with
no verdict counts as a failure. Exit 0 when every checked row HOLDS, 1 otherwise, 2 on bad usage. Stdlib only.
Log: each run appends one JSON line (runlog.py: script, action `check-truth`, outcome ok, failed or refused; step prepare or verdicts, and the row counts).
"""
import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folders are deployed; leave no __pycache__ in them
from check_shape import R_COLS, evidence_parts, tables  # noqa: E402
from logged import logged  # noqa: E402

CITE = re.compile(r"([^\s:`,;()'\"]+):(\d+)(?:-(\d+))?")  # a path:line or path:start-end anywhere in a part: backticked or before a remark
DOC_PATH = re.compile(r"(^|/)(readme[^/]*|agents\.md|claude\.md)$|\.(md|rst|adoc)$|^docs?/", re.I)
OWNER_LABEL = "owner requirement"
SEVERITY = ["HOLDS", "OVERSTATED", "UNSUPPORTED", "WRONG"]


def codemap_script(name):
    """The sibling skill's script by path. The skill folders are linked into several harnesses, so the path is resolved from this file's real location."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "deriving-readable-docs", "scripts", name)


def load_slice():
    spec = importlib.util.spec_from_file_location("codemap_slice", codemap_script("slice.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def register_rows(text):
    """[(doc_line, {column: cell})] for every row of the register table (the table with the R columns)."""
    rows = []
    for _, head, body in tables(text.splitlines()):
        if [c.lower() for c in head] == R_COLS:
            rows += [(n, dict(zip(R_COLS, cells))) for n, cells in body if len(cells) == len(R_COLS)]
    return rows


def source_label(cites, row):
    """What the sentence must say about where it comes from: a repo doc or README it cites, or a code comment the note names."""
    if any(DOC_PATH.search(p) for p, _ in cites):
        return "README" if any(re.search(r"readme", p, re.I) for p, _ in cites) else "doc"
    return "code comment" if re.search(r"\bcomment\b", row["note"], re.I) else ""


def to_doc(rows):
    """(doc text, [{id, line, cited}], not checked, failed, owner notes): the claims doc, which doc line holds which R-id, the owner-only rows left out, the rows with no usable evidence and the
    notes of the rows that state an owner requirement ([(doc line, R-id, note)])."""
    out, mapped, skipped, failed, notes = ["# Register claims", "", "Each `## R-n` section is one row of the register, for the claim checker."], [], [], [], []
    for _, row in rows:
        cites, owner, history, interview = [], False, False, False
        for kind, part in evidence_parts(row["evidence"]):
            if kind == "owner":
                owner = True
                interview = interview or part.startswith("owner:interview")
            elif kind in ("commit", "pr", "issue"):
                history = True
            elif kind == "cite":
                cites += [(m.group(1), m.group(2) + ("-" + m.group(3) if m.group(3) else "")) for m in CITE.finditer(part)]
        if not cites:
            reason = "owner evidence only, nothing in the repo to read" if owner else "history refs only: to be resolved by check_history_refs.py, claim not read-checked" if history else "evidence has neither a path:line nor an owner: or history part (%s)" % row["evidence"][:60]
            (skipped if owner or history else failed).append({"id": row["id"], "reason": reason})
            continue
        tags = [t for t in (source_label(cites, row), OWNER_LABEL if interview else "") if t]
        sentence = row["requirement"].rstrip()
        if tags:
            sentence = (sentence[:-1] if sentence.endswith(".") else sentence) + "".join(" (%s)" % t for t in tags) + "."
        out += ["", "## %s" % row["id"], "%s %s" % (sentence, ", ".join("`%s:%s`" % c for c in cites))]
        mapped.append({"id": row["id"], "line": len(out), "cited": ["%s:%s" % c for c in cites]})
        if interview:
            notes.append((len(out), row["id"], row["note"].replace("\n", " ").strip()))
    return "\n".join(out) + "\n", mapped, skipped, failed, notes


def row_key(row):
    """What the checker is shown of a row: if none of it changed, a verdict of the last round still stands."""
    return hashlib.sha1("\0".join((row["requirement"], row["evidence"], row["note"])).encode("utf-8")).hexdigest()


def carried_rows(rows, previous):
    """(rows to check, [{id, key}] that held unchanged in PREVIOUS_DIR); raises FileNotFoundError when verdicts has not run there."""
    with open(os.path.join(previous, "verdicts.json"), encoding="utf-8") as f:
        before = json.load(f)
    keep, carried = [], []
    for n, row in rows:
        old = before.get(row["id"])
        if old and old["verdict"] == "HOLDS" and old["key"] == row_key(row):
            carried.append({"id": row["id"], "key": old["key"]})
        else:
            keep.append((n, row))
    return keep, carried


def prepare(path, out, stats, since=None):
    with open(path, encoding="utf-8") as f:
        rows = register_rows(f.read())
    if not rows:
        print("%s: no register rows (no table with the R columns)" % path, file=sys.stderr)
        stats["reason"] = "no register rows"
        return 1
    carried = []
    if since:
        try:
            rows, carried = carried_rows(rows, since)
        except (OSError, ValueError, KeyError):
            print("%s: no usable verdicts.json (run `verdicts` in that folder first)" % since, file=sys.stderr)
            stats["reason"] = "no verdicts.json in --since"
            return 2
    keys = {r["id"]: row_key(r) for _, r in rows}
    doc, mapped, skipped, failed, notes = to_doc(rows)
    for m in mapped:
        m["key"] = keys[m["id"]]
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "register-claims.md"), "w", encoding="utf-8") as f:
        f.write(doc)
    with open(os.path.join(out, "owner-notes.txt"), "w", encoding="utf-8") as f:
        f.write("".join("%d | %s | %s\n" % n for n in notes))
    with open(os.path.join(out, "rows.json"), "w", encoding="utf-8") as f:
        json.dump({"source": os.path.abspath(path), "rows": mapped, "not_checked": skipped, "failed": failed, "carried": carried}, f, indent=2)
    stats.update(rows=len(mapped), not_checked=len(skipped), failed=len(failed), carried=len(carried))
    if carried:
        print("%d rows unchanged since %s and holding there, not checked again: %s" % (len(carried), since, ", ".join(c["id"] for c in carried)))
    print("%d rows to check, %d not checked: %s" % (len(mapped), len(skipped), ", ".join("%s (%s)" % (s["id"], s["reason"]) for s in skipped) or "none"))
    if notes:
        print("%d owner-requirement rows (%s): give each checker %s and %s as well" % (len(notes), ", ".join(n[1] for n in notes), os.path.join(HERE, "..", "references", "check-brief-owner-rows.md"), os.path.join(out, "owner-notes.txt")))
    for f in failed:
        print("%s FAILED %s" % (f["id"], f["reason"]))
    return 1 if failed else 0


def verdicts(folder, reports, stats):
    with open(os.path.join(folder, "rows.json"), encoding="utf-8") as f:
        meta = json.load(f)
    by_claim = load_slice().read_verdicts(reports)  # {"N.k": VERDICT}
    worst, bad = {}, 0
    for cid, v in by_claim.items():
        line = int(cid.split(".")[0])
        if v in SEVERITY and (line not in worst or SEVERITY.index(v) > SEVERITY.index(worst[line])):
            worst[line] = v
    judged = {}
    for row in meta["rows"]:
        v = worst.get(row["line"])
        bad += v != "HOLDS"
        judged[row["id"]] = {"key": row.get("key"), "verdict": v}
        print("%s %s %s" % (row["id"], v or "NO VERDICT", " ".join(row["cited"])))
    carried = meta.get("carried", [])
    for c in carried:
        judged[c["id"]] = {"key": c["key"], "verdict": "HOLDS"}
        print("%s HOLDS unchanged since the last round" % c["id"])
    with open(os.path.join(folder, "verdicts.json"), "w", encoding="utf-8") as f:
        json.dump(judged, f, indent=2)
    for s in meta["not_checked"]:
        print("%s NOT CHECKED %s" % (s["id"], s["reason"]))
    failed = meta["failed"]
    for s in failed:
        print("%s FAILED %s" % (s["id"], s["reason"]))
    stats.update(rows=len(meta["rows"]), holding=len(meta["rows"]) - bad, not_checked=len(meta["not_checked"]), failed=len(failed))
    print("%d of %d checked rows HOLD; %d not checked; %d failed before any checker%s" % (len(meta["rows"]) - bad, len(meta["rows"]), len(meta["not_checked"]), len(failed),
          "; %d unchanged since the last round, not checked again" % len(carried) if carried else ""))
    return 1 if bad or failed else 0


def cli(argv, stats):
    if len(argv) in (5, 7) and argv[1] == "prepare" and argv[3] == "--out" and os.path.isfile(argv[2]) and (len(argv) == 5 or argv[5] == "--since"):
        stats["step"] = "prepare"
        return prepare(argv[2], argv[4], stats, argv[6] if len(argv) == 7 else None)
    if len(argv) == 4 and argv[1] == "verdicts" and os.path.isfile(os.path.join(argv[2], "rows.json")) and os.path.isdir(argv[3]):
        stats["step"] = "verdicts"
        return verdicts(argv[2], argv[3], stats)
    print(__doc__.split("\n\n")[0], file=sys.stderr)
    stats["reason"] = "usage"
    return 2


if __name__ == "__main__":
    sys.exit(logged("check_truth.py", "check-truth", cli, sys.argv))
