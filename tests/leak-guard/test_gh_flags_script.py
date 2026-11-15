"""scripts/leak-guard-gh-flags: regenerates FLAGS and FLAGS_FROM_GH in scripts/leak-guard-gh from `gh <command> --help`.

Run against a fake gh that prints canned help, so the result does not depend on which gh release the machine has; one test also runs it against the
installed gh when that is the release the wrapper's tables came from.
"""
import importlib.machinery
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/leak-guard-gh-flags"
WRAPPER = ROOT / "scripts/leak-guard-gh"

HELP = {
    ("pr", "create"): "FLAGS\n  -b, --body string         Body for the pull request\n  -d, --draft               Mark as draft\n"
                      "      --newflag string      A flag gh added\n  -t, --title string        Title\n\nINHERITED FLAGS\n      --help   Show help for command\n"
                      "  -R, --repo [HOST/]OWNER/REPO   Select another repository\n\nEXAMPLES\n  $ gh pr create\n",
    ("pr", "view"): "FLAGS\n  -c, --comments   View comments\n\nINHERITED FLAGS\n      --help   Show help for command\n"
                    "  -R, --repo [HOST/]OWNER/REPO   Select another repository\n",
    ("pr",): "FLAGS\n  -R, --repo [HOST/]OWNER/REPO   Select another repository\n\nINHERITED FLAGS\n      --help   Show help for command\n",
}
FAKE_GH = '''#!%s
import json, os, sys
if sys.argv[1:] == ["--version"]:
    print("gh version 9.9.9 (2030-01-01)")
    sys.exit(0)
help = json.load(open(os.environ["FAKE_HELP"]))
print(help.get(" ".join(sys.argv[1:-1]), "no such command"))
''' % sys.executable


def load_script():
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("leak_guard_gh_flags_under_test", str(SCRIPT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("leak_guard_gh_flags_under_test", loader))
    loader.exec_module(mod)
    return mod


def load_wrapper(path):
    loader = importlib.machinery.SourceFileLoader("lg_wrapper_%d" % hash(str(path)), str(path))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


# a wrapper reduced to the parts the script rewrites: three commands, a stale table and a stale release
STALE = '''#!/usr/bin/env python3
"""stub"""
MARK = "x"
FLAGS_FROM_GH = "1.0.0"
FLAGS = {
    ("pr", ""): "R:repo=,h:help",
    ("pr", "create"): "b:body=,d:draft,old-flag,t:title=,h:help,R:repo=",
    ("pr", "view"): "c:comments,h:help,R:repo=",
}
TEXT = {}
'''


class FlagsScript(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gf-"))
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.gh = self.tmp / "gh"
        self.gh.write_text(FAKE_GH)
        self.gh.chmod(0o755)
        self.help = self.tmp / "help.json"
        self.help.write_text(json.dumps({" ".join(k): v for k, v in HELP.items()}))
        self.wrapper = self.tmp / "wrapper"
        self.wrapper.write_text(STALE)

    def run_script(self, *args, gh=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--gh", str(gh or self.gh), "--wrapper", str(self.wrapper), *args], capture_output=True, text=True,
                              env={"FAKE_HELP": str(self.help), "PATH": "/usr/bin:/bin"}, timeout=60)

    def test_it_rewrites_the_tables_and_the_release_from_the_help_of_every_command_already_in_the_table(self):
        done = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        mod = load_wrapper(self.wrapper)
        self.assertEqual(mod.FLAGS_FROM_GH, "9.9.9")
        self.assertEqual(mod.FLAGS[("pr", "create")], "b:body=,d:draft,newflag=,t:title=,h:help,R:repo=")
        self.assertEqual(set(mod.FLAGS), {("pr", ""), ("pr", "create"), ("pr", "view")})
        self.assertEqual(mod.FLAGS[("pr", "view")], "c:comments,h:help,R:repo=")
        self.assertTrue(done.stdout)

    def test_the_rewritten_table_is_what_the_help_lists_and_the_rest_of_the_file_is_untouched(self):
        self.run_script()
        text = self.wrapper.read_text()
        self.assertIn('("pr", "create"): "b:body=,d:draft,newflag=,t:title=,h:help,R:repo=",', text)
        self.assertNotIn("old-flag", text)
        self.assertTrue(text.startswith('#!/usr/bin/env python3\n"""stub"""\nMARK = "x"\n'))
        self.assertTrue(text.endswith("TEXT = {}\n"))

    def test_it_names_each_flag_added_or_removed_per_command_so_a_person_can_classify_them(self):
        out = self.run_script().stdout
        self.assertRegex(out, r"pr create.*added.*--newflag")
        self.assertRegex(out, r"pr create.*removed.*--old-flag")
        self.assertNotRegex(out, r"pr view.*(added|removed)")
        self.assertIn("9.9.9", out)

    def test_check_reports_a_difference_and_writes_nothing_and_a_second_run_changes_nothing(self):
        before = self.wrapper.read_text()
        done = self.run_script("--check")
        self.assertEqual((done.returncode, self.wrapper.read_text()), (1, before))
        self.assertEqual(self.run_script().returncode, 0)
        after = self.wrapper.read_text()
        done = self.run_script("--check")
        self.assertEqual((done.returncode, self.wrapper.read_text()), (0, after))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(self.wrapper.read_text(), after)

    def test_a_help_line_it_cannot_read_or_a_listed_dash_h_fails_and_writes_nothing(self):
        before = self.wrapper.read_text()
        for bad in ("FLAGS\n  something odd here\n", "FLAGS\n  -h, --help   Show help\n"):
            with self.subTest(bad):
                self.help.write_text(json.dumps({"pr create": bad, "pr view": HELP[("pr", "view")], "pr": HELP[("pr",)]}))
                done = self.run_script()
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(self.wrapper.read_text(), before)

    def test_a_command_gh_does_not_know_fails_and_writes_nothing(self):
        before = self.wrapper.read_text()
        self.help.write_text(json.dumps({"pr create": HELP[("pr", "create")], "pr": HELP[("pr",)]}))          # no help for `pr view`
        done = self.run_script()
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.wrapper.read_text(), before)

    def test_against_the_installed_gh_the_script_reproduces_the_wrapper_exactly_when_it_is_the_release_the_tables_came_from(self):
        script = load_script()
        gh = script.installed_gh()
        wrapper = load_wrapper(WRAPPER)
        if not gh or script.gh_version(gh) != wrapper.FLAGS_FROM_GH:
            self.skipTest("needs the gh release %s that the tables came from" % wrapper.FLAGS_FROM_GH)
        done = subprocess.run([sys.executable, str(SCRIPT), "--check", "--gh", gh], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
