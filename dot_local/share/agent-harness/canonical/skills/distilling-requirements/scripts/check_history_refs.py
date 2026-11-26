#!/usr/bin/env python3
"""Resolve the history refs in the evidence column of a REQUIREMENTS.md: `commit:<sha>`, `pr:<n>` and `issue:<n>`.

usage: check_history_refs.py REQUIREMENTS.md REPO [--commit SHA]

For each ref prints `R-id | ref | resolved | subject or title`, `R-id | ref | UNRESOLVED | reason` or `R-id | ref | NOT CHECKED | reason`.
  commit  must exist (`git -C REPO cat-file -e <sha>^{commit}`) and be an ancestor of the snapshot commit: --commit, else the header's `commit:`
          (an archive has none, so only existence is checked, and the output says so)
  pr      `gh pr view <n>` run in REPO: it must be a merged PR whose merge commit is an ancestor of the snapshot commit (a PR still open, closed unmerged or merged later fails)
  issue   `gh issue view <n>` run in REPO: it must be an issue, not a PR, created no later than the snapshot commit's time
A pr or issue that gh says does not exist, or that fails those tests, is UNRESOLVED. With no `gh` on PATH, or a gh that cannot run (not signed in, no network, no GitHub remote), it is NOT CHECKED
and the output says why; that alone does not fail the run. Then one line lists the rows whose refs all resolved: "resolved, claim not read-checked". A ref that resolves
proves the commit, PR or issue exists, not that it says what the row says.
Exit 1 when any ref is UNRESOLVED (a commit that is missing or not an ancestor, a PR or issue gh says is not there or that fails the tests above), 0 otherwise, 2 on bad usage. Stdlib only.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folders are deployed; leave no __pycache__ in them
from check_shape import evidence_parts  # noqa: E402
from check_truth import register_rows  # noqa: E402


def run(argv, cwd=None):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, cwd=cwd, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


NOT_FOUND = re.compile(r"could not resolve to a (?:pullrequest|issue|issue or pull request)\b|not found|no (?:pull requests?|issues?) found|http 404", re.I)


def resolve_commit(repo, ref, snapshot):
    sha = ref.split(":", 1)[1]
    if run(["git", "-C", repo, "cat-file", "-e", sha + "^{commit}"])[0]:
        return "UNRESOLVED", "no such commit in %s" % repo
    if snapshot and run(["git", "-C", repo, "merge-base", "--is-ancestor", sha, snapshot])[0]:
        return "UNRESOLVED", "not an ancestor of the snapshot commit %s" % snapshot[:7]
    return "resolved", run(["git", "-C", repo, "log", "-1", "--format=%s", sha])[1]


def utc(stamp):
    return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def resolve_gh(repo, ref, snapshot=None):
    kind, number = ref.split(":", 1)
    if not shutil.which("gh"):
        return "NOT CHECKED", "gh is not available"
    fields = "title,state,mergeCommit,url" if kind == "pr" else "title,createdAt,url"
    code, out, err = run(["gh", kind, "view", number, "--json", fields], cwd=repo)
    if code:
        first = (err.splitlines() or ["exit %d" % code])[0]
        return ("UNRESOLVED", "gh says it does not exist: %s" % first) if NOT_FOUND.search(err) else ("NOT CHECKED", "gh cannot run here (not signed in, no network or no GitHub remote): %s" % first)
    try:
        info = json.loads(out)
        title = info["title"]
    except (ValueError, KeyError, TypeError):
        return "NOT CHECKED", "gh gave output this script cannot read: %s" % out[:80]
    if kind == "pr":
        oid = (info.get("mergeCommit") or {}).get("oid")
        if info.get("state") != "MERGED" or not oid:
            return "UNRESOLVED", "pull request %s is %s, not merged: %s" % (number, (info.get("state") or "not open").lower(), title)
        if snapshot and run(["git", "-C", repo, "merge-base", "--is-ancestor", oid, snapshot])[0]:
            return "UNRESOLVED", "pull request %s was merged at %s, which is not an ancestor of the snapshot commit %s: %s" % (number, oid[:7], snapshot[:7], title)
        return "resolved", title
    if "/pull/" in (info.get("url") or ""):
        return "UNRESOLVED", "%s is a pull request, not an issue (cite it as pr:%s): %s" % (number, number, title)
    if snapshot and info.get("createdAt"):
        when = run(["git", "-C", repo, "log", "-1", "--format=%ct", snapshot])[1]
        if when.isdigit() and utc(info["createdAt"]).timestamp() > int(when):
            return "UNRESOLVED", "issue %s was created %s, after the snapshot commit %s: %s" % (number, info["createdAt"], snapshot[:7], title)
    return "resolved", title


def main(argv):
    args, snapshot, it = [], None, iter(argv[1:])
    for a in it:
        if a == "--commit":
            snapshot = next(it, None)
        else:
            args.append(a)
    if len(args) != 2 or not os.path.isfile(args[0]) or not os.path.isdir(args[1]) or snapshot == "":
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    repo = args[1]
    with open(args[0], encoding="utf-8") as f:
        text = f.read()
    if snapshot is None:
        m = re.search(r"^commit:\s*([0-9a-f]{40})\s*$", text, re.M)
        snapshot = m.group(1) if m else None
    if snapshot and run(["git", "-C", repo, "cat-file", "-e", snapshot + "^{commit}"])[0]:
        print("snapshot commit %s is not in %s" % (snapshot, repo), file=sys.stderr)
        return 2
    print("snapshot commit: %s" % (snapshot or "none (archive): commits are checked for existence only"))
    rows = register_rows(text)
    failed, clean, unresolved, unchecked = False, [], [], []
    for _, row in rows:
        refs = [(k, p) for k, p in evidence_parts(row["evidence"]) if k in ("commit", "pr", "issue")]
        ok_all = bool(refs)
        for kind, ref in refs:
            status, text_ = resolve_commit(repo, ref, snapshot) if kind == "commit" else resolve_gh(repo, ref, snapshot)
            print("%s | %s | %s | %s" % (row["id"], ref, status, text_))
            if status != "resolved":
                ok_all = False
                (unresolved if status == "UNRESOLVED" else unchecked).append("%s %s" % (row["id"], ref))
                failed = failed or status == "UNRESOLVED"
        if ok_all:
            clean.append(row["id"])
    print("resolved, claim not read-checked: %s" % (", ".join(clean) or "none"))
    print("unresolved: %s" % (", ".join(unresolved) or "none"))
    print("not checked (gh could not run): %s" % (", ".join(unchecked) or "none"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
