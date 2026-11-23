"""The daily pull of the work coordinator checkout (docs/work-coordinator-pull.md): the LaunchAgent
local.coordinator-pull-main.plist.tmpl and its load script run_onchange_after_92_coordinator_pull_main_launchd.sh.tmpl.

Static: both templates and .chezmoiignore are rendered with `chezmoi execute-template --override-data`, so the profile and the OS are
chosen per test and the suite runs on any host. Behaviour: the plist's sh -c script is run as a real process against a fake checkout,
and the load script against a fake launchctl and uname. Nothing here calls the real launchctl or launchd.
Run: python3 -m unittest discover -s tests/coordinator-pull-main
"""
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLIST = REPO / "Library/LaunchAgents/local.coordinator-pull-main.plist.tmpl"
LOADER = REPO / "run_onchange_after_92_coordinator_pull_main_launchd.sh.tmpl"
IGNORE = REPO / ".chezmoiignore"
LIB = REPO / "dot_local/share/launchd-reload/launchd_reload.sh"
WORK = "axon-work-computer"
PATHS = ("Library/LaunchAgents/local.coordinator-pull-main.plist", "92_coordinator_pull_main_launchd.sh")
SYS = "/usr/bin:/bin:/usr/sbin:/sbin"


def render(path, profile=WORK, os_="darwin", extra=None):
    data = {"profile": profile, "chezmoi": {"os": os_, "homeDir": "/Users/test", "sourceDir": str(REPO)}}
    data.update(extra or {})
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: personal\n")
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml",
                            "execute-template", "--override-data", json.dumps(data)],
                           input=path.read_text(), capture_output=True, text=True, timeout=120,
                           env={**os.environ, "HOME": str(tmp)})
    if r.returncode:
        raise AssertionError("chezmoi execute-template failed: %s" % r.stderr)
    return r.stdout


class PlistTest(unittest.TestCase):
    def plist(self, **kw):
        return plistlib.loads(render(PLIST, **kw).encode())

    def test_work_renders_a_daily_job_in_the_default_checkout(self):
        p = self.plist()
        self.assertEqual(p["Label"], "local.coordinator-pull-main")
        self.assertEqual(p["StartCalendarInterval"], {"Hour": 7, "Minute": 15})
        self.assertIs(p["RunAtLoad"], False)
        a = p["ProgramArguments"]
        self.assertEqual(a[:2], ["/bin/sh", "-c"])
        self.assertEqual(a[3:], ["sh", "/Users/test/coordinator-work", "/Users/test/Library/Logs/coordinator-work/pull-main.log"])
        self.assertIn("sh scripts/pull-main.sh", a[2])

    def test_the_minute_is_clear_of_pull_mains_refused_window(self):
        self.assertNotIn(self.plist()["StartCalendarInterval"]["Minute"], (0, 1, 2))

    def test_local_data_moves_the_checkout_and_the_path(self):
        p = self.plist(extra={"instances": {"coordinator": {"repo": "/Users/test/src/coord", "extraPath": "/opt/node/bin"}}})
        self.assertEqual(p["ProgramArguments"][4], "/Users/test/src/coord")
        self.assertTrue(p["EnvironmentVariables"]["PATH"].startswith("/opt/node/bin:/Users/test/.local/share/mise/shims:"))

    def test_the_loader_reloads_when_the_checkout_changes(self):
        a = render(LOADER)
        b = render(LOADER, extra={"instances": {"coordinator": {"repo": "/Users/test/src/coord"}}})
        self.assertNotEqual(a, b)


class GateTest(unittest.TestCase):
    def ignored(self, **kw):
        out = render(IGNORE, **kw).splitlines()
        return [p for p in PATHS if p in out]

    def test_work_macos_deploys_both(self):
        self.assertEqual(self.ignored(), [])

    def test_personal_macos_leaves_both_out(self):
        self.assertEqual(self.ignored(profile="personal"), list(PATHS))

    def test_work_on_linux_leaves_both_out(self):
        self.assertEqual(self.ignored(os_="linux"), list(PATHS))


class RunTest(unittest.TestCase):
    """The plist's sh -c script, run as launchd would, against a fake checkout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.script = plistlib.loads(render(PLIST).encode())["ProgramArguments"][2]

    def run_(self, repo):
        log = self.root / "logs/pull-main.log"
        p = subprocess.run(["/bin/sh", "-c", self.script, "sh", str(repo), str(log)], capture_output=True, text=True,
                           timeout=30, env={"PATH": SYS})
        return p, log.read_text().splitlines()

    def checkout(self, body):
        repo = self.root / "coordinator-work"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts/pull-main.sh").write_text(body)
        return repo

    def test_a_pull_logs_start_output_and_exit_0(self):
        repo = self.checkout("echo pulled abc123\npwd\n")
        p, lines = self.run_(repo)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertRegex(lines[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ start %s$" % repo)
        self.assertEqual(lines[1], "pulled abc123")
        self.assertEqual(lines[2], str(repo.resolve()), "pull-main runs with the checkout as its working directory")
        self.assertRegex(lines[3], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ exit 0$")

    def test_a_refusal_keeps_its_status_and_its_line(self):
        repo = self.checkout("echo 'pull-main: refused: not on main' >&2\nexit 1\n")
        p, lines = self.run_(repo)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(lines[1], "pull-main: refused: not on main")
        self.assertRegex(lines[-1], r"Z exit 1$")

    def test_a_missing_checkout_is_logged_not_silent(self):
        p, lines = self.run_(self.root / "nope")
        self.assertEqual(p.returncode, 2)
        self.assertTrue(any("cannot enter" in l for l in lines), lines)
        self.assertRegex(lines[-1], r"Z exit 2$")

    def test_each_run_appends(self):
        repo = self.checkout("echo ok\n")
        self.run_(repo)
        _, lines = self.run_(repo)
        self.assertEqual(len(lines), 6)


FAKE_LAUNCHCTL = r"""#!/bin/sh
echo "launchctl $*" >> "$FAKE/calls"
case $1 in
  print) [ -f "$FAKE/loaded" ] || exit 113 ;;
  bootout) [ -f "$FAKE/loaded" ] || exit 3; rm -f "$FAKE/loaded" ;;
  bootstrap) [ ! -f "$FAKE/loaded" ] || exit 5; : > "$FAKE/loaded" ;;
  *) exit 64 ;;
esac
"""


class LoaderTest(unittest.TestCase):
    def run_loader(self, installed=True, loaded=False):
        script = render(LOADER)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        h, fake, bin_ = root / "home", root / "fake", root / "bin"
        for d in (h / "Library/LaunchAgents", fake, bin_, h / ".local/share/launchd-reload"):
            d.mkdir(parents=True)
        (bin_ / "launchctl").write_text(FAKE_LAUNCHCTL)
        (bin_ / "uname").write_text("#!/bin/sh\necho Darwin\n")
        for f in bin_.iterdir():
            f.chmod(0o755)
        shutil.copy(LIB, h / ".local/share/launchd-reload/launchd_reload.sh")
        if installed:
            (h / "Library/LaunchAgents/local.coordinator-pull-main.plist").write_text("<plist/>")
        if loaded:
            (fake / "loaded").write_text("")
        p = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, timeout=30,
                           env=dict(HOME=str(h), FAKE=str(fake), PATH="%s:%s" % (bin_, SYS), LAUNCHD_POLL_SLEEP="0.01"))
        calls = (fake / "calls").read_text().splitlines() if (fake / "calls").exists() else []
        return p, [c.split()[1] for c in calls], h

    def test_loads_the_plist_and_makes_the_log_folder(self):
        p, calls, h = self.run_loader()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(calls, ["print", "bootstrap"])
        self.assertTrue((h / "Library/Logs/coordinator-work").is_dir())
        self.assertIn("07:15", p.stdout)

    def test_a_loaded_job_is_booted_out_first(self):
        p, calls, _ = self.run_loader(loaded=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(calls, ["print", "bootout", "print", "bootstrap"])

    def test_without_the_plist_the_apply_fails_so_it_is_retried(self):
        p, calls, _ = self.run_loader(installed=False)
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("bootstrap", calls)

    def test_it_does_nothing_off_macos(self):
        script = render(LOADER)
        p = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, timeout=30,
                           env=dict(HOME="/nonexistent", PATH="/bin:/usr/bin"))
        if os.uname().sysname == "Darwin":
            self.skipTest("this host is macOS")
        self.assertEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
