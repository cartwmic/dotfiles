"""Tests for `kgate prune` (docs/kgate.md, "Prune").

The decision (`prune_plan`) is called directly. The real script also runs as a process against a fake state folder in a scratch
XDG_STATE_HOME (old, young, running, logged, journal-cited and PR-cited jobs, and things that are not job folders), with a fake `gh`
first on PATH: nothing reaches GitHub, and the folder is checked from outside before and after.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_kgate as T  # noqa: E402

K = T.K
# test_kgate deletes its rendered script when its own module ends, which can come before this module runs, so render a copy here.
_SCRIPT_DIR = tempfile.mkdtemp(prefix="kgate-prune-script-")
SCRIPT = Path(_SCRIPT_DIR) / "kgate"
SCRIPT.write_text(T.render_script("personal"))
SCRIPT.chmod(0o755)

NOW = datetime.datetime.now(datetime.timezone.utc)
DAY = 86400

# gh stand-in: `api user/repos` prints FAKE_GH_REPOS; `pr list -R X` prints FAKE_GH_PRS[X]; FAKE_GH_FAIL makes every call fail.
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
if os.environ.get("FAKE_GH_FAIL"):
    sys.stderr.write(os.environ["FAKE_GH_FAIL"] + "\nsecond line\n")
    sys.exit(1)
a = sys.argv[1:]
if a[:2] == ["api", "user/repos"]:
    print(os.environ.get("FAKE_GH_REPOS", ""))
elif a[:2] == ["pr", "list"]:
    print(json.dumps(json.loads(os.environ.get("FAKE_GH_PRS", "{}")).get(a[a.index("-R") + 1], [])))
else:
    sys.exit("fake gh: unexpected " + " ".join(a))
'''


def jid(days_old, pid):
    return "kgate-%d-%d" % (int(NOW.timestamp() - days_old * DAY), pid)


def iso(days_old):
    return (NOW - datetime.timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Plan(unittest.TestCase):
    def test_each_reason_keeps_and_the_rest_goes(self):
        old = [jid(20, n) for n in range(1, 7)]
        young = jid(1, 9)
        delete, kept, n_young = K.prune_plan(old + [young], NOW, {old[0]}, {old[1]}, {old[2]}, {old[3]})
        self.assertEqual(delete, sorted(old[4:]))
        self.assertEqual(kept, {"running": [old[0]], "logged": [old[1]], "journal": [old[2]], "pr": [old[3]]})
        self.assertEqual(n_young, 1)

    def test_the_age_line_is_three_days(self):
        just_over, just_under = jid(3.01, 1), jid(2.99, 2)
        delete, _, young = K.prune_plan([just_over, just_under], NOW, set(), set(), set(), set())
        self.assertEqual((delete, young), ([just_over], 1))


def tree_digest(root):
    """Every path under root with its mode and the hash of each file: equal before and after means nothing changed."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in sorted(os.walk(root)):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            p = os.path.join(dirpath, name)
            h.update((os.path.relpath(p, root) + "\0").encode())
            if os.path.isfile(p) and not os.path.islink(p):
                h.update(Path(p).read_bytes())
    return h.hexdigest()


class Process(unittest.TestCase):
    """The script as a process. Each job folder holds one 1 MiB file, so a folder reads 1.0 MiB whatever the filesystem charges for the directory itself."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kgate-prune-"))
        self.xdg = self.tmp / "xdg"
        self.state = self.xdg / "kgate"
        (self.state / "active").mkdir(parents=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "gh").write_text(FAKE_GH)
        (self.bin / "gh").chmod(0o755)
        self.ids = {n: jid(20, i) for i, n in enumerate(("old", "running", "logged", "cited", "pr", "other"), 1)}
        self.ids["young"] = jid(1, 50)
        for fid in self.ids.values():
            self.job_dir(fid)
        (self.state / ("kgate-1-1.out")).write_text("a plain file named like a job folder")
        (self.state / "merged-1-1.out").mkdir()
        (self.state / "merged-1-1.out" / "verdict.txt").write_text("VERDICT: PASSED\n")
        (self.state / "split-1-1").mkdir()
        (self.state / (self.ids["old"] + ".log")).write_text("a job's log\n")
        os.symlink(self.state / "active", self.state / "kgate-2-2.out")
        (self.state / "active" / (self.ids["running"] + ".json")).write_text("{}")
        self.write_log([(self.ids["logged"], 5, "coordinator")])
        self.journal = self.xdg / "coordinator-ci" / "main-journeys.jsonl"
        self.write_journal({"cited": [self.ids["cited"]]})
        self.prs = {"o/coordinator": [{"number": 7, "body": "## Proven\nran %s on kgate\n" % self.ids["pr"]}]}
        self.repos = "o/coordinator\no/other\n"

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)])

    def job_dir(self, fid):
        d = self.state / (fid + ".out")
        d.mkdir()
        (d / "journeys.log").write_bytes(os.urandom(2**20))

    def write_log(self, rows):
        with open(self.state / "log.jsonl", "w") as f:
            for fid, days, repo in rows:
                f.write(json.dumps({"id": fid, "start": iso(days), "repo": repo, "exit": 0}) + "\n")
            f.write(json.dumps({"id": jid(30, 99), "start": iso(30), "repo": "scratch-clone", "exit": 0}) + "\n")

    def write_journal(self, runs):
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal, "w") as j:
            for name, ids in runs.items():
                receipt = self.xdg / "coordinator-ci" / (name + "-cluster.log")
                receipt.write_text("".join("merged: %s/%s.out\n" % (self.state, i) for i in ids))
                j.write(json.dumps({"tip": "a" * 40, "verdict": "pass", "receipts": {"cluster": str(receipt)}}) + "\n")
            j.write(json.dumps({"tip": "b" * 40, "verdict": "flake", "issue": 1}) + "\n")  # a flake ruling names no receipts

    def prune(self, *args, **env):
        e = dict(os.environ, XDG_STATE_HOME=str(self.xdg), PATH="%s:%s" % (self.bin, os.environ["PATH"]), FAKE_GH_REPOS=self.repos, FAKE_GH_PRS=json.dumps(self.prs))
        e.update(env)
        return subprocess.run([sys.executable, str(SCRIPT), "prune", *args], capture_output=True, text=True, env=e, timeout=60)

    def present(self):
        return {n for n, fid in self.ids.items() if (self.state / (fid + ".out")).is_dir()}

    def test_dry_run_says_what_it_would_remove_and_changes_nothing(self):
        before = tree_digest(self.state)
        r = self.prune()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(tree_digest(self.state), before)
        lines = r.stdout.splitlines()
        self.assertEqual([l for l in lines if l.startswith("would delete kgate-")], ["would delete %s.out  %s" % (self.ids[n], "1.0 MiB") for n in ("old", "other")])
        self.assertIn("would delete 2 folders, 2.0 MiB (disk blocks) would be freed; kept 4 older than 3 days (running (active/ entry) 1, log.jsonl record in the last 7 days 1, "
                      "cited by the main-run journal 1, cited in an open PR body 1); 1 younger left alone", r.stdout)
        self.assertIn("PRs not scanned (no GitHub repo of that name that gh lists): scratch-clone", r.stdout)

    def test_delete_removes_exactly_the_planned_folders(self):
        job_folders = {i + ".out" for i in self.ids.values()}
        outside = {p.name for p in self.state.iterdir()} - job_folders
        before_log = (self.state / "log.jsonl").read_bytes()
        r = self.prune("--delete")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.present(), {"running", "logged", "cited", "pr", "young"})
        self.assertEqual({p.name for p in self.state.iterdir()} - job_folders - {"prune.jsonl"}, outside)  # everything that is not a job folder is still there
        for kept in ("active", "log.jsonl", "kgate-1-1.out", "kgate-2-2.out", "merged-1-1.out", "split-1-1", self.ids["old"] + ".log"):
            self.assertTrue((self.state / kept).exists() or (self.state / kept).is_symlink(), kept)
        self.assertEqual((self.state / "log.jsonl").read_bytes(), before_log)
        self.assertTrue((self.state / "active" / (self.ids["running"] + ".json")).exists())
        rec = json.loads((self.state / "prune.jsonl").read_text())
        self.assertEqual(rec["deleted"], 2)
        self.assertTrue(2 * 2**20 <= rec["bytes"] < 2 * 2**20 + 65536, rec)

    def test_a_job_with_no_journal_present_is_not_a_refusal(self):
        self.journal.unlink()
        r = self.prune("--delete")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("journal not present", r.stdout)
        self.assertEqual(self.present(), {"running", "logged", "pr", "young"})  # nothing cites "cited" any more

    def refused(self, why, **env):
        before = tree_digest(self.state)
        for args in ((), ("--delete",)):
            with self.subTest(why, args=args):
                r = self.prune(*args, **env)
                self.assertEqual(r.returncode, 69, r.stdout + r.stderr)
                self.assertIn("refused, nothing deleted", r.stderr)
                self.assertEqual(tree_digest(self.state), before)
                self.assertEqual(self.present(), set(self.ids))
        return r

    def test_gh_failing_deletes_nothing_and_names_the_source(self):
        r = self.refused("gh fails", FAKE_GH_FAIL="HTTP 401: bad credentials")
        self.assertIn("open PR bodies: gh api user/repos --paginate failed: HTTP 401: bad credentials", r.stderr)

    def test_gh_missing_deletes_nothing(self):
        (self.bin / "gh").unlink()
        r = self.refused("no gh", PATH=str(self.bin))  # no gh and no python3 on PATH: the script is run by its interpreter path
        self.assertIn("open PR bodies", r.stderr)

    def test_an_unreadable_journal_receipt_deletes_nothing(self):
        (self.xdg / "coordinator-ci" / "cited-cluster.log").unlink()
        r = self.refused("receipt file gone")
        self.assertIn("main-journeys.jsonl line 1: receipt file", r.stderr)

    def test_a_journal_line_that_does_not_parse_deletes_nothing(self):
        with open(self.journal, "a") as f:
            f.write("{not json\n")
        r = self.refused("bad journal line")
        self.assertIn("line 3 does not parse", r.stderr)

    def test_a_missing_or_garbled_job_log_deletes_nothing(self):
        (self.state / "log.jsonl").write_text("{broken\n")
        self.assertIn("1 lines that do not parse", self.refused("garbled log").stderr)
        (self.state / "log.jsonl").unlink()
        self.assertIn("is missing", self.refused("no log").stderr)

    def test_a_bad_flag_is_a_usage_error(self):
        r = self.prune("--force")
        self.assertEqual(r.returncode, 64)
        self.assertIn("kgate prune [--delete]", r.stderr)  # the usage text names the subcommand


if __name__ == "__main__":
    unittest.main()
