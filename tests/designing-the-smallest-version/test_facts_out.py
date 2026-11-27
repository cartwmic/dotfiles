"""repo_facts.py --out never replaces a file that is already there unless --force is given.
Run: python3 -I tests/designing-the-smallest-version/test_facts_out.py"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = tempfile.mkdtemp(prefix="state-")  # the script logs each run (runlog.py): keep these runs out of the real log
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

SKILLS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills"
REPO_FACTS = SKILLS / "designing-the-smallest-version/scripts/repo_facts.py"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def run(repo, *args, cwd=None):
    return subprocess.run([sys.executable, "-B", str(REPO_FACTS), str(repo), *args], capture_output=True, text=True,
                          cwd=cwd)


class OutNeverLosesABlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="facts_out-"))
        cls.repo = cls.tmp / "repo"
        (cls.repo / "src").mkdir(parents=True)
        (cls.repo / "src/a.py").write_text("x = 1\n")
        cls.parts = cls.tmp / "parts.tsv"
        cls.parts.write_text("src/**\tsrc part\n")
        for cmd in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", "c")):
            subprocess.run(["git", "-C", str(cls.repo), *cmd], check=True, capture_output=True, env=ENV)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def out(self, name):
        return self.tmp / name

    def test_an_existing_file_is_refused_and_survives_whatever_the_options(self):
        f = self.out("a.json")
        self.assertEqual(run(self.repo, "--parts", str(self.parts), "--out", str(f)).returncode, 0)
        before = f.read_text()
        for opts in (("--summary",), (), ("--parts", str(self.parts)), ("--scope", "src/**"), ("--scope", "lib/**", "--summary")):
            done = run(self.repo, *opts, "--out", str(f))
            self.assertEqual(done.returncode, 2, (opts, done.stdout))
            self.assertIn("already exists", done.stderr)
            self.assertEqual(f.read_text(), before)

    def test_the_refusal_comes_before_any_analysis(self):
        f = self.out("b.json")
        f.write_text("keep")
        done = run(self.tmp / "no-such-repo", "--out", str(f))  # a path that is no git repo would fail with its own message if the analysis ran first
        self.assertEqual(done.returncode, 2)
        self.assertIn("already exists", done.stderr)
        self.assertEqual(f.read_text(), "keep")

    def test_force_replaces_the_file(self):
        f = self.out("c.json")
        self.assertEqual(run(self.repo, "--scope", "src/**", "--out", str(f)).returncode, 0)
        self.assertEqual(run(self.repo, "--force", "--out", str(f)).returncode, 0)
        self.assertNotIn("scope", json.loads(f.read_text()))

    def last_record(self):
        state = Path(os.environ["XDG_STATE_HOME"])  # the folder the runs used: whichever test module set it last
        return json.loads((state / "designing-the-smallest-version/log.jsonl").read_text().splitlines()[-1])

    def test_a_fresh_path_is_written_and_logged_as_not_replaced(self):
        f = self.out("log-new.json")
        self.assertEqual(run(self.repo, "--out", str(f)).returncode, 0)
        rec = self.last_record()
        self.assertEqual((rec["outcome"], rec["exit"], rec["out"], rec["force"], rec["replaced"]), ("ok", 0, str(f), False, False))

    def test_a_forced_overwrite_changes_the_file_and_is_logged_as_replaced(self):
        f = self.out("log-force.json")
        f.write_text("old")
        self.assertEqual(run(self.repo, "--force", "--out", str(f)).returncode, 0)
        self.assertIn("rev", json.loads(f.read_text()))
        rec = self.last_record()
        self.assertEqual((rec["outcome"], rec["out"], rec["force"], rec["replaced"]), ("ok", str(f), True, True))

    def test_force_into_a_new_path_is_logged_as_not_replaced(self):
        f = self.out("log-force-new.json")
        self.assertEqual(run(self.repo, "--force", "--out", str(f)).returncode, 0)
        rec = self.last_record()
        self.assertEqual((rec["force"], rec["replaced"]), (True, False))

    def assert_refused(self, done, f, reason):
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertEqual(f.read_bytes(), b"old bytes")  # the file is as it was
        rec = self.last_record()
        self.assertEqual((rec["outcome"], rec["exit"]), ("refused", 2))
        self.assertIn(reason, rec["reason"])
        self.assertNotIn("replaced", rec)  # a refused run replaced nothing, and says nothing of it
        self.assertIn(reason, done.stderr)
        return rec

    def test_an_existing_file_without_force_is_refused_and_logged_with_no_replaced(self):
        f = self.out("r1.json")
        f.write_bytes(b"old bytes")
        rec = self.assert_refused(run(self.repo, "--out", str(f)), f, "already exists")
        self.assertEqual((rec["out"], rec["force"]), (str(f), False))

    def test_a_bad_rev_is_refused_with_or_without_force_and_the_file_is_kept(self):
        for name, force in (("r2a.json", ()), ("r2b.json", ("--force",))):  # a bad rev with --force once logged replaced: true
            f = self.out(name)
            f.write_bytes(b"old bytes")
            if force:
                rec = self.assert_refused(run(self.repo, "--rev", "no-such-rev", "--force", "--out", str(f)), f, "unknown rev")
                self.assertEqual((rec["force"], rec["out"]), (True, str(f)))
            else:  # without --force the existing file is refused first, before the rev is looked at
                self.assert_refused(run(self.repo, "--rev", "no-such-rev", "--out", str(f)), f, "already exists")

    def test_a_bad_rev_into_a_fresh_path_writes_nothing(self):
        f = self.out("r2c.json")
        done = run(self.repo, "--rev", "no-such-rev", "--out", str(f))
        self.assertEqual(done.returncode, 2)
        self.assertFalse(f.exists())
        self.assertIn("unknown rev", self.last_record()["reason"])
        self.assertNotIn("replaced", self.last_record())

    def test_a_path_that_is_not_a_git_repo_is_refused_and_the_file_is_kept(self):
        f = self.out("r3.json")
        f.write_bytes(b"old bytes")
        self.assert_refused(run(self.tmp / "no-such-repo", "--force", "--out", str(f)), f, "not a git repo")

    def test_a_fault_in_os_replace_leaves_the_old_file_and_logs_failed(self):
        f = self.out("r4.json")
        f.write_bytes(b"old bytes")
        code = ("import os, sys, runpy\n"
                "def boom(*a): raise OSError(5, 'injected')\n"
                "os.replace = boom\n"
                "sys.argv = ['repo_facts.py', %r, '--force', '--out', %r]\n"
                "runpy.run_path(%r, run_name='__main__')" % (str(self.repo), str(f), str(REPO_FACTS)))
        done = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(f.read_bytes(), b"old bytes")
        self.assertEqual(sorted(p.name for p in self.tmp.glob(".facts-*")), [])  # the temp file is gone
        rec = self.last_record()
        self.assertEqual((rec["outcome"], rec["exit"], rec["force"]), ("failed", 1, True))
        self.assertIn("injected", rec["error"])
        self.assertNotIn("replaced", rec)

    def test_a_file_that_appears_after_the_first_check_is_still_refused(self):
        f = self.out("r4b.json")
        code = ("import os, sys, runpy\n"
                "real = os.fsync\n"
                "def fsync(fd):\n"
                "    real(fd)\n"
                "    open(%r, 'wb').write(b'arrived late')\n"
                "os.fsync = fsync\n"
                "sys.argv = ['repo_facts.py', %r, '--out', %r]\n"
                "runpy.run_path(%r, run_name='__main__')" % (str(f), str(self.repo), str(f), str(REPO_FACTS)))
        done = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertEqual(f.read_bytes(), b"arrived late")
        self.assertEqual(sorted(p.name for p in self.tmp.glob(".facts-*")), [])
        rec = self.last_record()
        self.assertEqual(rec["outcome"], "refused")
        self.assertNotIn("replaced", rec)

    def test_a_run_with_no_out_logs_no_out_fields(self):
        self.assertEqual(run(self.repo).returncode, 0)
        self.assertNotIn("replaced", self.last_record())

    def test_the_audit_skill_forces_its_scratch_facts_file(self):
        text = (SKILLS / "auditing-design-principles/SKILL.md").read_text()
        line = next(l for l in text.splitlines() if "repo_facts.py" in l)
        self.assertIn("--out <scratch>/facts.json --force", line)  # a rerun of the audit would be refused without it

    def test_the_audit_skill_says_the_facts_script_reads_rust(self):
        text = (SKILLS / "auditing-design-principles/SKILL.md").read_text()
        line = next(l for l in text.splitlines() if "Import `edges` and cycles cover" in l)
        self.assertIn("Rust", line)  # an auditor of a Rust repo must not discard its edges

    def test_a_new_file_is_free_and_a_summary_with_no_out_writes_no_file(self):
        self.assertEqual(run(self.repo, "--summary", "--out", str(self.out("fresh.json"))).returncode, 0)
        before = set(self.tmp.iterdir())
        cwd = Path(tempfile.mkdtemp(prefix="facts_cwd-"))
        self.addCleanup(shutil.rmtree, cwd, True)
        self.assertEqual(run(self.repo, "--summary", cwd=cwd).returncode, 0)
        self.assertEqual(set(self.tmp.iterdir()), before)
        self.assertEqual(list(cwd.iterdir()), [], "a run with no --out wrote a file into its working folder")


if __name__ == "__main__":
    unittest.main()
