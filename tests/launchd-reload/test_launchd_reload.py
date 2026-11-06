"""The shared wait-then-bootstrap helper (dot_local/share/launchd-reload/launchd_reload.sh) and a loader that uses it (script 72).

launchd's race: `launchctl bootstrap` straight after `launchctl bootout` fails (5, Input/output error) while the old job is still being
torn down, and the agent stays unloaded after an apply. The fake launchctl here models exactly that: after a bootout the job stays visible
to `print` for FAKE_TEARDOWN more polls, and a bootstrap in that time fails with 5. Nothing here calls the real launchctl or launchd.

    HelperTest   the helper sourced by a small driver: waits, retries, succeeds; never-goes-away; never-loads; the old sequence as a RED control
    LoaderTest   script 72 rendered by the real chezmoi and run against the fake (scripts 71 and the reconcile script are covered in
                 tests/qmd and tests/instances)
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "dot_local/share/launchd-reload/launchd_reload.sh"
LOADER = REPO / "run_onchange_after_72_heavy_gate_watchdog_launchd.sh.tmpl"
LABEL = "local.heavy-gate-watchdog"
SYS = "/usr/bin:/bin:/usr/sbin:/sbin"
# The shipped numbers (20 polls, 3 retries); only the sleeps are shortened.
FAST = {"LAUNCHD_POLL_SLEEP": "0.001", "LAUNCHD_RETRY_SLEEP": "0"}

# "loaded" is a file. print: 0 while loaded, 113 when not (as the real one). bootout starts a teardown of FAKE_TEARDOWN polls (default: none).
# bootstrap: 5 while a teardown is in progress, 5 for the first FAKE_BOOTSTRAP_FAILS tries, otherwise it loads the job.
FAKE_LAUNCHCTL = r"""#!/bin/sh
echo "$1" >> "$FAKE/calls"
label=${2##*/}
case $1 in
  print)
    if [ -f "$FAKE/teardown" ]; then
      n=$(cat "$FAKE/teardown")
      if [ "$n" -gt 0 ]; then echo $((n - 1)) > "$FAKE/teardown"; exit 0; fi
      rm -f "$FAKE/teardown" "$FAKE/loaded"
    fi
    [ -f "$FAKE/loaded" ] || exit 113 ;;
  bootout)
    [ -f "$FAKE/loaded" ] || exit 3
    if [ -n "${FAKE_TEARDOWN:-}" ]; then echo "$FAKE_TEARDOWN" > "$FAKE/teardown"; else rm -f "$FAKE/loaded"; fi ;;
  bootstrap)
    [ ! -f "$FAKE/teardown" ] || { echo "Bootstrap failed: 5: Input/output error" >&2; exit 5; }
    c=$(cat "$FAKE/bootstrap.calls" 2>/dev/null || echo 0); echo $((c + 1)) > "$FAKE/bootstrap.calls"
    [ "$c" -ge "${FAKE_BOOTSTRAP_FAILS:-0}" ] || { echo "Bootstrap failed: 5: Input/output error" >&2; exit 5; }
    : > "$FAKE/loaded" ;;
  *) exit 64 ;;
esac
"""


def write_exec(path, text):
    """Temp file, then rename: a reader never sees a half-written executable."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.rename(tmp, path)


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home, self.fake, self.bin = root / "home", root / "fake", root / "bin"
        for d in (self.home / "Library/LaunchAgents", self.home / ".local/share/launchd-reload", self.fake, self.bin):
            d.mkdir(parents=True)
        write_exec(self.bin / "launchctl", FAKE_LAUNCHCTL)
        write_exec(self.bin / "uname", "#!/bin/sh\necho Darwin\n")
        shutil.copy(LIB, self.home / ".local/share/launchd-reload/launchd_reload.sh")
        self.plist = self.home / "Library/LaunchAgents" / (LABEL + ".plist")
        self.plist.write_text("<plist/>")

    def start_loaded(self):
        (self.fake / "loaded").write_text("")

    def sh(self, script, **env):
        e = dict(os.environ, HOME=str(self.home), FAKE=str(self.fake), PATH="%s:%s" % (self.bin, SYS), **FAST)
        e.update({k: str(v) for k, v in env.items()})
        return subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, timeout=60, env=e)

    def calls(self):
        f = self.fake / "calls"
        return f.read_text().splitlines() if f.exists() else []

    @property
    def loaded(self):
        return (self.fake / "loaded").exists()


# bootout, wait, bootstrap: the sequence a loader runs, as a driver around the helper.
DRIVER = '''set -eu
. "$HOME/.local/share/launchd-reload/launchd_reload.sh"
launchctl bootout gui/$(id -u)/%(label)s >/dev/null 2>&1 || :
launchd_wait_gone %(label)s || { echo "STILL LOADED"; exit 1; }
launchd_bootstrap %(label)s "$HOME/Library/LaunchAgents/%(label)s.plist"
''' % {"label": LABEL}

# The sequence the scripts had: no wait, one try.
OLD_SEQUENCE = '''set -eu
launchctl bootout gui/$(id -u)/%(label)s >/dev/null 2>&1 || :
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/%(label)s.plist"
''' % {"label": LABEL}


class HelperTest(Scratch):
    def test_it_waits_for_the_bootout_then_retries_the_bootstrap_then_succeeds(self):
        self.start_loaded()
        p = self.sh(DRIVER, FAKE_TEARDOWN="3", FAKE_BOOTSTRAP_FAILS="1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        # the bootout, four prints (three still there, the fourth fails: gone), a failed bootstrap, the retry that loads
        self.assertEqual(self.calls(), ["bootout"] + ["print"] * 4 + ["bootstrap"] * 2)
        self.assertTrue(self.loaded)
        self.assertIn("WARN: bootstrap of %s failed" % LABEL, p.stdout)
        self.assertNotIn("ERROR", p.stdout)

    def test_a_job_that_never_goes_away_stops_the_wait_after_20_polls(self):
        self.start_loaded()
        p = self.sh(DRIVER, FAKE_TEARDOWN="100000")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("STILL LOADED", p.stdout)
        self.assertEqual(self.calls(), ["bootout"] + ["print"] * 21, "20 sleeps, 21 prints, no bootstrap")

    def test_a_bootstrap_that_never_succeeds_gives_one_error_naming_the_label_and_plist_and_a_non_zero_exit(self):
        p = self.sh(DRIVER, FAKE_BOOTSTRAP_FAILS="100")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.calls().count("bootstrap"), 4, "one try and three retries")
        errors = [line for line in p.stdout.splitlines() if "ERROR" in line]
        self.assertEqual(len(errors), 1, p.stdout)
        self.assertIn(LABEL, errors[0])
        self.assertIn(str(self.plist), errors[0])
        self.assertIn("run: launchctl bootstrap gui/%d %s" % (os.getuid(), self.plist), errors[0])
        self.assertFalse(self.loaded)

    def test_the_log_tag_names_the_caller(self):
        p = self.sh(DRIVER, FAKE_BOOTSTRAP_FAILS="100", LAUNCHD_TAG="qmd_refresh_launchd")
        self.assertIn("[qmd_refresh_launchd] ERROR: could not load %s" % LABEL, p.stdout)

    def test_the_wait_is_not_taken_when_the_job_is_not_loaded(self):
        p = self.sh(DRIVER)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.calls().count("print"), 1, "one poll finds the job gone")
        self.assertTrue(self.loaded)

    def test_RED_control_the_old_sequence_fails_the_race(self):
        # Same fake, same teardown: the no-wait sequence sends the bootstrap while launchd still has the job, and the agent stays unloaded.
        self.start_loaded()
        p = self.sh(OLD_SEQUENCE, FAKE_TEARDOWN="3")
        self.assertNotEqual(p.returncode, 0, "the old sequence must fail against a teardown in progress")
        self.assertIn("Input/output error", p.stderr)
        self.assertEqual(self.calls(), ["bootout", "bootstrap"])
        self.assertTrue((self.fake / "loaded").exists() and (self.fake / "teardown").exists(), "still being torn down, never reloaded")
        # and the helper's sequence, on the same fake, loads it
        self.setUp_again()
        p = self.sh(DRIVER, FAKE_TEARDOWN="3")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(self.loaded)

    def setUp_again(self):
        for f in self.fake.iterdir():
            f.unlink()
        self.start_loaded()


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class LoaderTest(Scratch):
    """Script 72, rendered from the real source by chezmoi, then run with the fake launchctl first on PATH."""

    def setUp(self):
        super().setUp()
        cfg = Path(self.tmp.name) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: personal\n")
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                           input=LOADER.read_text(), capture_output=True, text=True, timeout=60, env=dict(os.environ, HOME=str(self.home)))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.script = r.stdout

    def test_a_reload_survives_the_teardown_and_a_failed_first_bootstrap(self):
        self.start_loaded()
        p = self.sh(self.script, FAKE_TEARDOWN="3", FAKE_BOOTSTRAP_FAILS="1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.calls(), ["print", "bootout"] + ["print"] * 4 + ["bootstrap"] * 2)
        self.assertTrue(self.loaded)
        self.assertIn("loaded %s" % LABEL, p.stdout)

    def test_a_job_that_never_goes_away_fails_the_apply(self):
        self.start_loaded()
        p = self.sh(self.script, FAKE_TEARDOWN="100000")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertIn("ERROR: could not unload %s" % LABEL, p.stdout)
        self.assertNotIn("bootstrap", self.calls())

    def test_a_job_that_never_loads_fails_the_apply_with_one_error(self):
        p = self.sh(self.script, FAKE_BOOTSTRAP_FAILS="100")
        self.assertNotEqual(p.returncode, 0, p.stdout)
        errors = [line for line in p.stdout.splitlines() if "ERROR" in line]
        self.assertEqual(len(errors), 1, p.stdout)
        self.assertIn(LABEL, errors[0])
        self.assertIn(str(self.plist), errors[0])

    def test_a_missing_helper_fails_the_apply_so_it_is_retried(self):
        (self.home / ".local/share/launchd-reload/launchd_reload.sh").unlink()
        p = self.sh(self.script)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("ERROR", p.stdout)
        self.assertEqual(self.calls(), [], "nothing is stopped when the helper is missing")


class DeployTest(unittest.TestCase):
    def test_the_helper_is_left_out_off_macos_like_its_callers(self):
        ignore = (REPO / ".chezmoiignore").read_text()
        block = ignore[ignore.index("# launchd only."):]
        block = block[:block.index("{{- end }}")]
        self.assertIn(".local/share/launchd-reload", block)
        self.assertIn("75_instances_reconcile.sh", block)

    def test_the_helper_is_posix_sh(self):
        r = subprocess.run(["/bin/sh", "-n", str(LIB)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
