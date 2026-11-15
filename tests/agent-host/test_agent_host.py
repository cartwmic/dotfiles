"""agentHost.disableTimers and agentHost.removeCoordinatorHook: omarchy's two cutover switches (.chezmoitemplates/agent_host_config).

Real chezmoi against this source with a throwaway HOME and config; nothing is applied and no script runs (managed, execute-template only).
The Claude settings side of removeCoordinatorHook is in tests/t3-hook. Linux only: the timers are Linux units.
Run: python3 -m unittest discover -s tests/agent-host
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UNITS = {".config/systemd/user/%s.%s" % (n, k) for n in ("session-cost", "mistakes-report", "agent-events") for k in ("service", "timer")}
LOADERS = {"77": "run_onchange_after_77_agent_events_systemd.sh.tmpl", "78": "run_onchange_after_78_mistakes_report_systemd.sh.tmpl",
           "86": "run_onchange_after_86_session_cost_systemd.sh.tmpl"}
TIMERS = {"77": "agent-events", "78": "mistakes-report", "86": "session-cost"}


def chezmoi(profile, verb, *args, data=None, stdin=None):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": dict(data or {}, profile=profile)}))
        return subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home),
                               verb, *args], input=stdin, capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=120)


def managed(profile, data=None):
    r = chezmoi(profile, "managed", data=data)
    assert r.returncode == 0, r.stderr
    return set(r.stdout.split())


def template(profile, text, data=None):
    return chezmoi(profile, "execute-template", data=data, stdin=text)


def loader(profile, key, data=None):
    r = template(profile, (REPO / LOADERS[key]).read_text(), data)
    assert r.returncode == 0, r.stderr
    return r.stdout


def config(profile, data=None):
    r = template(profile, '{{ includeTemplate "agent_host_config" . }}', data)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@unittest.skipUnless(sys.platform.startswith("linux"), "the timers are Linux units")
class AgentHostSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):   # each chezmoi call takes a few seconds; run them side by side
        off = {"agentHost": {"disableTimers": False, "removeCoordinatorHook": False}}
        on = {"agentHost": {"disableTimers": True}}
        with ThreadPoolExecutor() as pool:
            jobs = dict(
                default=pool.submit(managed, "personal"), off=pool.submit(managed, "personal", off), on=pool.submit(managed, "personal", on),
                hook_only=pool.submit(managed, "personal", {"agentHost": {"removeCoordinatorHook": True}}),
                forced=pool.submit(managed, "personal", {"agentHost": {"disableTimers": True}, "sessionCost": {"enabled": True},
                                                          "mistakesReport": {"enabled": True}, "agentEvents": {"enabled": True}}),
                work=pool.submit(managed, "axon-work-computer"),
                cfg_default=pool.submit(config, "personal"), cfg_on=pool.submit(config, "personal", {"agentHost": {"disableTimers": True, "removeCoordinatorHook": True}}),
                **{"load_default_" + k: pool.submit(loader, "personal", k) for k in LOADERS},
                **{"load_on_" + k: pool.submit(loader, "personal", k, on) for k in LOADERS},
                **{"load_hookonly_" + k: pool.submit(loader, "personal", k, {"agentHost": {"removeCoordinatorHook": True}}) for k in LOADERS})
            cls.got = {k: v.result() for k, v in jobs.items()}

    def test_default_installs_the_three_timers(self):
        self.assertLessEqual(UNITS, self.got["default"])
        self.assertEqual(self.got["default"], self.got["off"])  # explicit false is the same as no key

    def test_default_loaders_start_the_timers(self):
        for k, name in TIMERS.items():
            s = self.got["load_default_" + k]
            self.assertIn("systemctl --user enable %s.timer" % name, s)
            self.assertIn("systemctl --user restart %s.timer" % name, s)
            self.assertNotIn("disable --now", s)

    def test_switch_on_stops_and_removes_all_three_timers(self):
        self.assertEqual(UNITS & self.got["on"], set())
        for k, name in TIMERS.items():
            s = self.got["load_on_" + k]
            self.assertIn("disable --now %s.timer" % name, s)
            self.assertIn('rm -f "$dir/%s.service" "$dir/%s.timer"' % (name, name), s)
            self.assertNotIn("restart %s.timer" % name, s)

    def test_switch_on_wins_over_the_three_own_enabled_settings(self):
        self.assertEqual(UNITS & self.got["forced"], set())

    def test_switch_on_drops_only_the_three_timers_their_commands_code_and_loaders(self):
        related = ("session-cost", "token-efficiency", "mistakes-report", "agent-events", "77_agent_events", "78_mistakes", "86_session_cost")
        dropped = self.got["default"] - self.got["on"]
        self.assertLessEqual(UNITS, dropped)
        self.assertEqual({p for p in dropped if not any(w in p for w in related)}, set())
        self.assertEqual(self.got["on"] - self.got["default"], set())

    def test_hook_switch_alone_changes_no_timer_and_no_managed_path(self):
        self.assertEqual(self.got["hook_only"], self.got["default"])
        for k in LOADERS:
            self.assertEqual(self.got["load_hookonly_" + k], self.got["load_default_" + k])

    def test_work_profile_manages_none_of_the_units(self):
        self.assertEqual(UNITS & self.got["work"], set())

    def test_config_defaults_and_values(self):
        self.assertEqual(self.got["cfg_default"], {"removeCoordinatorHook": False, "disableTimers": False, "podTunnelKey": ""})
        self.assertEqual(self.got["cfg_on"], {"removeCoordinatorHook": True, "disableTimers": True, "podTunnelKey": ""})

    def test_a_typo_or_unknown_key_fails_the_render(self):
        for data, msg in (({"agentHost": {"disableTimers": "maybe"}}, "agentHost.disableTimers must be true or false"),
                          ({"agentHost": {"removeCoordinatorHook": 2}}, "agentHost.removeCoordinatorHook must be true or false"),
                          ({"agentHost": {"timers": True}}, "agentHost.timers is not a setting"),
                          ({"agentHost": {"podTunnelKey": 'ssh-ed25519 AAAA" ; rm -rf x'}}, "agentHost.podTunnelKey must be one ssh-ed25519"),
                          ({"agentHost": {"podTunnelKey": "ssh-rsa AAAAB3Nza pod"}}, "agentHost.podTunnelKey must be one ssh-ed25519"),
                          ({"agentHost": "on"}, "agentHost must be a map")):
            r = chezmoi("personal", "managed", data=data)
            self.assertNotEqual(r.returncode, 0, data)
            self.assertIn(msg, r.stderr, data)

    def test_either_switch_on_the_work_profile_fails_the_render(self):
        for key, value in (("disableTimers", True), ("removeCoordinatorHook", True), ("podTunnelKey", POD)):
            r = chezmoi("axon-work-computer", "managed", data={"agentHost": {key: value}})
            self.assertNotEqual(r.returncode, 0, key)
            self.assertIn("personal profile only", r.stderr, key)
            r = template("axon-work-computer", (REPO / "private_dot_ssh/modify_authorized_keys.tmpl").read_text(), {"agentHost": {key: value}})
            self.assertNotEqual(r.returncode, 0, key)

    def test_work_profile_with_the_switches_false_renders_as_before(self):
        self.assertEqual(managed("axon-work-computer", {"agentHost": {"disableTimers": False, "removeCoordinatorHook": False}}), self.got["work"])


POD = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPodPodPodPodPodPodPodPodPodPodPodPodPodPod agent-host-pod"
POD_LINE = 'restrict,port-forwarding,permitopen="127.0.0.1:3773" ' + POD
DOTFILES_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIe/9P7N9fERnMuJZoaiKQToUkAie/ktc6xz1QoNp5uH cartwmic@chezmoi"
LANEF = 'restrict,port-forwarding,permitopen="127.0.0.1:3773" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILaneFLaneFLaneFLaneFLaneFLaneFLaneFLaneFLane lanef-temp'
FOREIGN = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIForeignForeignForeignForeignForeignForeign someone@else"


class PodTunnelKeyTest(unittest.TestCase):
    """private_dot_ssh/modify_authorized_keys.tmpl with agentHost.podTunnelKey: the pod's line, restricted to the tunnel to omarchy's T3."""

    @classmethod
    def setUpClass(cls):
        text = (REPO / "private_dot_ssh/modify_authorized_keys.tmpl").read_text()
        cls.tmp = Path(tempfile.mkdtemp())
        with ThreadPoolExecutor() as pool:
            jobs = {"off": pool.submit(template, "personal", text), "on": pool.submit(template, "personal", text, {"agentHost": {"podTunnelKey": POD}}),
                    "termux": pool.submit(template, "termux", text)}
            for name, job in jobs.items():
                r = job.result()
                assert r.returncode == 0, r.stderr
                (cls.tmp / name).write_text(r.stdout)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp)

    def run_modify(self, name, existing):
        r = subprocess.run(["sh", str(self.tmp / name)], input=existing, capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return r.stdout

    def test_without_the_key_only_the_dotfiles_key_is_added_as_before(self):
        self.assertEqual(self.run_modify("off", ""), DOTFILES_KEY + "\n")
        self.assertEqual(self.run_modify("termux", FOREIGN + "\n"), FOREIGN + "\n" + DOTFILES_KEY + "\n")

    def test_with_the_key_the_pod_line_is_restricted_and_follows_the_dotfiles_key(self):
        out = self.run_modify("on", FOREIGN + "\n")
        self.assertEqual(out.splitlines(), [FOREIGN, DOTFILES_KEY, POD_LINE])
        self.assertTrue(POD_LINE.startswith('restrict,port-forwarding,permitopen="127.0.0.1:3773" '))

    def test_idempotent_and_a_missing_final_newline_is_handled(self):
        once = self.run_modify("on", FOREIGN)
        self.assertEqual(once.splitlines(), [FOREIGN, DOTFILES_KEY, POD_LINE])
        self.assertEqual(self.run_modify("on", once), once)
        no_nl = DOTFILES_KEY  # our key already there and no trailing newline: the pod line must not join it
        self.assertEqual(self.run_modify("on", no_nl).splitlines(), [DOTFILES_KEY, POD_LINE])

    def test_a_temporary_line_for_another_key_is_left_alone(self):
        existing = FOREIGN + "\n" + LANEF + "\n"
        out = self.run_modify("on", existing)
        self.assertTrue(out.startswith(existing))
        self.assertEqual(out.splitlines()[-1], POD_LINE)
        self.assertIn(LANEF, out.splitlines())

    def test_the_same_key_with_other_options_does_not_hide_the_pod_line(self):
        loose = "ssh-ed25519 " + POD.split()[1] + " loose\n"
        out = self.run_modify("on", loose)
        self.assertIn(POD_LINE, out.splitlines())
        self.assertIn(loose.strip(), out.splitlines())


if __name__ == "__main__":
    unittest.main()
