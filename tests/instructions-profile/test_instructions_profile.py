"""Render the three harness instruction templates for each profile with the real chezmoi.

The subagents, ownership and escalation paragraphs are in every render, ownership directly before escalation. profile-work.md is included only for axon-work-computer and
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
SEAT_ROWS = {
    "personal": (
        "| Coordinator | Opus 5.5 medium |",
        "| Lead | Opus 5.5 medium |",
        "| Planner | Sonnet 5.5 high |",
        "| Reviewer | Opus 5.5 medium |",
        "| Builder | Haiku 5.5 xhigh for small mechanical builds; Sonnet 5.5 high for anything long or ambiguous, and on any failure |",
        "| Computer use | Sonnet 5.5 high |",
    ),
    "axon-work-computer": (
        "| Coordinator | Opus 5.5 medium, Claude Code (claude-opus-5-5) |",
        "| Lead | Opus 5.5 medium, Claude Code (claude-opus-5-5) |",
        "| Planner | GLM 5.3 Flash H200, Pi (work-glm/test-model) |",
        "| Reviewer | Opus 5.5 medium, Claude Code (claude-opus-5-5) |",
        "| Builder | GLM 5.3 Flash H200, Pi (work-glm/test-model) |",
        "| Computer use | Sonnet 5.5 high, Pi (anthropic/claude-sonnet-5-5) |",
    ),
}
CLI_PROXY_LINE = "- Computer use runs through my cli proxy, like the other seats."
WORK_SEAT_BULLETS = (
    "- Coordinator, leads and reviewers use Claude Code (Anthropic, `claude-opus-5-5`, `medium` effort); "
    "T3 provider claudeAgent. Planners and builders use Pi (`work-glm/test-model`). Computer use runs on Pi with "
    "`--provider anthropic --model claude-sonnet-5-5` at high thinking.",
)
SUBAGENTS = (
    "Subagents. Prefer to use subagents. In a session I open myself that is not a seat, confirm with me at the start "
    "when you will use subagents and which models they will use; if that is not clear, ask again, and do not guess. "
    "In a seat session (coordinator, lead, planner, builder or reviewer: its brief's first line names the seat), do "
    "not ask me which subagents or models to use: the seat table decides, and the brief says the rest."
)
ESCALATION = (
    "Decisions and escalation. Decide anything that doesn't materially matter yourself, and don't ask about it: "
    "library choices, naming, style, reversible implementation details. Escalate only what materially matters: "
    "one-way doors, security or privacy, buying things (hardware, subscriptions, paid services), deleting data, "
    "behaviour other people will see, and taste or product calls only I can make. Never ask me about spend on agent "
    "work: report it. Escalate up the chain, not around it: a worker goes to its lead, a lead to the coordinator, the "
    "coordinator to me. Each level settles what it can before passing anything up. If running something could answer "
    "the question, run it instead. When you do ask: one question at a time, with your recommendation. The "
    "coordinator, and any session I open myself, ask me directly with your harness's question tool. A lead, planner, "
    "builder or reviewer session does not ask me directly: a worker goes to its lead, and a lead records the decision "
    "with `ledger open` and stops, so the coordinator asks me. No is an acceptable answer."
)
OLD_LINES = (
    "At the start of a session, confirm with the user when you will use subagents",
    "using your harness's question tool. No is an acceptable answer.",
    "security or privacy, spending, deleting data",
)
OWNERSHIP = (
    "Ownership. A codebase you work in is yours: what it's for and how it's built are your call, and you'll keep "
    "building on it. Merge duplicate code and fix bugs you find nearby. The escalation rules below still hold."
)
SCHEDULE_HEADING = "## Scheduled work"
SCHEDULE_RULE = (
    "A schedule is agent work if a run starts or messages a model. Agent work on a clock is a kit job in the "
    "coordinator (`coordinator jobs`), and I approve it first unless it is a one-off less than 24 hours out."
)
BAR_HEADING = "## The bar"
BAR_QUESTION = (
    "What is the bar for <repo>? Personal (my own project, good enough) or shared "
    "(work I share and want to be proud of)?"
)
BAR_TABLE_HEADING = "## Bar table"
BAR_ROWS = {
    "personal": (
        "| `github.com/StoryCraftTW/storycraft` | shared |",
        "| `github.com/cartwmic/*`, `gitea.internal.cartwmic.com/cartwmic/*` | personal |",
    ),
    "axon-work-computer": ("| `git.example.test/*`, `github.com/axon-*` | shared |",),
}


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
        self.assertIn(OWNERSHIP, (INSTR / "AGENTS.md").read_text())
        self.assertIn(SUBAGENTS, (INSTR / "AGENTS.md").read_text())

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
                    self.assertEqual(text.count(OWNERSHIP), 1)
                    self.assertEqual(text.count(SUBAGENTS), 1)
                    for old in OLD_LINES:
                        self.assertNotIn(old, text)
                    self.assertIn(OWNERSHIP + "\n\n" + ESCALATION, text)
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


    def test_personal_seat_table_has_the_computer_use_row(self):
        for name, template in TEMPLATES.items():
            with self.subTest(harness=name):
                text = render(template, "personal")
                self.assertEqual(text.count(SEAT_HEADING), 1)
                for row in SEAT_ROWS["personal"]:
                    self.assertEqual(text.count(row), 1)
                self.assertNotIn("| Browser work |", text)
                self.assertNotIn("Terra", text)
                self.assertEqual(text.count(CLI_PROXY_LINE), 1)

    def test_work_seat_table_has_the_computer_use_row(self):
        for name, template in TEMPLATES.items():
            with self.subTest(harness=name):
                text = render(template, "axon-work-computer")
                self.assertEqual(text.count(SEAT_HEADING), 1)
                for row in SEAT_ROWS["axon-work-computer"]:
                    self.assertEqual(text.count(row), 1)
                self.assertNotIn("| Browser work |", text)
                self.assertNotIn("| Browser use |", text)
                self.assertNotIn("Cursor", text)
                self.assertNotIn(CLI_PROXY_LINE, text)
                self.assertNotIn("127.0.0.1:9333", text)   # the tool rule lives in the using-computer skill
                for bullet in WORK_SEAT_BULLETS:
                    self.assertEqual(text.count(bullet), 1)

    def test_termux_has_no_seat_table(self):
        for name, template in TEMPLATES.items():
            with self.subTest(harness=name):
                self.assertNotIn(SEAT_HEADING, render(template, "termux"))

    def test_scheduling_rule_is_personal_only(self):
        for name, template in TEMPLATES.items():
            for profile in ("personal", "axon-work-computer", "termux"):
                with self.subTest(harness=name, profile=profile):
                    text = render(template, profile)
                    self.assertEqual(text.count(SCHEDULE_HEADING), int(profile == "personal"))
                    self.assertEqual(text.count(SCHEDULE_RULE), int(profile == "personal"))
                    self.assertEqual("coordinator schedules check" in text, profile == "personal")

    def test_bar_rule_and_table_in_every_harness(self):
        for name, template in TEMPLATES.items():
            for profile in ("personal", "axon-work-computer"):
                with self.subTest(harness=name, profile=profile):
                    text = render(template, profile)
                    self.assertEqual(text.count(BAR_HEADING), 1)
                    self.assertEqual(text.count(BAR_QUESTION), 1)
                    self.assertEqual(text.count(BAR_TABLE_HEADING), 1)
                    self.assertLess(text.index(BAR_HEADING), text.index(BAR_TABLE_HEADING))
                    for row in BAR_ROWS[profile]:
                        self.assertEqual(text.count(row), 1)
                    other = "axon-work-computer" if profile == "personal" else "personal"
                    for row in BAR_ROWS[other]:
                        self.assertNotIn(row, text)

    def test_termux_has_the_rule_but_no_table(self):
        for name, template in TEMPLATES.items():
            with self.subTest(harness=name):
                text = render(template, "termux")
                self.assertEqual(text.count(BAR_HEADING), 1)
                self.assertNotIn(BAR_TABLE_HEADING, text)

    def test_no_render_carries_the_old_risk_tolerance_block(self):
        for name, template in TEMPLATES.items():
            for profile in ("personal", "axon-work-computer", "termux"):
                with self.subTest(harness=name, profile=profile):
                    self.assertNotIn("Risk tolerance is high", render(template, profile))


if __name__ == "__main__":
    unittest.main()
