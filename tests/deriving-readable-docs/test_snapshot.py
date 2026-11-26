"""The snapshot header of a GUIDE.md: assemble.py prints it, lint_main.py fails a guide without it, and no other check counts it as a claim.
Run: python3 -I tests/deriving-readable-docs/test_snapshot.py"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = tempfile.mkdtemp(prefix="state-")  # the scripts log each run (runlog.py): keep these runs out of the real log
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_assemble import SCRIPTS, run, setup  # noqa: E402

PART1 = "## What it is\n\nNotes saves short notes. [A3.1]\nWho it is for: anyone who takes notes. [A3.1]\n\n## How to start\n\nYou set a tag with an option. [A4.1]\n"
LINE = "Not maintained: it records the code at that commit, not today's."
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull)


def assembled(git=False):
    d, repo = tempfile.mkdtemp(), tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)
    atexit.register(shutil.rmtree, repo, True)
    setup(d, repo, **{"part1.md": PART1})
    sha = None
    if git:
        for cmd in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "x"]):
            subprocess.run(["git", "-C", repo, *cmd], check=True, capture_output=True, env=ENV)
        sha = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    code, out, err = run("assemble.py", d, repo, "--date", "2026-11-20", "--clean")
    assert code == 0, err
    return Path(d), repo, sha


def lint(d, repo, guide=None):
    if guide is not None:
        Path(d, "GUIDE.md").write_text(guide)
    return run("lint_main.py", str(Path(d, "GUIDE.md")), repo, "--surfaces", str(Path(d, "surfaces.json")))


class SnapshotHeaderTest(unittest.TestCase):
    def test_a_git_repo_gets_the_fixed_line_with_its_short_sha_and_the_key_with_the_full_one(self):
        d, repo, sha = assembled(git=True)
        guide = (d / "GUIDE.md").read_text()
        self.assertIn("\nSnapshot of %s at %s on 2026-11-20. %s\n" % (os.path.basename(repo), sha[:7], LINE), guide)
        self.assertIn("Snapshot: 2026-11-20 at %s." % sha, guide)
        self.assertLess(guide.index("# %s guide" % os.path.basename(repo)), guide.index("Snapshot of"))
        self.assertEqual(lint(d, repo)[0], 0)

    def test_a_repo_with_no_git_says_no_git_in_both_places(self):
        d, repo, _ = assembled()
        guide = (d / "GUIDE.md").read_text()
        self.assertIn("at no-git on 2026-11-20. " + LINE, guide)
        self.assertIn("Snapshot: 2026-11-20 at no-git.", guide)
        self.assertEqual(lint(d, repo)[0], 0)

    def test_the_clean_copy_keeps_the_snapshot_line(self):
        d, repo, _ = assembled()
        self.assertIn(LINE, (d / "GUIDE.clean.md").read_text())

    def test_the_line_is_no_claim_and_no_check_reads_it(self):
        d, repo, _ = assembled()
        self.assertEqual(run("check_citations.py", str(d / "GUIDE.md"), repo, "--max-words", "6000", "--max-sentence-words", "18")[0], 0)
        code, out, err = run("slice.py", str(d / "GUIDE.md"), repo, "--out", str(d / "slices"))
        self.assertEqual(code, 0, err)
        self.assertNotIn("Not maintained", "".join(p.read_text() for p in (d / "slices").glob("*.claims.txt")))

    def test_a_guide_without_the_line_fails_the_lint(self):
        d, repo, _ = assembled()
        guide = (d / "GUIDE.md").read_text()
        for broken in (guide.replace("Snapshot of", "Notes of"), guide.replace(LINE, "Kept up to date."), guide[guide.index("# Part 1"):]):
            code, out, _ = lint(d, repo, broken)
            self.assertEqual(code, 1)
            self.assertIn("FAIL snapshot", out)

    def test_the_key_must_agree_with_the_line(self):
        d, repo, _ = assembled()
        guide = (d / "GUIDE.md").read_text()
        for broken in (guide.replace("Snapshot: 2026-11-20 at", "Snapshot: 2026-11-21 at"), guide.replace("Snapshot: 2026-11-20 at no-git.", "Snapshot: 2026-11-20 at " + "a" * 40 + "."), guide.replace("Snapshot: 2026-11-20 at no-git.", "")):
            code, out, _ = lint(d, repo, broken)
            self.assertEqual(code, 1)
            self.assertIn("the header needs `Snapshot: 2026-11-20 at <full sha>.`", out)


if __name__ == "__main__":
    unittest.main()
