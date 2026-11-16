"""The mistakes-report's chezmoi gate (data mistakesReport.enabled, default on only on personal Linux) and the script that retires its old timer.

The Retro lead keeper runs the command weekly, so the systemd timer and service are gone from the source. .chezmoiignore is rendered from the
real source with the profile and OS overridden; the retire script runs against a fake systemctl. Nothing here touches the real systemd.
Run: python3 -m unittest discover -s tests/mistakes-report
"""
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
RETIRE = REPO / "run_onchange_after_78_retire_mistakes_report_timer.sh"
RETIRE_DEST = "78_retire_mistakes_report_timer.sh"
UNITS = ("mistakes-report.service", "mistakes-report.timer")
PATHS = (".local/bin/mistakes-report", ".local/share/mistakes-report")


def render(path, profile="personal", os_name="linux", data=None, installed=False):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        dest = Path(tmp) / "dest"
        (dest / ".config/systemd/user").mkdir(parents=True)
        if installed:
            (dest / ".config/systemd/user/mistakes-report.timer").write_text("")
        override = {"profile": profile, "chezmoi": {"os": os_name, "destDir": str(dest)}}
        if data is not None:
            override["mistakesReport"] = data
        return subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "execute-template", "--override-data", json.dumps(override)],
                              input=Path(path).read_text(), capture_output=True, text=True, timeout=120, env={**os.environ, "HOME": tmp})


def ignored(**kw):
    r = render(IGNORE, **kw)
    assert r.returncode == 0, r.stderr
    return {line.strip() for line in r.stdout.splitlines() if line.strip() and not line.startswith("#")}


class SourceTest(unittest.TestCase):
    def test_the_timer_and_service_are_gone_from_the_source(self):
        for name in UNITS:
            self.assertFalse((REPO / "dot_config/systemd/user" / name).exists(), name)
        self.assertFalse((REPO / "run_onchange_after_78_mistakes_report_systemd.sh.tmpl").exists())

    def test_the_command_the_keeper_calls_is_still_in_the_source(self):
        self.assertTrue((REPO / "dot_local/bin/executable_mistakes-report").exists())
        self.assertTrue((REPO / "dot_local/share/mistakes-report/mistakes_report.py").exists())


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class GateTest(unittest.TestCase):
    def test_personal_linux_gets_the_command_and_its_code(self):
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
            ig = ignored(profile=profile, os_name=os_name, installed=True)
            for p in PATHS + (RETIRE_DEST,):
                self.assertIn(p, ig, (profile, os_name))

    def test_turned_off_stops_managing_the_command(self):
        for p in PATHS:
            self.assertIn(p, ignored(data={"enabled": False}))

    def test_the_retire_script_runs_only_where_the_old_timer_is_still_installed(self):
        self.assertNotIn(RETIRE_DEST, ignored(installed=True))
        self.assertNotIn(RETIRE_DEST, ignored(profile="axon-work-computer", installed=True))
        self.assertIn(RETIRE_DEST, ignored(installed=False))
        self.assertIn(RETIRE_DEST, ignored(profile="axon-work-computer", installed=False))

    def test_a_bad_setting_fails_the_render(self):
        for data in ({"enabeld": True}, {"enabled": "yes"}, {"enabled": None}, "on"):
            for path in (CONFIG, IGNORE):
                self.assertNotEqual(render(path, data=data).returncode, 0, (path.name, data))


class RetireTest(unittest.TestCase):
    def run_retire(self, installed=True, active=False, wsl=False, systemd=True):
        with tempfile.TemporaryDirectory() as tmp:
            home, bin_ = Path(tmp) / "home", Path(tmp) / "bin"
            (home / ".config/systemd/user").mkdir(parents=True)
            bin_.mkdir()
            if installed:
                for n in UNITS:
                    (home / ".config/systemd/user" / n).write_text("")
            log = Path(tmp) / "calls"
            (bin_ / "systemctl").write_text('#!/bin/sh\necho "$*" >> "%s"\n[ "$2" = show-environment ] && [ "%s" = no ] && exit 1\n[ "$2" = is-active ] && [ "%s" = no ] && exit 3\nexit 0\n'
                                            % (log, "yes" if systemd else "no", "yes" if active else "no"))
            (bin_ / "systemctl").chmod(0o755)
            marker = Path(tmp) / "wsl"
            if wsl:
                marker.write_text("")
            p = subprocess.run(["sh", str(RETIRE)], capture_output=True, text=True,
                               env={"HOME": str(home), "PATH": "%s:/usr/bin:/bin" % bin_, "MISTAKES_REPORT_WSL_MARKER": str(marker)})
            self.units = sorted(x.name for x in (home / ".config/systemd/user").iterdir())
            return p, log.read_text().splitlines() if log.exists() else []

    def test_it_stops_and_disables_the_timer_removes_both_units_and_reloads(self):
        p, calls = self.run_retire()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.units, [])
        self.assertEqual([c for c in calls if "show-environment" not in c],
                         ["--user disable --now mistakes-report.timer", "--user is-active --quiet mistakes-report.timer", "--user daemon-reload"])

    def test_it_is_idempotent_when_the_units_are_already_gone(self):
        p, calls = self.run_retire(installed=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.units, [])

    def test_it_fails_and_keeps_the_units_when_the_timer_will_not_stop(self):
        p, calls = self.run_retire(active=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("could not stop mistakes-report.timer", p.stdout)
        self.assertEqual(self.units, list(UNITS))
        self.assertNotIn("--user daemon-reload", calls)

    def test_wsl_is_left_alone(self):
        p, calls = self.run_retire(wsl=True)
        self.assertEqual((p.returncode, calls), (0, []))
        self.assertEqual(self.units, list(UNITS))

    def test_a_host_with_no_systemd_user_manager_is_a_clean_notice(self):
        p, calls = self.run_retire(systemd=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.units, list(UNITS))
        self.assertNotIn("--user disable --now mistakes-report.timer", calls)


if __name__ == "__main__":
    unittest.main()
