#!/usr/bin/env python3
"""Check a REQUIREMENTS.md against references/output-shape.md.

Usage: python3 check_shape.py REQUIREMENTS.md [REPO]
Exit 0 and "ok" when clean; exit 1 and one problem per line otherwise.
Checks structure only (columns, ids, enums, evidence present, counts, dangling refs, the snapshot line),
not whether a requirement is true. A `path:line` citation into docs/snapshots/ is an error; with REPO, so is one into any file that holds the snapshot line on a line of its own (`Snapshot of <name> at <sha7|no-git> on <date>. Not maintained: ...`, in the first 60 lines). A file with `shape: requirements/1` is refused: rerun the skill.
"""
import os
import re
import sys

R_COLS = ["id", "lens", "kind", "durability", "status", "requirement", "evidence", "check", "fit", "enforced", "note"]
U_COLS = ["id", "invariant relied on", "relied on at", "missing guard", "violation reachable", "evidence"]
F_COLS = ["id", "machine/ref", "impact", "confidence", "path to it", "evidence", "proposed regression test", "issue group"]
I_COLS = ["id", "invariant", "enforced by", "evidence"]
T_COLS = ["from", "event", "guard", "to", "effects", "evidence"]
S_COLS = ["state", "meaning", "evidence"]
ENUMS = {
    "lens": {"product", "behavioral", "technical", "quality"},
    "kind": {"explicit", "implicit", "inferred"},
    "durability": {"enduring", "incidental", "unclear"},
    "status": {"proposed", "accepted", "disputed"},
    "fit": {"full", "partial", "none", "title"},
    "impact": {"high", "medium", "low"},
    "confidence": {"confirmed", "likely", "suspected"},
}


SHAPE = "requirements/2"
SNAPSHOT_FIXED = "Not maintained: it records the code at that commit, not today's."
HISTORY = {"commit": re.compile(r"commit:[0-9a-f]{7,40}"), "pr": re.compile(r"pr:\d+"), "issue": re.compile(r"issue:\d+")}
ENFORCED = {"R": {"yes", "partial", "no"}, "I": {"type", "check", "constraint", "convention", "test", "none"}}


def evidence_parts(cell):
    """[(kind, text)] for the `;`-separated parts of an evidence cell. kind is owner, commit, pr, issue, bad (a commit/pr/issue part that is malformed) or cite (anything else: a
    `path:line` or a path with a remark). Everything that reads a cell goes through here, so `pr:12` is never taken for a line of a file called pr."""
    out = []
    for part in (p.strip().strip("`") for p in cell.split(";")):
        if not part:
            continue
        kind = "owner" if part.startswith("owner:") else next((k for k, rx in HISTORY.items() if part.startswith(k + ":")), "cite")
        if kind in HISTORY and not HISTORY[kind].fullmatch(part):
            kind = "bad"
        out.append((kind, part))
    return out


SNAPSHOT_MARK = re.compile(r"Snapshot of \S+ at (?:[0-9a-f]{7,40}|no-git) on \d{4}-\d\d-\d\d\. " + re.escape(SNAPSHOT_FIXED))
MARK_LINES = 60  # the header fence, title and snapshot line of every shape sit well inside this


def snapshot_line(hdr):
    """The fixed line that must come first under the title, built from the header's repo, commit and date."""
    commit = hdr.get("commit", "").strip()
    return "Snapshot of %s at %s on %s. %s" % (hdr.get("repo", "").strip(), commit[:7] if re.fullmatch(r"[0-9a-f]{40}", commit) else commit, hdr.get("date", "").strip(), SNAPSHOT_FIXED)


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


def is_snapshot_file(path, repo):
    """True when `path` is inside docs/snapshots/, or (with REPO) a file with the whole snapshot line (`Snapshot of <name> at <sha> on <date>. Not maintained: ...`) as a line of its own near the top: a snapshot is never evidence.
    A docstring that quotes the line with placeholders, or mid-sentence, is not a snapshot."""
    norm = os.path.normpath(path).lstrip("/")
    if norm == "docs/snapshots" or norm.startswith("docs/snapshots/") or "/docs/snapshots/" in "/" + norm:
        return True
    if repo:
        try:
            with open(os.path.join(repo, norm), encoding="utf-8", errors="replace") as f:
                return any(SNAPSHOT_MARK.fullmatch(next(f, "").strip()) for _ in range(MARK_LINES))
        except OSError:
            return False
    return False


def main(path, repo=None):
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()
    if not text.lstrip().startswith("```text"):
        print("file must start with the header fence (```text); put the title below it")
        return 1
    errs = []
    hdr = dict(re.findall(r"^(\w[\w-]*):\s*(.+)$", text.split("```", 2)[1], re.M))
    if hdr.get("shape") == "requirements/1":
        print("shape requirements/1 is the old shape: rerun the distilling-requirements skill to write requirements/2")
        return 1
    if hdr.get("shape") != SHAPE:
        errs.append(f"header: shape must be {SHAPE}")
    for k in ("repo", "commit", "scope", "date", "not-read", "counts", "snapshot", "history", "interview", "repo-wide"):
        if k not in hdr:
            errs.append(f"header: missing {k}")
    if hdr.get("repo-wide") and hdr["repo-wide"].strip() not in ("yes", "no"):
        errs.append("header: repo-wide must be yes or no")
    if "snapshot" in hdr:
        want = "%s at %s" % (hdr.get("date", "").strip(), hdr.get("commit", "").strip())
        if hdr["snapshot"].strip() != want or not re.fullmatch(r"\d{4}-\d\d-\d\d at ([0-9a-f]{40}|no-git)", hdr["snapshot"].strip()):
            errs.append(f"header: snapshot must be '<date> at <full sha>' (or 'no-git' for an archive) and match date and commit; expected {want!r}")
    if "history" in hdr and not re.fullmatch(r"[0-9a-f]{40}|no-git", hdr["history"].strip()):
        errs.append("header: history must be the full sha the history signals were read at, or 'no-git'")
    elif "history" in hdr and hdr["history"].strip() != hdr.get("commit", "").strip():
        errs.append("header: history must equal commit (the signals are read at the snapshot commit)")
    body = text.split("```", 2)[2].splitlines() if text.count("```") >= 2 else []
    under_title = [l for l in body if l.strip()][:2]
    if len(under_title) < 2 or not under_title[0].startswith("# ") or under_title[1] != snapshot_line(hdr):
        errs.append(f"snapshot line: the first line under the title must be exactly {snapshot_line(hdr)!r}")
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
            if "evidence" in r:
                parts = evidence_parts(r["evidence"])
                for k, part in parts:
                    if k == "bad":
                        errs.append(f"line {ln}: evidence {part!r} is not commit:<7+ hex>, pr:<number> or issue:<number>")
                for k, part in parts:
                    cited = re.match(r"(.+?):\d", part) if k == "cite" else None
                    if cited and is_snapshot_file(cited.group(1), repo):
                        errs.append(f"line {ln}: evidence {part!r} cites a snapshot (docs/snapshots/ or a file marked 'Not maintained'): a snapshot is never evidence, cite the code")
                if not any(k in ("owner", "commit", "pr", "issue") or re.search(r"\S+:\d+", t) for k, t in parts):
                    errs.append(f"line {ln}: evidence needs path:line, commit:<sha>, pr:<n>, issue:<n> or owner:<source>")
                if kind == "R" and r["status"] == "accepted" and not any(k == "owner" for k, _ in parts):
                    errs.append(f"line {ln}: status=accepted needs owner: evidence (only the owner accepts, during this run)")
                if kind == "R" and r["kind"] == "inferred" and r["status"] not in ("proposed", "disputed"):
                    errs.append(f"line {ln}: an inferred row has status proposed or disputed, never accepted: once the owner confirms it, it is explicit")
                if kind == "R" and any(t.startswith("owner:interview") for k, t in parts) and hdr.get("interview", "").strip() == "none":
                    errs.append(f"line {ln}: owner:interview evidence but the header says interview: none")
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
    for sec in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## Run log"):
        if not any(l.startswith(sec) for l in lines):
            errs.append(f"missing section {sec}")
    if errs:
        print("\n".join(sorted(set(errs))))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]) if len(sys.argv) in (2, 3) else print(__doc__) or 2)
