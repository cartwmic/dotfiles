"""Render dot_pi/private_agent/literal_AGENTS.md.tmpl for both desktop profiles with the real chezmoi.

The doorbell rule (call notify_owner when you need the owner or have answered a question) is for the personal profile only; the
work profile must render without it. Skipped when chezmoi is not installed.

    python3 -m unittest discover -s tests/pi-agents-render -v
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "dot_pi" / "private_agent" / "literal_AGENTS.md.tmpl"
# Work-profile-only section, included right after the heading block.
PLAYBOOK_TEMPLATE = ROOT / "dot_local" / "share" / "agent-harness" / "canonical" / "instructions" / "axon-playbook.md.tmpl"

INSTR = ROOT / "dot_local" / "share" / "agent-harness" / "canonical" / "instructions"
# Profile rule fragments, each included for one profile right after the playbook position.
WORK_RULE = (INSTR / "profile-work.md").read_text(encoding="utf-8").rstrip("\n") + "\n\n"
PERSONAL_RULE = (INSTR / "profile-personal.md").read_text(encoding="utf-8").rstrip("\n") + "\n\n"

RISK_PARAGRAPH = """- Risk tolerance is high. This is personal, one-person software: good enough
  is the bar. It does not need to be perfect, large-scale, production-grade
  secure, or resilient. Nobody else is going to try to break or misuse it.
  Theoretical attack, hostile operators, and enterprise hardening are out of
  scope unless they already fail in ordinary single-user use.
"""
DOORBELL_SECTION = """
## Doorbell

The doorbell rings the owner only when you ask it to. Call the `notify_owner` tool, with a
one-line summary, in two cases, and put the same text in your reply:

- You need the owner to answer or decide (the question).
- You have answered a question the owner or coordinator asked you (`answer ready: <topic>`).
  Someone is waiting on an answer, so it must ring; do not finish it quietly.

Pass `kind` (and `scope`, `attachments`, `options`, `recommendation`, `door` where they apply)
as the tool description says; use `summary`, not `question`.

End your turn after the call. An `ask_user_question` dialog rings by itself: do not also call
`notify_owner` for it. Do not ring for progress or for finishing a turn nobody is waiting on:
that stays silent. Report progress on a separate `Status:` line.
"""


# The local data keys the work profile requires (docs/profiles.md, "Local data keys"); placeholder values.
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}


def render(profile, template=None):
    with tempfile.TemporaryDirectory() as home:
        config = Path(home) / "chezmoi.yaml"
        config.write_text("{}\n")  # no hooks from the developer's own config
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "execute-template", "--override-data", json.dumps({"profile": profile, **(WORK_DATA if profile == "axon-work-computer" else {})})],
            input=(template or TEMPLATE).read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120,
        )
    assert result.returncode == 0, result.stderr
    return result.stdout


# The playbook fragment as the work profile renders it (no workGitHost set), included right after the heading block.
PLAYBOOK_SECTION = render("axon-work-computer", PLAYBOOK_TEMPLATE).rstrip("\n") + "\n\n"


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class AgentsRenderTests(unittest.TestCase):
    def test_personal_profile_gets_the_doorbell_rule(self):
        text = render("personal")
        self.assertIn("Call the `notify_owner` tool, with a", text)
        self.assertIn("answer ready: <topic>", text)
        self.assertIn("Pass `kind` (and `scope`", text)
        self.assertNotIn("AWAITING-OWNER: none", text)
        self.assertNotIn("AWAITING-OWNER: <the one question>", text)
        self.assertEqual(text.count(DOORBELL_SECTION), 1)
        self.assertTrue(text.endswith(DOORBELL_SECTION))

    def test_work_profile_has_no_doorbell_rule(self):
        text = render("axon-work-computer")
        self.assertNotIn("AWAITING-OWNER", text)
        self.assertNotIn("Doorbell", text)
        self.assertTrue(text.endswith("any follow-up the user still owns.\n"))

    def test_only_the_work_profile_gets_the_axon_playbook_section(self):
        self.assertEqual(render("axon-work-computer").count(PLAYBOOK_SECTION), 1)
        self.assertNotIn("## Axon playbook", render("personal"))

    def test_the_profiles_differ_only_by_the_risk_paragraph_the_doorbell_and_the_playbook(self):
        personal, work = render("personal"), render("axon-work-computer")
        self.assertEqual(
            personal.replace(DOORBELL_SECTION, "").replace(RISK_PARAGRAPH, "").replace(PERSONAL_RULE, "", 1),
            work.replace(PLAYBOOK_SECTION, "", 1).replace(WORK_RULE, "", 1),
        )


if __name__ == "__main__":
    unittest.main()
