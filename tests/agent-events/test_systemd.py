"""The agent-events exporter on Linux: a systemd user service + timer (the twin of the macOS LaunchAgent), its load script and its gate.

Rendered from the real source with a throwaway config (no hooks). The load script runs against a fake systemctl; nothing here touches the
real systemd or a live file. Run: python3 -m unittest discover -s tests/agent-events
"""
import configparser
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_config import BAD, DEFAULT_ENDPOINT, REPO, WORK, render

SERVICE = REPO / "dot_config/systemd/user/agent-events.service.tmpl"
TIMER = REPO / "dot_config/systemd/user/agent-events.timer"
LOADER = REPO / "run_onchange_after_77_agent_events_systemd.sh.tmpl"
IGNORE = REPO / ".chezmoiignore"
UNITS = (".config/systemd/user/agent-events.service", ".config/systemd/user/agent-events.timer")
SCRIPT = "77_agent_events_systemd.sh"


def parse(text):
    parser = configparser.ConfigParser(interpolation=None, strict=False)   # strict=False: Environment= may repeat
    parser.optionxform = str
    parser.read_string(text)
    return parser


def service(profile="personal", data=""):
    return parse(render(SERVICE, profile, data)[0].stdout)


def env_of(text):
    out = {}
    for line in text.splitlines():
        if line.startswith("Environment="):
            k, v = line[len("Environment="):].strip('"').split("=", 1)
            out[k] = v
    return out


def ignored(profile, chezmoi_os, data=None, installed=False):
    """The destination patterns .chezmoiignore lists for this profile and OS (a render with the OS overridden)."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        dest = Path(tmp) / "dest"
        (dest / ".config/systemd/user").mkdir(parents=True)
        if installed:
            (dest / ".config/systemd/user/agent-events.timer").write_text("")
        override = {"profile": profile, "chezmoi": {"os": chezmoi_os, "destDir": str(dest)}}
        if data is not None:
            override["agentEvents"] = data
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "execute-template", "--override-data", json.dumps(override)],
                           input=IGNORE.read_text(), capture_output=True, text=True, timeout=120, env={**os.environ, "HOME": tmp})
    assert r.returncode == 0, r.stderr
    return {line.strip() for line in r.stdout.splitlines() if line.strip() and not line.startswith("#")}


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class UnitTest(unittest.TestCase):
    def test_personal_default_runs_todays_command_with_the_machine_label(self):
        text = render(SERVICE)[0].stdout
        p = parse(text)
        self.assertEqual(p["Service"]["Type"], "oneshot")
        self.assertEqual(p["Service"]["ExecStart"], "/bin/sh %h/.local/bin/agent-events run")
        self.assertEqual(p["Service"]["Nice"], "10")
        self.assertEqual(env_of(text), {"AGENT_EVENTS_OTLP_ENDPOINT": DEFAULT_ENDPOINT, "AGENT_EVENTS_MACHINE": "personal",
                                        "AGENT_TRACES_ALLOW_PRODUCTION_WRITE": "1"})   # the kit's guard: a tick without it builds and exports nothing

    def test_overrides_render(self):
        text = render(SERVICE, WORK, "agentEvents: {enabled: true, machine: work-laptop, endpoint: 'https://x.example/v1/metrics'}")[0].stdout
        self.assertEqual(env_of(text), {"AGENT_EVENTS_OTLP_ENDPOINT": "https://x.example/v1/metrics", "AGENT_EVENTS_MACHINE": "work-laptop",
                                        "AGENT_TRACES_ALLOW_PRODUCTION_WRITE": "1"})

    def test_the_settings_match_the_launch_agent_for_the_same_data(self):
        # One source of the values: the unit never spells the endpoint or the label itself.
        self.assertNotIn("otel-collector", SERVICE.read_text().split("\n", 1)[1].replace("{{", ""), "no endpoint hard-coded in the unit")

    def test_a_bad_value_fails_the_render_of_the_unit_and_the_loader(self):
        for data in BAD:
            for path in (SERVICE, LOADER):
                r, _ = render(path, data=data, check=False)
                self.assertNotEqual(r.returncode, 0, (path.name, data))

    def test_the_timer_ticks_every_two_minutes_from_load(self):
        p = parse(TIMER.read_text())
        self.assertEqual(p["Timer"]["OnUnitActiveSec"], "2min")
        self.assertEqual(p["Timer"]["OnActiveSec"], "5s")
        self.assertEqual(p["Install"]["WantedBy"], "timers.target")

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze is not installed")
    def test_systemd_accepts_the_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "agent-events.service").write_text(render(SERVICE)[0].stdout)
            shutil.copy(TIMER, d / "agent-events.timer")
            r = subprocess.run(["systemd-analyze", "verify", "--user", str(d / "agent-events.service"), str(d / "agent-events.timer")],
                               capture_output=True, text=True, timeout=60, cwd=tmp)
        bad = [l for l in r.stderr.splitlines() if "agent-events" in l and "/bin/sh" not in l and "agent-events run" not in l]
        self.assertEqual(bad, [], r.stderr)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class GateTest(unittest.TestCase):
    def test_personal_linux_manages_the_units_and_the_loader(self):
        ig = ignored("personal", "linux")
        for name in (*UNITS, SCRIPT):
            self.assertNotIn(name, ig)

    def test_work_linux_manages_none_until_the_setting_is_turned_on(self):
        ig = ignored("axon-work-computer", "linux")
        for name in (*UNITS, SCRIPT):
            self.assertIn(name, ig)
        ig = ignored("axon-work-computer", "linux", data={"enabled": True})
        for name in (*UNITS, SCRIPT):
            self.assertNotIn(name, ig)

    def test_macos_and_termux_get_none(self):
        for profile, chezmoi_os in (("personal", "darwin"), ("axon-work-computer", "darwin"), ("termux", "android")):
            ig = ignored(profile, chezmoi_os)
            for name in (*UNITS, SCRIPT):
                self.assertIn(name, ig, (profile, chezmoi_os))

    def test_disabled_keeps_only_the_unload_script_while_the_timer_is_installed(self):
        ig = ignored("personal", "linux", data={"enabled": False}, installed=False)
        for name in (*UNITS, SCRIPT):
            self.assertIn(name, ig)
        ig = ignored("personal", "linux", data={"enabled": False}, installed=True)
        for name in UNITS:
            self.assertIn(name, ig)
        self.assertNotIn(SCRIPT, ig)

    def test_the_macos_pieces_stay_off_linux(self):
        ig = ignored("personal", "linux")
        self.assertIn("Library/LaunchAgents/local.agent-events.plist", ig)
        self.assertIn("70_agent_events_launchd.sh", ig)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class LoaderTest(unittest.TestCase):
    def run_loader(self, data="", profile="personal", installed=True, wsl=False, user_manager=True, active=True, active_after_stop=False):
        if os.uname().sysname != "Linux":   # the loader's first gate is uname -s = Linux; elsewhere it exits 0 before it calls systemctl
            self.skipTest("the loader runs only on Linux (uname -s gate)")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home, fake, bin_ = root / "home", root / "fake", root / "bin"
            for d in ((home / ".config/systemd/user"), fake, bin_):
                d.mkdir(parents=True)
            if installed:
                for name in ("agent-events.service", "agent-events.timer"):
                    (home / ".config/systemd/user" / name).write_text("")
            rendered = render(LOADER, profile, data)[0].stdout
            script = root / "load.sh"
            script.write_text(rendered)
            # Fake systemctl: records its arguments; "show-environment" fails without a user manager; "is-active" answers from $ACTIVE.
            (bin_ / "systemctl").write_text(
                '#!/bin/sh\necho "$*" >> "$FAKE/calls"\n'
                'case "$2" in\n'
                '  show-environment) [ "$USER_MANAGER" = 1 ] || exit 1 ;;\n'
                '  is-active) [ "$ACTIVE" = 1 ] || exit 3 ;;\n'
                'esac\nexit 0\n')
            (bin_ / "systemctl").chmod(0o755)
            marker = root / "wsl"
            if wsl:
                marker.write_text("")
            env = {"PATH": "%s:/usr/bin:/bin" % bin_, "HOME": str(home), "FAKE": str(fake), "USER_MANAGER": "1" if user_manager else "0",
                   "ACTIVE": "1" if active else "0", "AGENT_EVENTS_WSL_MARKER": str(marker)}
            r = subprocess.run(["sh", str(script)], capture_output=True, text=True, env=env, timeout=30)
            calls = (fake / "calls").read_text().splitlines() if (fake / "calls").exists() else []
            left = sorted(p.name for p in (home / ".config/systemd/user").iterdir())
        return r, calls, left

    def test_enabled_reloads_enables_and_starts_the_timer(self):
        r, calls, left = self.run_loader()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(calls, ["--user show-environment", "--user daemon-reload", "--user enable agent-events.timer",
                                 "--user restart agent-events.timer", "--user is-active --quiet agent-events.timer"])
        self.assertIn("loaded agent-events.timer", r.stdout)

    def test_a_timer_that_is_not_active_fails_the_apply_so_it_is_retried(self):
        r, _, _ = self.run_loader(active=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not active", r.stdout)

    def test_missing_units_fail_the_apply_so_it_is_retried(self):
        r, calls, _ = self.run_loader(installed=False)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("--user restart agent-events.timer", calls)

    def test_no_user_manager_is_a_clean_notice(self):
        r, calls, _ = self.run_loader(user_manager=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no systemd user manager", r.stdout)
        self.assertEqual(calls, ["--user show-environment"])

    def test_wsl_is_left_alone(self):
        r, calls, _ = self.run_loader(wsl=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WSL", r.stdout)
        self.assertEqual(calls, [])

    def test_disabled_stops_the_timer_and_removes_the_units(self):
        r, calls, left = self.run_loader(data="agentEvents: {enabled: false}", active=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--user disable --now agent-events.timer", calls)
        self.assertEqual(left, [])
        self.assertIn("removed", r.stdout)

    def test_a_timer_that_will_not_stop_fails_the_apply_and_keeps_the_units(self):
        r, _, left = self.run_loader(data="agentEvents: {enabled: false}", active=True)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(left, ["agent-events.service", "agent-events.timer"])

    def test_the_script_changes_with_the_units_and_the_setting_so_chezmoi_reruns_it(self):
        base = render(LOADER)[0].stdout
        self.assertNotEqual(base, render(LOADER, data="agentEvents: {machine: other}")[0].stdout)
        self.assertNotEqual(base, render(LOADER, data="agentEvents: {endpoint: 'http://a.example/v1/metrics'}")[0].stdout)
        self.assertEqual(subprocess.run(["sh", "-n"], input=base, text=True, capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
