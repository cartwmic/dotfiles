"""Black-box tests for dot_local/bin/executable_qmd-refresh.

The real script runs as a real process (and the real perl flock). Only qmd and heavy-gate are fakes (first on PATH):
the fake qmd logs its argv and QMD_EMBED_PARALLELISM and can fail, sleep or ignore TERM; the fake heavy-gate logs its argv
and runs the job in the FOREGROUND like the real one (so signal timing is realistic) and can sleep before the job or
delete the embedding model first (cache eviction while waiting). QMD_REFRESH_SCRIPT points the suite at a mutated copy.
The real gate is exercised by hand (PR body), not here.
"""
import fcntl
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(os.environ.get("QMD_REFRESH_SCRIPT") or Path(__file__).resolve().parents[2] / "dot_local/bin/executable_qmd-refresh")
MODEL = "hf_ggml-org_embeddinggemma-300M-Q8_0.gguf"

FAKE_QMD = r"""#!/bin/sh
echo "qmd $* | par=${QMD_EMBED_PARALLELISM:-unset}" >> "$FAKE/calls"
pwd -P > "$FAKE/cwd"
cmd=$1
if [ "${FAKE_QMD_SLEEP:-}" = "$cmd" ]; then
  [ -z "${FAKE_QMD_DEAF:-}" ] || trap '' TERM
  echo $$ > "$FAKE/qmd.pid.tmp"; mv "$FAKE/qmd.pid.tmp" "$FAKE/qmd.pid"
  sleep ${FAKE_QMD_SECS:-60} &
  wait
fi
[ "${FAKE_QMD_FAIL:-}" = "$cmd" ] && exit "${FAKE_QMD_CODE:-3}"
exit 0
"""
FAKE_GATE = r"""#!/bin/sh
echo "heavy-gate $1 $2 $3 $4 $5 | $7 $8 $9" >> "$FAKE/calls"
echo "nice=$(ps -o nice= -p $$ | tr -d ' ')" >> "$FAKE/nice"
if [ -n "${FAKE_GATE_SLEEP:-}" ]; then echo $$ > "$FAKE/gate.pid"; sleep "$FAKE_GATE_SLEEP"; fi
[ -z "${FAKE_GATE_EVICT:-}" ] || rm -f "$FAKE_GATE_EVICT"
shift 3
"$@"
"""


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def until(cond, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


class Env:
    def __init__(self, model=True):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fake, self.bin, self.home = (self.root / n for n in ("fake", "bin", "home"))
        for d in (self.fake, self.bin, self.home):
            d.mkdir()
        (self.bin / "qmd").write_text(FAKE_QMD)
        (self.bin / "heavy-gate").write_text(FAKE_GATE)
        for f in (self.bin / "qmd", self.bin / "heavy-gate"):
            f.chmod(0o755)
        self.cache = self.root / "cache"
        self.state = self.root / "state"
        self.model = self.cache / "qmd" / "models" / MODEL
        if model:
            self.model.parent.mkdir(parents=True)
            self.model.write_text("x")
        self.env = dict(os.environ, HOME=str(self.home), FAKE=str(self.fake), XDG_CACHE_HOME=str(self.cache),
                        XDG_STATE_HOME=str(self.state), XDG_CONFIG_HOME=str(self.root / "config"),
                        PATH="%s:/usr/bin:/bin:/usr/sbin:/sbin" % self.bin, QMD_REFRESH_GRACE="1")
        for k in ("QMD_BIN", "QMD_EMBED_PARALLELISM", "QMD_EMBED_MODEL", "QMD_CONFIG_DIR"):
            self.env.pop(k, None)
        self.procs = []

    def popen(self, *args, **env):
        p = subprocess.Popen(["/bin/sh", str(SCRIPT), *args], env=dict(self.env, **env), text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.procs.append(p)
        return p

    def run(self, *args, **env):
        p = self.popen(*args, **env)
        self.out, self.err = p.communicate(timeout=60)
        return p.returncode

    def run_with(self, cmd, code):
        return self.run(FAKE_QMD_FAIL=cmd, FAKE_QMD_CODE=str(code))

    def qmd_pid(self, secs=10):
        f = self.fake / "qmd.pid"
        self.assert_started = until(f.exists, secs)
        return int(f.read_text()) if f.exists() else None

    @property
    def calls(self):
        f = self.fake / "calls"
        return f.read_text().splitlines() if f.exists() else []

    @property
    def qmd_calls(self):
        return [c for c in self.calls if c.startswith("qmd")]

    @property
    def stamp(self):
        return self.state / "qmd-refresh" / "last-success"

    @property
    def lockfile(self):
        return self.state / "qmd-refresh" / "lock"

    def cleanup(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.communicate()
        pid = self.fake / "qmd.pid"
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass
        subprocess.run(["pkill", "-KILL", "-f", str(self.root)], check=False)
        self.tmp.cleanup()


class Base(unittest.TestCase):
    def make(self, **kw):
        e = Env(**kw)
        self.addCleanup(e.cleanup)
        return e

    def setUp(self):
        self.e = self.make()


class RefreshTest(Base):
    def test_update_then_embed_in_one_gate_call_with_the_low_memory_flags(self):
        self.assertEqual(self.e.run(), 0, self.e.err)
        gate = [c for c in self.e.calls if c.startswith("heavy-gate")]
        self.assertEqual(gate, ["heavy-gate --wait 7200 -- sh -c | sh %s embed" % (self.e.bin / "qmd")])
        self.assertEqual((self.e.fake / "nice").read_text().split(), ["nice=10"], "heavy-gate itself runs niced")
        self.assertEqual(self.e.qmd_calls, [
            "qmd update | par=unset",
            "qmd embed --timeout 0 --max-docs-per-batch 50 --max-batch-mb 8 | par=1",
        ])

    def test_success_writes_the_stamp_and_status_reads_it(self):
        self.assertEqual(self.e.run(), 0)
        self.assertRegex(self.e.stamp.read_text(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ ok: update \+ embed\n$")
        self.assertEqual(self.e.run("status"), 0)
        self.assertIn("ok: update + embed", self.e.out)
        self.assertNotIn("running now", self.e.out, "the lock file stays but is not held")

    def test_status_before_any_refresh(self):
        self.assertEqual(self.e.run("status"), 0)
        self.assertIn("never refreshed", self.e.out)
        self.assertEqual(self.e.calls, [])

    def test_wait_is_passed_to_the_gate(self):
        self.assertEqual(self.e.run("--wait", "90"), 0)
        self.assertTrue(any(c.startswith("heavy-gate --wait 90 -- ") for c in self.e.calls))
        self.assertEqual(self.e.run("--wait=15"), 0)
        self.assertTrue(any(c.startswith("heavy-gate --wait 15 -- ") for c in self.e.calls))

    def test_bad_arguments(self):
        for args in (["--wait", "soon"], ["--wait"], ["--bogus"], ["now"]):
            self.assertEqual(self.e.run(*args), 2, args)
        self.assertEqual(self.e.calls, [])
        self.assertEqual(self.e.run("--help"), 0)
        self.assertIn("usage: qmd-refresh", self.e.out)

    def test_no_embed_runs_update_only(self):
        self.assertEqual(self.e.run("--no-embed"), 0)
        self.assertEqual(self.e.qmd_calls, ["qmd update | par=unset"])
        self.assertTrue(any(" sh %s noembed " % (self.e.bin / "qmd") in c + " " for c in self.e.calls))
        self.assertIn("ok: update\n", self.e.stamp.read_text())

    def test_dry_run_runs_nothing(self):
        self.assertEqual(self.e.run("--dry-run"), 0)
        self.assertEqual(self.e.calls, [])
        self.assertFalse(self.e.state.exists(), "no lock, no stamp")
        self.assertIn("--timeout 0 --max-docs-per-batch 50 --max-batch-mb 8", self.e.out)
        self.assertIn("QMD_EMBED_PARALLELISM=1", self.e.out)

    def test_update_failure_skips_embed_keeps_the_status_and_the_old_stamp(self):
        self.assertEqual(self.e.run(), 0)
        old = self.e.stamp.read_text()
        (self.e.fake / "calls").unlink()
        self.assertEqual(self.e.run_with("update", 7), 7)
        self.assertEqual(self.e.qmd_calls, ["qmd update | par=unset"])
        self.assertEqual(self.e.stamp.read_text(), old)
        self.assertIn("failed with status 7", self.e.err)

    def test_embed_failure_is_reported_and_not_stamped(self):
        self.assertEqual(self.e.run_with("embed", 4), 4)
        self.assertFalse(self.e.stamp.exists())

    def test_qmd_bin_overrides_path(self):
        alt = self.e.root / "alt-qmd"
        alt.write_text('#!/bin/sh\necho alt "$@" >> "$FAKE/calls"\n')
        alt.chmod(0o755)
        self.assertEqual(self.e.run("--no-embed", QMD_BIN=str(alt)), 0)
        self.assertIn("alt update", self.e.calls)

    def test_missing_tools(self):
        (self.e.bin / "qmd").unlink()
        self.assertEqual(self.e.run(), 127)
        self.assertIn("qmd not found", self.e.err)
        e = self.make()
        (e.bin / "heavy-gate").unlink()
        self.assertEqual(e.run(), 127)
        self.assertIn("heavy-gate not found", e.err)

    def test_falls_back_to_the_mise_shim(self):
        (self.e.bin / "qmd").unlink()
        shim = self.e.home / ".local/share/mise/shims"
        shim.mkdir(parents=True)
        (shim / "qmd").write_text('#!/bin/sh\necho shim "$@" >> "$FAKE/calls"\n')
        (shim / "qmd").chmod(0o755)
        self.assertEqual(self.e.run("--no-embed"), 0, self.e.err)
        self.assertIn("shim update", self.e.calls)


class ModelGuardTest(Base):
    """qmd downloads a missing model by itself and has no offline switch, so the wrapper must not let it try."""

    def assert_update_only(self, e, rc, hint="qmd pull"):
        self.assertEqual(rc, 0, e.err)
        self.assertEqual(e.qmd_calls, ["qmd update | par=unset"])
        self.assertIn(hint, e.err)

    def test_no_model(self):
        e = self.make(model=False)
        self.assert_update_only(e, e.run())
        self.assertIn("ok: update (embed skipped", e.stamp.read_text())

    def test_other_quantization_does_not_count(self):
        e = self.make(model=False)
        d = e.model.parent
        d.mkdir(parents=True)
        (d / "hf_ggml-org_embeddinggemma-300M-Q4_K_M.gguf").write_text("x")
        (d / "hf_ggml-org_embeddinggemma-300M-Q8_0.gguf.etag").write_text("x")
        self.assert_update_only(e, e.run())

    def test_model_evicted_while_waiting_for_the_gate(self):
        self.assert_update_only(self.e, self.e.run(FAKE_GATE_EVICT=str(self.e.model)))

    def config(self, embed):
        cfg = self.e.root / "config" / "qmd"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "index.yml").write_text("collections: {}\nmodels:\n  embed: %s\n  rerank: x\n" % embed)

    def test_a_different_configured_model_means_update_only_even_if_a_file_like_it_exists(self):
        self.config("hf:acme/some-repo/other-Q4.gguf")
        # node-llama-cpp names this file hf_acme_some-repo_other-Q4.gguf; whatever it is called, we must not embed
        for name in ("hf_acme_other-Q4.gguf", "hf_acme_some-repo_other-Q4.gguf"):
            (self.e.model.parent / name).write_text("x")
        self.assert_update_only(self.e, self.e.run(), "pinned")

    def test_the_pinned_model_in_the_config_embeds(self):
        self.config("hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf")
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertEqual(len(self.e.qmd_calls), 2)

    def test_quoted_value_and_other_indent_are_read(self):
        cfg = self.e.root / "config" / "qmd"
        cfg.mkdir(parents=True)
        (cfg / "index.yml").write_text("models:\n    embed: 'hf:acme/x/y.gguf'\n")
        self.assert_update_only(self.e, self.e.run(), "pinned")

    def test_env_model_means_update_only_whatever_the_config_says(self):
        self.config("hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf")
        self.assert_update_only(self.e, self.e.run(QMD_EMBED_MODEL="hf:acme/repo/env.gguf"), "pinned")

    def test_the_job_runs_in_the_state_dir_so_a_project_local_qmd_config_is_not_picked_up(self):
        work = self.e.root / "work"
        (work / ".qmd").mkdir(parents=True)
        p = subprocess.run(["/bin/sh", str(SCRIPT), "--no-embed"], env=self.e.env, cwd=work, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual((self.e.fake / "cwd").read_text().strip(), str((self.e.state / "qmd-refresh").resolve()))


class StatusPassThroughTest(Base):
    """Only wrapper-made outcomes are reported out of band; a real status is never reinterpreted."""

    def test_real_statuses_survive_and_do_not_stamp(self):
        for cmd in ("update", "embed"):
            for code in (64, 73, 75):
                with self.subTest(cmd=cmd, code=code):
                    self.assertEqual(self.e.run_with(cmd, code), code, self.e.err)
                    self.assertFalse(self.e.stamp.exists())
                    self.assertNotIn("another refresh", self.e.err)
                    self.assertNotIn("skipped", self.e.err)


class LockTest(Base):
    def hold(self, e):
        """Hold the lock the way a live job does, from a separate process."""
        e.lockfile.parent.mkdir(parents=True, exist_ok=True)
        holder = subprocess.Popen(["perl", "-e", 'use Fcntl qw(:flock); open(F, ">>", shift); flock(F, LOCK_EX); print "held\\n"; $|=1; sleep 60',
                                   str(e.lockfile)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (holder.kill(), holder.wait(), holder.stdout.close()))
        self.assertEqual(holder.stdout.readline().strip(), "held")
        return holder

    def test_held_lock_refuses_and_touches_nothing(self):
        self.hold(self.e)
        self.assertEqual(self.e.run(), 75)
        self.assertIn("another refresh is running", self.e.err)
        self.assertEqual(self.e.qmd_calls, [])
        self.assertFalse(self.e.stamp.exists())
        self.e.run("status")
        self.assertIn("running now", self.e.out)

    def test_a_dead_holder_leaves_nothing_to_clean_up(self):
        holder = self.hold(self.e)
        holder.kill()
        holder.wait()
        self.assertEqual(self.e.run(), 0, self.e.err)

    def test_concurrent_starts_run_exactly_one(self):
        procs = [self.e.popen(FAKE_QMD_SLEEP="update", FAKE_QMD_SECS="2") for _ in range(6)]
        codes = sorted(p.wait(timeout=60) for p in procs)
        self.assertEqual(codes, [0, 75, 75, 75, 75, 75])
        self.assertEqual(self.e.calls.count("qmd update | par=unset"), 1)

    def test_a_killed_wrapper_does_not_free_the_lock_while_its_job_lives(self):
        p = self.e.popen(FAKE_QMD_SLEEP="embed", FAKE_QMD_SECS="5")
        qpid = self.e.qmd_pid()
        self.assertTrue(self.e.assert_started)
        p.kill()          # SIGKILL: no trap runs, the job is orphaned (it keeps the pipes open, so do not communicate())
        p.wait(timeout=10)
        p.stdout.close()
        p.stderr.close()
        self.assertTrue(alive(qpid))
        self.assertEqual(self.e.run(), 75, "the orphaned job still holds the lock")
        # every process of the job (also the fake's `sleep`) holds the lock: it frees when the last one exits
        self.assertTrue(until(lambda: self.e.run() == 0, 15), "free once the whole job is gone")


class SignalTest(Base):
    def start_embed(self, **env):
        p = self.e.popen(FAKE_QMD_SLEEP="embed", **env)
        qpid = self.e.qmd_pid()
        self.assertTrue(self.e.assert_started, "job never started")
        return p, qpid

    def test_each_signal_stops_the_job_and_frees_the_lock(self):
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(sig=sig.name):
                (self.e.fake / "qmd.pid").unlink(missing_ok=True)
                p, qpid = self.start_embed()
                t0 = time.time()
                p.send_signal(sig)
                p.communicate(timeout=30)
                self.assertEqual(p.returncode, 143)
                self.assertLess(time.time() - t0, 10, "must not wait out the embed")
                self.assertTrue(until(lambda: not alive(qpid), 5), "qmd child survived")
                self.assertFalse(self.e.stamp.exists())
                self.assertEqual(self.e.run(), 0, "the lock is free again")
                (self.e.fake / "calls").unlink()
                self.e.stamp.unlink()

    def test_a_job_that_ignores_term_is_killed_after_the_grace_period(self):
        p, qpid = self.start_embed(FAKE_QMD_DEAF="1")
        p.send_signal(signal.SIGTERM)
        _, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 143)
        self.assertTrue(until(lambda: not alive(qpid), 5), "TERM-resistant job survived")
        self.assertIn("sending KILL", err)

    def test_a_signal_at_any_moment_of_startup_leaves_nothing_running(self):
        for delay in (0, 0.02, 0.05, 0.1, 0.2, 0.4):
            with self.subTest(delay=delay):
                p = self.e.popen(FAKE_QMD_SLEEP="update", FAKE_QMD_DEAF="1", QMD_REFRESH_GRACE="1")
                time.sleep(delay)
                p.send_signal(signal.SIGTERM)
                p.communicate(timeout=30)
                self.assertIn(p.returncode, (143, -signal.SIGTERM))
                self.assertTrue(until(lambda: subprocess.run(["pgrep", "-f", str(self.e.bin / "qmd")], capture_output=True).returncode != 0, 8),
                                "a job process survived")
                self.assertEqual(self.e.run(), 0, "the lock is free again")
                for n in ("calls", "qmd.pid"):
                    (self.e.fake / n).unlink(missing_ok=True)
                self.e.stamp.unlink(missing_ok=True)

    def test_signal_while_still_waiting_for_the_gate(self):
        p = self.e.popen(FAKE_GATE_SLEEP="60")
        gate = self.e.fake / "gate.pid"
        self.assertTrue(until(gate.exists))
        gpid = int(gate.read_text())
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=30)
        self.assertEqual(p.returncode, 143)
        self.assertTrue(until(lambda: not alive(gpid), 5), "waiting gate survived")
        self.assertEqual(self.e.qmd_calls, [], "the job never started")
        self.assertEqual(self.e.run(), 0)


if __name__ == "__main__":
    unittest.main()
