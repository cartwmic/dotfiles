#!/usr/bin/env python3
"""The triaging-automated-review skill: valid front matter, the local-overlay step, and no employer content.
Run: python3 -I -m unittest discover -s tests/triaging-automated-review -v
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "dot_local/share/agent-harness/canonical/skills/triaging-automated-review/SKILL.md"

OVERLAY_GLOB = "~/.local/share/agent-harness/external-skills/*/skills/triaging-automated-review/SKILL.md"

# Shapes that mean work-profile content got into this shared file: a URL or host, a planning ID, an HTML marker
# comment, an environment-variable assignment, a script path, a slash command. The leak guard holds the real names.
FORBIDDEN_PATTERNS = (
    (r"https?://", "a URL"),
    (r"\b[A-Z]{1,4}-\d+\b", "a planning or ticket ID"),
    (r"<!--", "an HTML marker comment"),
    (r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+=", "an environment-variable assignment"),
    (r"\bbin/[\w.-]+", "a script path"),
    (r"[\"'`]/[a-z]+\b", "a slash command"),
)


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
        self.assertEqual(front["name"], "triaging-automated-review")
        self.assertRegex(front["description"], r"^Use when ")
        self.assertLessEqual(len(front["description"]), 1024)

    def test_is_a_plain_skill_file(self):
        # The run_onchange hash glob only matches */SKILL.md, so a .tmpl would change without rerunning the sync.
        self.assertTrue(SKILL.is_file())
        self.assertFalse(SKILL.with_name("SKILL.md.tmpl").exists())

    def test_names_the_local_overlay_glob(self):
        _, body = parts()
        self.assertIn(OVERLAY_GLOB, body.replace("\n  ", "").replace("`", ""))
        self.assertIn("it wins", body)

    def test_names_the_four_tests_and_the_loop_skills(self):
        _, body = parts()
        for needle in ("finding-triage.md", "**Real.**", "**Useful.**", "**Maintainable.**", "**Fits.**", "design-principles.md",
                       "`reviewing-prs` skill", "`no-ai-slop` skill", "gh pr checks", "resolveReviewThread"):
            self.assertIn(needle, body)

    def test_step_7_reaches_the_self_review(self):
        # Step 7 must not loop back to step 1 unconditionally, or step 8 (reviewing-prs) is never reached.
        _, body = parts()
        step7 = body[body.index("7. **Re-request"):body.index("8. **Run the")]
        self.assertIn("go to step 8", " ".join(step7.split()))

    def test_does_not_restate_the_shared_tests(self):
        # The wording of the four tests lives in finding-triage.md; two copies drift.
        _, body = parts()
        self.assertNotIn("Verify it against the code: reproduce it or read it", body)
        self.assertNotIn("Fixing it is worth the change", body)

    def test_has_no_work_profile_content(self):
        text = SKILL.read_text()
        for pattern, what in FORBIDDEN_PATTERNS:
            m = re.search(pattern, text)
            self.assertIsNone(m, "the shared skill holds %s: %r" % (what, m and m.group(0)))

    def test_the_patterns_catch_what_they_name(self):
        # Each pattern fires on a planted example, so a loosened pattern cannot pass silently.
        planted = {"a URL": "see https://host.example/x", "a planning or ticket ID": "per AB-4", "an HTML marker comment": "<!-- X -->",
                   "an environment-variable assignment": "SOME_HOST=x gh pr view", "a script path": "run bin/check",
                   "a slash command": 'comment "/rerun"'}
        for pattern, what in FORBIDDEN_PATTERNS:
            self.assertRegex(planted[what], pattern, what)


if __name__ == "__main__":
    unittest.main()
