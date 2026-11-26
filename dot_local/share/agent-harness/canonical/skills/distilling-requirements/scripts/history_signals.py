#!/usr/bin/env python3
"""List the history signals a requirements run reads to find leads for inferred requirements, as markdown (default) or JSON.

usage: history_signals.py REPO [--scope PATH ...] [--rev REV] [--format md|json] [--limit N] [--out FILE] [--churn-min N] [--gh-limit N] [--no-gh]

Everything is read from REV (default HEAD, resolved to a full sha and printed), never from the working tree. With --scope, only history that touches those
repo-relative paths (a file or a folder, repeatable or comma-separated; `./src` is `src`, an absolute path inside the repo is made relative, `.` is the whole repo) is listed, and a scope that does not exist at REV is an error; with none, the whole repo. A folder with no git
reports "no git history" (to --out when given) and exits 0. `docs/snapshots/` is skipped: a snapshot is never evidence.
  signal commits   a commit whose subject matches fix, revert, perf, security, race, timeout, crash or flaky; sha, date, subject, the files it touched (inside the scope).
                   The match is on keywords only: it picks leads, not requirements
  high churn       files that exist at REV and were touched by at least --churn-min commits (default 4), most first
  merged PRs       from `gh pr list --state merged --search "merged:A..B"` with no upper date (GitHub dates are UTC), kept only when the PR's merge commit is an ancestor of REV: number, title, labels
  issues           from `gh issue list --state all --search "created:A..B"` up to the UTC day after the commit, then only those created by the commit time; with a scope, only those whose title or body names a scope path
GitHub search returns at most 1,000 results, so a search that returns that many is split by date and repeated until every window is under the cap (--gh-limit, at most 1,000 per search). The PR and issue lists say how many gh returned and whether one day alone still hit the cap. With no `gh`, a failing gh or --no-gh the section says why.
No list is cut by default (`--limit 0` is the same). With `--limit N` each list is cut to its N newest rows and says "(M more rows cut by --limit)". With `--out FILE` the report is
written to FILE and stdout gets one line saying where and how many lines: use it when the report is long, and read the file in parts. Exit 0, 2 on bad usage, an unknown REV or a scope that is not in REV. Stdlib only.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folders are deployed; leave no __pycache__ in them
from scopes import parse_scopes  # noqa: E402
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


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, encoding="utf-8", errors="replace")
    if p.returncode:
        raise RuntimeError("git %s failed: %s" % (" ".join(args[:2]), (p.stderr.strip().splitlines() or ["exit %d" % p.returncode])[0]))
    return p.stdout


def resolve(repo, rev):
    """The full sha of REV in REPO, or None when it is not a commit there."""
    p = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", rev + "^{commit}"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


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


SEARCH_MAX = 1000  # GitHub search returns at most 1,000 results, whatever --limit says
FIRST_DAY = datetime.date(2008, 1, 1)


def gh_query(repo, kind, field, lo, hi, fields, limit):
    argv = ["gh", kind, "list", "--state", "merged" if kind == "pr" else "all", "--search", "%s:%s..%s" % (field, lo, hi), "--limit", str(limit), "--json", fields]
    p = subprocess.run(argv, capture_output=True, text=True, cwd=repo)
    if p.returncode:
        raise RuntimeError("gh could not list %ss: %s" % (kind, (p.stderr.strip().splitlines() or ["exit %d" % p.returncode])[0]))
    return json.loads(p.stdout or "[]")


def gh_list(repo, kind, field, until, fields, limit):
    """(rows, reason, fetched, cap_hit) for everything from FIRST_DAY to `until` (YYYY-MM-DD; None means no upper bound): a search that returns `limit` rows may be cut off, so its date window is
    split in two and each half searched again, until every window returns fewer. A single day that still returns `limit` rows is cap_hit. rows is None with the reason when gh is absent or fails."""
    if not shutil.which("gh"):
        return None, "gh is not available", 0, False
    limit = min(limit, SEARCH_MAX)
    seen, state = {}, {"hit": False}

    def window(lo, hi):
        rows = gh_query(repo, kind, field, lo.isoformat(), hi.isoformat(), fields, limit)
        if len(rows) < limit:
            seen.update((r["number"], r) for r in rows)
        elif lo < hi:
            mid = lo + (hi - lo) // 2
            window(lo, mid)
            window(mid + datetime.timedelta(days=1), hi)
        else:
            state["hit"] = True
            seen.update((r["number"], r) for r in rows)

    try:
        top = datetime.date.fromisoformat(until) if until else datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=1)  # no upper bound: tomorrow covers every UTC date
        window(FIRST_DAY, top)
    except RuntimeError as e:
        return None, str(e), 0, False
    return sorted(seen.values(), key=lambda r: -r["number"]), "", len(seen), state["hit"]


def gh_section(rows, reason, fetched, cap, cap_hit, kept):
    return {"available": rows is not None, "reason": reason, "fetched": fetched, "cap": cap, "cap_hit": cap_hit, "total": len(kept), "rows": kept}


def commit_files(repo, oid):
    """Paths a PR changed, read from git (every kept PR's merge commit is in the rev's history, so gh need not list files): a squash or rebase commit's own diff; for a
    two-parent merge commit the branch's changes since it left the first parent (`P1...P2`), because the first-parent diff would also hold whatever the branch merged in from main."""
    parents = subprocess.run(["git", "-C", repo, "rev-list", "--parents", "-n", "1", oid], capture_output=True, text=True).stdout.split()[1:]
    if len(parents) == 2:
        cmd = ["git", "-C", repo, "diff", "--name-only", parents[0] + "..." + parents[1]]
    else:
        cmd = ["git", "-C", repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent", oid]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines()


def merged_prs(repo, sha, scope, limit):
    rows, reason, fetched, hit = gh_list(repo, "pr", "merged", None, "number,title,labels,mergedAt,mergeCommit", limit)
    if rows is None:
        return gh_section(None, reason, 0, min(limit, SEARCH_MAX), False, [])
    reachable = set(subprocess.run(["git", "-C", repo, "rev-list", sha], capture_output=True, text=True).stdout.split())
    kept = []
    for pr in rows:
        oid = (pr.get("mergeCommit") or {}).get("oid")
        if oid not in reachable:
            continue
        if scope and not any(in_scope(f, scope) for f in commit_files(repo, oid)):
            continue
        kept.append({"number": pr["number"], "title": pr["title"], "labels": [l["name"] for l in pr.get("labels") or []], "merged": (pr.get("mergedAt") or "")[:10]})
    return gh_section(rows, "", fetched, min(limit, SEARCH_MAX), hit, kept)


def created_by(stamp, committed):
    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() <= committed
    except (AttributeError, ValueError):
        return True


def issues(repo, scope, committed, limit):
    # GitHub search dates are UTC: search up to the UTC day after the commit, then keep only issues created by the commit's own time
    until = (datetime.datetime.fromtimestamp(committed, datetime.timezone.utc).date() + datetime.timedelta(days=1)).isoformat()
    rows, reason, fetched, hit = gh_list(repo, "issue", "created", until, "number,title,state,labels,createdAt,body", limit)
    if rows is None:
        return gh_section(None, reason, 0, min(limit, SEARCH_MAX), False, [])
    kept = [{"number": i["number"], "title": i["title"], "state": i["state"].lower(), "labels": [l["name"] for l in i.get("labels") or []], "created": (i.get("createdAt") or "")[:10]}
            for i in rows if created_by(i.get("createdAt"), committed) and (not scope or any(s in i["title"] + " " + (i.get("body") or "") for s in scope))]
    return gh_section(rows, "", fetched, min(limit, SEARCH_MAX), hit, kept)


def cut(rows, limit):
    """The `limit` newest rows and how many were cut; limit 0 means all."""
    if not limit:
        return rows, 0
    return rows[:limit], max(0, len(rows) - limit)


def gh_markdown(name, sec, line):
    head = "## %s (%d)" % (name, sec["total"])
    if not sec["available"]:
        return ["", head, "", "- unavailable: %s" % sec["reason"]]
    out = ["", head, "", "gh returned %d (searches split by date, each under the cap of %d), cap hit: %s" % (sec["fetched"], sec["cap"], "yes: one day holds that many, so some are missing" if sec["cap_hit"] else "no"), ""]
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
    sha = resolve(repo, rev)
    if not sha:
        return None
    for s in scope:
        if not git(repo, "ls-tree", sha, "--", s).strip():
            raise ValueError("scope %s does not exist at %s" % (s, sha[:7]))
    date = git(repo, "log", "-1", "--format=%cs", sha).strip()
    committed = int(git(repo, "log", "-1", "--format=%ct", sha).strip())
    present = set(git(repo, "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", sha).splitlines())
    commits = parse_log(git(repo, "-c", "core.quotepath=off", "log", sha, "-M", "--name-only", "--format=@@%H%x09%cs%x09%s", "--", *(scope or ["."]), ":(exclude)" + SNAPSHOTS))
    report = {"repo": os.path.basename(os.path.realpath(repo)), "rev": sha, "date": date, "scope": scope}
    for key, rows in (("signal_commits", signal_commits(commits, scope)), ("churn", churn(commits, scope, present, churn_min))):
        shown, extra = cut(rows, limit)
        report[key] = {"total": len(rows), "rows": shown, "cut": extra}
    off = {"available": False, "reason": "--no-gh", "fetched": 0, "cap": gh_limit, "cap_hit": False, "total": 0, "rows": []}
    for key, sec in (("merged_prs", merged_prs(repo, sha, scope, gh_limit) if with_gh else off), ("issues", issues(repo, scope, committed, gh_limit) if with_gh else off)):
        shown, extra = cut(sec["rows"], limit)
        report[key] = dict(sec, rows=shown, cut=extra)
    return report


def emit(text, out):
    """Print the report, or with --out write it to that file and print one line saying where. Returns the exit code, 0."""
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote %d lines to %s" % (text.count("\n"), out))
    else:
        print(text, end="")
    return 0


def main(argv):
    args, scope, opts, flags, it = [], [], {"--rev": "HEAD", "--format": "md", "--limit": "0", "--out": "", "--churn-min": "4", "--gh-limit": "1000"}, set(), iter(argv[1:])
    for a in it:
        if a == "--scope":
            scope.append(next(it, ""))
        elif a in opts:
            opts[a] = next(it, "")
        elif a == "--no-gh":
            flags.add(a)
        else:
            args.append(a)
    if len(args) != 1 or not os.path.isdir(args[0]) or opts["--format"] not in ("md", "json") or not all(opts[k].isdigit() for k in ("--limit", "--churn-min", "--gh-limit")) or int(opts["--gh-limit"]) < 1:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    scope = parse_scopes(args[0], scope)  # `.` gives [], the whole repo
    if scope is None:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    if subprocess.run(["git", "-C", args[0], "rev-parse", "--git-dir"], capture_output=True).returncode:
        return emit("no git history\n" if opts["--format"] == "md" else json.dumps({"history": "no git history"}) + "\n", opts["--out"])
    try:
        report = build(args[0], opts["--rev"], scope, int(opts["--limit"]), int(opts["--churn-min"]), int(opts["--gh-limit"]), "--no-gh" not in flags)
    except (RuntimeError, ValueError) as e:
        print("history_signals: %s" % e, file=sys.stderr)
        return 2
    if report is None:
        print("history_signals: %s is not a revision of %s" % (opts["--rev"], args[0]), file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2) + "\n" if opts["--format"] == "json" else markdown(report)
    return emit(text, opts["--out"])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
