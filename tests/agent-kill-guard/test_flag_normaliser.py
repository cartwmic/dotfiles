"""The flag normaliser in bash_rules.py (FLAG_ROWS, `normalise`, `gh_command`): one table per tool, one reader, and no rule that reads a flag itself.

test_flag_spellings.py checks the rules' verdicts across spellings. This file checks the pieces under them: the reader accepts every spelling for every flag in every row,
a gated command with a flag the table does not list is refused (and an ungated one is not), the gh rows are the gh wrapper's rows, and no function outside the normaliser
names a flag.
"""
import ast
import itertools
import re
import unittest
from pathlib import Path

import test_bash_rules as base

bash_rules = base.bash_rules
ROOT = base.ROOT
SOURCE = (base.HOOKS / "bash_rules.py").read_text()
LIVE = "/home/cartwmic/git/coordinator"
LIVE_KW = {"env": {"HOME": "/home/cartwmic"}, "cwd": "/home/cartwmic/tmp-home/x"}


def spellings(row_key):
    """(flag long name, takes a value, words that mean the flag with a value `v`, as lists) for every flag of one row."""
    longs, shorts = bash_rules._table(row_key)
    out = []
    for name, (short, takes, optional) in longs.items():
        if optional:
            continue
        if takes == 0:
            forms = [["--" + name]] if name != short else []
            if short:
                forms.append(["-" + short])
        else:
            forms = [["--%s" % name, "v"], ["--%s=v" % name]] if takes == 1 and name != short else ([["--%s" % name, "v", "w"]] if name != short else [])
            if short and takes == 1:
                forms += [["-" + short, "v"], ["-%sv" % short], ["-%s=v" % short]]
            if short and takes == 2:
                forms += [["-" + short, "v", "w"]]
        out.append((name, takes, forms))
    return out


class Reader(unittest.TestCase):
    def test_every_flag_of_every_row_is_read_in_every_spelling(self):
        for key in bash_rules.FLAG_ROWS:
            for name, takes, forms in spellings(key):
                for form in forms:
                    with self.subTest(row=key, flag=name, words=form):
                        read = bash_rules.normalise([key], ["x", *form, "y"])
                        self.assertEqual(read.names(), [name])
                        self.assertEqual(read.positional, ["x", "y"])
                        self.assertEqual(read.unknown, [])
                        if takes:
                            self.assertEqual(read.value(name), "v")

    def test_a_short_flag_in_a_cluster_is_read(self):
        read = bash_rules.normalise([("pr", "create")], ["-dt", "T", "-f"])
        self.assertEqual([(n, v) for n, v, _ in read.flags], [("draft", None), ("title", "T"), ("fill", None)])
        self.assertEqual(bash_rules.normalise([("pr", "create")], ["-dtT"]).value("title"), "T")
        self.assertEqual(bash_rules.normalise([("git", "merge")], ["-qvn"]).names(), ["quiet", "verbose", "n"])

    def test_two_dashes_end_the_flags_and_the_last_repeat_wins(self):
        read = bash_rules.normalise([("pr", "create")], ["--title", "a", "--", "--title", "b"])
        self.assertEqual((read.value("title"), read.positional), ("a", ["--title", "b"]))
        self.assertEqual(bash_rules.normalise([("pr", "create")], ["--title", "a", "-t", "b"]).value("title"), "b")

    def test_a_value_flag_with_no_word_after_it_has_no_value(self):
        self.assertIsNone(bash_rules.normalise([("pr", "create")], ["--title"]).value("title"))

    def test_a_value_flag_takes_the_next_word_whatever_it_looks_like(self):
        self.assertEqual(bash_rules.normalise([("pr", "create")], ["--title", "--draft", "-d"]).value("title"), "--draft")

    def test_a_flag_the_row_lacks_is_unknown(self):
        read = bash_rules.normalise([("pr", "merge")], ["--weird=1", "-Z", "-dZ"])
        self.assertEqual(read.unknown, ["--weird", "-Z", "-Z"])

    def test_a_no_form_of_a_boolean_flag_is_read(self):
        read = bash_rules.normalise([("git", "merge")], ["--no-stat", "--no-verify"])
        self.assertEqual((read.names(), read.unknown), (["no-stat", "no-verify"], []))

    def test_flags_between_the_group_and_the_verb_are_kept_with_the_command(self):
        gh = bash_rules.gh_command(["-R", "o/r", "pr", "-R", "p/q", "merge", "5", "-d"])
        self.assertEqual((gh.group, gh.verb, gh.operands, gh.argv.values("repo")), ("pr", "merge", ["5"], ["o/r", "p/q"]))
        self.assertEqual(bash_rules.gh_command(["pr", "new", "-tT"]).verb, "create")
        self.assertIsNone(bash_rules.gh_command([]))


class FailsClosed(unittest.TestCase):
    """A gated command (gh pr create/edit/merge, gh api on a PR or issue endpoint, git's merge/reset/stash/branch and any git option before the subcommand in the live
    checkout, docker before its subcommand) with a flag its row does not list is refused, and the refusal names the table. An ungated command is not touched."""
    REFUSED = [
        ("gh pr create --title t --weird x --body-file /tmp/pr-1-body.aB3xY9", {}),
        ("gh pr edit 5 --add-label x --weird", {}),
        ("gh pr merge 5 --weird", {}),
        ("ci-main-status --merge-gate c && pr-body-check c 5 && gh pr merge 5 --weird", {}),
        ("gh api repos/o/r/pulls/5 --weird", {}),
        ("gh api repos/o/r/issues/5 -Z", {}),
        ("gh api repos/o/r/pulls --weird", {}),
        ("git -C %s merge --weird" % LIVE, LIVE_KW),
        ("git -C %s branch --weird" % LIVE, LIVE_KW),
        ("git -C %s reset -Z" % LIVE, LIVE_KW),
        ("git -C %s stash -Z" % LIVE, LIVE_KW),
        ("git -C %s --weird status" % LIVE, LIVE_KW),
        ("docker --weird ps", {}),
        ("docker compose --weird ps", {}),
    ]
    ALLOWED = [
        ("gh pr view 5 --weird", {}),
        ("gh pr checks 5 --weird", {}),
        ("gh api repos/o/r/contents/x --weird", {}),
        ("gh issue edit 5 --weird", {}),
        ("git -C %s log --weird" % LIVE, LIVE_KW),
        ("git -C %s status --weird" % LIVE, LIVE_KW),
        ("git -C /tmp/scratch merge --weird", LIVE_KW),
        ("git merge --weird", {}),
        ("docker run --weird alpine --rm", {"profile": "axon-work-computer"}),
        ("docker ps --weird", {}),
    ]

    def test_an_unknown_flag_on_a_gated_command_is_refused_naming_the_table(self):
        for text, kw in self.REFUSED:
            with self.subTest(text=text):
                message = base.check(text, **kw)
                self.assertIn("FLAG_ROWS", message or "")

    def test_the_unknown_flag_message_names_the_table_to_extend(self):
        for text in ["gh pr merge 5 --weird", "gh pr create --weird", "gh pr edit 5 --weird", "gh api repos/o/r/pulls/5 --weird", "docker --weird ps"]:
            with self.subTest(text=text):
                message = base.check(text)
                self.assertIn("FLAG_ROWS", message)
                self.assertIn("--weird", message)
                self.assertIn("bash_rules.py", message)

    def test_an_unknown_flag_on_a_gated_git_command_names_the_table(self):
        for text in ["git -C %s merge --weird" % LIVE, "git -C %s --weird status" % LIVE]:
            with self.subTest(text=text):
                message = base.check(text, **LIVE_KW)
                self.assertIn("FLAG_ROWS", message)
                self.assertIn("--weird", message)

    def test_an_ungated_command_is_not_touched(self):
        for text, kw in self.ALLOWED:
            with self.subTest(text=text):
                self.assertIsNone(base.check(text, **kw))

    def test_the_log_line_names_the_flag_without_a_value(self):
        found = bash_rules.refusal("gh pr merge 5 --weird=secret", base.ctx())
        self.assertEqual(found[1].log, {"reason": "flag not in FLAG_ROWS", "flag": "--weird"})
        self.assertNotIn("secret", str(found[1]))


class Tables(unittest.TestCase):
    def test_the_gh_rows_are_the_gh_wrappers_rows(self):
        """The hook cannot import scripts/gh-wrapper (an extensionless script, installed apart from the hooks), so its rows are copied and this compares them."""
        wrapper = ast.literal_eval(re.search(r"^FLAGS = (\{.*?^\})", (ROOT / "scripts/gh-wrapper").read_text(), re.M | re.S).group(1))
        for key in [("pr", ""), ("pr", "create"), ("pr", "edit"), ("pr", "merge"), ("api", "")]:
            with self.subTest(row=key):
                self.assertEqual(bash_rules.FLAG_ROWS[key], wrapper[key])

    def test_the_gh_root_row_lists_only_the_flags_the_hook_reads_before_the_group(self):
        """The ("gh", "") row is the hook's own (the wrapper has no root row): `-R`/`--repo` and the two flags gh itself answers. Any other flag before the group is
        unknown, so `gh_command` reports it in `before_verb` and the rules refuse the command."""
        longs, shorts = bash_rules._table(("gh", ""))
        self.assertEqual(sorted(longs), ["help", "repo", "version"])
        self.assertEqual(shorts, {"R": "repo", "h": "help"})
        self.assertEqual(longs["repo"], ("R", 1, False))
        self.assertEqual(bash_rules.FLAG_ROWS[("gh", "")].split(",")[:2], bash_rules.FLAG_ROWS[("pr", "")].split(","))
        for words in (["-R", "o/r"], ["-Ro/r"], ["--repo=o/r"], ["--repo", "o/r"]):
            with self.subTest(words=words):
                read = bash_rules.normalise([("gh", "")], words + ["pr"], until_positional=True)
                self.assertEqual((read.value("repo"), read.unknown, read.positional), ("o/r", [], ["pr"]))
        self.assertEqual(bash_rules.normalise([("gh", "")], ["-t", "x", "pr"], until_positional=True).unknown, ["-t"])

    def test_gh_command_reports_the_flag_before_the_group_or_the_verb(self):
        before = lambda *args: bash_rules.gh_command(list(args)).before_verb
        self.assertIsNone(before("pr", "merge", "5"))
        self.assertIsNone(before("-R", "o/r", "pr", "-R", "p/q", "merge", "5", "-d"))
        self.assertIsNone(before("pr", "merge", "5", "-x"))  # after the verb: the table for `pr merge` decides
        self.assertIsNone(before("issue", "-x", "list"))      # not a gated group
        self.assertEqual(before("pr", "-t", "T", "edit", "5"), "-t")
        self.assertEqual(before("-t", "x", "pr", "merge", "5"), "-t")
        self.assertEqual(before("-R", "o/r", "pr", "--weird", "edit"), "--weird")

    def test_the_pr_body_check_row_is_its_parse_args_options(self):
        script = Path.home() / "git/coordinator/scripts/pr-body-check.ts"
        if not script.exists():
            self.skipTest("no coordinator checkout here")
        block = re.search(r"parseArgs\(\{.*?options: \{(.*?)\n\s*\},\s*strict", script.read_text(), re.S).group(1)
        options = {m.group(1).strip("'"): m.group(2) for m in re.finditer(r"('?[\w-]+'?): \{ type: '(\w+)' \}", block)}
        row = {t.rstrip("="): t.endswith("=") for t in bash_rules.FLAG_ROWS[("pr-body-check", "")].split(",")}
        self.assertEqual(row, {name: kind == "string" for name, kind in options.items()})

    def test_every_row_parses(self):
        for key, row in bash_rules.FLAG_ROWS.items():
            with self.subTest(row=key):
                longs, shorts = bash_rules._table(key)
                self.assertEqual(len(longs), len([t for t in row.split(",") if t]), "a flag is listed twice")
                self.assertTrue(set(shorts.values()) <= set(longs))


class Guard(unittest.TestCase):
    """No function names a flag as a string: a rule that reads a flag does it through the normaliser, so a new spelling is handled in one place. A new flag goes into
    FLAG_ROWS. The few places that build a command to run, or read find's expression, are listed here with why."""
    ALLOWED = {
        "origin_of": "builds the git command it runs",
        "_command": "reads find's -exec: an expression word, not an option",
    }
    FLAG = re.compile(r"--?[A-Za-z][\w-]*(=.*)?")

    def test_no_function_names_a_flag(self):
        tree = ast.parse(SOURCE)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name not in self.ALLOWED:
                for const in ast.walk(node):
                    if isinstance(const, ast.Constant) and isinstance(const.value, str) and self.FLAG.fullmatch(const.value):
                        found.append("%s:%d %r" % (node.name, const.lineno, const.value))
        self.assertEqual(found, [], "a function names a flag as a string. Add the flag to FLAG_ROWS in bash_rules.py and read it through normalise (or gh_command) instead.")

    def test_no_module_constant_names_a_flag_outside_the_table(self):
        tree = ast.parse(SOURCE)
        found = []
        for node in tree.body:
            if isinstance(node, ast.Assign) and not any(isinstance(t, ast.Name) and t.id == "FLAG_ROWS" for t in node.targets):
                for const in ast.walk(node):
                    if isinstance(const, ast.Constant) and isinstance(const.value, str) and self.FLAG.fullmatch(const.value):
                        found.append("%s:%d %r" % (node.targets[0].id if isinstance(node.targets[0], ast.Name) else "?", const.lineno, const.value))
        self.assertEqual(found, [])

    def test_the_old_readers_are_gone(self):
        for name in ["_flag_value", "read_gh_flags", "GhArgs", "_gh_table", "_read_flag", "GIT_VALUE_OPTIONS", "DOCKER_OPTIONS_WITH_VALUE", "COMPOSE_OPTIONS_WITH_VALUE",
                     "JS_VALUE_OPTIONS", "SCRIPT_FIRST", "MKTEMP_VALUE_OPTIONS", "GH_FLAGS", "PR_BODY_VERBS"]:
            with self.subTest(name=name):
                self.assertFalse(hasattr(bash_rules, name), "%s was replaced by FLAG_ROWS" % name)


if __name__ == "__main__":
    unittest.main()
