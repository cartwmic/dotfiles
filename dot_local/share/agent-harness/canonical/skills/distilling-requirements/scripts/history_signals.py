#!/usr/bin/env python3
"""List the history signals a requirements run reads to propose inferred requirements, as markdown (default) or JSON.

usage: history_signals.py REPO [--scope PATH ...] [--rev REV] [--format md|json] [--limit N] [--churn-min N] [--no-prs]

Everything is read from REV (default HEAD, resolved to a full sha and printed), never from the working tree. With --scope, only history that touches those
repo-relative paths (a file or a folder) is listed; with none, the whole repo.
  signal commits   a commit whose subject matches fix, revert, perf, security, race, timeout, crash or flaky; sha, date, subject, the files it touched (inside the scope)
  high churn       files that exist at REV and were touched by at least --churn-min commits (default 4), most first
  deleted paths    paths removed by a commit and absent at REV (a rename is not a deletion): skip any requirement row whose code was there
  merged PRs       from `gh pr list --state merged` run in REPO, merged on or before REV: number, title, labels. With no `gh`, or a gh that fails, the section says why
Each list is cut to --limit rows (default 40) and says how many it cut. The git helper is repo_facts.py's, loaded by path from the sibling skill
designing-the-smallest-version. Exit 0, 2 on bad usage or an unknown REV. Stdlib only.
"""
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True  # the skill folders are deployed; leave no __pycache__ in them
REPO_FACTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "designing-the-smallest-version", "scripts", "repo_facts.py")
SIGNALS = {
    "fix": r"\bfix(?:e[sd]|ing)?\b|\bbug ?fix|\bregression\b|\bhotfix\b",
    "revert": r"\brevert(?:s|ed|ing)?\b",
    "perf": r"\bperf\b|\bperformance\b|\bslow(?:er|ness)?\b|\bspeed ?up\b|\bfaster\b|\blatency\b",
    "security": r"\bsecur(?:e|ity)\b|\bvulnerab\w*|\bcve-\d|\bxss\b|\bcsrf\b|\binjection\b|\bsanitiz\w*|\bsecrets?\b",
    "race": r"\brace\b|\bdeadlock\b|\bconcurren\w*",
    "timeout": r"\btime-?outs?\b",
    "crash": r"\bcrash\w*|\bpanic\w*|\bsegfault\b",
    "flaky": r"\bflak(?:y|e|iness)\b",
}
SIGNAL_RE = {k: re.compile(v, re.I) for k, v in SIGNALS.items()}
FILES_SHOWN = 6


def load_git():
    if not os.path.isfile(REPO_FACTS):
        print("history_signals: repo_facts.py not found at %s: install the designing-the-smallest-version skill next to distilling-requirements" % REPO_FACTS, file=sys.stderr)
        sys.exit(2)
    spec = importlib.util.spec_from_file_location("repo_facts", REPO_FACTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.git, mod.resolve


def in_scope(path, scope):
    return not scope or any(path == s or path.startswith(s + "/") for s in scope)


def parse_log(out):
    """[{sha, date, subject, files}] from `git log --format=@@%H%x09%cs%x09%s --name-only`."""
    commits = []
    for line in out.splitlines():
        if line.startswith("@@"):
            sha, date, subject = (line[2:].split("\t", 2) + ["", ""])[:3]
            commits.append({"sha": sha, "date": date, "subject": subject, "files": []})
        elif line.strip() and commits:
            commits[-1]["files"].append(line)
    return commits


def signal_commits(commits, scope):
    out = []
    for c in commits:
        kinds = [k for k, rx in SIGNAL_RE.items() if rx.search(c["subject"])]
        if kinds:
            out.append({"sha": c["sha"], "date": c["date"], "subject": c["subject"], "signals": kinds, "files": [f for f in c["files"] if in_scope(f, scope)]})
    return out


def churn(commits, scope, present, minimum):
    count = {}
    for c in commits:
        for f in c["files"]:
            if f in present and in_scope(f, scope):
                count[f] = count.get(f, 0) + 1
    return sorted(({"path": f, "commits": n} for f, n in count.items() if n >= minimum), key=lambda r: (-r["commits"], r["path"]))


def deleted(git, repo, sha, scope, present):
    out, seen = [], set()
    log = git(repo, "-c", "core.quotepath=off", "log", sha, "-M", "--diff-filter=D", "--name-only", "--format=@@%H%x09%cs%x09%s", "--", *(scope or ["."]))
    for c in parse_log(log):
        for f in c["files"]:
            if f not in present and f not in seen and in_scope(f, scope):
                seen.add(f)
                out.append({"path": f, "sha": c["sha"], "date": c["date"], "subject": c["subject"]})
    return out


def merged_prs(repo, scope, until):
    if not shutil.which("gh"):
        return {"available": False, "reason": "gh is not available", "rows": []}
    p = subprocess.run(["gh", "pr", "list", "--state", "merged", "--limit", "200", "--json", "number,title,labels,mergedAt,files"], capture_output=True, text=True, cwd=repo)
    if p.returncode:
        return {"available": False, "reason": "gh could not list PRs: %s" % ((p.stderr.strip().splitlines() or ["exit %d" % p.returncode])[0]), "rows": []}
    rows = []
    for pr in json.loads(p.stdout or "[]"):
        merged = datetime.datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00")) if pr.get("mergedAt") else None
        if merged and merged > until:
            continue
        if scope and not any(in_scope(f["path"], scope) for f in pr.get("files") or []):
            continue
        rows.append({"number": pr["number"], "title": pr["title"], "labels": [l["name"] for l in pr.get("labels") or []], "merged": pr.get("mergedAt", "")[:10]})
    return {"available": True, "reason": "", "rows": rows}


def cut(rows, limit):
    return rows[:limit], max(0, len(rows) - limit)


def markdown(r):
    out = ["# History signals for %s at %s" % (r["repo"], r["rev"][:7]), "", "rev: %s (committed %s)" % (r["rev"], r["date"]), "scope: %s" % (", ".join(r["scope"]) or "whole repo"), ""]
    sec = r["signal_commits"]
    out += ["## Signal commits (%d)" % sec["total"], ""]
    for c in sec["rows"]:
        files = c["files"][:FILES_SHOWN]
        out.append("- %s %s [%s] %s | files: %s%s" % (c["sha"][:7], c["date"], ",".join(c["signals"]), c["subject"], ", ".join(files) or "none in scope", " +%d more" % (len(c["files"]) - FILES_SHOWN) if len(c["files"]) > FILES_SHOWN else ""))
    out += ["", "## High-churn files (%d)" % r["churn"]["total"], ""] + ["- %d commits  %s" % (c["commits"], c["path"]) for c in r["churn"]["rows"]]
    out += ["", "## Deleted paths (%d): skip rows whose code was here" % r["deleted"]["total"], ""] + ["- %s | %s %s %s" % (d["path"], d["sha"][:7], d["date"], d["subject"]) for d in r["deleted"]["rows"]]
    prs = r["merged_prs"]
    out += ["", "## Merged PRs (%d)" % prs["total"], ""]
    out += ["- unavailable: %s" % prs["reason"]] if not prs["available"] else ["- #%d %s [%s] merged %s" % (p["number"], p["title"], ",".join(p["labels"]), p["merged"]) for p in prs["rows"]]
    for name, sec in (("signal_commits", sec), ("churn", r["churn"]), ("deleted", r["deleted"]), ("merged_prs", prs)):
        if sec.get("cut"):
            out.append("(%s: %d more rows cut by --limit)" % (name, sec["cut"]))
    return "\n".join(out) + "\n"


def build(repo, rev, scope, limit, churn_min, with_prs):
    git, resolve = load_git()
    sha = resolve(repo, rev)
    if not sha:
        return None
    date = git(repo, "log", "-1", "--format=%cs", sha).strip()
    until = datetime.datetime.fromisoformat(git(repo, "log", "-1", "--format=%cI", sha).strip())
    present = set(git(repo, "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", sha).splitlines())
    commits = parse_log(git(repo, "-c", "core.quotepath=off", "log", sha, "-M", "--name-only", "--format=@@%H%x09%cs%x09%s", "--", *(scope or ["."])))
    report = {"repo": os.path.basename(os.path.realpath(repo)), "rev": sha, "date": date, "scope": scope}
    for key, rows in (("signal_commits", signal_commits(commits, scope)), ("churn", churn(commits, scope, present, churn_min)), ("deleted", deleted(git, repo, sha, scope, present))):
        shown, extra = cut(rows, limit)
        report[key] = {"total": len(rows), "rows": shown, "cut": extra}
    prs = merged_prs(repo, scope, until) if with_prs else {"available": False, "reason": "--no-prs", "rows": []}
    shown, extra = cut(prs["rows"], limit)
    report["merged_prs"] = {"available": prs["available"], "reason": prs["reason"], "total": len(prs["rows"]), "rows": shown, "cut": extra}
    return report


def main(argv):
    args, scope, opts, flags, it = [], [], {"--rev": "HEAD", "--format": "md", "--limit": "40", "--churn-min": "4"}, set(), iter(argv[1:])
    for a in it:
        if a == "--scope":
            scope.append((next(it, "") or "").strip("/"))
        elif a in opts:
            opts[a] = next(it, "")
        elif a == "--no-prs":
            flags.add(a)
        else:
            args.append(a)
    if len(args) != 1 or not os.path.isdir(args[0]) or opts["--format"] not in ("md", "json") or not opts["--limit"].isdigit() or not opts["--churn-min"].isdigit() or "" in scope:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    try:
        report = build(args[0], opts["--rev"], scope, int(opts["--limit"]), int(opts["--churn-min"]), "--no-prs" not in flags)
    except RuntimeError as e:
        print("history_signals: %s" % e, file=sys.stderr)
        return 2
    if report is None:
        print("history_signals: %s is not a revision of %s" % (opts["--rev"], args[0]), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if opts["--format"] == "json" else markdown(report), end="\n" if opts["--format"] == "json" else "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
