"""The weekly mistakes-report's chezmoi gate (data mistakesReport.enabled, default on only on personal Linux), its units and its load script.

.chezmoiignore is rendered from the real source with the profile and OS overridden; the load script runs against a fake systemctl.
Nothing here touches the real systemd. Run: python3 -m unittest discover -s tests/mistakes-report
"""
import configparser
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IGNORE = REPO / ".chezmoiignore"
CONFIG = REPO / ".chezmoitemplates/mistakes_report_config"
LOADER = REPO / "run_onchange_after_78_mistakes_report_systemd.sh.tmpl"
SERVICE = REPO / "dot_config/systemd/user/mistakes-report.service"
TIMER = REPO / "dot_config/systemd/user/mistakes-report.timer"
PATHS = (".config/systemd/user/mistakes-report.service", ".config/systemd/user/mistakes-report.timer", "78_mistakes_report_systemd.sh",
         ".local/bin/mistakes-report", ".local/share/mistakes-report")


def render(path, profile="personal", os_name="linux", data=None):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        override = {"profile": profile, "chezmoi": {"os": os_name, "destDir": str(Path(tmp) / "dest")}}
        if data is not None:
            override["mistakesReport"] = data
        return subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "execute-template", "--override-data", json.dumps(override)],
                              input=Path(path).read_text(), capture_output=True, text=True, timeout=120, env={**os.environ, "HOME": tmp})


def ignored(**kw):
    r = render(IGNORE, **kw)
    assert r.returncode == 0, r.stderr
    return {line.strip() for line in r.stdout.splitlines() if line.strip() and not line.startswith("#")}


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class GateTest(unittest.TestCase):
    def test_personal_linux_gets_every_piece(self):
        ig = ignored()
        for p in PATHS:
            self.assertNotIn(p, ig)

    def test_work_gets_none_until_the_setting_is_turned_on(self):
        for p in PATHS:
            self.assertIn(p, ignored(profile="axon-work-computer"))
        for p in PATHS:
            self.assertNotIn(p, ignored(profile="axon-work-computer", data={"enabled": True}))

    def test_other_systems_get_none(self):
        for profile, os_name in (("personal", "darwin"), ("axon-work-computer", "darwin"), ("termux", "android")):
            for p in PATHS:
                self.assertIn(p, ignored(profile=profile, os_name=os_name), (profile, os_name))

    def test_personal_can_turn_it_off(self):
        for p in PATHS:
            self.assertIn(p, ignored(data={"enabled": False}))

    def test_a_bad_setting_fails_the_render(self):
        for data in ({"enabeld": True}, {"enabled": "yes"}, {"enabled": None}, "on"):
            for path in (CONFIG, IGNORE, LOADER):
                self.assertNotEqual(render(path, data=data).returncode, 0, (path.name, data))


class UnitTest(unittest.TestCase):
    def test_the_timer_runs_weekly_and_catches_up(self):
        p = configparser.ConfigParser(interpolation=None)
        p.optionxform = str
        p.read_string(TIMER.read_text())
        self.assertEqual(p["Timer"]["OnCalendar"], "Mon *-*-* 07:30:00")
        self.assertEqual(p["Timer"]["Persistent"], "true")
        self.assertEqual(p["Install"]["WantedBy"], "timers.target")

    def test_the_service_runs_the_command_with_a_path_that_finds_claude(self):
        text = SERVICE.read_text()
        self.assertIn("ExecStart=%h/.local/bin/mistakes-report", text)
        self.assertIn("command-wrappers/bin", text)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze is not installed")
    def test_systemd_accepts_the_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            for src in (SERVICE, TIMER):
                shutil.copy(src, Path(tmp) / src.name)
            r = subprocess.run(["systemd-analyze", "verify", "--user", str(Path(tmp) / "mistakes-report.service"), str(Path(tmp) / "mistakes-report.timer")],
                               capture_output=True, text=True, timeout=60, cwd=tmp)
        bad = [l for l in r.stderr.splitlines() if "mistakes-report" in l and "mistakes-report " not in l.split("Command")[0] and "not executable" not in l and "No such file" not in l]
        self.assertEqual(bad, [], r.stderr)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class LoaderTest(unittest.TestCase):
    def run_loader(self, installed=True, active=True):
        r = render(LOADER)
        self.assertEqual(r.returncode, 0, r.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            home, bin_ = Path(tmp) / "home", Path(tmp) / "bin"
            (home / ".config/systemd/user").mkdir(parents=True)
            bin_.mkdir()
            if installed:
                for n in ("mistakes-report.service", "mistakes-report.timer"):
                    (home / ".config/systemd/user" / n).write_text("")
            log = Path(tmp) / "calls"
            (bin_ / "systemctl").write_text('#!/bin/sh\necho "$*" >> "%s"\n[ "$2" = is-active ] && [ "%s" = no ] && exit 3\nexit 0\n' % (log, "yes" if active else "no"))
            (bin_ / "systemctl").chmod(0o755)
            script = Path(tmp) / "load.sh"
            script.write_text(r.stdout)
            p = subprocess.run(["sh", str(script)], capture_output=True, text=True, env={"HOME": str(home), "PATH": "%s:/usr/bin:/bin" % bin_})
            return p, log.read_text().splitlines() if log.exists() else []

    def test_it_enables_and_restarts_the_timer(self):
        p, calls = self.run_loader()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([c for c in calls if "mistakes-report.timer" in c],
                         ["--user enable mistakes-report.timer", "--user restart mistakes-report.timer", "--user is-active --quiet mistakes-report.timer"])

    def test_it_fails_when_the_units_are_not_installed_or_the_timer_is_not_active(self):
        self.assertEqual(self.run_loader(installed=False)[0].returncode, 1)
        self.assertEqual(self.run_loader(active=False)[0].returncode, 1)


if __name__ == "__main__":
    unittest.main()
