"""The sessionCost.enabled gate: which profiles get the command, the code folder, the timer units and the loader, and what the loader does.
Real chezmoi against this source, a throwaway HOME. Linux only: the default (on) needs .chezmoi.os == linux.
Run: python3 -m unittest discover -s tests/session-cost
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
PATHS = {".local/bin/session-cost", ".local/share/token-efficiency", ".local/share/token-efficiency/session_cost.py",
         ".local/share/token-efficiency/collect.py", ".config/systemd/user/session-cost.service",
         ".config/systemd/user/session-cost.timer", "86_session_cost_systemd.sh"}


def chezmoi(profile, verb, *args, enabled=None, stdin=None):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        extra = "" if enabled is None else "  sessionCost:\n    enabled: %s\n" % enabled
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
        loader = (REPO / "run_onchange_after_86_session_cost_systemd.sh.tmpl").read_text()
        with ThreadPoolExecutor() as pool:
            jobs = dict(personal=pool.submit(managed, "personal"), work=pool.submit(managed, "axon-work-computer"),
                        off=pool.submit(managed, "personal", "false"), work_on=pool.submit(managed, "axon-work-computer", "true"),
                        script_on=pool.submit(chezmoi, "personal", "execute-template", enabled="true", stdin=loader),
                        script_off=pool.submit(chezmoi, "personal", "execute-template", enabled="false", stdin=loader))
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
        self.assertIn("sessionCost.enabled must be true or false", r.stderr)

    def load_script(self, enabled):
        r = self.got["script_" + ("on" if enabled == "true" else "off")]
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_loader_starts_the_timer_when_on(self):
        s = self.load_script("true")
        self.assertIn("systemctl --user enable session-cost.timer", s)
        self.assertIn("systemctl --user restart session-cost.timer", s)
        self.assertNotIn("disable --now", s)

    def test_loader_stops_the_timer_and_removes_the_units_when_off(self):
        s = self.load_script("false")
        self.assertIn("disable --now session-cost.timer", s)
        self.assertIn('rm -f "$dir/session-cost.service" "$dir/session-cost.timer"', s)
        self.assertNotIn("restart session-cost.timer", s)


if __name__ == "__main__":
    unittest.main()
