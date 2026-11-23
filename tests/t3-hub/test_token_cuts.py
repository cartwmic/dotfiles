"""Agent token-efficiency settings in the seat files and the T3 seat instances, rendered with the real chezmoi into a throwaway HOME.

- The builder seat's advisor runs on Opus 5.5 (`advisorModel` in seat-builder.json); no other seat file sets one.
- Helpers (sub-agents started with the Agent tool) default to Haiku 5.5 on the lead, builder and planner instances (CLAUDE_CODE_SUBAGENT_MODEL), and on no other.
- The scout seat: a read-only Haiku 5.5 instance with an empty MCP file.

    python3 -m unittest discover -s tests/t3-hub -p test_token_cuts.py -v
"""
import json
import unittest
from pathlib import Path

import test_t3_hub as base  # a module import, so the suite's own test classes are not collected a second time here
from test_t3_hub import (FIXTURE, FIZZY, HELPER_MODEL, HELPER_SEATS, KEEP, REPO, SCOUT_DENY, SEATS, UNUSED_TOOLS, WORKER_ENV, fleet_env, run_script)

PROFILES = ("personal", "axon-work-computer")


def instances():
    """The provider instances the settings script writes on personal Linux, and the home they were rendered for."""
    script, home = base.LinuxSettingsTest().render()
    return json.loads(run_script(script, FIXTURE))["providerInstances"], home


class BuilderAdvisorModelTest(unittest.TestCase):
    def test_only_the_builder_seat_file_sets_the_advisor_model_and_it_is_opus(self):
        for profile in PROFILES:
            env = fleet_env(profile)
            try:
                for seat in KEEP:
                    f = json.loads(env.render("dot_claude/fleet/seat-%s.json.tmpl" % seat))
                    self.assertEqual(f.get("advisorModel"), "claude-opus-5-5" if seat == "builder" else None, (profile, seat))
            finally:
                env.close()

    def test_the_builder_instance_keeps_its_advisor_switched_on_and_the_global_advisor_is_unchanged(self):
        inst, _ = instances()
        self.assertNotIn("CLAUDE_CODE_DISABLE_ADVISOR_TOOL", [e["name"] for e in inst["seat-builder"]["environment"]])
        self.assertIn('.advisorModel = "claude-fable-5-2"', (REPO / "dot_claude/modify_settings.json.tmpl").read_text())


class HelperModelTest(unittest.TestCase):
    def test_lead_builder_and_planner_default_their_helpers_to_haiku_and_no_other_instance_does(self):
        inst, _ = instances()
        for name, i in inst.items():
            has = HELPER_MODEL in i.get("environment", [])
            self.assertEqual(has, name in HELPER_SEATS, name)
        for name in ("seat-reviewer", "seat-computer", "seat-scout"):
            self.assertNotIn("CLAUDE_CODE_SUBAGENT_MODEL", [e["name"] for e in inst[name]["environment"]], name)

    def test_the_variable_is_a_plain_environment_entry_after_the_others(self):
        inst, _ = instances()
        for name in HELPER_SEATS:
            self.assertEqual(inst[name]["environment"][-1], HELPER_MODEL, name)
            self.assertIn(FIZZY, inst[name]["environment"], name)


class ScoutSeatTest(unittest.TestCase):
    def test_the_instance_has_no_advisor_the_worker_instructions_and_an_empty_mcp_file(self):
        inst, home = instances()
        self.assertIn("seat-scout", inst)
        i = inst["seat-scout"]
        self.assertEqual((i["driver"], i["displayName"], i["enabled"]), ("claudeAgent", "Claude (scout)", True))
        self.assertEqual(i["config"]["autoCompactWindow"], "200000")
        self.assertEqual(i["config"]["launchArgs"], "--settings %s/.claude/fleet/seat-scout.json --add-dir %s/.claude/fleet/worker --strict-mcp-config --mcp-config %s/.claude/fleet/mcp-scout.json" % (home, home, home))
        self.assertEqual(i["environment"], [{"name": "CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "sensitive": False, "value": "1"}, FIZZY, WORKER_ENV])

    def test_the_scout_comes_after_the_reviewer_and_before_the_computer_seat(self):
        inst, _ = instances()
        names = [k for k in inst if k.startswith("seat-")]
        self.assertEqual(names[:6], list(SEATS))
        self.assertLess(names.index("seat-reviewer"), names.index("seat-scout"))
        self.assertLess(names.index("seat-scout"), names.index("seat-computer"))

    def test_the_seat_file_is_read_only_runs_haiku_at_xhigh_and_keeps_no_skill(self):
        for profile in PROFILES:
            env = fleet_env(profile)
            try:
                f = json.loads(env.render("dot_claude/fleet/seat-scout.json.tmpl"))
                self.assertEqual(f["model"], "claude-haiku-5-5", profile)
                self.assertEqual(f["modelSettings"], {"claude-haiku-5-5": {"effortLevel": "xhigh"}}, profile)
                deny = f["permissions"]["deny"]
                self.assertEqual(deny, ["Artifact"] + sorted(UNUSED_TOOLS) + SCOUT_DENY, profile)
                for tool in ("Edit", "Write", "NotebookEdit", "mcp__t3-code"):
                    self.assertIn(tool, deny, profile)
                self.assertNotIn("Bash", deny, "a scout searches through Bash")
                self.assertEqual(set(f["skillOverrides"].values()), {"off"}, profile)
                self.assertEqual(f["claudeMdExcludes"], ["%s/.claude/CLAUDE.md" % env.home], profile)
                self.assertNotIn("hooks", f, profile)
                self.assertNotIn("advisorModel", f, profile)
            finally:
                env.close()

    def test_the_mcp_file_holds_no_server(self):
        env = fleet_env("personal")
        try:
            self.assertEqual(json.loads(env.render("dot_claude/fleet/mcp-scout.json.tmpl")), {"mcpServers": {}})
        finally:
            env.close()

    def test_the_scout_seat_file_and_mcp_file_are_managed_on_both_profiles(self):
        for profile in PROFILES:
            env = fleet_env(profile)
            try:
                managed = set(env.chezmoi("managed", "--include=files").split())
                self.assertTrue({".claude/fleet/seat-scout.json", ".claude/fleet/mcp-scout.json"} <= managed, profile)
            finally:
                env.close()


if __name__ == "__main__":
    unittest.main()
