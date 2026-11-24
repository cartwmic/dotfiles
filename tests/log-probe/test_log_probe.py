"""Black-box test for dot_local/share/agent-harness/bin/executable_log-probe.

The fixture is the past mistake, written generically: a wrapper that falls back to another program was
"fixed" so that it says so on stderr and exits with a code. A reviewer cited design principle 14 (a log is a
record that survives the terminal; stderr and an exit code are not one). The probe must fail that command and
pass one that appends a JSON line to a file. Every command here is a few lines of sh run in a scratch HOME;
nothing writes inside the dotfiles checkout or the real home.

    python3 -m unittest discover -s tests/log-probe -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/share/agent-harness/bin/executable_log-probe"

# the shape of the failed fix: one line on stderr and an exit code, no file
STDERR_ONLY = 'echo "wrapper: using fallback kit /x/kit" >&2; exit 3'
# the shape of the fix that holds: a JSON line appended under the state folder, then the same exit code
JSON_LOG = 'mkdir -p "$HOME/.local/state/w"; printf \'{"utc":"2026-11-23T00:00:00Z","outcome":"fallback"}\\n\' >> "$HOME/.local/state/w/wrapper.jsonl"; echo "wrapper: using fallback" >&2; exit 3'


class LogProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = Path(self.tmp) / "state"  # the caller's state folder: where log-probe writes its own line
        self.env = dict(os.environ, XDG_STATE_HOME=str(self.state))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def probe(self, *args, command=None):
        cmd = [sys.executable, str(SCRIPT), *args]
        if command is not None:
            cmd += ["--", "sh", "-c", command]
        return subprocess.run(cmd, capture_output=True, text=True, env=self.env, timeout=60)

    def test_stderr_and_exit_code_only_fails(self):
        r = self.probe(command=STDERR_ONLY)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("FAIL", r.stdout)
        self.assertIn("exit 3", r.stdout)  # shown, not judged

    def test_json_line_in_a_file_passes_even_when_the_command_exits_nonzero(self):
        r = self.probe(command=JSON_LOG)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASS 1 record(s)", r.stdout)
        self.assertIn('"outcome":"fallback"', r.stdout)

    def test_a_plain_text_line_is_not_a_structured_record(self):
        r = self.probe(command='mkdir -p "$HOME/.local/state/w"; echo "used fallback kit" >> "$HOME/.local/state/w/wrapper.log"')
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("holds no JSON line", r.stdout)

    def test_a_record_written_before_the_run_does_not_count(self):
        seed = Path(self.tmp) / "seed" / ".local/state/w"
        seed.mkdir(parents=True)
        (seed / "wrapper.jsonl").write_text('{"utc":"2026-01-01T00:00:00Z"}\n')
        r = self.probe("--seed", str(seed.parents[2]), command=STDERR_ONLY)
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_a_line_appended_to_a_seeded_file_counts(self):
        seed = Path(self.tmp) / "seed" / ".local/state/w"
        seed.mkdir(parents=True)
        (seed / "wrapper.jsonl").write_text('{"utc":"2026-01-01T00:00:00Z"}\n')
        r = self.probe("--seed", str(seed.parents[2]), command=JSON_LOG)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("PASS 1 record(s)", r.stdout)  # the seeded line is not counted

    def test_expect_picks_the_path_under_test(self):
        ok = self.probe("--expect", '"outcome":"fallback"', command=JSON_LOG)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        wrong = self.probe("--expect", '"outcome":"refused"', command=JSON_LOG)
        self.assertEqual(wrong.returncode, 1, wrong.stdout)
        self.assertIn("none matches --expect", wrong.stdout)

    def test_watch_sees_a_record_outside_home(self):
        outside = Path(self.tmp) / "traces"
        outside.mkdir()
        r = self.probe("--watch", str(outside), "--env", "OUT=%s" % outside,
                       command='printf \'{"utc":"2026-11-23T00:00:00Z"}\\n\' >> "$OUT/run.jsonl"')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("run.jsonl", r.stdout)
        self.assertEqual((outside / "run.jsonl").read_text().count("\n"), 1)  # the run's own line; nothing else touched

    def test_the_command_runs_in_a_scratch_home(self):
        real = Path(self.tmp) / "realhome"
        real.mkdir()
        self.env["HOME"] = str(real)
        r = self.probe(command='mkdir -p "$HOME/.local/state/w"; echo \'{"a":1}\' >> "$HOME/.local/state/w/x.jsonl"')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(list(real.rglob("x.jsonl")), [])

    def test_a_missing_command_is_an_error_not_a_fail(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--", "/no/such/command"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no such command", r.stderr)

    def test_no_command_is_an_error(self):
        r = self.probe()
        self.assertEqual(r.returncode, 2)

    def test_it_logs_its_own_run_and_never_the_arguments(self):
        self.probe(command=JSON_LOG + " # secret-argument")
        lines = (self.state / "log-probe" / "log.jsonl").read_text().splitlines()
        rec = json.loads(lines[-1])
        self.assertEqual((rec["outcome"], rec["exit_code"], rec["records"], rec["command"]), ("pass", 3, 1, "sh"))
        self.assertNotIn("secret-argument", lines[-1])

    def test_an_unwritable_own_log_changes_nothing(self):
        blocker = Path(self.tmp) / "blocked"
        blocker.write_text("a file where the state folder should be")
        self.env["XDG_STATE_HOME"] = str(blocker)
        r = self.probe(command=JSON_LOG)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
