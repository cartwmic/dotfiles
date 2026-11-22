#!/usr/bin/env python3
"""The closing step: re-check what changed after the last checker report, repair what can be repaired once, and cut what does not hold.

usage: final_recheck.py changed GUIDE.md <repo> --was OLD.md [--skip held.txt]... [--out changed.txt]
       final_recheck.py repair GUIDE.md <repo> --ids changed.txt --reports DIR [--was OLD.md] [--try N] [--out repair.txt]
       final_recheck.py cut GUIDE.md <repo> --ids changed.txt --reports DIR [--was OLD.md] [--except repair.txt] [--held-out held.txt] [-o OUT.md] [--clean]
       final_recheck.py drop GUIDE.md <repo> --ids dropped.txt [-o OUT.md] [--clean]

changed  lists the claims that differ from OLD.md, the guide as the last checker saw it (the same test as slice.py --was: a changed sentence, tag or cited line, or a
         line that moved). It prints one row a claim, `N.k | sentence`, and writes the ids to --out, one a line, for slice.py --ids. With no changed claim it says so and writes
         an empty file: there is nothing to check.
repair   reads the same reports and lists each claim whose verdict is not HOLDS as `fix` or `cut`. A claim whose finding row names the cause MISSING_CONDITION, NAME or COUNT is `fix`:
         it gets one fix and one re-check before it may be cut. Any other cause (KIND, OTHER, no cause) is `cut`. --out writes the ids of the `fix` claims, one a line, for `cut --except`.
         --try N (an extend pass) is the repair try this check closes, from 1: on try 1 and 2 every claim that did not HOLD is `fix`, whatever its cause (a MISSING_CONDITION, NAME, COUNT, KIND,
         OTHER or no cause); from try 3 every one is `cut`, so a claim is repaired twice at most. Without --try the causes above decide.
--was OLD.md (with repair or cut) marks an extend pass: a claim that did not HOLD in the reports and is not in the ids file is acted on as if the ids file named it, whatever line it is: one
         the pass wrote, a line next to a changed claim that slice.py pulled in, or a line as OLD.md has it. A failure is never left without a route. It prints how many such claims it added.
cut      reads the verdicts of the fresh checker's reports in DIR (`read | N.k | VERDICT | path:line` rows) for the claims in the ids file. A claim whose verdict is not HOLDS is
         cut: an appendix claim loses its line, a Part 1 claim loses its sentence. Then every Part 1 sentence is looked at: a tag that points at a cut appendix line is
         removed, and a sentence left with no tag is cut too. A sentence that keeps another tag stays, and is listed. Nothing is reworded. Writes the guide to -o (default:
         GUIDE.md in place); --clean also writes the guide without tags next to it. A claim of the ids file with no row in the reports is an error (exit 1): the checker
         skipped it, so run it again. A Part 1 line with a citation, or an appendix line with two claims, is refused for the same reason.
--except FILE (with cut) leaves the claims it names uncut: the ones being repaired. They still need a report row.
--held-out FILE (with cut) writes the content of every checked claim whose verdict is HOLDS (its sentence, tags and cited lines, not its number), and `changed --skip FILE` (once for each file of
         each round) leaves those out of a later list. It also writes a `pending` row for each claim left to be repaired (--except): `changed` lists a pending claim until a checker passes it,
         even an unchanged incoming line the repair never touched. The later list then holds every claim still different from OLD.md that no checker passed as it stands: a repaired claim, and a claim that was left to be repaired and never edited,
         which is re-checked and cut when it still fails. A passed claim that only moved (its neighbours changed) is listed again.
drop     cuts the claims the ids file names without a report, with the same tag clean-up as cut, for a Part 1 sentence that still fails lint_main.py after its one fix. It refuses (exit 1,
         nothing written) the `Who it is for` sentence and the last sentence of How to start: those are fixed, never dropped.
Cutting the guide in place is the last edit: do not run assemble.py again afterwards, it would bring the cut text back from the section files.
Exit 2 on bad usage. Stdlib only.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from assemble import clean, clean_path  # noqa: E402
from claims import LIST_MARK, TAG, claim_ids, line_items, split_lines, split_sentences, tags_before_stop, words_of  # noqa: E402
from lint_main import WHO_FOR, section_lines  # noqa: E402
from score import FINDING  # noqa: E402
from slice import SliceError, changed_since, part1_lines, read_ids, read_verdicts, signatures  # noqa: E402

REPAIRABLE = ("MISSING_CONDITION", "NAME", "COUNT")  # the causes a fix can remove: the sentence lacks a condition, or has a wrong name, value or count
MAX_REPAIRS = 2  # an extend pass repairs a claim twice, then cuts it


class CutError(Exception):
    pass


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def changed(text, old_text, repo, held=frozenset(), pending=frozenset()):
    """The claims that differ from OLD (see changed_since), less the held ones: a claim a checker passed as it stands is not listed again. A held claim that is still a claim of OLD
    and is listed because it moved stays on the list: its neighbours are not the ones the checker saw. A `pending` claim (one that failed and was left to be repaired) is listed
    too, edited or not, until a checker passes it: an unchanged incoming line that was routed to repair and never touched is not left to ship."""
    claims = claim_ids(text, repo)
    ids = changed_since(old_text, claims, text, repo)
    sigs = dict(zip([c[0] for c in claims], signatures(text, claims, repo)))
    old = set(signatures(old_text, claim_ids(old_text, repo), repo))
    return [c for c in claims if (c[0] in ids and (sigs[c[0]] not in held or sigs[c[0]] in old)) or (sigs[c[0]] in pending and sigs[c[0]] not in held)]


def held_rows(text, repo, chosen, verdicts, keep=()):
    """The content of each chosen claim whose verdict is HOLDS, as JSON lines of [sentence, [tags], [[path, first, last]]]: a claim as `changed --skip` knows it, by what it says.
    Each chosen claim that did not HOLD and is in `keep` (left to be repaired) follows as {"pending": [...the same...]}."""
    claims = claim_ids(text, repo)
    sigs = dict(zip([c[0] for c in claims], signatures(text, claims, repo)))
    row = lambda c: [sigs[c[0]][0], list(sigs[c[0]][1]), [list(x) for x in sigs[c[0]][2]]]
    return "".join(json.dumps(row(c)) + "\n" for c in chosen if verdicts.get(c[0]) == "HOLDS") + \
        "".join(json.dumps({"pending": row(c)}) + "\n" for c in chosen if verdicts.get(c[0]) not in (None, "HOLDS") and c[0] in keep)


def read_rows(path):
    """([signature of each passed row], [signature of each pending row]) of a held-out file, as `signatures` makes them."""
    held, pending = set(), set()
    for line in read(path).splitlines():
        if line.strip():
            row = json.loads(line)
            sentence, tags, cites = row["pending"] if isinstance(row, dict) else row
            (pending if isinstance(row, dict) else held).add((sentence, tuple(tags), tuple(tuple(c) for c in cites)))
    return held, pending


def read_held(path):
    """The set of signatures of the claims a held-out file holds as passed."""
    return read_rows(path)[0]


def part1_pieces(line):
    """A Part 1 line as (mark, pieces, counted): its list mark, its sentences cut as claim_ids cuts them, and which pieces are claims (they hold a word)."""
    mark = LIST_MARK.match(line)
    body = re.sub(r"\s+", " ", line[mark.end():] if mark else line).strip()
    pieces = [body] if body.startswith("|") else split_sentences(tags_before_stop(body))
    return (mark.group(0) if mark else ""), pieces, [bool(words_of(p)) for p in pieces]


def read_causes(folder, claims):
    """{claim id: CAUSE} from the finding rows (`claim id | verdict | CAUSE | ...`) of every report in the folder. A row keyed by a bare doc line N names every claim of that line;
    a finding with no cause is not in the result."""
    out = {}
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not (name.endswith((".md", ".txt")) and os.path.isfile(path)):
            continue
        for m in FINDING.finditer(read(path)):
            if not m.group(2):
                continue
            key = re.search(r"(\d+(?:\.\d+)?|A\d+\.\w+)\s*$", m.group(0).split("|")[0])
            if not key:
                continue
            ids = [c[0] for c in claims if c[0] == key.group(1) or (re.fullmatch(r"\d+", key.group(1)) and c[1] == int(key.group(1)))]
            out.update(dict.fromkeys(ids, m.group(2)))
    return out


def repair_rows(text, repo, chosen, verdicts, causes, tries=None):
    """[(kind, claim id, verdict, cause, sentence)] for each chosen claim that did not HOLD: `fix` when its cause is one a fix removes, else `cut`. With `tries` (the repair try
    this check closes) every one is `fix` while the try is within MAX_REPAIRS, whatever its cause, and `cut` after it."""
    missing = [c[0] for c in chosen if c[0] not in verdicts]
    if missing:
        raise CutError("no report row for: %s (the checker skipped them: run it again)" % ", ".join(missing))
    fixable = lambda c: causes.get(c[0]) in REPAIRABLE if tries is None else tries <= MAX_REPAIRS
    return [("fix" if fixable(c) else "cut", c[0], verdicts[c[0]], causes.get(c[0], "none named"), c[2]) for c in chosen if verdicts[c[0]] != "HOLDS"]


def with_new_failures(text, repo, chosen, verdicts, old_text):
    """(chosen, extra, as_was): the chosen claims plus each claim the reports fail that the ids file did not name (a line next to a changed claim that a slice pulled in, or a line as the
    old guide has it), in doc order; `extra` is the claims added, and `as_was` the ones of them that are as the old guide has them (same sentence, tag and cited line)."""
    claims = claim_ids(text, repo)
    sigs = dict(zip([c[0] for c in claims], signatures(text, claims, repo)))
    old, named = set(signatures(old_text, claim_ids(old_text, repo), repo)), {c[0] for c in chosen}
    extra = [c for c in claims if c[0] not in named and verdicts.get(c[0], "HOLDS") != "HOLDS"]
    return [c for c in claims if c[0] in named or c in extra], extra, [c for c in extra if sigs[c[0]] in old]


def protected(text, repo, chosen):
    """Why each chosen Part 1 claim may not be dropped: the `Who it is for` sentence, or the last sentence of How to start. [(claim id, reason)]."""
    first, after = part1_lines(text)
    if not first:
        return []
    lines = split_lines(text)
    sections = section_lines("\n".join(lines[first - 1:after - 1]))
    start = next((v for k, v in sections.items() if k.startswith("how to start")), None)
    claims = [c for c in claim_ids(text, repo) if first <= c[1] < after]
    ids = {c[0] for c in chosen}
    steps = [c for c in claims if start and start[0] <= c[1] - first + 1 <= start[1]]
    out = []
    for c in chosen:
        if c[0] in {x[0] for x in claims} and WHO_FOR.match(TAG.sub(" ", c[2])):
            out.append((c[0], "it is the Who it is for sentence: fix it, never drop it"))
        elif c in steps and all(x[0] in ids for x in steps):
            out.append((c[0], "it is the last sentence of How to start: fix it, never drop it"))
    return out


def cut_text(text, repo, chosen, verdicts, keep=()):
    """(new_text, report rows): the guide with every chosen claim that did not HOLD cut, and the Part 1 sentences whose tags it left dead cut or untagged. A claim in `keep` is not cut."""
    claims = claim_ids(text, repo)
    lines = split_lines(text)
    p1 = part1_lines(text)
    missing = [c[0] for c in chosen if c[0] not in verdicts]
    if missing:
        raise CutError("no report row for: %s (the checker skipped them: run it again)" % ", ".join(missing))
    failed = {c[0]: verdicts[c[0]] for c in chosen if verdicts[c[0]] != "HOLDS" and c[0] not in keep}
    per_line = {}
    for c in claims:
        per_line.setdefault(c[1], []).append(c[0])
    rows, drop_lines, dead = [], set(), set()
    for c in claims:
        if c[0] not in failed or p1[0] <= c[1] < p1[1]:
            continue
        if len(per_line[c[1]]) > 1:
            raise CutError("appendix line %d holds several claims (%s): cut it by hand" % (c[1], ", ".join(per_line[c[1]])))
        drop_lines.add(c[1])
        dead |= set(TAG.findall(lines[c[1] - 1]))
        rows.append("cut | %s | %s | %s" % (c[0], failed[c[0]], c[2]))
    edits = {}  # doc line -> {claim id: "cut" | the dead tags to strip}
    for c in claims:
        if not p1[0] <= c[1] < p1[1]:
            continue
        tags = TAG.findall(c[2])
        lost = [t for t in tags if t in dead]
        if c[0] in failed:
            edits.setdefault(c[1], {})[c[0]] = "cut"
            rows.append("cut | %s | %s | %s" % (c[0], failed[c[0]], c[2]))
        elif not lost:
            continue
        elif len(lost) == len(tags):
            edits.setdefault(c[1], {})[c[0]] = "cut"
            rows.append("cut, lost its only tag | %s | %s" % (c[0], c[2]))
        else:
            edits.setdefault(c[1], {})[c[0]] = lost
            rows.append("kept, tag removed (%s) | %s | %s" % (" ".join(lost), c[0], c[2]))
    out, deleted_last = [], False
    for n, line in enumerate(lines, 1):
        if n in drop_lines:
            deleted_last = True
            continue
        if deleted_last and not line.strip() and out and not out[-1].strip():
            continue  # the cut line stood alone between two blank lines
        deleted_last = False
        if n in edits:
            if any(cites for _, _, cites, _ in line_items(line, repo)):
                raise CutError("Part 1 line %d has a citation: cut it by hand" % n)
            mark, pieces, counted = part1_pieces(line)
            kept, k = [], 0
            for piece, is_claim in zip(pieces, counted):
                k += is_claim
                todo = edits[n].get("%d.%d" % (n, k)) if is_claim else None
                if todo == "cut":
                    continue
                for tag in todo or []:
                    piece = piece.replace(tag, "")
                piece = re.sub(r"\s+([.!?])", r"\1", re.sub(r"\s+", " ", piece)).strip()
                kept.append(re.sub(r"((?:\s*%s)+)([.!?])$" % TAG.pattern, r"\2\1", piece))  # the tags go back after the stop, where the front writer puts them
            if not kept:
                deleted_last = True
                continue
            line = mark + " ".join(kept)
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), rows


def usage():
    print(__doc__.split("\n\n")[0], file=sys.stderr)
    return 2


def options(argv, names):
    """({flag: value}, positional) from argv; None when a flag is unknown or has no value. The value of --skip is the list of its values."""
    found, rest, it = {}, [], iter(argv)
    for a in it:
        if a == "--clean":
            found[a] = True
        elif a in names:
            value = next(it, None)
            if not value:
                return None
            found[a] = (found.get(a, []) + [value]) if a == "--skip" else value  # --skip is given once for each round's held file
        elif a.startswith("-") and len(a) > 1:
            return None
        else:
            rest.append(a)
    return found, rest


def main(argv):
    if len(argv) < 2 or argv[1] not in ("changed", "repair", "cut", "drop"):
        return usage()
    mode = argv[1]
    names = {"changed": ("--was", "--out", "--skip"), "repair": ("--ids", "--reports", "--was", "--try", "--out"), "cut": ("--ids", "--reports", "--was", "--except", "--held-out", "-o"), "drop": ("--ids", "-o")}[mode]
    parsed = options(argv[2:], names)
    if parsed is None or len(parsed[1]) != 2:
        return usage()
    opts, (doc, repo) = parsed
    repo = os.path.realpath(repo)
    need = {"changed": ("--was",), "repair": ("--ids", "--reports"), "cut": ("--ids", "--reports"), "drop": ("--ids",)}[mode]
    if not os.path.isfile(doc) or not os.path.isdir(repo) or any(k not in opts for k in need) or ("--clean" in opts and mode in ("changed", "repair")):
        return usage()
    if any(not os.path.isfile(opts[k]) for k in ("--was", "--ids", "--except") if k in opts) or any(not os.path.isfile(f) for f in opts.get("--skip", [])) \
            or ("--reports" in opts and not os.path.isdir(opts["--reports"])) or ("--try" in opts and not re.fullmatch(r"[1-9]\d*", opts["--try"])):
        return usage()
    text = read(doc)
    if mode == "changed":
        held_pending = [read_rows(f) for f in opts.get("--skip", [])]
        rows = changed(text, read(opts["--was"]), repo, frozenset().union(*[h for h, _ in held_pending]), frozenset().union(*[p for _, p in held_pending]))
        for c in rows:
            print("%s | %s" % (c[0], c[2]))
        print("%d claims changed since %s" % (len(rows), opts["--was"]) if rows else "nothing changed since %s: no final check needed" % opts["--was"])
        if "--out" in opts:
            with open(opts["--out"], "w", encoding="utf-8") as f:
                f.write("".join(c[0] + "\n" for c in rows))
        return 0
    try:
        claims = claim_ids(text, repo)
        chosen = read_ids(opts["--ids"], claims, text, repo)
        verdicts = read_verdicts(opts["--reports"]) if "--reports" in opts else {}
        if "--was" in opts and mode in ("repair", "cut"):
            chosen, extra, as_was = with_new_failures(text, repo, chosen, verdicts, read(opts["--was"]))
            if extra:
                print("%d failing claims the ids file did not name are routed too (%d as %s has them)" % (len(extra), len(as_was), os.path.basename(opts["--was"])))
        if mode == "repair":
            rows = repair_rows(text, repo, chosen, verdicts, read_causes(opts["--reports"], claims), int(opts["--try"]) if "--try" in opts else None)
            for kind, cid, verdict, cause, sentence in rows:
                print("%s | %s | %s | %s | %s" % (kind, cid, verdict, cause, sentence))
            fix = [r[1] for r in rows if r[0] == "fix"]
            print("%d claims checked: %d to fix once, %d to cut, %d hold" % (len(chosen), len(fix), len(rows) - len(fix), len(chosen) - len(rows)))
            if "--out" in opts:
                with open(opts["--out"], "w", encoding="utf-8") as f:
                    f.write("".join(i + "\n" for i in fix))
            return 0
        if mode == "drop":
            stop = protected(text, repo, chosen)
            if stop:
                raise CutError("; ".join("claim %s: %s" % s for s in stop))
            new, rows = cut_text(text, repo, chosen, dict.fromkeys((c[0] for c in chosen), "DROPPED"))
        else:
            keep = {c[0] for c in read_ids(opts["--except"], claims, text, repo)} if "--except" in opts else set()
            new, rows = cut_text(text, repo, chosen, verdicts, keep)
            if "--held-out" in opts:
                with open(opts["--held-out"], "w", encoding="utf-8") as f:
                    f.write(held_rows(text, repo, chosen, verdicts, keep))
    except (SliceError, CutError) as e:
        print(e, file=sys.stderr)
        return 1
    out = opts.get("-o", doc)
    with open(out, "w", encoding="utf-8") as f:
        f.write(new)
    for r in rows:
        print(r)
    print("%d claims %s, %s: wrote %s" % (len(chosen), "named" if mode == "drop" else "checked", "%d rows above" % len(rows) if rows else "all HOLD, nothing cut", out))
    if "--clean" in opts:
        with open(clean_path(out), "w", encoding="utf-8") as f:
            f.write(clean(new))
        print("wrote %s" % clean_path(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
