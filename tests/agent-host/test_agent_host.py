"""agentHost.disableTimers and agentHost.removeCoordinatorHook: omarchy's two cutover switches (.chezmoitemplates/agent_host_config).

Real chezmoi against this source with a throwaway HOME and config; nothing is applied and no script runs (managed, execute-template only).
The Claude settings side of removeCoordinatorHook is in tests/t3-hook. Linux only: the timers are Linux units.
Run: python3 -m unittest discover -s tests/agent-host
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
UNITS = {".config/systemd/user/%s.%s" % (n, k) for n in ("session-cost", "agent-events") for k in ("service", "timer")}
LOADERS = {"77": "run_onchange_after_77_agent_events_systemd.sh.tmpl", "86": "run_onchange_after_86_session_cost_systemd.sh.tmpl"}
TIMERS = {"77": "agent-events", "86": "session-cost"}
MISTAKES = {".local/bin/mistakes-report", ".local/share/mistakes-report/README.md", ".local/share/mistakes-report/classes.json", ".local/share/mistakes-report/mistakes_report.py"}   # no timer; the Retro keeper runs it


def chezmoi(profile, verb, *args, data=None, stdin=None):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": dict(data or {}, profile=profile)}))
        return subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home),
                               verb, *args], input=stdin, capture_output=True, text=True, env=source_tree.chezmoi_env(home), timeout=120)


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

    def test_default_installs_the_two_timers(self):
        self.assertLessEqual(UNITS, self.got["default"])
        self.assertEqual(self.got["default"], self.got["off"])  # explicit false is the same as no key

    def test_default_loaders_start_the_timers(self):
        for k, name in TIMERS.items():
            s = self.got["load_default_" + k]
            self.assertIn("systemctl --user enable %s.timer" % name, s)
            self.assertIn("systemctl --user restart %s.timer" % name, s)
            self.assertNotIn("disable --now", s)

    def test_switch_on_stops_and_removes_both_timers(self):
        self.assertEqual(UNITS & self.got["on"], set())
        for k, name in TIMERS.items():
            s = self.got["load_on_" + k]
            self.assertIn("disable --now %s.timer" % name, s)
            self.assertIn('rm -f "$dir/%s.service" "$dir/%s.timer"' % (name, name), s)
            self.assertNotIn("restart %s.timer" % name, s)

    def test_switch_on_wins_over_the_two_own_enabled_settings(self):
        self.assertEqual(UNITS & self.got["forced"], set())

    def test_switch_on_drops_only_the_two_timers_their_commands_code_and_loaders(self):
        related = ("session-cost", "token-efficiency", "agent-events", "77_agent_events", "86_session_cost")
        dropped = self.got["default"] - self.got["on"]
        self.assertLessEqual(UNITS, dropped)
        self.assertEqual({p for p in dropped if not any(w in p for w in related)}, set())
        self.assertEqual(self.got["on"] - self.got["default"], set())

    def test_hook_switch_alone_changes_no_timer_and_no_managed_path(self):
        self.assertEqual(self.got["hook_only"], self.got["default"])
        for k in LOADERS:
            self.assertEqual(self.got["load_hookonly_" + k], self.got["load_default_" + k])

    def test_switch_on_leaves_the_mistakes_report_command_managed(self):
        self.assertLessEqual(MISTAKES, self.got["default"])
        self.assertLessEqual(MISTAKES, self.got["on"])

    def test_work_profile_manages_none_of_the_units(self):
        self.assertEqual(UNITS & self.got["work"], set())

    def test_config_defaults_and_values(self):
        self.assertEqual(self.got["cfg_default"], {"removeCoordinatorHook": False, "disableTimers": False, "sessionCopy": False, "podTunnelKey": ""})
        self.assertEqual(self.got["cfg_on"], {"removeCoordinatorHook": True, "disableTimers": True, "sessionCopy": False, "podTunnelKey": ""})

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
        for key, value in (("disableTimers", True), ("removeCoordinatorHook", True), ("sessionCopy", True), ("podTunnelKey", POD)):
            r = chezmoi("axon-work-computer", "managed", data={"agentHost": {key: value}})
            self.assertNotEqual(r.returncode, 0, key)
            self.assertIn("personal profile only", r.stderr, key)
            r = template("axon-work-computer", (REPO / "private_dot_ssh/modify_private_authorized_keys.tmpl").read_text(), {"agentHost": {key: value}})
            self.assertNotEqual(r.returncode, 0, key)

    def test_work_profile_with_the_switches_false_renders_as_before(self):
        self.assertEqual(managed("axon-work-computer", {"agentHost": {"disableTimers": False, "removeCoordinatorHook": False}}), self.got["work"])


POD = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPodPodPodPodPodPodPodPodPodPodPodPodPodPod agent-host-pod"
POD_LINE = 'restrict,port-forwarding,permitopen="127.0.0.1:3773" ' + POD
DOTFILES_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIe/9P7N9fERnMuJZoaiKQToUkAie/ktc6xz1QoNp5uH cartwmic@chezmoi"
LANEF = 'restrict,port-forwarding,permitopen="127.0.0.1:3773" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILaneFLaneFLaneFLaneFLaneFLaneFLaneFLaneFLane lanef-temp'
FOREIGN = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIForeignForeignForeignForeignForeignForeign someone@else"


class PodTunnelKeyTest(unittest.TestCase):
    """private_dot_ssh/modify_private_authorized_keys.tmpl with agentHost.podTunnelKey: the pod's line, restricted to the tunnel to omarchy's T3."""

    @classmethod
    def setUpClass(cls):
        text = (REPO / "private_dot_ssh/modify_private_authorized_keys.tmpl").read_text()
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


COPY_FILES = {".config/systemd/user/agent-session-copy.service", ".config/systemd/user/agent-session-copy.timer",
              ".local/bin/agent-session-copy", "89_agent_session_copy_systemd.sh"}


@unittest.skipUnless(sys.platform.startswith("linux"), "the timer is a Linux unit")
class SessionCopyGateTest(unittest.TestCase):
    """agent-session-copy: personal Linux only, shipped disabled, enabled by agentHost.sessionCopy."""

    @classmethod
    def setUpClass(cls):
        text = (REPO / "run_onchange_after_89_agent_session_copy_systemd.sh.tmpl").read_text()
        with ThreadPoolExecutor() as pool:
            jobs = dict(personal=pool.submit(managed, "personal"), work=pool.submit(managed, "axon-work-computer"),
                        off=pool.submit(template, "personal", text), on=pool.submit(template, "personal", text, {"agentHost": {"sessionCopy": True}}))
            cls.got = {k: v.result() for k, v in jobs.items()}

    def test_personal_linux_gets_the_timer_service_command_and_loader_and_work_gets_none(self):
        self.assertLessEqual(COPY_FILES, self.got["personal"])
        self.assertEqual(COPY_FILES & self.got["work"], set())

    def test_the_timer_runs_every_30_minutes_in_the_form_the_check_reads(self):
        timer = (REPO / "dot_config/systemd/user/agent-session-copy.timer").read_text().splitlines()
        self.assertIn("OnUnitActiveSec=30min", timer)
        self.assertIn("ExecStart=%h/.local/bin/agent-session-copy", (REPO / "dot_config/systemd/user/agent-session-copy.service").read_text())

    def test_shipped_disabled_the_loader_stops_the_timer_and_keeps_the_units(self):
        s = self.got["off"].stdout
        self.assertEqual(self.got["off"].returncode, 0, self.got["off"].stderr)
        self.assertIn("disable --now agent-session-copy.timer", s)
        self.assertNotIn("enable agent-session-copy.timer", s.replace("disable --now", ""))
        self.assertNotIn("rm -f", s)

    def test_switch_on_enables_and_starts_the_timer(self):
        s = self.got["on"].stdout
        self.assertEqual(self.got["on"].returncode, 0, self.got["on"].stderr)
        self.assertIn("systemctl --user enable agent-session-copy.timer", s)
        self.assertIn("systemctl --user restart agent-session-copy.timer", s)
        self.assertNotIn("disable --now", s)


STUB = """#!/bin/sh
# Stands in for scripts/agent-host/kubectl.sh: runs the command after "--" here, as the pod would.
[ -n "${STUB_FAIL:-}" ] && { echo "stub: pod unreachable" >&2; exit 1; }
while [ "$1" != "--" ]; do shift; done
shift
exec "$@"
"""


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("rsync") and shutil.which("flock"), "rsync and flock needed")
class SessionCopyScriptTest(unittest.TestCase):
    """The copy command end to end with a stub kubectl that runs the pod's side in a temp directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "kubectl.sh").write_text(STUB)
        for d in ("claude/-home-x", "pi/--x--", "codex/2026/11/15", "codex-archived", "dest"):
            (self.tmp / d).mkdir(parents=True)
        self.c = self.tmp / "claude/-home-x/s1.jsonl"
        self.c.write_text('{"a":1}\n')
        (self.tmp / "claude/-home-x/notes.txt").write_text("not a transcript")
        (self.tmp / "pi/--x--/p1.jsonl").write_text('{"p":1}\n')
        self.x = self.tmp / "codex/2026/11/15/rollout-1.jsonl"
        self.x.write_text('{"x":1}\n')
        (self.tmp / "codex/2026/11/15/history.txt").write_text("not a transcript")
        (self.tmp / "codex/2026/11/15/rollout-old.jsonl.zst").write_bytes(b"\x28\xb5\x2f\xfd zst")
        self.a = self.tmp / "codex-archived/rollout-2.jsonl"
        self.a.write_text('{"arch":1}\n')
        (self.tmp / "codex-archived/rollout-3.jsonl.zst").write_bytes(b"\x28\xb5\x2f\xfd zst2")
        (self.tmp / "codex-archived/notes.txt").write_text("not a transcript")

    def run_copy(self, *args, **env):
        e = dict(os.environ, XDG_RUNTIME_DIR=str(self.tmp), AGENT_SESSION_COPY_KUBECTL=str(self.tmp / "kubectl.sh"),
                 AGENT_SESSION_COPY_DEST=str(self.tmp / "dest"), AGENT_SESSION_COPY_CLAUDE_SRC=str(self.tmp / "claude"),
                 AGENT_SESSION_COPY_PI_SRC=str(self.tmp / "pi"),
                 AGENT_SESSION_COPY_CODEX_SRC=str(self.tmp / "codex"),
                 AGENT_SESSION_COPY_CODEX_ARCHIVED_SRC=str(self.tmp / "codex-archived"), **env)
        return subprocess.run(["sh", str(REPO / "dot_local/bin/executable_agent-session-copy"), *args], capture_output=True, text=True, env=e, timeout=60)

    def test_copies_jsonl_with_the_same_bytes_and_only_what_changed_afterwards(self):
        r = self.run_copy()
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertIn("claude: 1 file(s) sent", r.stdout)
        self.assertIn("pi: 1 file(s) sent", r.stdout)
        got = self.tmp / "dest/claude/-home-x/s1.jsonl"
        self.assertEqual(got.read_bytes(), self.c.read_bytes())
        self.assertFalse((self.tmp / "dest/claude/-home-x/notes.txt").exists())
        again = self.run_copy().stdout
        self.assertIn("claude: 0 file(s) sent", again)
        self.assertIn("pi: 0 file(s) sent", again)
        self.c.write_text('{"a":1}\n{"a":2}\n')
        third = self.run_copy().stdout
        self.assertIn("claude: 1 file(s) sent", third)
        self.assertIn("pi: 0 file(s) sent", third)
        self.assertEqual(got.read_bytes(), self.c.read_bytes())

    def test_codex_sessions_keep_their_year_month_day_tree_and_only_jsonl_moves(self):
        r = self.run_copy()
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertIn("codex: 2 file(s) sent", r.stdout)
        got = self.tmp / "dest/codex/2026/11/15/rollout-1.jsonl"
        self.assertEqual(got.read_bytes(), self.x.read_bytes())
        self.assertFalse((self.tmp / "dest/codex/2026/11/15/history.txt").exists())
        self.assertEqual((self.tmp / "dest/codex/2026/11/15/rollout-old.jsonl.zst").read_bytes(), b"\x28\xb5\x2f\xfd zst")
        self.assertIn("codex: 0 file(s) sent", self.run_copy().stdout)
        self.x.unlink()
        self.run_copy()
        self.assertTrue(got.exists())  # removed here, kept in the pod

    def test_archived_codex_sessions_are_copied_flat_with_jsonl_and_zst_only(self):
        r = self.run_copy()
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertIn("codex-archived: 2 file(s) sent", r.stdout)
        self.assertEqual((self.tmp / "dest/codex-archived/rollout-2.jsonl").read_bytes(), self.a.read_bytes())
        self.assertEqual((self.tmp / "dest/codex-archived/rollout-3.jsonl.zst").read_bytes(), b"\x28\xb5\x2f\xfd zst2")
        self.assertFalse((self.tmp / "dest/codex-archived/notes.txt").exists())
        self.assertIn("codex-archived: 0 file(s) sent", self.run_copy().stdout)
        self.a.unlink()
        self.run_copy()
        self.assertTrue((self.tmp / "dest/codex-archived/rollout-2.jsonl").exists())  # removed here, kept in the pod

    def test_claude_and_pi_still_send_jsonl_only(self):
        (self.tmp / "claude/-home-x/old.jsonl.zst").write_bytes(b"z")
        (self.tmp / "pi/--x--/old.jsonl.zst").write_bytes(b"z")
        self.run_copy()
        self.assertFalse((self.tmp / "dest/claude/-home-x/old.jsonl.zst").exists())
        self.assertFalse((self.tmp / "dest/pi/--x--/old.jsonl.zst").exists())

    def test_dry_run_sends_nothing_and_nothing_is_ever_deleted_in_the_pod(self):
        r = self.run_copy("--dry-run")
        self.assertIn("would be sent", r.stdout)
        self.assertFalse((self.tmp / "dest/claude/-home-x/s1.jsonl").exists())
        self.run_copy()
        self.c.unlink()
        self.run_copy()
        self.assertTrue((self.tmp / "dest/claude/-home-x/s1.jsonl").exists())  # removed here, kept there

    def test_an_unreachable_pod_exits_69_with_the_reason(self):
        r = self.run_copy(STUB_FAIL="1")
        self.assertEqual(r.returncode, 69)
        self.assertIn("cannot reach", r.stdout + r.stderr)

    def test_a_missing_source_is_skipped(self):
        shutil.rmtree(self.tmp / "pi")
        r = self.run_copy()
        self.assertEqual(r.returncode, 0)
        self.assertIn("pi:", r.stdout)
        self.assertIn("does not exist here; skipped", r.stdout)


if __name__ == "__main__":
    unittest.main()
