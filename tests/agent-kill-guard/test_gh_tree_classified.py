"""Every command and verb gh lists in its own help is on gh_surface's table, so a gh upgrade that adds one fails here instead of passing the hook unread.

The help is read from the installed gh (no network, no sign-in), with an empty config directory so a user's aliases and extensions do not appear: the top-level commands,
the verbs of `gh pr`, `gh issue` and `gh agent-task`, and the aliases each of those lists (`gh pr ls`, `gh agent`). "On the table" means gh_surface lists it: a verb the module
refuses on purpose is listed, a verb it has no row for is not. A command that is off the PR/issue surface is on the table as ALLOW; it must still be named, so that someone
decides it is off the surface. Needs the real gh: skipped without one (CI's runner has it), like the flag-table test in tests/leak-guard.
"""
import importlib.machinery
import importlib.util
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_bash_rules as base

bash_rules = base.bash_rules
ROOT = base.ROOT
import gh_surface as gs  # noqa: E402  (test_bash_rules put the hooks directory on sys.path)

_loader = importlib.machinery.SourceFileLoader("leak_guard_gh_flags", str(ROOT / "scripts/leak-guard-gh-flags"))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
FLAGS_SCRIPT = importlib.util.module_from_spec(_spec)
_loader.exec_module(FLAGS_SCRIPT)
installed_gh = FLAGS_SCRIPT.installed_gh  # LEAK_GUARD_TEST_GH, else the first real gh on PATH
GROUPS_WITH_VERBS = ("pr", "issue", "agent-task")


def help_text(gh, *command):
    with tempfile.TemporaryDirectory() as config:
        env = dict(os.environ, GH_CONFIG_DIR=config, GH_NO_UPDATE_NOTIFIER="1", GH_PROMPT_DISABLED="1", NO_COLOR="1")
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
            env.pop(name, None)
        done = subprocess.run([gh, *command, "--help"], capture_output=True, text=True, timeout=60, env=env)
    if done.returncode != 0:
        raise AssertionError("`gh %s --help` failed: %s" % (" ".join(command), done.stderr.strip()))
    return done.stdout


def names_listed(text):
    """The commands a help page lists under a heading that ends in COMMANDS (not the extension ones, and not the help topics: `gh actions` is `gh help actions`)."""
    found, section = [], None
    for line in text.splitlines():
        if re.match(r"^[A-Z][A-Z ]+$", line):
            section = line
        elif section and section.endswith("COMMANDS") and section != "EXTENSION COMMANDS":
            match = re.match(r"^  ([\w-]+):\s", line)
            if match:
                found.append(match.group(1))
    return found


def aliases_listed(text):
    """The aliases of a command, each as the words after `gh` (`gh pr ls` -> ["pr", "ls"]), from the ALIASES section of its help."""
    found, section = [], None
    for line in text.splitlines():
        if re.match(r"^[A-Z][A-Z ]+$", line):
            section = line
        elif section == "ALIASES":
            found += [part.split()[1:] for part in line.split(",") if part.strip().startswith("gh ")]
    return found


def flags_listed(text):
    """The long names of the flags under the FLAGS heading of a help page."""
    found, section = set(), None
    for line in text.splitlines():
        if re.match(r"^[A-Z][A-Z ]+$", line):
            section = line
        elif section == "FLAGS":
            match = re.match(r"^\s+(?:-\w, )?--([a-z][\w-]*)", line)
            if match:
                found.add(match.group(1))
    return found


@unittest.skipUnless(installed_gh(), "needs the real gh")
class EveryGhVerbIsOnTheTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gh = installed_gh()
        cls.top = names_listed(help_text(cls.gh))
        cls.verbs = {group: names_listed(help_text(cls.gh, group)) for group in GROUPS_WITH_VERBS if group in cls.top}

    def assertListed(self, words):
        got = gs.surface(bash_rules.gh_command(list(words)))
        self.assertTrue(got.listed, "gh_surface.py has no row for `gh %s`: decide what it does to a pull request or an issue and add it (see the tables in that file)" % " ".join(words))

    def test_the_help_was_read(self):
        """Not vacuous: a help page in a shape this parser cannot read would list nothing and pass."""
        self.assertTrue({"pr", "issue", "api", "repo"} <= set(self.top), self.top)
        self.assertGreater(len(self.top), 20)
        self.assertTrue({"create", "edit", "merge", "comment", "view"} <= set(self.verbs["pr"]), self.verbs)
        self.assertTrue({"create", "edit", "comment", "close"} <= set(self.verbs["issue"]), self.verbs)

    def test_every_top_level_command_and_its_aliases(self):
        for command in self.top:
            with self.subTest(command=command):
                self.assertListed(["api", "user"] if command == "api" else [command])  # `gh api` alone names no endpoint, which the table refuses
                for alias in aliases_listed(help_text(self.gh, command)):
                    self.assertListed(alias)

    def test_every_verb_of_pr_issue_and_agent_task_and_its_aliases(self):
        for group, verbs in self.verbs.items():
            for verb in verbs:
                with self.subTest(command="%s %s" % (group, verb)):
                    self.assertListed([group, verb])
                    for alias in aliases_listed(help_text(self.gh, group, verb)):
                        self.assertListed(alias)

    def test_the_edit_flags_are_the_flags_gh_lists(self):
        """`gh pr edit --help` and `gh issue edit --help` name the flags FLAG_ROWS has, and so EDIT_FLAGS: a gh upgrade that adds a text flag fails here, whatever the wrapper's table says."""
        for group in ("pr", "issue"):
            with self.subTest(group=group):
                listed = flags_listed(help_text(self.gh, group, "edit")) - gs.EDIT_IGNORED
                self.assertGreater(len(listed), 10, listed)
                self.assertEqual(listed, set(bash_rules._table((group, "edit"))[0]) - gs.EDIT_IGNORED, "gh %s edit --help and FLAG_ROWS differ" % group)
                self.assertLessEqual(listed, set(gs.EDIT_FLAGS), "gh %s edit has a flag that EDIT_FLAGS does not name" % group)

    def test_a_verb_gh_does_not_have_is_not_on_the_table(self):
        """The check can fail: a verb no row names is refused, not read as a no-op."""
        for words in (["pr", "frobnicate"], ["issue", "frobnicate"], ["frobnicate"]):
            with self.subTest(words=words):
                got = gs.surface(bash_rules.gh_command(words))
                self.assertEqual((got.listed, got.verdict), (False, gs.REFUSE))


if __name__ == "__main__":
    unittest.main()
