#!/usr/bin/env python3
"""Resolve the history refs in the evidence column of a REQUIREMENTS.md: `commit:<sha>`, `pr:<n>` and `issue:<n>`.

usage: check_history_refs.py REQUIREMENTS.md REPO

For each ref prints `R-id | ref | resolved | subject or title` or `R-id | ref | UNRESOLVED | reason`.
  commit  resolved with `git -C REPO cat-file -e <sha>^{commit}`; the subject comes from `git log -1`
  pr      resolved with `gh pr view <n> --json title` run in REPO
  issue   resolved with `gh issue view <n> --json title` run in REPO
With no `gh` on PATH, or a `gh` that fails, a pr or issue is listed UNRESOLVED with the reason; that does not fail the run (the number is checked by nothing else).
Then one line lists the rows whose refs all resolved: "resolved, claim not read-checked". A ref that resolves proves the commit, PR or issue exists, not that it says what the row says.
Exit 1 when a commit ref does not resolve, 0 otherwise, 2 on bad usage. Stdlib only.
"""
import os
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


def resolve_commit(repo, ref):
    sha = ref.split(":", 1)[1]
    code, _, err = run(["git", "-C", repo, "cat-file", "-e", sha + "^{commit}"])
    if code:
        return False, "no such commit in %s" % repo
    return True, run(["git", "-C", repo, "log", "-1", "--format=%s", sha])[1]


def resolve_gh(repo, ref):
    kind, number = ref.split(":", 1)
    if not shutil.which("gh"):
        return False, "gh is not available"
    code, out, err = run(["gh", kind, "view", number, "--json", "title", "--jq", ".title"], cwd=repo)
    if code:
        return False, "gh could not read it: %s" % ((err.splitlines() or ["exit %d" % code])[0])
    return True, out


def main(argv):
    if len(argv) != 3 or not os.path.isfile(argv[1]) or not os.path.isdir(argv[2]):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    repo = argv[2]
    with open(argv[1], encoding="utf-8") as f:
        rows = register_rows(f.read())
    bad_commit, clean, unresolved = 0, [], []
    for _, row in rows:
        refs = [(k, p) for k, p in evidence_parts(row["evidence"]) if k in ("commit", "pr", "issue")]
        ok_all = bool(refs)
        for kind, ref in refs:
            ok, text = (resolve_commit if kind == "commit" else resolve_gh)(repo, ref)
            print("%s | %s | %s | %s" % (row["id"], ref, "resolved" if ok else "UNRESOLVED", text))
            if not ok:
                ok_all = False
                unresolved.append("%s %s" % (row["id"], ref))
                bad_commit += kind == "commit"
        if ok_all:
            clean.append(row["id"])
    print("resolved, claim not read-checked: %s" % (", ".join(clean) or "none"))
    print("unresolved: %s" % (", ".join(unresolved) or "none"))
    return 1 if bad_commit else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
