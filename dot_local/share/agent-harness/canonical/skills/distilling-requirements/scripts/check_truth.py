#!/usr/bin/env python3
"""Truth check for the register rows of a REQUIREMENTS.md: turn each R-row into a claim the deriving-readable-docs checker takes.

usage:
  check_truth.py prepare REQUIREMENTS.md --out DIR
  check_truth.py verdicts DIR REPORTS_DIR

prepare writes DIR/register-claims.md, a doc in the shape slice.py, check_citations.py and score.py read (one `## R-n` heading, then the row's requirement
sentence and its evidence as backticked `path:line` citations), and DIR/rows.json (doc line -> R-id, and the rows it could not hand to a checker). It finds every
`path:line` or `path:start-end` in each `;` part of the evidence cell, whether backticked, in a comma list or followed by a remark. A row whose evidence is an `owner:`
source only is listed as not checked: there is nothing in the repo to read. A row with neither a citation nor an `owner:` part fails (prepare prints it and exits 1,
and verdicts counts it as a failure). A row whose evidence is a README or doc, or whose
note names a code comment, gets that source in its sentence ("(README)", "(doc)", "(code comment)"), because the check brief fails a claim that rests on one without saying so.
The checker then runs from the sibling skill, by path, unchanged: see SKILL.md step 9.
verdicts reads the checker reports in REPORTS_DIR (the `read | N.k | VERDICT | path:line` rows) and prints one verdict per R-row, the worst of its claims. A row with
no verdict counts as a failure. Exit 0 when every checked row HOLDS, 1 otherwise, 2 on bad usage. Stdlib only.
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folders are deployed; leave no __pycache__ in them
from check_shape import R_COLS, evidence_parts, tables  # noqa: E402

CITE = re.compile(r"([^\s:`,;()'\"]+):(\d+)(?:-(\d+))?")  # a path:line or path:start-end anywhere in a part: backticked, in a comma list, before a remark
DOC_PATH = re.compile(r"(^|/)(readme[^/]*|agents\.md|claude\.md)$|\.(md|rst|adoc)$|^docs?/", re.I)
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
    """(doc text, [{id, line, cited}], not checked, failed): the claims doc, which doc line holds which R-id, the owner-only rows left out and the rows with no usable evidence."""
    out, mapped, skipped, failed = ["# Register claims", "", "Each `## R-n` section is one row of the register, for the claim checker."], [], [], []
    for _, row in rows:
        cites, owner, history = [], False, False
        for kind, part in evidence_parts(row["evidence"]):
            if kind == "owner":
                owner = True
            elif kind in ("commit", "pr", "issue"):
                history = True
            elif kind == "cite":
                cites += [(m.group(1), m.group(2) + ("-" + m.group(3) if m.group(3) else "")) for m in CITE.finditer(part)]
        if not cites:
            reason = "owner evidence only, nothing in the repo to read" if owner else "history refs only: resolved by check_history_refs.py, claim not read-checked" if history else "evidence has neither a path:line nor an owner: or history part (%s)" % row["evidence"][:60]
            (skipped if owner or history else failed).append({"id": row["id"], "reason": reason})
            continue
        label = source_label(cites, row)
        sentence = row["requirement"].rstrip()
        if label:
            sentence = (sentence[:-1] if sentence.endswith(".") else sentence) + " (%s)." % label
        out += ["", "## %s" % row["id"], "%s %s" % (sentence, ", ".join("`%s:%s`" % c for c in cites))]
        mapped.append({"id": row["id"], "line": len(out), "cited": ["%s:%s" % c for c in cites]})
    return "\n".join(out) + "\n", mapped, skipped, failed


def prepare(path, out):
    with open(path, encoding="utf-8") as f:
        rows = register_rows(f.read())
    if not rows:
        print("%s: no register rows (no table with the R columns)" % path, file=sys.stderr)
        return 1
    doc, mapped, skipped, failed = to_doc(rows)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "register-claims.md"), "w", encoding="utf-8") as f:
        f.write(doc)
    with open(os.path.join(out, "rows.json"), "w", encoding="utf-8") as f:
        json.dump({"source": os.path.abspath(path), "rows": mapped, "not_checked": skipped, "failed": failed}, f, indent=2)
    print("%d rows to check, %d not checked: %s" % (len(mapped), len(skipped), ", ".join("%s (%s)" % (s["id"], s["reason"]) for s in skipped) or "none"))
    for f in failed:
        print("%s FAILED %s" % (f["id"], f["reason"]))
    return 1 if failed else 0


def verdicts(folder, reports):
    with open(os.path.join(folder, "rows.json"), encoding="utf-8") as f:
        meta = json.load(f)
    by_claim = load_slice().read_verdicts(reports)  # {"N.k": VERDICT}
    worst, bad = {}, 0
    for cid, v in by_claim.items():
        line = int(cid.split(".")[0])
        if v in SEVERITY and (line not in worst or SEVERITY.index(v) > SEVERITY.index(worst[line])):
            worst[line] = v
    for row in meta["rows"]:
        v = worst.get(row["line"])
        bad += v != "HOLDS"
        print("%s %s %s" % (row["id"], v or "NO VERDICT", " ".join(row["cited"])))
    for s in meta["not_checked"]:
        print("%s NOT CHECKED %s" % (s["id"], s["reason"]))
    failed = meta["failed"]
    for s in failed:
        print("%s FAILED %s" % (s["id"], s["reason"]))
    print("%d of %d checked rows HOLD; %d not checked; %d failed before any checker" % (len(meta["rows"]) - bad, len(meta["rows"]), len(meta["not_checked"]), len(failed)))
    return 1 if bad or failed else 0


def main(argv):
    if len(argv) == 5 and argv[1] == "prepare" and argv[3] == "--out" and os.path.isfile(argv[2]):
        return prepare(argv[2], argv[4])
    if len(argv) == 4 and argv[1] == "verdicts" and os.path.isfile(os.path.join(argv[2], "rows.json")) and os.path.isdir(argv[3]):
        return verdicts(argv[2], argv[3])
    print(__doc__.split("\n\n")[0], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
