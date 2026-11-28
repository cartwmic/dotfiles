#!/usr/bin/env python3
"""The false-hit rate of public-text-check on a sample: the N (default 50) merged pull requests of a repository that
`gh pr list --repo R --state merged --limit N` returns (the most recently updated first), each title and description run through the check.

    scripts/public-text-sample.py OWNER/REPO [N]

GitHub reads: one `gh pr list`, plus the check's own visibility lookup for each pull request (N + 1 in all). Prints, for each refused pull request, the class and line of each hit (never the text), then one line: how many were
selected, checked, refused and unreadable (the check could not run). A person then reads each refused one: a real private detail is a catch, anything else is a false hit.
Nothing is posted; the check's own log goes to a scratch directory. PUBLIC_TEXT_CHECK names another command, PUBLIC_TEXT_CLASSES_FILE another table."""
import json
import os
import re
import subprocess
import sys
import tempfile

if len(sys.argv) < 2:
    sys.exit("usage: public-text-sample.py OWNER/REPO [N]")
repo, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 50
check = os.environ.get("PUBLIC_TEXT_CHECK", "public-text-check")
listing = subprocess.run(["gh", "pr", "list", "--repo", repo, "--state", "merged", "--limit", str(n), "--json", "number,title,body"], capture_output=True, text=True)
if listing.returncode != 0:
    sys.exit("gh pr list failed: " + listing.stderr.strip()[:200])
prs = json.loads(listing.stdout)
refused = unreadable = 0
with tempfile.TemporaryDirectory(prefix="public-text-sample.") as scratch:
    env = dict(os.environ, XDG_STATE_HOME=os.path.join(scratch, "state"))
    for pr in prs:
        body = os.path.join(scratch, "body.md")
        with open(body, "w", encoding="utf-8") as f:
            f.write(pr["body"] or "")
        done = subprocess.run([check, "--repo", repo, "--caller", "sample", "--title", pr["title"], "--file", "body=" + body], capture_output=True, text=True, env=env)
        if done.returncode == 1:
            refused += 1
            hits = [m.group(0).strip() for line in done.stderr.splitlines() if (m := re.match(r"\s*(?:title|body):\d+: .+", line))]
            print("#%d: %s" % (pr["number"], "; ".join(hits)))
        elif done.returncode != 0:
            unreadable += 1
            print("#%d: could not be checked (exit %d)" % (pr["number"], done.returncode))
print("%s: last %d merged (gh pr list --state merged --limit %d): %d selected, %d checked, %d refused, %d unreadable" % (repo, n, n, len(prs), len(prs) - unreadable, refused, unreadable))
