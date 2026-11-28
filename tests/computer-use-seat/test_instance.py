"""The Computer use seat's T3 instance (`seat-computer`), its seat file and its MCP file. The instance exists only on the personal profile, outside container mode; the seat and MCP files render on both profiles.

The real chezmoi renders the real source into a throwaway HOME. A missing chezmoi fails the test (it does not skip).

    python3 -m unittest discover -s tests/computer-use-seat -p test_instance.py -v
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
SETTINGS = REPO / "dot_t3/private_userdata/modify_settings.json.tmpl"
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}
FIZZY = {"name": "CLAUDE_CODE_FIZZY_GROVE", "sensitive": False, "value": "1"}
WORKER_ENV = {"name": "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "sensitive": False, "value": "1"}
ADVISOR_OFF = {"name": "CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "sensitive": False, "value": "1"}
KEEP = {"using-computer", "using-browse"}


class Home:
    """A throwaway HOME and a chezmoi config for one profile, optionally in container mode."""

    def __init__(self, profile="personal", container=False, skills=("using-computer", "using-browse", "no-ai-slop", "hill-climb", "omarchy")):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.cfg = Path(self._tmp.name) / "chezmoi.yaml"
        text = "data:\n  profile: %s\n  hub:\n    enabled: false\n" % profile
        if profile != "personal":
            text += "".join("  %s: %s\n" % kv for kv in WORK_DATA.items())
        if container:
            text += "  container:\n    enabled: true\n"
        self.cfg.write_text(text)
        for name in skills:
            (self.home / ".claude/skills" / name).mkdir(parents=True)
            (self.home / ".claude/skills" / name / "SKILL.md").write_text("---\nname: %s\n---\n" % name)

    def chezmoi(self, *args, stdin=None):
        r = subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(self.cfg), "--config-format", "yaml", "--destination", str(self.home), *args],
                           input=stdin, capture_output=True, text=True, timeout=120, env=source_tree.chezmoi_env(self.home))
        if r.returncode:
            raise AssertionError("chezmoi %s failed: %s" % (" ".join(args), r.stderr))
        return r.stdout

    def render(self, source, os_name=None):
        extra = ["--override-data", json.dumps({"chezmoi": {"os": os_name}})] if os_name else []
        return self.chezmoi("execute-template", *extra, stdin=(REPO / source).read_text())

    def settings(self, os_name):
        """(WANT, OWNED) as the rendered modify script holds them."""
        script = self.render("dot_t3/private_userdata/modify_settings.json.tmpl", os_name)
        want = re.search(r"^WANT='(.*)'$", script, re.M).group(1)
        owned = re.search(r"^OWNED='(.*)'$", script, re.M).group(1)
        return json.loads(want), json.loads(owned)

    def close(self):
        self._tmp.cleanup()


class SeatComputerInstanceTest(unittest.TestCase):
    def test_chezmoi_is_installed(self):
        self.assertIsNotNone(shutil.which("chezmoi"), "chezmoi is needed to render the source")

    def test_personal_linux_and_mac_write_the_instance_exactly(self):
        for os_name in ("linux", "darwin"):
            h = Home()
            try:
                want, owned = h.settings(os_name)
                fleet = "%s/.claude/fleet" % h.home
                self.assertEqual(want["seat-computer"], {
                    "config": {"autoCompactWindow": "200000",
                               "launchArgs": "--settings %s/seat-computer.json --add-dir %s/worker --strict-mcp-config --mcp-config %s/mcp-computer.json" % (fleet, fleet, fleet)},
                    "displayName": "Claude (computer)", "driver": "claudeAgent", "enabled": True,
                    "environment": [ADVISOR_OFF, FIZZY, WORKER_ENV]}, os_name)
                self.assertIn("seat-computer", owned, os_name)
                # the other four seats are unchanged: still on mcp.json
                for seat in ("lead", "builder", "planner", "reviewer"):
                    self.assertTrue(want["seat-" + seat]["config"]["launchArgs"].endswith("--mcp-config %s/mcp.json" % fleet), (os_name, seat))
            finally:
                h.close()

    def test_the_instance_sets_no_model_endpoint_so_it_routes_like_the_other_seats(self):
        h = Home()
        try:
            want, _ = h.settings("linux")
            names = {e["name"] for e in want["seat-computer"]["environment"]}
            self.assertFalse({n for n in names if n.startswith("ANTHROPIC_")}, names)
            # the planner also sets the helper model (CLAUDE_CODE_SUBAGENT_MODEL); the computer seat does not
            self.assertEqual({e["name"] for e in want["seat-planner"]["environment"]} - {"CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "CLAUDE_CODE_SUBAGENT_MODEL"}, names - {"CLAUDE_CODE_DISABLE_ADVISOR_TOOL"})
            self.assertEqual(want["seat-computer"]["driver"], want["seat-planner"]["driver"])
        finally:
            h.close()

    def test_container_mode_has_no_such_instance(self):
        h = Home(container=True)
        try:
            want, owned = h.settings("linux")
            self.assertNotIn("seat-computer", want)
            self.assertNotIn("seat-computer", owned)
            self.assertEqual({k for k in want if k.startswith("seat-")}, {"seat-lead", "seat-builder", "seat-planner", "seat-reviewer", "seat-scout", "seat-homelab-chat"})
        finally:
            h.close()

    def test_the_work_profile_gets_only_the_restricted_t3_settings_file_and_no_instance(self):
        h = Home(profile="axon-work-computer")
        try:
            managed = set(h.chezmoi("managed").split())
            # the restricted work mode (docs/profiles.md): the settings file only, no other .t3 file
            self.assertEqual({p for p in managed if p.startswith(".t3")}, {".t3", ".t3/userdata", ".t3/userdata/settings.json"})
            # the work mode creates no provider instance at all, so the gate keeps seat-computer out of the code that runs
            script = h.render("dot_t3/private_userdata/modify_settings.json.tmpl", "darwin")
            self.assertNotIn("seat-computer", script[script.index("\nset -eu\n") + 1:], "seat-computer reached the work mode's code")
        finally:
            h.close()


class SeatComputerFilesTest(unittest.TestCase):
    def test_mcp_file_has_browse_on_both_profiles(self):
        for profile, os_name, browser in (("personal", "linux", "browse"), ("personal", "darwin", "browse"), ("axon-work-computer", "darwin", "browse")):
            h = Home(profile=profile)
            try:
                servers = json.loads(h.render("dot_claude/fleet/mcp-computer.json.tmpl", os_name))["mcpServers"]
                self.assertEqual(set(servers), {"hindsight", "shartifacts", browser}, (profile, os_name))
                shared = json.loads(h.render("dot_claude/fleet/mcp.json.tmpl", os_name))["mcpServers"]
                self.assertEqual(set(shared), {"hindsight", "shartifacts"}, "the shared MCP file stays as it was")
                for name in ("hindsight", "shartifacts"):
                    self.assertEqual(servers[name], shared[name])
            finally:
                h.close()

    def test_mcp_file_has_no_browser_tool_in_container_mode(self):
        h = Home(container=True)
        try:
            self.assertEqual(set(json.loads(h.render("dot_claude/fleet/mcp-computer.json.tmpl", "linux"))["mcpServers"]), {"hindsight", "shartifacts"})
        finally:
            h.close()

    def test_seat_file_keeps_the_two_skills_and_turns_every_other_off(self):
        for profile in ("personal", "axon-work-computer"):
            h = Home(profile=profile)
            try:
                f = json.loads(h.render("dot_claude/fleet/seat-computer.json.tmpl"))
                off = f["skillOverrides"]
                self.assertEqual(set(off.values()), {"off"}, profile)
                self.assertFalse(KEEP & set(off), profile)
                self.assertTrue({"no-ai-slop", "hill-climb", "omarchy"} <= set(off), profile)
                self.assertEqual(f["permissions"], {"deny": ["Artifact", "ListAgents", "ReportFindings", "ScheduleWakeup", "Workflow"]}, profile)
                self.assertEqual(f["claudeMdExcludes"], ["%s/.claude/CLAUDE.md" % h.home], profile)
                hooks = f["hooks"]["SessionStart"]
                self.assertEqual(len(hooks), 1, profile)
                cmd = hooks[0]["hooks"][0]["command"]
                self.assertIn("%s/.local/share/agent-harness/canonical/skills/using-computer/SKILL.md" % h.home, cmd, profile)
                self.assertEqual(set(f["hooks"]), {"SessionStart"}, profile)
            finally:
                h.close()

    def test_both_files_deploy_on_both_profiles(self):
        for profile in ("personal", "axon-work-computer"):
            h = Home(profile=profile)
            try:
                managed = set(h.chezmoi("managed", "--include=files").split())
                self.assertTrue({".claude/fleet/seat-computer.json", ".claude/fleet/mcp-computer.json"} <= managed, profile)
            finally:
                h.close()


if __name__ == "__main__":
    unittest.main()
