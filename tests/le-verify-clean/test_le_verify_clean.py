"""Black-box tests for dot_local/bin/executable_le-verify-clean.

The real script runs as a real process in a real bwrap. Only `lean-change` is scripted: a fake first on PATH that makes a failed-journey folder
in /tmp the way the real journeys do (journey.ts hard-codes mkdtempSync("/tmp", "le-journey-<name>-")), records what it was given, and can
wait, sleep or exit with a chosen status. Everything is checked from outside: the real /tmp, the run folder, the output file and the exit code.

The class this guards: the old per-run helper deleted /tmp/le-journey-* folders by matching their repo copy's head or base, so it deleted
another run's folders (2026-11-17). test_old_helper_deletes_another_runs_folder runs that helper (old-verify-clean-env.sh, verbatim) against
the same decoy and shows it deleting it; test_other_runs_folder_survives shows le-verify-clean leaves it.
bwrap-dependent tests skip where bwrap cannot start (a host without user namespaces).
Run: python3 -m unittest discover -s tests/le-verify-clean
"""
import glob
import os
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get("LE_VERIFY_CLEAN") or HERE.parents[1] / "dot_local/bin/executable_le-verify-clean")
OLD_HELPER = HERE / "old-verify-clean-env.sh"

# The scripted lean-change. FAKE_RUN is the run folder (verify's cwd); FAKE_NAME makes its journey folder name unique to the test.
FAKE_LEAN_CHANGE = r'''#!/bin/sh
d=$(mktemp -d "/tmp/le-journey-$FAKE_NAME-XXXXXX")
mkdir "$d/state"
echo "journey log" > "$d/server.log"
echo "nested log" > "$d/state/board.log"
echo "not a log" > "$d/notes.txt"
echo "$d" > "$FAKE_RUN/journey-dir"
echo $$ > "$FAKE_RUN/pid"
pwd > "$FAKE_RUN/cwd"
env | grep -E '^(T3|CLAUDE)' > "$FAKE_RUN/leaked-env"
cat > "$FAKE_RUN/stdin"
: > "$FAKE_RUN/started"
if [ -n "${FAKE_WAIT_FOR:-}" ]; then
  while [ ! -e "$FAKE_RUN/$FAKE_WAIT_FOR" ]; do sleep 0.05; done
fi
echo '{"verify":"ran"}'
[ -z "${FAKE_SLEEP:-}" ] || exec sleep 600
exit "${FAKE_EXIT:-0}"
'''


def bwrap_works():
    try:
        return subprocess.run(["bwrap", "--dev-bind", "/", "/", "true"], capture_output=True, timeout=30).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


HAVE_BWRAP = bwrap_works()
needs_bwrap = unittest.skipUnless(HAVE_BWRAP, "bwrap cannot start here")


FIXED = {"GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


def git(*args, cwd):
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", **FIXED)
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                         cwd=cwd, check=True, capture_output=True, text=True, env=env)
    return out.stdout.strip()


def make_repo(path, commits=("base",)):
    """A git repo whose commits have fixed dates and identity, so the same list gives the same ids in any repo. Returns the first commit's id."""
    path.mkdir(parents=True)
    git("init", "-q", cwd=path)
    for message in commits:
        git("commit", "-q", "--allow-empty", "-m", message, cwd=path)
    return git("rev-list", "--max-parents=0", "HEAD", cwd=path)


def wait_for(path, timeout=30):
    deadline = time.time() + timeout
    while not path.exists():
        if time.time() > deadline:
            raise AssertionError("%s never appeared" % path)
        time.sleep(0.02)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class Base(unittest.TestCase):
    def setUp(self):
        # Not under /tmp: the helper binds its private root over /tmp, which would hide the fake lean-change and the run folder from verify.
        self.tmp = Path(tempfile.mkdtemp(prefix="le-verify-clean-test-", dir="/var/tmp"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.name = "t" + secrets.token_hex(4)  # this test's journey folders are /tmp/le-journey-<name>-*
        self.addCleanup(self.rm_shared)
        self.run_dir = self.tmp / "run"
        self.run_dir.mkdir()
        (self.run_dir / "show-full.json").write_text('{"show":"full"}')
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        fake = self.bin / "lean-change"
        fake.write_text(FAKE_LEAN_CHANGE)
        fake.chmod(0o755)
        self.env = dict(os.environ, PATH="%s:%s" % (self.bin, os.environ["PATH"]), FAKE_RUN=str(self.run_dir), FAKE_NAME=self.name)

    def shared_journey_dirs(self):
        return glob.glob("/tmp/le-journey-%s-*" % self.name)

    def rm_shared(self):
        for p in self.shared_journey_dirs():
            shutil.rmtree(p, True)

    def helper(self, *args, env=None):
        return subprocess.run(["sh", str(SCRIPT), *args], capture_output=True, text=True, env=dict(self.env, **(env or {})), timeout=120)

    def run_while_another_run_makes_a_folder(self, cmd, base):
        """Start `cmd`, and once verify is running make another run's journey folder in the real /tmp, whose repo copy is at commit `base`
        (the old helper matched on that), then let verify finish. Returns (decoy folder, exit code, stderr)."""
        proc = subprocess.Popen(cmd, env=dict(self.env, FAKE_WAIT_FOR="go"), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        wait_for(self.run_dir / "started")
        decoy = Path(tempfile.mkdtemp(prefix="le-journey-decoy-", dir="/tmp"))
        self.addCleanup(shutil.rmtree, decoy, True)
        self.assertEqual(make_repo(decoy / "playbook-repo"), base)
        (self.run_dir / "go").touch()
        _, err = proc.communicate(timeout=60)
        return decoy, proc.returncode, err

    def make_run_repo(self):
        """The run's repo (two commits, head after base); profile.json carries the base. Returns the base."""
        base = make_repo(self.run_dir / "repo", commits=("base", "head"))
        (self.run_dir / "profile.json").write_text('{"base": "%s"}' % base)
        return base


@needs_bwrap
class LeVerifyCleanTest(Base):
    def test_other_runs_folder_survives_and_own_scratch_never_reaches_shared_tmp(self):
        base = self.make_run_repo()
        decoy, code, err = self.run_while_another_run_makes_a_folder(["sh", str(SCRIPT), str(self.run_dir), "verify.json"], base)
        self.assertEqual(code, 0, err)
        self.assertTrue((decoy / "playbook-repo").is_dir(), "another run's folder in the shared /tmp was deleted")
        self.assertEqual(self.shared_journey_dirs(), [], "verify's own journey folder reached the shared /tmp")

    def test_verify_runs_in_the_run_folder_with_show_full_and_no_agent_env(self):
        r = self.helper(str(self.run_dir), "verify.json",
                        env={"T3_THREAD_ID": "x", "T3CODE_HOME": "y", "CLAUDECODE": "1", "CLAUDE_CODE_FOO": "2"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.run_dir / "verify.json").read_text().strip(), '{"verify":"ran"}')
        self.assertEqual((self.run_dir / "stdin").read_text(), '{"show":"full"}')
        self.assertEqual((self.run_dir / "cwd").read_text().strip(), str(self.run_dir.resolve()))
        self.assertEqual((self.run_dir / "leaked-env").read_text(), "", "T3*/CLAUDE* variables leaked into verify")

    def test_private_root_is_printed_and_gone_and_failed_journey_logs_are_kept(self):
        r = self.helper(str(self.run_dir), "verify.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        printed = [line for line in r.stderr.splitlines() if "private /tmp is" in line]
        self.assertEqual(len(printed), 1, r.stderr)
        root = Path(printed[0].split("private /tmp is ")[1])
        self.assertEqual(root.parent, self.run_dir.resolve() / "vtmp")
        self.assertFalse(root.exists(), "the private /tmp was not removed")
        journey = Path((self.run_dir / "journey-dir").read_text().strip()).name  # le-journey-<name>-XXXXXX, inside the private root
        kept = self.run_dir / "logs" / ("kept-" + journey)
        self.assertEqual((kept / "server.log").read_text(), "journey log\n")
        self.assertEqual((kept / "state/board.log").read_text(), "nested log\n")
        self.assertFalse((kept / "notes.txt").exists(), "only *.log files are evidence")

    def test_exit_status_passes_through_and_scratch_is_still_cleaned(self):
        r = self.helper(str(self.run_dir), "verify.json", env={"FAKE_EXIT": "7"})
        self.assertEqual(r.returncode, 7, r.stderr)
        self.assertEqual(list((self.run_dir / "vtmp").iterdir()), [])
        self.assertEqual((self.run_dir / "verify.json").read_text().strip(), '{"verify":"ran"}')

    def test_term_is_forwarded_and_scratch_removed(self):
        proc = subprocess.Popen(["sh", str(SCRIPT), str(self.run_dir), "verify.json"], env=dict(self.env, FAKE_SLEEP="1"),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        wait_for(self.run_dir / "started")
        pid = int((self.run_dir / "pid").read_text())
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 143)
        deadline = time.time() + 10
        while alive(pid) and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(alive(pid), "verify kept running after TERM")
        self.assertEqual(list((self.run_dir / "vtmp").iterdir()), [])


class RefusalAndPastMistakeTest(Base):
    def test_missing_bwrap_is_refused_and_verify_never_runs(self):
        # PATH holds the fake lean-change and the tools the script uses, and no bwrap.
        nobwrap = self.tmp / "nobwrap"
        nobwrap.mkdir()
        for tool in ("env", "grep", "tr", "mktemp", "chmod", "mkdir", "cp", "find", "rm", "rmdir"):
            (nobwrap / tool).symlink_to(shutil.which(tool))
        shutil.copy(self.bin / "lean-change", nobwrap / "lean-change")
        r = subprocess.run([shutil.which("sh"), str(SCRIPT), str(self.run_dir), "verify.json"], capture_output=True, text=True,
                           env=dict(self.env, PATH=str(nobwrap)), timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("bwrap", r.stderr)
        self.assertFalse((self.run_dir / "started").exists(), "verify ran without bwrap")
        self.assertFalse((self.run_dir / "verify.json").exists())
        self.assertFalse((self.run_dir / "vtmp").exists())
        self.assertEqual(self.shared_journey_dirs(), [])

    def test_old_helper_deletes_another_runs_folder(self):
        # The recorded mistake (2026-11-17): two runs share a base, a folder of the other run appears in the shared /tmp during this run's
        # verify, and the old helper removes it because its repo copy is at this run's base. The same scenario as the le-verify-clean test above.
        base = self.make_run_repo()
        text = OLD_HELPER.read_text()
        self.assertEqual(sum(line.startswith("W=/home/cartwmic/") for line in text.splitlines()), 1)
        old = self.run_dir / "old-helper.sh"
        old.write_text("".join("W=%s\n" % self.run_dir if line.startswith("W=/home/cartwmic/") else line + "\n" for line in text.splitlines()))
        decoy, code, err = self.run_while_another_run_makes_a_folder(["bash", str(old), "verify.json"], base)
        self.assertEqual(code, 0, err)
        self.assertFalse(decoy.exists(), "the old helper no longer deletes another run's folder, so the guard test above proves nothing")
        self.assertIn(str(decoy), err)


if __name__ == "__main__":
    unittest.main()
