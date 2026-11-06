"""Render the three harness instruction templates for each profile with the real chezmoi.

The escalation paragraph is in every render. profile-work.md is included only for axon-work-computer and
profile-personal.md only for personal; termux gets neither. Skipped when chezmoi is not installed.

    python3 -m unittest discover -s tests/instructions-profile -v
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTR = ROOT / "dot_local" / "share" / "agent-harness" / "canonical" / "instructions"
TEMPLATES = {
    "claude": ROOT / "dot_claude" / "CLAUDE.md.tmpl",
    "codex": ROOT / "dot_codex" / "modify_AGENTS.md.tmpl",
    "pi": ROOT / "dot_pi" / "private_agent" / "literal_AGENTS.md.tmpl",
}
WORK = "Never merge or deploy without my explicit approval for that change."
PERSONAL = "Merging and deploying approved work is yours to do: if checks pass and it keeps the product requirements, ship it and tell me after."
SEAT_HEADING = "## Agent seats and models"
SEAT_ROWS = (
    "| Coordinator | Opus 5.5 medium |",
    "| Lead | Sonnet 5.5 high |",
    "| Planner | Sonnet 5.5 high |",
    "| Reviewer | Opus 5.5 medium |",
    "| Builder | Haiku 5.5 xhigh; escalate to Sonnet 5.5 high on failure, or when the work is ambiguous |",
)
BROWSER = {
    "personal": "| Browser work | Terra 6.1 (cliproxy/gpt-6.1-terra) if available, else Sonnet 5.5 high |",
    "axon-work-computer": "| Browser work | Sonnet 5.5 high |",
}
ESCALATION = (
    "Decisions and escalation. Decide anything that doesn't materially matter yourself, and don't ask about it: "
    "library choices, naming, style, reversible implementation details. Escalate only what materially matters: "
    "one-way doors, security or privacy, spending, deleting data, behaviour other people will see, and taste or "
    "product calls only I can make. Escalate up the chain, not around it: a worker goes to its lead, a lead to the "
    "coordinator, the coordinator to me. Each level settles what it can before passing anything up. If running "
    "something could answer the question, run it instead. When you do ask: one question at a time, with your "
    "recommendation, using your harness's question tool. No is an acceptable answer."
)


# The local data keys the work profile requires (docs/profiles.md, "Local data keys"); placeholder values.
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}


def render(template, profile):
    with tempfile.TemporaryDirectory() as home:
        config = Path(home) / "chezmoi.yaml"
        config.write_text("{}\n")
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "execute-template", "--override-data", json.dumps({"profile": profile, **(WORK_DATA if profile == "axon-work-computer" else {})})],
            input=template.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120,
        )
    assert result.returncode == 0, result.stderr
    return result.stdout


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class InstructionProfileTests(unittest.TestCase):
    def test_fragments_hold_the_exact_rule(self):
        self.assertIn(WORK, (INSTR / "profile-work.md").read_text())
        self.assertIn(PERSONAL, (INSTR / "profile-personal.md").read_text())
        self.assertIn(ESCALATION, (INSTR / "AGENTS.md").read_text())

    def test_every_harness_and_profile(self):
        for name, template in TEMPLATES.items():
            for profile, want, not_want in (
                ("personal", PERSONAL, WORK),
                ("axon-work-computer", WORK, PERSONAL),
                ("termux", None, None),
            ):
                with self.subTest(harness=name, profile=profile):
                    text = render(template, profile)
                    self.assertEqual(text.count(ESCALATION), 1)
                    self.assertNotIn("Decisions and doors", text)
                    self.assertNotIn("Walk through two-way doors", text)
                    if want:
                        self.assertEqual(text.count(want), 1)
                        self.assertNotIn(not_want, text)
                    else:
                        self.assertNotIn(WORK, text)
                        self.assertNotIn(PERSONAL, text)
                    self.assertEqual(profile == "axon-work-computer", "## Work computer" in text)
                    self.assertEqual(profile == "personal", "## Personal computer" in text)


    def test_seat_table_once_per_harness_with_the_right_browser_row(self):
        for name, template in TEMPLATES.items():
            for profile in ("personal", "axon-work-computer", "termux"):
                with self.subTest(harness=name, profile=profile):
                    text = render(template, profile)
                    if profile == "termux":
                        self.assertNotIn(SEAT_HEADING, text)
                        continue
                    self.assertEqual(text.count(SEAT_HEADING), 1)
                    for row in SEAT_ROWS:
                        self.assertEqual(text.count(row), 1)
                    self.assertEqual(text.count("| Browser work |"), 1)
                    self.assertEqual(text.count(BROWSER[profile]), 1)
                    self.assertEqual(("Terra" in text), profile == "personal")


if __name__ == "__main__":
    unittest.main()
