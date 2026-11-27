"""Render dot_pi/private_agent/literal_AGENTS.md.tmpl for both desktop profiles with the real chezmoi.

Both profiles must render without a doorbell rule (the `notify_owner` tool is gone). Skipped when chezmoi is not installed.

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
PERSONAL_RULE = (INSTR / "profile-personal.md").read_text(encoding="utf-8").rstrip("\n") + "\n\n"

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


# The playbook and work-profile fragments as the work profile renders them, included right after the heading block.
PLAYBOOK_SECTION = render("axon-work-computer", PLAYBOOK_TEMPLATE).rstrip("\n") + "\n\n"
WORK_RULE = render("axon-work-computer", INSTR / "profile-work.md").rstrip("\n") + "\n\n"


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class AgentsRenderTests(unittest.TestCase):
    def test_no_profile_gets_a_doorbell_rule(self):
        for profile in ("personal", "axon-work-computer"):
            text = render(profile)
            self.assertNotIn("notify_owner", text)
            self.assertNotIn("Doorbell", text)
            self.assertNotIn("AWAITING-OWNER", text)
            self.assertTrue(text.endswith("any follow-up the user still owns.\n"))

    def test_only_the_work_profile_gets_the_axon_playbook_section(self):
        self.assertEqual(render("axon-work-computer").count(PLAYBOOK_SECTION), 1)
        self.assertNotIn("## Axon playbook", render("personal"))

    def test_the_profiles_differ_only_by_the_playbook_and_the_profile_rules(self):
        personal, work = render("personal"), render("axon-work-computer")
        self.assertEqual(
            personal.replace(PERSONAL_RULE, "", 1),
            work.replace(PLAYBOOK_SECTION, "", 1).replace(WORK_RULE, "", 1),
        )


if __name__ == "__main__":
    unittest.main()
