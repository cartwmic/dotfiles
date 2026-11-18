"""Black-box tests for dot_local/user_scripts/executable_op_read_cached.sh: the 1Password token guard.

The real script runs as a real process with a fake `op` first on PATH. The fake logs its arguments and answers only when the
token in its environment is the expected one. Checked from outside: exit status, stdout, stderr, and whether op ran at all.
Run: python3 -m unittest discover -s tests/op-token -v
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/user_scripts/executable_op_read_cached.sh"
REF = "op://developer/item/password"
TOKEN = "ops_fake-token-for-tests-only"  # a stand-in service-account token; never a real one
NO_TOKEN = "1Password service account token not set; refusing to use the desktop app (playbook 78819cbd)"
FAKE_OP = '''#!/bin/sh
echo "$*" >> "$FAKE_CALLS"
[ "${OP_SERVICE_ACCOUNT_TOKEN-}" = "$EXPECT_TOKEN" ] || { echo "fake op: not the service account token" >&2; exit 1; }
printf 'secret-value'
'''


class OpReadCached(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="op-token-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin, self.home = self.tmp / "bin", self.tmp / "home"
        self.bin.mkdir()
        self.home.mkdir()
        self.calls = self.tmp / "op-calls"
        (self.bin / "op").write_text(FAKE_OP)
        (self.bin / "op").chmod(0o755)

    def run_script(self, *args, token_env=None, token_file=None):
        """token_env: the OP_SERVICE_ACCOUNT_TOKEN value to set (None: unset). token_file: the token file's text, if any."""
        if token_file is not None:
            (self.home / ".config/agent-harness").mkdir(parents=True, exist_ok=True)
            (self.home / ".config/agent-harness/op-service-token").write_text(token_file)
        env = {"PATH": "%s:/usr/bin:/bin" % self.bin, "HOME": str(self.home), "OP_READ_CACHE_DIR": str(self.tmp / "cache"),
               "XDG_STATE_HOME": str(self.tmp / "state"), "FAKE_CALLS": str(self.calls), "EXPECT_TOKEN": TOKEN}
        if token_env is not None:
            env["OP_SERVICE_ACCOUNT_TOKEN"] = token_env
        return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)

    def cache_entry(self):
        """The one cached value file, wherever the layout puts it."""
        files = [p for p in (self.tmp / "cache").rglob("*") if p.is_file()]
        self.assertEqual(len(files), 1, files)
        return files[0]

    def make_age(self, path, seconds):
        old = os.stat(path).st_mtime - seconds
        os.utime(path, (old, old))

    def slow_tool(self, name):
        """A stand-in for `name` first on PATH that logs its call and hangs: a hit must never reach it."""
        (self.bin / name).write_text('#!/bin/sh\necho "%s $*" >> "$FAKE_CALLS"\nexec sleep 30\n' % name)  # exec: one process, like the real op binary
        (self.bin / name).chmod(0o755)

    def op_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_no_token_refuses_with_the_exact_message_and_op_never_runs(self):
        done = self.run_script(REF)
        self.assertEqual(done.returncode, 69, done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertIn(NO_TOKEN, done.stderr)
        self.assertEqual(self.op_calls(), [], "op was never run, so it could not fall back to the desktop app")

    def test_no_token_refuses_an_empty_environment_variable_too(self):
        done = self.run_script(REF, token_env="")
        self.assertEqual(done.returncode, 69, done.stderr)
        self.assertEqual(self.op_calls(), [])

    def test_the_token_in_the_environment_is_used(self):
        done = self.run_script(REF, token_env=TOKEN)
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertEqual(self.op_calls(), ["read %s --no-newline" % REF])

    def test_the_token_from_the_file_is_used_when_the_environment_has_none(self):
        done = self.run_script(REF, token_env="", token_file=TOKEN + "\n")
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertEqual(self.op_calls(), ["read %s --no-newline" % REF])
        self.assertNotIn(TOKEN, done.stdout + done.stderr)

    def test_no_token_serves_a_stale_cached_value_and_still_never_calls_op(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)  # a miss: caches the value
        cache = self.cache_entry()
        old = os.stat(cache).st_mtime - 3 * 24 * 3600  # three days old: past the 12 h TTL, so a miss
        os.utime(cache, (old, old))
        self.calls.unlink()
        done = self.run_script(REF, token_env="")
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertIn(NO_TOKEN, done.stderr)
        self.assertEqual(self.op_calls(), [], "op was not run")

    def records(self):
        path = self.tmp / "state/agent-harness/op-read-cached.jsonl"
        return path.read_text().splitlines() if path.exists() else []

    def test_a_refusal_is_recorded_with_the_reference_and_no_value(self):
        done = self.run_script(REF)
        self.assertEqual(done.returncode, 69)
        lines = self.records()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn('"event":"refused"', lines[0])
        self.assertIn('"ref":"%s"' % REF, lines[0])
        self.assertNotIn("secret-value", lines[0])

    def test_a_stale_serve_is_recorded_as_stale_served(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)
        cache = self.cache_entry()
        old = os.stat(cache).st_mtime - 3 * 24 * 3600
        os.utime(cache, (old, old))
        self.assertEqual(self.run_script(REF, token_env="").returncode, 0)
        self.assertEqual(len([l for l in self.records() if "stale-served" in l]), 1, self.records())
        self.assertNotIn("secret-value", "\n".join(self.records()))

    def test_a_fresh_cache_hit_needs_no_op_and_no_token(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)  # a miss: reads and caches the value
        done = self.run_script(REF, token_env="")
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertEqual(len(self.op_calls()), 1, "the hit did not call op again")

    def test_a_fresh_hit_reads_the_file_without_op_hashing_or_the_token(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)  # a miss: caches the value
        self.calls.unlink()
        for name in ("op", "shasum", "sha256sum"):
            self.slow_tool(name)  # each hangs 30 s: a hit that touched one would blow the bound below
        start = time.monotonic()
        done = self.run_script(REF, token_env="", token_file="unreadable-on-purpose")
        took = time.monotonic() - start
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertEqual(self.op_calls(), [], "a hit ran none of op, shasum or sha256sum")
        self.assertLess(took, 2.0, "a hit must stay far under pi's 10 s limit")

    def test_the_cache_path_is_built_from_the_reference(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)
        self.assertEqual(self.cache_entry(), self.tmp / "cache/ref/developer/item/password.v")
        self.assertEqual(oct(os.stat(self.tmp / "cache/ref").st_mode & 0o777), "0o700")

    def test_unsafe_reference_paths_are_refused(self):
        for bad in ("op://", "op:///abs/item/field", "op://vault/../../etc/passwd", "op://vault//field", "op://vault/item/",
                    "op://vault/./item/field", "op://vault/item/.", "op://vault/item\nfield"):
            done = self.run_script(bad, token_env=TOKEN)
            self.assertEqual(done.returncode, 2, (bad, done.stderr))
            self.assertEqual(self.op_calls(), [], bad)

    def test_an_entry_in_the_older_hashed_layout_is_used_and_keeps_its_age(self):
        cache = self.tmp / "cache"
        cache.mkdir(mode=0o700)
        legacy = cache / hashlib.sha256(REF.encode()).hexdigest()
        legacy.write_text("legacy-value")
        self.make_age(legacy, 3600)
        done = self.run_script(REF, token_env=TOKEN)
        self.assertEqual((done.returncode, done.stdout), (0, "legacy-value"), done.stderr)
        self.assertEqual(self.op_calls(), [], "a fresh legacy entry needs no op")
        moved = cache / "ref/developer/item/password.v"
        self.assertEqual(moved.read_text(), "legacy-value")
        self.assertAlmostEqual(os.stat(moved).st_mtime, os.stat(legacy).st_mtime, delta=2)

    def test_a_hung_op_on_a_miss_serves_the_stale_value_inside_pis_10s_limit(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)
        self.make_age(self.cache_entry(), 3 * 24 * 3600)  # past the TTL: a miss
        self.calls.unlink()
        self.slow_tool("op")
        start = time.monotonic()
        done = self.run_script(REF, token_env=TOKEN)
        took = time.monotonic() - start
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertLess(took, 9.5, "the default op bound must leave pi time to get the stale value")
        self.assertEqual(len([l for l in self.records() if "op-failed-stale-served" in l]), 1, self.records())
        record = json.loads([l for l in self.records() if "op-failed-stale-served" in l][0])
        self.assertEqual((record["reason"], record["op_exit"]), ("timeout", 137), record)
        self.assertLessEqual(record["op_seconds"], 7, record)

    def test_a_failed_read_with_no_cache_is_recorded(self):
        (self.bin / "op").write_text("#!/bin/sh\nexit 1\n")
        done = self.run_script(REF, token_env=TOKEN)
        self.assertEqual(done.returncode, 1)
        self.assertEqual(len([l for l in self.records() if '"event":"op-failed"' in l]), 1, self.records())
        record = json.loads([l for l in self.records() if '"event":"op-failed"' in l][0])
        self.assertEqual((record["reason"], record["op_exit"]), ("error", 1), record)

    def test_a_field_and_a_section_of_the_same_name_do_not_collide(self):
        (self.bin / "op").write_text('#!/bin/sh\necho "$*" >> "$FAKE_CALLS"\nprintf "value-of-%s" "$2"\n')
        three, four = "op://vault/item/s", "op://vault/item/s/f"
        for ref in (three, four, three, four):  # misses, then hits, in both orders
            done = self.run_script(ref, token_env=TOKEN)
            self.assertEqual((done.returncode, done.stdout), (0, "value-of-" + ref), done.stderr)
        self.assertEqual(len(self.op_calls()), 2, "the second pass was two hits")

    def test_with_nothing_cached_a_slow_read_gets_the_long_bound(self):
        (self.bin / "op").write_text('#!/bin/sh\nsleep 7\nprintf slow-value\n')  # past 5 s, inside 20 s
        done = self.run_script(REF, token_env=TOKEN)
        self.assertEqual((done.returncode, done.stdout), (0, "slow-value"), done.stderr)
        self.assertEqual(self.cache_entry().read_text(), "slow-value")

    def test_a_caller_kill_during_a_no_cache_read_is_recorded_and_stops_op(self):
        """pi's execSync sends SIGTERM at 10 s, inside the 20 s no-cache bound: the read must still be logged."""
        (self.bin / "op").write_text('#!/bin/sh\necho "$$" > "$FAKE_CALLS.pid"\nexec sleep 30\n')
        (self.bin / "op").chmod(0o755)
        env = {"PATH": "%s:/usr/bin:/bin" % self.bin, "HOME": str(self.home), "OP_READ_CACHE_DIR": str(self.tmp / "cache"),
               "XDG_STATE_HOME": str(self.tmp / "state"), "FAKE_CALLS": str(self.calls), "OP_SERVICE_ACCOUNT_TOKEN": TOKEN}
        proc = subprocess.Popen(["sh", str(SCRIPT), REF], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pid_file = Path(str(self.calls) + ".pid")
        deadline = time.monotonic() + 10
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(pid_file.exists(), "op started")
        proc.terminate()  # SIGTERM, as execSync's timeout sends
        start = time.monotonic()
        out, _ = proc.communicate(timeout=10)
        self.assertLess(time.monotonic() - start, 3, "the script exits promptly on the caller's SIGTERM")
        self.assertEqual((proc.returncode, out), (143, b""))
        record = json.loads([l for l in self.records() if '"event":"op-failed"' in l][0])
        self.assertEqual(record["reason"], "caller-killed", record)
        op_pid = int(pid_file.read_text())
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError, msg="op was stopped too"):
            os.kill(op_pid, 0)
        self.assertEqual([p for p in (self.tmp / "cache").rglob("*") if p.is_file()], [], "no temp output left behind")

    def stalled_find(self, seconds):
        """`find` first on PATH that stalls (as a paged-out process does), then runs the real find; it marks when it started."""
        (self.bin / "find").write_text('#!/bin/sh\n: > "$FAKE_CALLS.find"\nsleep %s\nexec /usr/bin/find "$@"\n' % seconds)
        (self.bin / "find").chmod(0o755)

    @unittest.skipUnless(subprocess.run(["sh", "-c", 'echo "${SECONDS:-none}"'], capture_output=True, text=True).stdout.strip() != "none",
                         "this sh has no $SECONDS (dash): slow hits are not timed there, by design")
    def test_a_hit_that_takes_seconds_is_recorded_as_slow(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)  # a miss: caches the value
        self.stalled_find(3.2)
        done = self.run_script(REF, token_env="")
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        deadline = time.monotonic() + 5      # the record is written in the background, after the value is returned
        while not [l for l in self.records() if '"event":"slow-hit"' in l] and time.monotonic() < deadline:
            time.sleep(0.05)
        record = json.loads([l for l in self.records() if '"event":"slow-hit"' in l][0])
        self.assertGreaterEqual(record["seconds"], 3, record)

    def test_a_caller_kill_during_a_hit_is_recorded_with_its_phase(self):
        """pi's execSync sends SIGTERM at 10 s: a hit stalled by the machine must still leave a record naming where it was."""
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)
        self.stalled_find(2)
        env = {"PATH": "%s:/usr/bin:/bin" % self.bin, "HOME": str(self.home), "OP_READ_CACHE_DIR": str(self.tmp / "cache"),
               "XDG_STATE_HOME": str(self.tmp / "state"), "FAKE_CALLS": str(self.calls)}
        proc = subprocess.Popen(["sh", str(SCRIPT), REF], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        marker = Path(str(self.calls) + ".find")
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        proc.terminate()
        out, _ = proc.communicate(timeout=15)
        self.assertEqual((proc.returncode, out), (143, b""))
        record = json.loads([l for l in self.records() if '"event":"caller-killed"' in l][0])
        self.assertEqual(record["phase"], "hit", record)
        self.assertEqual(record["ref"], REF, record)


if __name__ == "__main__":
    unittest.main()
