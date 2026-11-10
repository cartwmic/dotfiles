#!/usr/bin/env python3
"""Check a REQUIREMENTS.md against references/output-shape.md.

Usage: python3 check_shape.py REQUIREMENTS.md
Exit 0 and "ok" when clean; exit 1 and one problem per line otherwise.
Checks structure only (columns, ids, enums, evidence present, counts, dangling refs),
not whether a requirement is true.
"""
import re
import sys

R_COLS = ["id", "lens", "kind", "durability", "status", "requirement", "evidence", "check", "fit", "enforced", "note"]
U_COLS = ["id", "invariant relied on", "relied on at", "missing guard", "violation reachable", "evidence"]
F_COLS = ["id", "machine/ref", "impact", "confidence", "path to it", "evidence", "proposed regression test", "issue group"]
I_COLS = ["id", "invariant", "enforced by", "evidence"]
T_COLS = ["from", "event", "guard", "to", "effects", "evidence"]
S_COLS = ["state", "meaning", "evidence"]
ENUMS = {
    "lens": {"product", "behavioral", "technical"},
    "kind": {"explicit", "implicit"},
    "durability": {"enduring", "incidental", "unclear"},
    "status": {"proposed", "accepted", "disputed"},
    "fit": {"full", "partial", "none", "title"},
    "impact": {"high", "medium", "low"},
    "confidence": {"confirmed", "suspected"},
}


ENFORCED = {"R": {"yes", "partial", "no"}, "I": {"type", "check", "constraint", "test", "none"}}


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def tables(lines):
    """Yield (start_line_no, header_cells, rows[(line_no, cells)]) for each pipe table."""
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head, rows, j = cells(lines[i]), [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append((j + 1, cells(lines[j])))
                j += 1
            yield i + 1, head, rows
            i = j
        else:
            i += 1


def main(path):
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()
    if not text.lstrip().startswith("```text"):
        print("file must start with the header fence (```text); put the title below it")
        return 1
    errs = []
    hdr = dict(re.findall(r"^(\w[\w-]*):\s*(.+)$", text.split("```", 2)[1], re.M))
    if hdr.get("shape") != "requirements/1":
        errs.append("header: shape must be requirements/1")
    for k in ("repo", "commit", "scope", "date", "not-read", "counts"):
        if k not in hdr:
            errs.append(f"header: missing {k}")
    ids = {"R": [], "I": [], "U": [], "F": []}
    sm = 0
    sm_at = []
    for n, ln in enumerate(lines):
        if re.match(r"^### SM-\d+: ", ln):
            sm += 1
            sm_at.append(n)
    for k, n in enumerate(sm_at):
        end = sm_at[k + 1] if k + 1 < len(sm_at) else len(lines)
        block = "\n".join(lines[n:end])
        if not re.search(r"^- writers:", block, re.M):
            errs.append(f"line {n + 1}: state machine has no '- writers:' line")
    qids = re.findall(r"^- (Q-\d+):", text, re.M)
    ids["Q"] = qids
    for start, head, rows in tables(lines):
        h = [c.lower() for c in head]
        kind = {tuple(R_COLS): "R", tuple(U_COLS): "U", tuple(F_COLS): "F", tuple(I_COLS): "I", tuple(T_COLS): "T", tuple(S_COLS): "S"}.get(tuple(h))
        if kind is None:
            errs.append(f"line {start}: table columns match no shape table: {head}")
            continue
        for ln, row in rows:
            if len(row) != len(h):
                errs.append(f"line {ln}: {len(row)} cells, expected {len(h)}")
                continue
            r = dict(zip(h, row))
            if kind in "RUFI":
                if not re.fullmatch(kind + r"-\d+", r["id"]):
                    errs.append(f"line {ln}: bad id {r['id']!r}")
                else:
                    ids[kind].append(r["id"])
            ecol = "enforced by" if kind == "I" else "enforced"
            if kind in ENFORCED and r[ecol] not in ENFORCED[kind]:
                errs.append(f"line {ln}: {ecol}={r[ecol]!r} not in {sorted(ENFORCED[kind])}")
            if kind == "R" and r["enforced"] in ("partial", "no") and not r["note"]:
                errs.append(f"line {ln}: enforced={r['enforced']} needs a note saying what is not enforced")
            if kind == "R" and (r["status"] == "disputed" or r["durability"] == "unclear") and not re.search(r"\bQ-\d+\b", r["note"]):
                errs.append(f"line {ln}: a disputed or unclear row needs a Q-<n> in its note")
            for col, allowed in ENUMS.items():
                if col in r and r[col] not in allowed:
                    errs.append(f"line {ln}: {col}={r[col]!r} not in {sorted(allowed)}")
            if "evidence" in r and not re.search(r"\S+:\d+", r["evidence"]) and "owner:" not in r["evidence"]:
                errs.append(f"line {ln}: evidence needs path:line or owner:<source>")
            if kind == "R" and r["fit"] == "partial" and not r["note"]:
                errs.append(f"line {ln}: fit=partial needs a note naming what is not asserted")
            if kind == "R" and r["fit"] != "none" and r["check"].lower() == "none":
                errs.append(f"line {ln}: check=none needs fit=none")
            if kind == "R" and r["check"].lower() != "none" and r["fit"] == "none":
                errs.append(f"line {ln}: a named check needs fit=full or partial")
    for k, v in ids.items():
        dup = {x for x in v if v.count(x) > 1}
        if dup:
            errs.append(f"duplicate ids: {sorted(dup)}")
    defined = {x for v in ids.values() for x in v}
    for m in re.finditer(r"\b([RIUFQ])-(\d+)\b", text):
        if m.group(0) not in defined:
            errs.append(f"dangling reference {m.group(0)}")
    want = f"R={len(ids['R'])} SM={sm} I={len(ids['I'])} U={len(ids['U'])} F={len(ids['F'])} Q={len(ids['Q'])}"
    if hdr.get("counts", "").strip() != want:
        errs.append(f"header counts {hdr.get('counts')!r} != actual {want!r}")
    for sec in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## Changelog"):
        if not any(l.startswith(sec) for l in lines):
            errs.append(f"missing section {sec}")
    if errs:
        print("\n".join(sorted(set(errs))))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else print(__doc__) or 2)
