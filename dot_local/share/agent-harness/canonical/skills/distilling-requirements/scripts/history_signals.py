#!/usr/bin/env python3
"""List the history signals a requirements run reads to find leads for inferred requirements, as markdown (default) or JSON.

usage: history_signals.py REPO [--scope PATH ...] [--rev REV] [--format md|json] [--limit N] [--churn-min N] [--gh-limit N] [--no-gh]

Everything is read from REV (default HEAD, resolved to a full sha and printed), never from the working tree. With --scope, only history that touches those
repo-relative paths (a file or a folder; `./src` is `src`) is listed, and a scope that does not exist at REV is an error; with none, the whole repo. A folder with no git
prints "no git history" and exits 0. `docs/snapshots/` is skipped: a snapshot is never evidence.
  signal commits   a commit whose subject matches fix, revert, perf, security, race, timeout, crash or flaky; sha, date, subject, the files it touched (inside the scope).
                   The match is on keywords only: it picks leads, not requirements
  high churn       files that exist at REV and were touched by at least --churn-min commits (default 4), most first
  merged PRs       from `gh pr list --state merged --search "merged:<=DATE"`, kept only when the PR's merge commit is an ancestor of REV: number, title, labels
  issues           from `gh issue list --state all --search "created:<=DATE"`; with a scope, only those whose title or body names a scope path
The PR and issue lists say how many gh returned, the cap (--gh-limit, default 2000) and whether the cap was hit. With no `gh`, a failing gh or --no-gh the section says why.
Each list is cut to --limit rows (default 40) and says how many it cut. The git helper is repo_facts.py's, loaded by path from the sibling skill
designing-the-smallest-version. Exit 0, 2 on bad usage, an unknown REV or a scope that is not in REV. Stdlib only.
"""
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
SNAPSHOTS = "docs/snapshots"  # a snapshot is never evidence: its folder is skipped


def load_git():
    if not os.path.isfile(REPO_FACTS):
        print("history_signals: repo_facts.py not found at %s: install the designing-the-smallest-version skill next to distilling-requirements" % REPO_FACTS, file=sys.stderr)
        sys.exit(2)
    spec = importlib.util.spec_from_file_location("repo_facts", REPO_FACTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.git, mod.resolve


def in_scope(path, scope):
    if path == SNAPSHOTS or path.startswith(SNAPSHOTS + "/"):
        return False
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


def gh_list(repo, kind, search, fields, limit):
    """(rows, reason, fetched, cap_hit) from `gh <kind> list`; rows is None with the reason when gh is absent or fails."""
    if not shutil.which("gh"):
        return None, "gh is not available", 0, False
    argv = ["gh", kind, "list", "--state", "merged" if kind == "pr" else "all", "--search", search, "--limit", str(limit), "--json", fields]
    p = subprocess.run(argv, capture_output=True, text=True, cwd=repo)
    if p.returncode:
        return None, "gh could not list %ss: %s" % (kind, (p.stderr.strip().splitlines() or ["exit %d" % p.returncode])[0]), 0, False
    rows = json.loads(p.stdout or "[]")
    return rows, "", len(rows), len(rows) >= limit


def gh_section(rows, reason, fetched, cap, cap_hit, kept):
    return {"available": rows is not None, "reason": reason, "fetched": fetched, "cap": cap, "cap_hit": cap_hit, "total": len(kept), "rows": kept}


def merged_prs(repo, sha, scope, date, limit):
    rows, reason, fetched, hit = gh_list(repo, "pr", "merged:<=%s" % date, "number,title,labels,mergedAt,mergeCommit" + (",files" if scope else ""), limit)
    if rows is None:
        return gh_section(None, reason, 0, limit, False, [])
    reachable = set(subprocess.run(["git", "-C", repo, "rev-list", sha], capture_output=True, text=True).stdout.split())
    kept = []
    for pr in rows:
        oid = (pr.get("mergeCommit") or {}).get("oid")
        if oid not in reachable:
            continue
        if scope and not any(in_scope(f["path"], scope) for f in pr.get("files") or []):
            continue
        kept.append({"number": pr["number"], "title": pr["title"], "labels": [l["name"] for l in pr.get("labels") or []], "merged": (pr.get("mergedAt") or "")[:10]})
    return gh_section(rows, "", fetched, limit, hit, kept)


def issues(repo, scope, date, limit):
    rows, reason, fetched, hit = gh_list(repo, "issue", "created:<=%s" % date, "number,title,state,labels,createdAt,body", limit)
    if rows is None:
        return gh_section(None, reason, 0, limit, False, [])
    kept = [{"number": i["number"], "title": i["title"], "state": i["state"].lower(), "labels": [l["name"] for l in i.get("labels") or []], "created": (i.get("createdAt") or "")[:10]}
            for i in rows if not scope or any(s in i["title"] + " " + (i.get("body") or "") for s in scope)]
    return gh_section(rows, "", fetched, limit, hit, kept)


def cut(rows, limit):
    return rows[:limit], max(0, len(rows) - limit)


def gh_markdown(name, sec, line):
    head = "## %s (%d)" % (name, sec["total"])
    if not sec["available"]:
        return ["", head, "", "- unavailable: %s" % sec["reason"]]
    out = ["", head, "", "gh returned %d, cap %d, cap hit: %s" % (sec["fetched"], sec["cap"], "yes, so older ones are missing: raise --gh-limit" if sec["cap_hit"] else "no"), ""]
    return out + [line(p) for p in sec["rows"]] + (["(%d more rows cut by --limit)" % sec["cut"]] if sec.get("cut") else [])


def markdown(r):
    out = ["# History signals for %s at %s" % (r["repo"], r["rev"][:7]), "", "rev: %s (committed %s)" % (r["rev"], r["date"]), "scope: %s" % (", ".join(r["scope"]) or "whole repo"),
           "These are leads, not requirements: the keywords only pick commits worth opening."]
    sec = r["signal_commits"]
    out += ["", "## Signal commits (%d)" % sec["total"], ""]
    for c in sec["rows"]:
        files = c["files"][:FILES_SHOWN]
        out.append("- %s %s [%s] %s | files: %s%s" % (c["sha"][:7], c["date"], ",".join(c["signals"]), c["subject"], ", ".join(files) or "none in scope", " +%d more" % (len(c["files"]) - FILES_SHOWN) if len(c["files"]) > FILES_SHOWN else ""))
    if sec["cut"]:
        out.append("(%d more rows cut by --limit)" % sec["cut"])
    out += ["", "## High-churn files (%d)" % r["churn"]["total"], ""] + ["- %d commits  %s" % (c["commits"], c["path"]) for c in r["churn"]["rows"]]
    if r["churn"]["cut"]:
        out.append("(%d more rows cut by --limit)" % r["churn"]["cut"])
    out += gh_markdown("Merged PRs", r["merged_prs"], lambda p: "- #%d %s [%s] merged %s" % (p["number"], p["title"], ",".join(p["labels"]), p["merged"]))
    out += gh_markdown("Issues", r["issues"], lambda p: "- #%d %s (%s) [%s] created %s" % (p["number"], p["title"], p["state"], ",".join(p["labels"]), p["created"]))
    return "\n".join(out) + "\n"


def build(repo, rev, scope, limit, churn_min, gh_limit, with_gh):
    git, resolve = load_git()
    sha = resolve(repo, rev)
    if not sha:
        return None
    for s in scope:
        if not git(repo, "ls-tree", sha, "--", s).strip():
            raise ValueError("scope %s does not exist at %s" % (s, sha[:7]))
    date = git(repo, "log", "-1", "--format=%cs", sha).strip()
    present = set(git(repo, "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", sha).splitlines())
    commits = parse_log(git(repo, "-c", "core.quotepath=off", "log", sha, "-M", "--name-only", "--format=@@%H%x09%cs%x09%s", "--", *(scope or ["."]), ":(exclude)" + SNAPSHOTS))
    report = {"repo": os.path.basename(os.path.realpath(repo)), "rev": sha, "date": date, "scope": scope}
    for key, rows in (("signal_commits", signal_commits(commits, scope)), ("churn", churn(commits, scope, present, churn_min))):
        shown, extra = cut(rows, limit)
        report[key] = {"total": len(rows), "rows": shown, "cut": extra}
    off = {"available": False, "reason": "--no-gh", "fetched": 0, "cap": gh_limit, "cap_hit": False, "total": 0, "rows": []}
    for key, sec in (("merged_prs", merged_prs(repo, sha, scope, date, gh_limit) if with_gh else off), ("issues", issues(repo, scope, date, gh_limit) if with_gh else off)):
        shown, extra = cut(sec["rows"], limit)
        report[key] = dict(sec, rows=shown, cut=extra)
    return report


def main(argv):
    args, scope, opts, flags, it = [], [], {"--rev": "HEAD", "--format": "md", "--limit": "40", "--churn-min": "4", "--gh-limit": "2000"}, set(), iter(argv[1:])
    for a in it:
        if a == "--scope":
            path = os.path.normpath((next(it, "") or "").strip() or ".")
            scope.append("" if path == "." else path.strip("/"))
        elif a in opts:
            opts[a] = next(it, "")
        elif a == "--no-gh":
            flags.add(a)
        else:
            args.append(a)
    if len(args) != 1 or not os.path.isdir(args[0]) or opts["--format"] not in ("md", "json") or not all(opts[k].isdigit() for k in ("--limit", "--churn-min", "--gh-limit")) or "" in scope:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    if subprocess.run(["git", "-C", args[0], "rev-parse", "--git-dir"], capture_output=True).returncode:
        print("no git history" if opts["--format"] == "md" else json.dumps({"history": "no git history"}))
        return 0
    try:
        report = build(args[0], opts["--rev"], scope, int(opts["--limit"]), int(opts["--churn-min"]), int(opts["--gh-limit"]), "--no-gh" not in flags)
    except (RuntimeError, ValueError) as e:
        print("history_signals: %s" % e, file=sys.stderr)
        return 2
    if report is None:
        print("history_signals: %s is not a revision of %s" % (opts["--rev"], args[0]), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2) if opts["--format"] == "json" else markdown(report), end="\n" if opts["--format"] == "json" else "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
