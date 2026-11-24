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

    def own_lines(self):
        path = self.state / "log-probe" / "log.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def run_raw(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=60)

    def test_every_usage_refusal_is_logged_with_a_reason(self):
        cases = [
            (["--seed", "/nope", "--", "true"], "--seed"),
            (["--watch", "/nope", "--", "true"], "--watch"),
            ([], "no command"),
            (["--expect", "(", "--", "true"], "--expect"),
            (["--timeout", "soon", "--", "true"], "--timeout"),
            (["--env", "NOEQUALS", "--", "true"], "--env"),
            (["--frobnicate", "--", "true"], "unknown option"),
            (["--seed"], "needs a value"),
        ]
        for n, (args, word) in enumerate(cases, 1):
            r = self.run_raw(*args)
            self.assertEqual(r.returncode, 2, (args, r.stderr))
            lines = self.own_lines()
            self.assertEqual(len(lines), n, (args, lines))  # one new line per refusal
            self.assertEqual(lines[-1]["outcome"], "refused", args)
            self.assertIn(word, lines[-1]["reason"], args)  # the log alone says which refusal

    def test_each_error_is_logged_with_its_own_reason(self):
        self.run_raw("--", "/no/such/command")
        noexec = Path(self.tmp) / "noexec"
        noexec.write_text("#!/bin/sh\n")
        noexec.chmod(0o644)
        self.run_raw("--", str(noexec))
        r = self.run_raw("--timeout", "0.3", "--", "sleep", "5")
        self.assertEqual(r.returncode, 2)
        self.assertIn("did not finish", r.stderr)
        got = [(x["outcome"], x["exit_code"], x["reason"]) for x in self.own_lines()]
        self.assertEqual(got, [("error", None, "missing command"), ("error", None, "permission denied"), ("error", None, "timeout")])

    def test_a_fail_is_logged_with_its_reason(self):
        self.probe(command=STDERR_ONLY)
        self.probe("--expect", "nomatch", command=JSON_LOG)
        got = [(x["outcome"], x["reason"]) for x in self.own_lines()]
        self.assertEqual(got, [("fail", "no JSON line in a new or grown file"), ("fail", "none matches --expect")])

    def test_a_pass_and_help_are_logged_without_a_reason(self):
        self.probe(command=JSON_LOG)
        self.run_raw("--help")
        lines = self.own_lines()
        self.assertEqual([x["outcome"] for x in lines], ["pass", "help"])
        self.assertTrue(all("reason" not in x for x in lines))

    def test_log_probe_passes_its_own_refusal_probe(self):
        # the self-probe: a refusal of log-probe must leave a record, so log-probe passes on it
        r = self.run_raw("--", sys.executable, str(SCRIPT), "--seed", "/nope", "--", "true")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('"outcome": "refused"', r.stdout)
        self.assertIn("--seed", r.stdout)

    def test_a_renamed_seeded_log_shows_as_new_and_the_reviewer_judges_it(self):
        # known limit: "new or grown file", not "appended line". The old record is printed under the new name,
        # so the reviewer sees the 2026-01-01 time and can tell it is not this run's record.
        seed = Path(self.tmp) / "seed" / ".local/state/w"
        seed.mkdir(parents=True)
        (seed / "log.jsonl").write_text('{"utc":"2026-01-01T00:00:00Z"}\n')
        r = self.probe("--seed", str(seed.parents[2]), command='cd "$HOME/.local/state/w" && mv log.jsonl log.1.jsonl')
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("log.1.jsonl (new)", r.stdout)
        self.assertIn("2026-01-01T00:00:00Z", r.stdout)

    def test_a_timeout_stops_the_command_and_is_an_error(self):
        r = self.run_raw("--timeout", "0.3", "--", "sleep", "5")
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("PASS", r.stdout)

    def test_an_unwritable_own_log_changes_nothing(self):
        blocker = Path(self.tmp) / "blocked"
        blocker.write_text("a file where the state folder should be")
        self.env["XDG_STATE_HOME"] = str(blocker)
        r = self.probe(command=JSON_LOG)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
