#!/usr/bin/env python3
"""The triaging-automated-review skill: valid front matter, the local-overlay step, and no employer content.
Run: python3 -I -m unittest discover -s tests/triaging-automated-review -v
"""
import os
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


# The skill must not share a sentence, or a run of words, with the file named by SKILL_NO_COPY_FROM (a read-only
# source it was written from). The test is skipped when the variable is unset; it never prints the source's text.
NO_COPY_ENV = "SKILL_NO_COPY_FROM"
MIN_SENTENCE_CHARS = 25
SHARED_RUN_WORDS = 8


def prose_pieces(text):
    """The sentences of a Markdown file as (first line number, normalised text), code blocks and front matter keys left out."""
    pieces, para, start, fenced = [], [], 0, False

    def flush():
        nonlocal para
        if para:
            joined = " ".join(para)
            for sentence in re.split(r"(?<=[.!?])\s+", joined):
                words = re.sub(r"[*`_]", "", sentence).lower().split()
                norm = " ".join(w.strip("\"'(),;:") for w in words)
                if len(norm) >= MIN_SENTENCE_CHARS:
                    pieces.append((start, norm))
        para = []

    for number, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            flush()
            fenced = not fenced
            continue
        if fenced:
            continue
        if not line.strip() or re.match(r"\s*(?:[-*]|\d+\.)\s", line) or line.startswith("#"):
            flush()
            if not line.strip() or line.startswith("#"):
                continue
        if not para:
            start = number
        para.append(re.sub(r"^\s*(?:[-*]|\d+\.)\s", "", line).strip())
    flush()
    return pieces


def word_runs(norm, size):
    words = norm.split()
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


def copied_lines(skill_text, source_text):
    """Line numbers in the skill with a sentence equal to one in the source, or sharing a run of SHARED_RUN_WORDS words."""
    source = prose_pieces(source_text)
    sentences = {norm for _, norm in source}
    runs = set().union(*(word_runs(norm, SHARED_RUN_WORDS) for _, norm in source)) if source else set()
    return sorted({line for line, norm in prose_pieces(skill_text)
                   if norm in sentences or word_runs(norm, SHARED_RUN_WORDS) & runs})


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

    def test_a_human_reply_in_a_bot_thread_keeps_the_thread_open(self):
        # Resolving a bot thread hides a human reply in it, which the owner has not approved.
        _, body = parts()
        flat = " ".join(body.split())
        self.assertIn("Before you resolve a bot thread, read every reply in it.", flat)
        self.assertIn("If any reply's author is neither a bot nor the owner (the `viewer` login), treat the thread as a human finding: draft the reply for the owner and leave the thread open.", flat)
        self.assertIn("Your own replies post as the owner and do not count.", flat)  # or the thread would never resolve
        self.assertIn("{viewer{login} repository(", flat)  # the query returns the owner's login to compare with
        self.assertIn("comments(last:20){totalCount nodes{author{login __typename}", flat)  # the query reads the replies

    def test_does_not_restate_the_shared_tests(self):
        # The wording of the four tests lives in finding-triage.md; two copies drift. No test's own sentence appears here.
        _, body = parts()
        flat = " ".join(body.split())
        shared = (ROOT / "dot_local/share/agent-harness/finding-triage.md").read_text()
        sentences = [line.split("**", 2)[2].strip().split(". ")[0] for line in shared.splitlines()
                     if re.match(r"\d\. \*\*", line)]
        self.assertEqual(len(sentences), 4)
        self.assertEqual([s for s in sentences if s and s in flat], [])

    @unittest.skipUnless(os.environ.get(NO_COPY_ENV), "set %s to a file to check the skill shares no sentence with it" % NO_COPY_ENV)
    def test_shares_no_sentence_with_the_named_source(self):
        found = copied_lines(SKILL.read_text(), Path(os.environ[NO_COPY_ENV]).read_text())
        self.assertEqual(found, [], "SKILL.md lines that share a sentence or a %d-word run with the source: %s" % (SHARED_RUN_WORDS, found))

    def test_the_copy_check_catches_a_copied_sentence_and_a_copied_run(self):
        source = "The agent reads every open thread before it decides anything about the pull request.\n\nA second sentence stays apart here."
        skill = "# T\n\nSomething else entirely, written fresh and long enough to count as a sentence.\n\n- The agent reads every open thread before it decides anything about the pull request.\n- Then it says: reads every open thread before it decides anything, and moves on.\n- Wholly different words appear on this particular list line, nothing shared.\n"
        self.assertEqual(copied_lines(skill, source), [5, 6])
        self.assertEqual(copied_lines("```\nthe agent reads every open thread before it decides anything about the pull request\n```\n", source), [])  # code is exempt

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
