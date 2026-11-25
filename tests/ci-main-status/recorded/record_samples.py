#!/usr/bin/env python3
"""Record the small real-`gh` samples that test_ci_main_status.py compares the fake `gh` against.

Run it by hand, with a logged-in `gh`, when GitHub's behaviour might have changed:  python3 record_samples.py
It writes three files next to itself. Each holds only the shape the script relies on (field names, a few values), never a 1,000-row dump.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO, WORKFLOW = "cartwmic/dotfiles", "ci.yml"
HERE = Path(__file__).resolve().parent
FIELDS = "databaseId,attempt,createdAt,startedAt,updatedAt,conclusion,status,event,headSha,headBranch"


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode:
        sys.exit("gh %s: %s" % (" ".join(args), r.stderr))
    return json.loads(r.stdout)


def save(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    # 1. A rerun keeps the run's createdAt; startedAt is when the rerun began. One row with attempt >= 2.
    rows = gh("run", "list", "-R", REPO, "--workflow", WORKFLOW, "--limit", "300", "--json", FIELDS)
    rerun = next(r for r in rows if r["attempt"] >= 2 and r["status"] == "completed")
    first = gh("api", "repos/%s/actions/runs/%d/attempts/1" % (REPO, rerun["databaseId"]))
    save("rerun_keeps_created_at.json", {"row": rerun, "attempt_1": {k: first[k] for k in ("created_at", "run_started_at", "run_attempt", "conclusion", "status")}})
    # 2. A list with --created that asks for more than 1,000 rows gives 1,000 (without --created it gives them all): the ceiling the script splits on.
    big = gh("run", "list", "-R", REPO, "--workflow", WORKFLOW, "--created", ">=2020-01-01", "--limit", "1100", "--json", "databaseId,createdAt")
    plain = gh("run", "list", "-R", REPO, "--workflow", WORKFLOW, "--limit", "1100", "--json", "databaseId")
    save("run_list_ceiling.json", {"requested": 1100, "got_without_created": len(plain), "got": len(big), "keys": sorted(big[0]), "newest_first": [r["createdAt"] for r in big] == sorted((r["createdAt"] for r in big), reverse=True)})
    # 3. compare: status and the counts, and the keys of one listed commit.
    tip = gh("api", "repos/%s/commits/HEAD" % REPO)
    base = gh("api", "repos/%s/commits/HEAD~3" % REPO)
    cmp = gh("api", "repos/%s/compare/%s...%s" % (REPO, base["sha"], tip["sha"]))
    save("compare_ahead_by.json", {"status": cmp["status"], "ahead_by": cmp["ahead_by"], "behind_by": cmp["behind_by"], "total_commits": cmp["total_commits"],
                                    "listed": len(cmp["commits"]), "top_keys": sorted(k for k in cmp if k in ("status", "ahead_by", "behind_by", "total_commits", "commits")),
                                    "commit_keys": sorted(cmp["commits"][0]), "commit_commit_keys": sorted(cmp["commits"][0]["commit"]), "committer_keys": sorted(cmp["commits"][0]["commit"]["committer"])})


main()
