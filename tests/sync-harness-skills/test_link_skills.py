"""apply_harness_config.sh links canonical skills first, and a canonical skill wins a name collision with an external one.

Runs the real script (`skills` target) against a throwaway HOME, canonical root and external root.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APPLY = REPO / "dot_local/user_scripts/executable_apply_harness_config.sh"
HARNESSES = (".claude/skills", ".codex/skills", ".pi/agent/skills", ".agents/skills")


class LinkSkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "home"
        self.canon = self.tmp / "canonical"
        self.ext = self.tmp / "external"
        self.skill(self.canon / "skills/alpha")
        self.skill(self.ext / "repo-a/skills/alpha")  # collides with canonical
        self.skill(self.ext / "repo-a/gamma")
        self.skill(self.ext / "repo-b/gamma")  # collides with another external skill

    @staticmethod
    def skill(path):
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text("x\n")

    def link(self):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "AGENT_HARNESS_CANONICAL_ROOT": str(self.canon),
               "AGENT_HARNESS_EXTERNAL_ROOT": str(self.ext), "AGENT_HARNESS_GENERATED_ROOT": str(self.tmp / "gen")}
        r = subprocess.run(["sh", str(APPLY), "skills"], env=env, capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def links(self, harness=".claude/skills"):
        d = self.home / harness
        return {p.name: os.readlink(p) for p in d.iterdir() if p.is_symlink()}

    def plant(self, name, target, harness=".claude/skills"):
        d = self.home / harness
        d.mkdir(parents=True, exist_ok=True)
        (d / name).symlink_to(target)

    def test_canonical_replaces_an_existing_external_link_with_the_same_name(self):
        # An install that linked the external copy before the canonical skill existed, in every harness.
        for harness in HARNESSES:
            self.plant("alpha", self.ext / "repo-a/skills/alpha", harness)
        out = self.link()
        for harness in HARNESSES:
            self.assertEqual(self.links(harness)["alpha"], str(self.canon / "skills/alpha"), harness)
        self.assertEqual(out.count("canonical replaces the external link"), len(HARNESSES))
        self.assertNotIn("canonical replaces", self.link())  # the next run has nothing to replace

    def test_fresh_destination_links_the_canonical_copy_and_replaces_nothing(self):
        out = self.link()
        for harness in HARNESSES:
            self.assertEqual(self.links(harness)["alpha"], str(self.canon / "skills/alpha"), harness)
        self.assertNotIn("canonical replaces", out)

    def test_a_link_to_another_source_is_left_alone(self):
        elsewhere = self.tmp / "elsewhere/alpha"
        self.skill(elsewhere)
        self.plant("alpha", elsewhere)
        out = self.link()
        self.assertEqual(self.links()["alpha"], str(elsewhere))
        self.assertIn("already linked from another source", out)

    def test_a_real_directory_is_left_alone(self):
        mine = self.home / ".claude/skills/alpha"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("mine\n")
        self.link()
        self.assertFalse(mine.is_symlink())
        self.assertEqual((mine / "SKILL.md").read_text(), "mine\n")

    def test_one_external_skill_never_displaces_another(self):
        # Only the canonical pass replaces an external link.
        self.plant("gamma", self.ext / "repo-a/gamma")
        self.link()
        self.assertEqual(self.links()["gamma"], str(self.ext / "repo-a/gamma"))


if __name__ == "__main__":
    unittest.main()
