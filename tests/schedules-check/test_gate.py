"""The schedulesCheck.enabled gate: which profiles get the schedules-check timer units and loader, what the service runs, and what the loader does.
Real chezmoi against this source, a throwaway HOME. Linux only: the default (on) needs .chezmoi.os == linux.
Run: python3 -m unittest discover -s tests/schedules-check
"""
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
PATHS = {".config/systemd/user/schedules-check.service", ".config/systemd/user/schedules-check.timer", "91_schedules_check_systemd.sh"}
SERVICE = REPO / "dot_config/systemd/user/schedules-check.service.tmpl"
TIMER = REPO / "dot_config/systemd/user/schedules-check.timer"
LOADER = REPO / "run_onchange_after_91_schedules_check_systemd.sh.tmpl"


def chezmoi(profile, verb, *args, enabled=None, stdin=None):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        extra = "" if enabled is None else "  schedulesCheck:\n    enabled: %s\n" % enabled
        cfg.write_text("data:\n  profile: %s\n%s" % (profile, extra))
        return subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home),
                               verb, *args], input=stdin, capture_output=True, text=True, env=source_tree.chezmoi_env(home), timeout=120)


def managed(profile, enabled=None):
    r = chezmoi(profile, "managed", enabled=enabled)
    assert r.returncode == 0, r.stderr
    return set(r.stdout.split())


@unittest.skipUnless(sys.platform.startswith("linux"), "the default gate needs Linux")
class GateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):   # each chezmoi call takes a few seconds; run them side by side
        with ThreadPoolExecutor() as pool:
            jobs = dict(personal=pool.submit(managed, "personal"), work=pool.submit(managed, "axon-work-computer"),
                        off=pool.submit(managed, "personal", "false"), work_on=pool.submit(managed, "axon-work-computer", "true"),
                        service=pool.submit(chezmoi, "personal", "execute-template", stdin=SERVICE.read_text()),
                        script_on=pool.submit(chezmoi, "personal", "execute-template", enabled="true", stdin=LOADER.read_text()),
                        script_off=pool.submit(chezmoi, "personal", "execute-template", enabled="false", stdin=LOADER.read_text()))
            cls.got = {k: v.result() for k, v in jobs.items()}

    def test_personal_linux_gets_all_of_it(self):
        self.assertLessEqual(PATHS, self.got["personal"])

    def test_work_profile_gets_none_of_it(self):
        self.assertEqual(PATHS & self.got["work"], set())

    def test_switched_off_leaves_all_of_it_out(self):
        self.assertEqual(PATHS & self.got["off"], set())

    def test_switched_on_for_work_installs_it(self):
        self.assertLessEqual(PATHS, self.got["work_on"])

    def test_a_typo_fails_the_render(self):
        r = chezmoi("personal", "managed", enabled="maybe")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("schedulesCheck.enabled must be true or false", r.stderr)

    def test_timer_is_daily_at_0830_utc_and_persistent(self):
        t = TIMER.read_text()
        self.assertIn("OnCalendar=*-*-* 08:30:00 UTC", t)
        self.assertIn("Persistent=true", t)

    def test_service_runs_the_coordinator_schedules_check(self):
        r = self.got["service"]
        self.assertEqual(r.returncode, 0, r.stderr)
        exec_line = next(l for l in r.stdout.splitlines() if l.startswith("ExecStart="))
        self.assertTrue(exec_line.endswith("/src/coordinatord/cli.ts schedules check"), exec_line)
        self.assertIn("Type=oneshot", r.stdout)

    def load_script(self, enabled):
        r = self.got["script_" + ("on" if enabled == "true" else "off")]
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_loader_starts_the_timer_when_on(self):
        s = self.load_script("true")
        self.assertIn("systemctl --user enable schedules-check.timer", s)
        self.assertIn("systemctl --user restart schedules-check.timer", s)
        self.assertNotIn("disable --now", s)

    def test_loader_stops_the_timer_and_removes_the_units_when_off(self):
        s = self.load_script("false")
        self.assertIn("disable --now schedules-check.timer", s)
        self.assertIn('rm -f "$dir/schedules-check.service" "$dir/schedules-check.timer"', s)
        self.assertNotIn("restart schedules-check.timer", s)


if __name__ == "__main__":
    unittest.main()
