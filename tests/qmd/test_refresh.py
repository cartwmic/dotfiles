"""Black-box tests for dot_local/bin/executable_qmd-refresh.

The real script runs as a real process. Only qmd and heavy-gate are fakes (first on PATH): the fake qmd logs its argv and
QMD_EMBED_PARALLELISM and can fail or sleep; the fake heavy-gate logs its argv, parses "--wait N --" and runs the job in the
FOREGROUND like the real one (so signal timing is realistic). QMD_REFRESH_SCRIPT points the suite at a mutated copy.
"""
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(os.environ.get("QMD_REFRESH_SCRIPT") or Path(__file__).resolve().parents[2] / "dot_local/bin/executable_qmd-refresh")

FAKE_QMD = r"""#!/bin/sh
echo "qmd $* | par=${QMD_EMBED_PARALLELISM:-unset}" >> "$FAKE/calls"
cmd=$1
if [ "${FAKE_QMD_SLEEP:-}" = "$cmd" ]; then echo $$ > "$FAKE/qmd.pid"; sleep 60; fi
[ "${FAKE_QMD_FAIL:-}" = "$cmd" ] && exit "${FAKE_QMD_CODE:-3}"
exit 0
"""
FAKE_GATE = r"""#!/bin/sh
echo "heavy-gate $1 $2 $3 $4 $5 | $7 $8 $9" >> "$FAKE/calls"
echo "nice=$(ps -o nice= -p $$ | tr -d ' ')" >> "$FAKE/nice"
shift 3
"$@"
"""


class Env:
    def __init__(self, model=True):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fake = self.root / "fake"
        self.bin = self.root / "bin"
        self.home = self.root / "home"
        for d in (self.fake, self.bin, self.home):
            d.mkdir()
        (self.bin / "qmd").write_text(FAKE_QMD.replace("\\$", "$"))
        (self.bin / "heavy-gate").write_text(FAKE_GATE)
        for f in (self.bin / "qmd", self.bin / "heavy-gate"):
            f.chmod(0o755)
        self.cache = self.root / "cache"
        self.state = self.root / "state"
        if model:
            m = self.cache / "qmd" / "models"
            m.mkdir(parents=True)
            (m / "hf_ggml-org_embeddinggemma-300M-Q8_0.gguf").write_text("x")
        self.env = dict(os.environ, HOME=str(self.home), FAKE=str(self.fake), XDG_CACHE_HOME=str(self.cache),
                        XDG_STATE_HOME=str(self.state), PATH="%s:/usr/bin:/bin:/usr/sbin:/sbin" % self.bin)
        for k in ("QMD_BIN", "QMD_EMBED_PARALLELISM"):
            self.env.pop(k, None)

    def popen(self, *args, **env):
        return subprocess.Popen(["/bin/sh", str(SCRIPT), *args], env=dict(self.env, **env), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def run(self, *args, **env):
        p = self.popen(*args, **env)
        out, err = p.communicate(timeout=60)
        self.out, self.err = out, err
        return p.returncode

    @property
    def calls(self):
        f = self.fake / "calls"
        return f.read_text().splitlines() if f.exists() else []

    @property
    def stamp(self):
        return self.state / "qmd-refresh" / "last-success"

    @property
    def lock(self):
        return self.state / "qmd-refresh" / "lock"


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.tmp.cleanup)

    def test_update_then_embed_in_one_gate_call_with_the_low_memory_flags(self):
        self.assertEqual(self.e.run(), 0, self.e.err)
        gate = [c for c in self.e.calls if c.startswith("heavy-gate")]
        self.assertEqual(len(gate), 1, "one slot, not two")
        self.assertEqual((self.e.fake / "nice").read_text().split(), ["nice=10"], "heavy-gate itself runs niced")
        self.assertEqual(gate[0], "heavy-gate --wait 7200 -- sh -c | sh %s embed" % (self.e.bin / "qmd"))
        self.assertEqual([c for c in self.e.calls if c.startswith("qmd")], [
            "qmd update | par=unset",
            "qmd embed --timeout 0 --max-docs-per-batch 50 --max-batch-mb 8 | par=1",
        ])

    def test_success_writes_the_stamp_and_releases_the_lock(self):
        self.assertEqual(self.e.run(), 0)
        self.assertRegex(self.e.stamp.read_text(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ ok: update \+ embed\n$")
        self.assertFalse(self.e.lock.exists())
        self.assertEqual(self.e.run("status"), 0)
        self.assertIn("ok: update + embed", self.e.out)

    def test_status_before_any_refresh(self):
        self.assertEqual(self.e.run("status"), 0)
        self.assertIn("never refreshed", self.e.out)
        self.assertEqual(self.e.calls, [])

    def test_wait_is_passed_to_the_gate(self):
        self.assertEqual(self.e.run("--wait", "90"), 0)
        self.assertIn("heavy-gate --wait 90 -- sh -c | sh %s embed" % (self.e.bin / "qmd"), self.e.calls)
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
        self.assertEqual([c for c in self.e.calls if c.startswith("qmd")], ["qmd update | par=unset"])
        self.assertTrue(self.e.calls[0].endswith("noembed"), self.e.calls[0])
        self.assertIn("ok: update\n", self.e.stamp.read_text())

    def test_missing_embedding_model_runs_update_only_and_says_so(self):
        e = Env(model=False)
        self.addCleanup(e.tmp.cleanup)
        self.assertEqual(e.run(), 0, e.err)
        self.assertEqual([c for c in e.calls if c.startswith("qmd")], ["qmd update | par=unset"])
        self.assertIn("qmd pull", e.err)
        self.assertIn("ok: update\n", e.stamp.read_text())

    def test_dry_run_runs_nothing(self):
        self.assertEqual(self.e.run("--dry-run"), 0)
        self.assertEqual(self.e.calls, [])
        self.assertFalse(self.e.state.exists(), "no lock, no stamp")
        self.assertIn("--timeout 0 --max-docs-per-batch 50 --max-batch-mb 8", self.e.out)
        self.assertIn("QMD_EMBED_PARALLELISM=1", self.e.out)

    def test_update_failure_skips_embed_keeps_the_status_and_the_old_stamp(self):
        self.assertEqual(self.e.run(), 0)
        old = self.e.stamp.read_text()
        self.e.fake.joinpath("calls").unlink()
        self.assertEqual(self.e.run_with("update", 7), 7)
        self.assertEqual([c for c in self.e.calls if c.startswith("qmd")], ["qmd update | par=unset"])
        self.assertEqual(self.e.stamp.read_text(), old)
        self.assertFalse(self.e.lock.exists())
        self.assertIn("failed with status 7", self.e.err)

    def test_embed_failure_is_reported_and_not_stamped(self):
        self.assertEqual(self.e.run_with("embed", 4), 4)
        self.assertFalse(self.e.stamp.exists())
        self.assertFalse(self.e.lock.exists())

    def test_live_lock_refuses(self):
        holder = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        self.e.lock.mkdir(parents=True)
        (self.e.lock / "pid").write_text(str(holder.pid))
        self.assertEqual(self.e.run(), 75)
        self.assertIn("another refresh is running (pid %d)" % holder.pid, self.e.err)
        self.assertEqual(self.e.calls, [])
        self.assertTrue(self.e.lock.exists(), "the live holder's lock is not touched")
        self.e.run("status")
        self.assertIn("running now (pid %d)" % holder.pid, self.e.out)

    def test_dead_lock_is_taken_over(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.e.lock.mkdir(parents=True)
        (self.e.lock / "pid").write_text(str(dead.pid))
        self.assertEqual(self.e.run(), 0, self.e.err)
        self.assertIn("taking over", self.e.err)
        self.assertFalse(self.e.lock.exists())

    def test_term_stops_the_job_and_frees_the_lock(self):
        p = self.e.popen(FAKE_QMD_SLEEP="embed")
        pidfile = self.e.fake / "qmd.pid"
        for _ in range(100):
            if pidfile.exists():
                break
            time.sleep(0.1)
        self.assertTrue(pidfile.exists(), "job never started")
        qpid = int(pidfile.read_text())
        self.assertTrue(self.e.lock.exists())
        t0 = time.time()
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=20)
        self.assertEqual(p.returncode, 143)
        self.assertLess(time.time() - t0, 10, "TERM must not wait out the embed")
        self.assertFalse(self.e.lock.exists())
        self.assertFalse(self.e.stamp.exists())
        time.sleep(0.3)
        with self.assertRaises(ProcessLookupError):
            os.kill(qpid, 0)

    def test_qmd_bin_overrides_path(self):
        alt = self.e.root / "alt-qmd"
        alt.write_text("#!/bin/sh\necho alt \"$@\" >> \"$FAKE/calls\"\n")
        alt.chmod(0o755)
        self.assertEqual(self.e.run(QMD_BIN=str(alt)), 0)
        self.assertIn("alt update", self.e.calls)

    def test_missing_tools(self):
        (self.e.bin / "qmd").unlink()
        self.assertEqual(self.e.run(), 127)
        self.assertIn("qmd not found", self.e.err)
        e = Env()
        self.addCleanup(e.tmp.cleanup)
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


def run_with(self, cmd, code):
    return self.run(FAKE_QMD_FAIL=cmd, FAKE_QMD_CODE=str(code))


Env.run_with = run_with

if __name__ == "__main__":
    unittest.main()
