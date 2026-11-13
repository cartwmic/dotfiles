#!/usr/bin/env python3
"""The using-shartifacts skill: valid front matter, and it names the commands, tools and fields an agent needs.
Run: python3 -I tests/shx/test_skill.py
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "dot_local/share/agent-harness/canonical/skills/using-shartifacts/SKILL.md"

# What the skill must tell an agent, by the exact word it will search for.
NAMES = ("shx-note-image", "artifact_comments", "watch_artifacts", "stroke", "status", "gap", "cursor",
         "create_artifact", "update_artifact", "check", "--version", "--out", "--pad", "/view/",
         "current", "ok", "lost", "unchecked", "using-viz")


def parts():
    text = SKILL.read_text()
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    assert m, "SKILL.md must start with a --- front matter block"
    front = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        assert sep and key.strip() and value.strip(), "front matter line %r is not 'key: value'" % line
        front[key.strip()] = value.strip()
    return front, m.group(2)


class SkillTest(unittest.TestCase):
    def test_front_matter(self):
        front, _ = parts()
        self.assertEqual(set(front), {"name", "description"})
        self.assertEqual(front["name"], SKILL.parent.name)
        self.assertEqual(front["name"], "using-shartifacts")
        self.assertRegex(front["description"], r"^Use when ")
        self.assertLessEqual(len(front["description"]), 1024)

    def test_names_what_an_agent_needs(self):
        _, body = parts()
        self.assertEqual([n for n in NAMES if n not in body], [])

    def test_says_pages_for_his_review_or_input_go_on_shartifacts(self):
        _, body = parts()
        self.assertRegex(body, r"Pages for Michael's review or input go on shartifacts")
        self.assertRegex(body, r"viz\s+\(`using-viz`\) is for static charts, diagrams and PNGs")
        self.assertNotIn("still go on viz", body)

    def test_command_lines_match_the_command(self):
        # The two forms the skill shows are the two the command takes (core/domain.mjs USAGE).
        _, body = parts()
        usage = (ROOT / "dot_local/share/shx/core/domain.mjs").read_text()
        for form in ("shx-note-image <base-url> <artifact-id> <comment-id> [--version N] [--out file.png] [--pad 24]",
                     "shx-note-image check <base-url> <artifact-id>"):
            self.assertIn(form, usage)
        self.assertIn("[--version N] [--out file.png] [--pad 24]", body)
        self.assertRegex(body, r"shx-note-image check https://shartifacts\.internal\.cartwmic\.com <artifact-id>")


if __name__ == "__main__":
    unittest.main()
