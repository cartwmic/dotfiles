"""The gh wrapper (scripts/leak-guard-gh), as a process.

The wrapper is copied to a bin directory as `gh`, ahead of a fake real `gh` on PATH. leak-guard is the real script and `claude` is a fake one.
Every term and repository is invented: "fooco" is term 1, "bar.*baz" term 2, and `fooco-dev/guarded` the one guarded repository.
"""
import importlib.machinery
import importlib.util
import json
import os
import pty
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_leak_guard import FAKE_CLAUDE

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts/leak-guard-gh"
GUARD = ROOT / "dot_local/bin/executable_leak-guard"
GUARDED = "fooco-dev/guarded"
PLANTED = "an invented sentence naming fooco here"
CLEAN = "an invented sentence about gardens"

FAKE_GH = '''#!%s
import json, os, signal, sys
if sys.argv[1:3] == ["alias", "list"]:
    print(os.environ.get("FAKE_ALIASES", "co: pr checkout"))
    sys.exit(int(os.environ.get("FAKE_ALIASES_EXIT", "0")))
d = os.environ["FAKE"]
stdin = sys.stdin.read() if os.environ.get("FAKE_GH_STDIN") else ""
with open(os.path.join(d, "gh-calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin, "prompt_disabled": os.environ.get("GH_PROMPT_DISABLED")}) + "\\n")
if os.environ.get("FAKE_GH_SIGNAL"):
    os.kill(os.getpid(), int(os.environ["FAKE_GH_SIGNAL"]))
sys.stdout.write("real gh out\\n")
sys.stderr.write("real gh err\\n")
sys.exit(int(os.environ.get("FAKE_GH_EXIT", "0")))
''' % sys.executable


def script_copy(src, dest):
    text = src.read_text().split("\n", 1)
    dest.write_text("#!%s\n%s" % (sys.executable, text[1]))
    dest.chmod(0o755)


def load_wrapper():
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("leak_guard_gh_under_test", str(WRAPPER))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("leak_guard_gh_under_test", loader))
    loader.exec_module(mod)
    return mod


class WrapperBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = Path(tempfile.mkdtemp(prefix="gw-shared-")).resolve()
        cls.addClassCleanup(shutil.rmtree, cls.shared, True)
        cls.guarded_cwd = cls.make_repo("guarded", "https://github.com/%s.git" % GUARDED)
        cls.other_cwd = cls.make_repo("other", "https://github.com/someone/other.git")

    @classmethod
    def make_repo(cls, name, url):
        path = cls.shared / name
        path.mkdir()
        subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", url], check=True)
        return path

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gw-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        cfg = self.home / ".config" / "leak-guard"
        cfg.mkdir(parents=True)
        (cfg / "terms").write_text("# invented\nfooco\nbar.*baz\n")
        (cfg / "context").write_text("Fooco is the pretend employer. A work detail is anything naming it.\n")
        (cfg / "repos").write_text("# invented\n%s\n" % GUARDED)
        self.wbin, self.realbin, self.cbin, self.fake = (self.tmp / n for n in ("wbin", "realbin", "cbin", "fake"))
        for d in (self.wbin, self.realbin, self.cbin, self.fake):
            d.mkdir()
        script_copy(WRAPPER, self.wbin / "gh")
        script_copy(GUARD, self.tmp / "leak-guard")
        (self.realbin / "gh").write_text(FAKE_GH)
        (self.realbin / "gh").chmod(0o755)
        (self.cbin / "claude").write_text(FAKE_CLAUDE)
        (self.cbin / "claude").chmod(0o755)
        self.files = self.tmp / "files"
        self.files.mkdir()

    def repo(self, name, url):
        return self.make_repo("%s-%d" % (name, len(list(self.shared.iterdir()))), url)

    def reset(self):
        shutil.rmtree(self.fake)
        self.fake.mkdir()

    def env(self, extra=None):
        e = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST", "LEAK_GUARD_SKIP", "XDG_STATE_HOME", "FAKE_CLAUDE")}
        e.update(HOME=str(self.home), FAKE=str(self.fake), LEAK_GUARD_BIN=str(self.tmp / "leak-guard"), FAKE_GH_STDIN="1",
                 PATH="%s:%s:%s:/usr/bin:/bin" % (self.wbin, self.realbin, self.cbin))
        e.update(extra or {})
        return e

    def gh(self, *args, cwd=None, stdin="", env=None, timeout=60):
        return subprocess.run([str(self.wbin / "gh"), *args], cwd=str(cwd or self.guarded_cwd), input=stdin, capture_output=True, text=True,
                              env=self.env(env), timeout=timeout)

    def gh_tty(self, *args, cwd=None):
        """Run the wrapper with a pseudo-terminal as standard input, as a person's shell would."""
        master, slave = pty.openpty()
        try:
            return subprocess.run([str(self.wbin / "gh"), *args], cwd=str(cwd or self.guarded_cwd), stdin=slave, capture_output=True, text=True,
                                  env=self.env({"FAKE_GH_STDIN": ""}), timeout=60)
        finally:
            os.close(master)
            os.close(slave)

    def file(self, name, text):
        (self.files / name).write_text(text)
        return str(self.files / name)

    def real_calls(self):
        path = self.fake / "gh-calls.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def claude_calls(self):
        return len((self.fake / "calls").read_text()) if (self.fake / "calls").exists() else 0

    def log(self):
        path = self.home / ".local" / "state" / "leak-guard" / "log.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def gh_log(self):
        return [r for r in self.log() if r.get("mode") == "gh"]

    def assertBlocked(self, done, text=None):
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(self.real_calls(), [], "the real gh ran")
        if text:
            self.assertIn(text, done.stderr)

    def assertRan(self, done, *args, stdin=None):
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = self.real_calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0]["argv"], list(args))
        if stdin is not None:
            self.assertEqual(calls[0]["stdin"], stdin)


class Decisions(WrapperBase):
    """In-process view of what the wrapper decides, for the matrices of commands; the process-level tests below drive the same wrapper as a user does."""
    W = load_wrapper()
    REPOS = {("github.com", GUARDED)}

    aliases = "co: pr checkout"

    def decide(self, *args, repo=GUARDED):
        env = {"GH_HOST": "github.com", "FAKE_ALIASES": self.aliases, **({"GH_REPO": repo} if repo else {})}
        with mock.patch.dict(os.environ, env):
            if not repo:
                os.environ.pop("GH_REPO", None)
            name, texts = self.W.decide(list(args), self.REPOS, None, str(self.realbin / "gh"))
        return name, ({l: d.decode() for l, d in texts.items} if texts else None)

    def refused(self, *args, repo=GUARDED):
        env = {"GH_HOST": "github.com", "FAKE_ALIASES": self.aliases, **({"GH_REPO": repo} if repo else {})}
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(self.W.Refuse) as caught:
                self.W.decide(list(args), self.REPOS, None, str(self.realbin / "gh"))
        return str(caught.exception)


def installed_gh():
    """The first real gh on PATH (not a copy of this wrapper), or None."""
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, "gh")
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            try:
                if b"leak-guard gh wrapper" in Path(cand).read_bytes()[:4096]:
                    continue
            except OSError:
                continue
            return cand
    return None


def help_flags(gh, *command):
    """{(short, long, takes a value)} that `gh <command> --help` lists under FLAGS and INHERITED FLAGS."""
    import re
    out = subprocess.run([gh, *command, "--help"], capture_output=True, text=True, timeout=60).stdout
    flags, section = set(), None
    for line in out.splitlines():
        if re.match(r"^[A-Z][A-Z ]+$", line):
            section = line
        elif section in ("FLAGS", "INHERITED FLAGS") and line.strip():
            m = re.match(r"^ {2,6}(?:(-\w), )?--([\w-]+)(?: (\S.*?))?(?:\s{2,}\S.*)?$", line)
            if not m:
                raise AssertionError("a flag line this test cannot read: %r" % line)
            flags.add((m.group(1)[1:] if m.group(1) else "", m.group(2), bool(m.group(3))))
    return flags


@unittest.skipUnless(installed_gh(), "needs the real gh")
class FlagTables(unittest.TestCase):
    """The wrapper's FLAGS table is gh's own flag list. A gh upgrade that adds, drops or changes a flag shows up here."""
    W = load_wrapper()

    def test_every_table_matches_what_the_installed_gh_lists_for_that_command(self):
        gh = installed_gh()
        for (group, verb), spec in self.W.FLAGS.items():
            with self.subTest(group=group, verb=verb):
                ours = set()
                for item in spec.split(","):
                    short, _, rest = item.rpartition(":")
                    ours.add((short, rest.rstrip("="), rest.endswith("=")))
                command = (group,) + ((verb,) if verb else ())
                theirs = help_flags(gh, *command)
                # gh accepts -h for --help but does not list it
                ours = {("", l, t) if l == "help" else (s, l, t) for s, l, t in ours}
                self.assertEqual(ours, theirs, "the FLAGS table for `gh %s` no longer matches `gh %s --help` (gh %s)" % (" ".join(command), " ".join(command),
                                 subprocess.run([gh, "--version"], capture_output=True, text=True).stdout.split()[2]))


class WrapperRepo(WrapperBase):
    def test_the_current_directorys_remote_decides_https_scp_and_ssh_forms(self):
        for n, url in enumerate(("https://github.com/Fooco-Dev/Guarded.git", "git@github.com:fooco-dev/guarded.git", "ssh://git@github.com/fooco-dev/guarded",
                                 "https://user@github.com/fooco-dev/guarded/")):
            with self.subTest(url):
                cwd = self.repo("r%d" % n, url)
                self.assertBlocked(self.gh("pr", "comment", "5", "--body", PLANTED, cwd=cwd), "term 1")

    def test_an_unguarded_remote_or_no_repository_passes_straight_through_without_a_check(self):
        for cwd in (self.other_cwd, self.files):
            self.assertRan(self.gh("pr", "comment", "5", "--body", PLANTED, cwd=cwd), "pr", "comment", "5", "--body", PLANTED)
            self.reset()
        self.assertEqual(self.claude_calls(), 0)

    def test_dash_R_and_repo_name_the_repository_from_any_directory(self):
        for flags in (["-R", GUARDED], ["--repo", GUARDED], ["--repo=" + GUARDED], ["-R" + GUARDED.upper()]):
            with self.subTest(flags):
                self.reset()
                self.assertBlocked(self.gh("pr", "comment", "5", *flags, "--body", PLANTED, cwd=self.other_cwd), "term 1")
        self.reset()
        args = ["pr", "comment", "5", "-R", "someone/other", "--body", PLANTED]
        self.assertRan(self.gh(*args, cwd=self.other_cwd), *args)                      # only unguarded targets: gh runs as typed, nothing checked
        self.assertEqual(self.claude_calls(), 0)

    def test_a_github_url_argument_names_the_repository_from_any_directory(self):
        url = "https://github.com/%s/pull/5" % GUARDED
        self.assertBlocked(self.gh("pr", "comment", url, "--body", PLANTED, cwd=self.other_cwd), "term 1")
        self.reset()
        other = "https://github.com/someone/other/pull/5"
        self.assertRan(self.gh("pr", "comment", other, "--body", PLANTED, cwd=self.other_cwd), "pr", "comment", other, "--body", PLANTED)

    def test_a_url_inside_the_body_text_does_not_name_the_repository(self):
        body = "see https://github.com/%s/pull/5 for details" % GUARDED
        self.assertRan(self.gh("pr", "comment", "5", "--body", body, cwd=self.other_cwd), "pr", "comment", "5", "--body", body)
        self.assertEqual(self.claude_calls(), 0)

    def test_gh_repo_names_the_repository_from_any_directory(self):
        self.assertBlocked(self.gh("pr", "comment", "5", "--body", PLANTED, cwd=self.other_cwd, env={"GH_REPO": GUARDED}), "term 1")

    def test_a_command_is_guarded_when_any_target_it_names_is_guarded_whichever_one_gh_prefers(self):
        # gh takes the repository from a URL and ignores -R, from -R before GH_REPO, from GH_REPO before the checkout; the wrapper checks the union.
        url = "https://github.com/%s/pull/3" % GUARDED
        other_url = "https://github.com/someone/other/pull/3"
        cases = [(["pr", "comment", url, "-R", "someone/other"], self.other_cwd, {}),                    # a guarded URL with an unguarded -R
                 (["pr", "comment", "-R", "someone/other", url], self.other_cwd, {}),
                 (["pr", "comment", other_url, "-R", GUARDED], self.other_cwd, {}),                      # an unguarded URL with a guarded -R
                 (["issue", "comment", "https://github.com/%s/issues/3" % GUARDED, "-R", "someone/other"], self.other_cwd, {}),
                 (["pr", "comment", "3", "-R", "someone/other"], self.other_cwd, {"GH_REPO": GUARDED}),    # a guarded GH_REPO in an unguarded checkout
                 (["pr", "comment", "3"], self.other_cwd, {"GH_REPO": GUARDED}),
                 (["pr", "comment", "3", "-R", "someone/other"], self.guarded_cwd, {}),                  # a guarded checkout with an unguarded -R
                 (["pr", "comment", other_url], self.guarded_cwd, {}),
                 (["pr", "comment", "3"], self.guarded_cwd, {"GH_REPO": "someone/other"})]
        for args, cwd, env in cases:
            with self.subTest(args=args, cwd=cwd.name, env=env):
                self.reset()
                self.assertBlocked(self.gh(*args, "-b", PLANTED, cwd=cwd, env=env), "term 1")

    def test_a_guarded_remote_among_several_remotes_of_the_checkout_guards_the_command(self):
        cwd = self.repo("multi", "https://github.com/someone/first.git")
        for name, url in (("second", "https://github.com/someone/second.git"), ("fork", "git@github.com:%s.git" % GUARDED), ("fourth", "https://github.com/someone/fourth.git")):
            subprocess.run(["git", "-C", str(cwd), "remote", "add", name, url], check=True)
        self.assertBlocked(self.gh("pr", "comment", "3", "-b", PLANTED, cwd=cwd), "term 1")
        subprocess.run(["git", "-C", str(cwd), "remote", "set-url", "--push", "fork", "https://github.com/someone/elsewhere.git"], check=True)
        self.reset()
        self.assertBlocked(self.gh("pr", "comment", "3", "-b", PLANTED, cwd=cwd), "term 1")          # the fetch URL alone is enough

    def test_a_clean_command_with_only_unguarded_targets_passes_straight_through_untouched(self):
        other_url = "https://github.com/someone/other/pull/3"
        for args, env in ((["pr", "comment", "3", "-R", "someone/other", "-b", PLANTED], {}), (["pr", "comment", other_url, "-b", PLANTED], {}),
                          (["pr", "comment", "3", "-b", PLANTED], {"GH_REPO": "someone/other"}), (["pr", "close", "3", "-c", PLANTED], {}),
                          (["release", "create", "v1", "--notes", PLANTED, "-R", "someone/other"], {})):
            with self.subTest(args):
                self.reset()
                done = self.gh(*args, cwd=self.other_cwd, env=env, stdin="stdin text\n")
                self.assertRan(done, *args, stdin="stdin text\n")
                self.assertEqual(self.claude_calls(), 0)
                self.assertIsNone(self.real_calls()[0]["prompt_disabled"])
        self.assertEqual(self.gh_log(), [])

    def test_the_repos_file_may_name_another_host_and_a_foreign_host_with_the_same_name_is_not_guarded(self):
        (self.home / ".config" / "leak-guard" / "repos").write_text("git.example.test/team/proj\n")
        cwd = self.repo("ghe", "git@git.example.test:team/proj.git")
        self.assertBlocked(self.gh("pr", "comment", "5", "--body", PLANTED, cwd=cwd), "term 1")
        github = self.repo("gh", "https://github.com/team/proj.git")
        self.assertRan(self.gh("pr", "comment", "5", "--body", PLANTED, cwd=github), "pr", "comment", "5", "--body", PLANTED)


class WrapperText(Decisions):
    CASES = [
        (("pr", "create", "--title", "{}", "--body", CLEAN), "title"), (("pr", "create", "--title", "t", "--body", "{}"), "body"),
        (("pr", "edit", "5", "--title", "{}"), "title"), (("pr", "edit", "5", "--body", "{}"), "body"),
        (("pr", "comment", "5", "--body", "{}"), "body"), (("pr", "comment", "5", "-b", "{}"), "body"), (("pr", "comment", "5", "--body={}"), "body"),
        (("pr", "review", "5", "--approve", "--body", "{}"), "body"), (("pr", "review", "5", "--request-changes", "-b", "{}"), "body"),
        (("issue", "create", "--title", "{}", "--body", "b"), "title"), (("issue", "create", "-t", "t", "-b", "{}"), "body"),
        (("issue", "edit", "5", "--title", "{}"), "title"), (("issue", "edit", "5", "--body", "{}"), "body"),
        (("issue", "comment", "5", "--body", "{}"), "body"),
        (("release", "create", "v1", "--title", "{}"), "title"), (("release", "create", "v1", "--notes", "{}"), "notes"), (("release", "create", "v1", "-n", "{}"), "notes"),
        (("release", "edit", "v1", "--title", "{}"), "title"), (("release", "edit", "v1", "--notes", "{}"), "notes"),
        (("pr", "merge", "5", "--squash", "--subject", "{}"), "title"), (("pr", "merge", "5", "--body", "{}"), "body"),
        (("pr", "close", "5", "--comment", "{}"), "comment"), (("pr", "close", "5", "-c", "{}"), "comment"), (("pr", "reopen", "5", "--comment", "{}"), "comment"),
        (("issue", "close", "5", "--comment", "{}"), "comment"), (("issue", "reopen", "5", "-c", "{}"), "comment"),
    ]

    def fill(self, args, text):
        return [a.replace("{}", text) for a in args]

    def test_every_listed_command_gathers_its_text_under_the_part_that_carries_it(self):
        for args, label in self.CASES:
            with self.subTest(args):
                name, texts = self.decide(*self.fill(args, PLANTED))
                self.assertEqual(name, " ".join(args[:2]))
                self.assertIn(PLANTED, texts[label])

    def test_the_commands_for_a_guarded_repository_that_send_no_text_gather_none(self):
        for args in (("pr", "edit", "5", "--add-label", "bug"), ("pr", "merge", "5", "--squash"), ("issue", "close", "5")):
            with self.subTest(args):
                self.assertEqual(self.decide(*args), (" ".join(args[:2]), {}))

    def test_a_listed_command_blocks_a_term_names_the_part_the_line_and_the_term_number_and_runs_nothing(self):
        for args, label in self.CASES[::6]:
            with self.subTest(args):
                self.reset()
                done = self.gh(*self.fill(args, PLANTED))
                self.assertBlocked(done, "%s:1: term 1" % label)
                self.assertIn("LEAK_GUARD_SKIP", done.stderr)
                self.assertNotIn(str(self.tmp), done.stderr)      # no temporary path in the message

    def test_a_listed_command_runs_the_real_gh_with_the_same_arguments_on_a_clean_text(self):
        for args, label in self.CASES[::6]:
            with self.subTest(args):
                self.reset()
                clean = self.fill(args, CLEAN)
                self.assertRan(self.gh(*clean), *clean)

    def test_a_term_in_any_one_of_title_and_body_blocks_and_both_are_sent_to_claude(self):
        done = self.gh("pr", "create", "--title", "first words", "--body", "second words")
        self.assertEqual(done.returncode, 0, done.stderr)
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("first words", sent)
        self.assertIn("second words", sent)
        self.assertIn("=== file: title", sent)
        self.assertIn("=== file: body", sent)

    def test_a_claude_leak_verdict_blocks_the_real_gh(self):
        self.assertBlocked(self.gh("pr", "comment", "5", "--body", CLEAN, env={"FAKE_CLAUDE": "leak"}), "BLOCKED by Claude")

    def test_the_real_ghs_exit_code_and_output_come_back(self):
        done = self.gh("pr", "comment", "5", "--body", CLEAN, env={"FAKE_GH_EXIT": "5"})
        self.assertEqual(done.returncode, 5)
        self.assertIn("real gh out", done.stdout)
        self.assertIn("real gh err", done.stderr)

    def test_a_command_with_no_text_flag_runs_without_a_check(self):
        self.assertRan(self.gh("pr", "edit", "5", "--add-label", "bug"), "pr", "edit", "5", "--add-label", "bug")
        self.assertEqual(self.claude_calls(), 0)

    def test_release_create_with_asset_files_is_refused_and_the_tag_is_checked_as_text(self):
        self.assertIn("asset files", self.refused("release", "create", "v1", "CHANGES.txt", "-t", "x", "--notes", CLEAN))
        self.assertIn("asset files", self.refused("release", "create", "v1", "a.zip#label", "b.zip", "--notes", CLEAN))
        self.assertIn("asset files", self.refused("release", "create", "--notes", CLEAN, "v1", "--", "CHANGES.txt"))
        name, texts = self.decide("release", "create", "v1.2", "--target", "main", "--notes", CLEAN)           # --target's value is not a file
        self.assertEqual((name, texts["tag"]), ("release create", "v1.2"))
        name, texts = self.decide("release", "create", "-R", GUARDED, "--discussion-category", "General", "v1.2", "-n", CLEAN)
        self.assertEqual(texts["tag"], "v1.2")
        self.reset()
        self.assertBlocked(self.gh("release", "create", "v1-fooco", "--notes", CLEAN), "tag:1: term 1")
        self.reset()
        self.assertBlocked(self.gh("release", "create", "v1", "CHANGES.txt", "--notes", CLEAN), "asset files")
        self.assertIn("tag", self.decide("release", "edit", "v1", "--tag", "v2")[1])

    def test_help_is_help_only_when_it_stands_alone_and_not_as_a_flags_value(self):
        self.assertEqual(self.decide("pr", "create", "--help"), ("", None))
        self.assertEqual(self.decide("pr", "create", "-h"), ("", None))
        name, texts = self.decide("pr", "create", "-t", "x", "--body", "-h")
        self.assertEqual((name, texts["body"]), ("pr create", "-h"))
        name, texts = self.decide("pr", "create", "-t", "-h", "--body", "y")
        self.assertEqual(texts["title"], "-h")
        self.assertEqual(self.decide("api", "repos/%s/issues/1/comments" % GUARDED, "-f", "body=-h")[0], "api")
        self.assertEqual(self.decide("api", "repos/%s/issues/1/comments" % GUARDED, "--help"), ("", None))
        name, texts = self.decide("pr", "create", "--label", "--body", "--body", "SECRET", "-t", "x")
        self.assertEqual(texts["body"], "SECRET")

    def test_every_other_flag_in_every_form_can_precede_a_text_flag_without_hiding_it(self):
        # The cause of the review's follow-on: a flag's arity decides what the next argument is. Walk each command's whole table.
        for (group, verb), kinds in self.W.TEXT.items():
            longs, shorts = self.W.flag_table(group, verb)
            text_long = next(name for name in ("body", "notes", "comment", "title") if name in kinds)
            text_short = next((s for s, l in shorts.items() if l == text_long), None)
            for name, takes in longs.items():
                if name in kinds or name in ("help", "repo"):
                    continue
                prefixes = [["--%s" % name] + (["v"] if takes else [])]
                if takes:
                    prefixes.append(["--%s=v" % name])
                short = next((s for s, l in shorts.items() if l == name), None)
                if short:
                    prefixes += [["-%s" % short] + (["v"] if takes else [])] + ([["-%sv" % short], ["-%s=v" % short]] if takes else [])
                for prefix in prefixes:
                    for text_args in [["--%s" % text_long, "SECRET"], ["--%s=SECRET" % text_long]] + ([["-%s" % text_short, "SECRET"], ["-%sSECRET" % text_short]] if text_short else []):
                        flags, positionals, unknown, missing = self.W.parse_flags(prefix + text_args, group, verb)
                        self.assertEqual((unknown, missing), (None, None), (group, verb, prefix, text_args))
                        self.assertIn((text_long, "SECRET"), flags, (group, verb, prefix, text_args))
                        self.assertEqual(positionals, [], (group, verb, prefix, text_args))

    def test_the_reviewers_examples_with_short_switches_before_a_text_flag(self):
        for args, label, want in ((("pr", "review", "3", "-r", "-b", "SECRET"), "body", "SECRET"), (("pr", "review", "3", "-a", "-b", "SECRET"), "body", "SECRET"),
                                  (("pr", "review", "3", "-c", "-b", "SECRET"), "body", "SECRET"), (("pr", "merge", "3", "-r", "--body", "SECRET"), "body", "SECRET"),
                                  (("pr", "merge", "3", "-m", "-t", "SUBJ", "-b", "SECRET"), "title", "SUBJ"), (("pr", "merge", "3", "-s", "-b", "SECRET"), "body", "SECRET"),
                                  (("release", "create", "-p", "v1", "--notes", "SECRET"), "notes", "SECRET"), (("release", "create", "-d", "-p", "-t", "SECRET", "v1"), "title", "SECRET"),
                                  (("pr", "create", "-d", "-t", "SECRET", "-b", "x"), "title", "SECRET"), (("pr", "create", "-dt", "SECRET", "-b", "x"), "title", "SECRET"),
                                  (("pr", "create", "-l", "bug", "-r", "someone", "-b", "SECRET", "-t", "x"), "body", "SECRET")):
            with self.subTest(args):
                name, texts = self.decide(*args)
                self.assertEqual(texts[label], want)
                self.assertEqual(name, " ".join(args[:2]))
        self.assertEqual(self.decide("release", "create", "-p", "v1", "--notes", "x")[1]["tag"], "v1")        # -p is a switch, so v1 is still the tag

    def test_a_flag_that_is_not_in_the_commands_table_is_refused_and_named_by_position(self):
        for args, position in ((["pr", "create", "--frobnicate", "-t", "SECRET"], 3), (["pr", "review", "3", "-z", "-b", "SECRET"], 4), (["pr", "merge", "3", "-Z"], 4),
                               (["release", "create", "v1", "--made-up=1", "--notes", "SECRET"], 4), (["issue", "comment", "5", "-ab", "SECRET"], 4)):
            with self.subTest(args):
                message = self.refused(*args)
                self.assertIn("argument %d is a flag this wrapper does not know" % position, message)
                self.assertNotIn("SECRET", message)
        self.reset()
        self.assertBlocked(self.gh("pr", "create", "--frobnicate", "-t", PLANTED), "does not know")
        self.reset()
        args = ["pr", "create", "--frobnicate", "-t", PLANTED]
        self.assertRan(self.gh(*args, cwd=self.other_cwd), *args)               # another repository: gh runs as typed

    def test_the_short_form_of_a_composed_text_flag_is_refused_too(self):
        for args in (["pr", "create", "-f"], ["pr", "create", "-df"], ["pr", "create", "-t", "x", "-f"], ["pr", "create", "-e"], ["pr", "create", "-w"],
                     ["pr", "create", "-T", "t.md"], ["issue", "create", "-w"], ["pr", "comment", "5", "-e"], ["pr", "comment", "5", "-w"]):
            with self.subTest(args):
                self.assertIn("makes gh write the text itself", self.refused(*args))

    def test_a_value_flag_with_no_value_and_a_value_that_looks_like_a_flag(self):
        self.assertIn("has no value", self.refused("pr", "create", "-t"))
        self.assertEqual(self.decide("pr", "create", "-t", "-b", "-b", "SECRET")[1]["title"], "-b")      # gh takes the next argument whatever it looks like
        self.assertEqual(self.decide("pr", "create", "-t", "x", "-b", "SECRET", "--", "ignored")[1]["body"], "SECRET")

    def test_the_url_among_the_positional_arguments_names_the_repository_but_a_flag_value_does_not(self):
        url = "https://github.com/%s/pull/5" % GUARDED
        self.assertEqual(self.decide("pr", "comment", url, "-b", "x", repo="someone/other")[0], "pr comment")
        self.assertEqual(self.decide("pr", "comment", "5", "-b", url, repo="someone/other"), ("", None))        # a body that is a URL is just text
        self.assertEqual(self.decide("pr", "comment", "5", "-b", "x", "-R", "someone/other", repo="someone/another"), ("", None))
        self.assertEqual(self.decide("pr", "comment", "5", "-b", "x", "-R", "someone/other")[0], "pr comment")        # GH_REPO is guarded: the union is checked
        self.assertEqual(self.decide("pr", "comment", url, "-R", "someone/other", "-b", "x", repo="someone/other")[0], "pr comment")     # a guarded URL beats -R in gh
        self.assertEqual(self.decide("pr", "comment", "https://github.com/someone/other/pull/3", "-R", GUARDED, "-b", "x", repo="someone/other")[0], "pr comment")

    def test_a_gh_killed_by_a_signal_exits_as_a_shell_reports_it(self):
        done = self.gh("pr", "comment", "5", "--body-file", "-", stdin=CLEAN, env={"FAKE_GH_SIGNAL": "15"})      # stdin was read, so the wrapper runs gh as a child
        self.assertEqual(done.returncode, 143)

    def test_a_cluster_of_switches_ending_in_a_value_flag_is_parsed_like_gh_does(self):
        self.assertBlocked(self.gh("pr", "create", "-dt", PLANTED), "title:1: term 1")


class WrapperBodyFile(WrapperBase):
    def test_body_file_and_dash_F_are_read_and_checked(self):
        bad, ok = self.file("bad.md", "line one\n%s\n" % PLANTED), self.file("ok.md", CLEAN + "\n")
        for flag in ("--body-file", "-F"):
            with self.subTest(flag):
                self.reset()
                self.assertBlocked(self.gh("pr", "create", "--title", "t", flag, bad), "body:2: term 1")
                self.assertRan(self.gh("pr", "create", "--title", "t", flag, ok), "pr", "create", "--title", "t", flag, ok)
                self.reset()

    def test_notes_file_is_read_and_checked(self):
        self.assertBlocked(self.gh("release", "create", "v1", "--notes-file", self.file("n.md", PLANTED)), "notes:1: term 1")

    def test_a_body_file_of_dash_reads_stdin_and_the_real_gh_gets_the_same_stdin(self):
        self.assertBlocked(self.gh("pr", "comment", "5", "--body-file", "-", stdin=PLANTED + "\n"), "body:1: term 1")
        done = self.gh("pr", "comment", "5", "--body-file", "-", stdin=CLEAN + "\n")
        self.assertRan(done, "pr", "comment", "5", "--body-file", "-", stdin=CLEAN + "\n")

    def test_an_unreadable_file_blocks(self):
        self.assertBlocked(self.gh("pr", "comment", "5", "--body-file", str(self.files / "nope.md")), "cannot read")
        self.assertEqual(self.claude_calls(), 0)

    def test_a_command_that_would_ask_for_text_on_a_terminal_blocks_and_one_with_text_does_not(self):
        self.assertBlocked(self.gh_tty("pr", "create"), "terminal")
        done = self.gh_tty("pr", "create", "--title", "t", "--body", CLEAN)
        self.assertEqual(done.returncode, 0, done.stderr)
        done = self.gh_tty("pr", "review", "5", "--approve")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_stdin_is_untouched_for_an_unguarded_repository_even_with_a_body_file_of_dash(self):
        done = self.gh("pr", "comment", "5", "-R", "someone/other", "--body-file", "-", stdin="from stdin\n")
        self.assertRan(done, "pr", "comment", "5", "-R", "someone/other", "--body-file", "-", stdin="from stdin\n")


class WrapperApi(Decisions):
    EP = "repos/%s/issues/1/comments" % GUARDED

    def test_a_field_with_no_dash_X_is_a_write_and_the_endpoint_names_the_repository_from_any_directory(self):
        self.assertBlocked(self.gh("api", self.EP, "-f", "body=" + PLANTED, cwd=self.other_cwd), "field 1:1: term 1")
        clean = ["api", self.EP, "-f", "body=" + CLEAN]
        self.assertRan(self.gh(*clean, cwd=self.other_cwd), *clean)

    def test_every_field_flag_and_form_is_gathered(self):
        cases = [["-f", "body=" + PLANTED], ["-F", "body=" + PLANTED], ["--raw-field", "body=" + PLANTED], ["--field", "body=" + PLANTED],
                 ["--field=body=" + PLANTED], ["-fbody=" + PLANTED], ["-X", "POST", "-f", "body=" + PLANTED], ["-XPATCH", "-f", "body=" + PLANTED],
                 ["--method", "PUT", "-f", "body=" + PLANTED], ["-F", "body=@" + self.file("b.md", PLANTED)], ["-i", "-f", "body=" + PLANTED],
                 ["--jq", ".id", "-f", "body=" + PLANTED]]
        for flags in cases:
            for ep in (self.EP, "/" + self.EP, "https://api.github.com/" + self.EP):
                with self.subTest(flags=flags, ep=ep):
                    name, texts = self.decide("api", ep, *flags)
                    self.assertEqual(name, "api")
                    self.assertIn(PLANTED, " ".join(texts.values()))

    def test_input_files_and_stdin_are_checked_end_to_end(self):
        self.assertBlocked(self.gh("api", self.EP, "-F", "body=@-", stdin=PLANTED, cwd=self.other_cwd), "term 1")
        self.assertBlocked(self.gh("api", self.EP, "--input", self.file("in.json", json.dumps({"body": PLANTED})), cwd=self.other_cwd), "input:1: term 1")
        self.reset()
        done = self.gh("api", self.EP, "--input", "-", stdin=json.dumps({"body": CLEAN}), cwd=self.other_cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.real_calls()[-1]["stdin"], json.dumps({"body": CLEAN}))

    def test_placeholders_name_the_repository_from_the_current_directory(self):
        self.assertBlocked(self.gh("api", "repos/{owner}/{repo}/issues/1/comments", "-f", "body=" + PLANTED, cwd=self.guarded_cwd), "term 1")
        args = ["api", "repos/{owner}/{repo}/issues/1/comments", "-f", "body=" + PLANTED]
        self.assertRan(self.gh(*args, cwd=self.other_cwd), *args)

    def test_reads_other_repositories_and_non_repository_endpoints_pass_straight_through(self):
        for args in (["api", self.EP], ["api", self.EP, "-X", "GET", "-f", "q=" + PLANTED], ["api", self.EP, "--method", "HEAD"],
                     ["api", "repos/someone/other/issues/1/comments", "-f", "body=" + PLANTED], ["api", "user/starred/x/y", "-X", "PUT"],
                     ["api", "orgs/someone/hooks", "-f", "url=" + PLANTED]):
            with self.subTest(args):
                self.assertEqual(self.decide(*args, repo="someone/other"), ("", None))        # nothing it names is guarded
        # a guarded checkout or GH_REPO is a target too, whatever the endpoint says
        self.assertEqual(self.decide("api", "repos/someone/other/issues/1/comments", "-f", "body=" + PLANTED)[0], "api")

    def test_an_uploads_host_url_names_the_repository_and_a_numeric_repository_id_is_refused_for_a_write(self):
        name, texts = self.decide("api", "https://uploads.github.com/%s/releases/1/assets" % self.EP.split("/issues")[0], "-f", "body=" + PLANTED)
        self.assertEqual(name, "api")
        self.assertIn("numeric id", self.refused("api", "repositories/123/issues/1/comments", "-f", "body=" + CLEAN))
        self.assertEqual(self.decide("api", "repositories/123/issues/1/comments"), ("", None))        # a read passes
        done = self.gh("api", "repositories/123/issues/1/comments", "-X", "POST", cwd=self.other_cwd)
        self.assertBlocked(done, "numeric id")

    def test_an_api_flag_that_is_not_in_gh_apis_table_is_refused_when_the_call_may_be_aimed_at_a_guarded_repository(self):
        ep = "repos/%s/issues/1/comments" % GUARDED
        self.assertIn("flag this wrapper does not know", self.refused("api", ep, "--frobnicate", "-f", "body=x"))
        self.assertIn("flag this wrapper does not know", self.refused("api", "graphql", "--frobnicate", "-f", "query=mutation { x }"))
        self.assertIn("no value", self.refused("api", ep, "-f"))
        self.assertEqual(self.decide("api", "repos/someone/other/issues", "--frobnicate", "-f", "body=x", repo="someone/other"), ("", None))
        for flags in (["--paginate", "--slurp", "--silent", "--verbose"], ["-i", "-q", ".id"], ["-H", "Accept: x", "--cache", "1h"], ["-p", "x", "--allow-escape-sequences"]):
            self.assertEqual(self.decide("api", ep, *flags, "-f", "body=SECRET")[0], "api")

    def test_hostname_sets_the_host_so_another_host_is_not_a_guarded_repository(self):
        ep = "repos/%s/issues/1/comments" % GUARDED
        self.assertEqual(self.decide("api", "--hostname", "ghe.example.test", ep, "-f", "body=x", repo="someone/other"), ("", None))
        self.assertEqual(self.decide("api", "--hostname=ghe.example.test", ep, "-f", "body=x", repo="someone/other"), ("", None))
        self.assertEqual(self.decide("api", "--hostname", "github.com", ep, "-f", "body=x")[0], "api")
        with mock.patch.dict(os.environ, {"GH_HOST": "github.com"}):
            name, texts = self.W.decide(["api", "--hostname", "ghe.example.test", "repos/team/proj/issues", "-f", "body=x"], {("ghe.example.test", "team/proj")})
        self.assertEqual(name, "api")

    def test_field_keys_are_checked_as_text_and_a_hit_names_the_field_by_position_not_by_its_key(self):
        done = self.gh("api", self.EP, "-f", "body=" + CLEAN, "-f", "fooco-key=1", cwd=self.other_cwd)
        self.assertBlocked(done, "field 2 key:1: term 1")
        self.assertNotIn("fooco", done.stderr)
        name, texts = self.decide("api", self.EP, "-f", "body=x", "-F", "k=@" + self.file("v.txt", "vv"))
        self.assertEqual(texts, {"field 1": "x", "field 1 key": "body", "field 2": "vv", "field 2 key": "k"})

    def test_a_write_to_the_repository_with_no_text_passes_and_is_logged_without_a_check(self):
        args = ["api", "repos/%s/issues/1/comments/5" % GUARDED, "-X", "DELETE"]
        self.assertRan(self.gh(*args, cwd=self.other_cwd), *args)
        self.assertEqual(self.claude_calls(), 0)
        self.assertEqual([(r["verdict"], r["layer"]) for r in self.gh_log()], [("pass", "none")])


class WrapperGraphql(Decisions):
    MUT = 'mutation { addComment(input: {subjectId: "X", body: "%s"}) { clientMutationId } }'
    MUTV = "mutation($b: String!) { addComment(input: {subjectId: \"X\", body: $b}) { clientMutationId } }"

    def test_a_mutation_is_checked_for_every_directory_and_repository(self):
        for cwd in (self.other_cwd, self.files):
            with self.subTest(cwd):
                self.reset()
                self.assertBlocked(self.gh("api", "graphql", "-f", "query=" + self.MUT % PLANTED, cwd=cwd), "term 1")
        clean = ["api", "graphql", "-f", "query=" + self.MUT % CLEAN]
        self.assertRan(self.gh(*clean, cwd=self.other_cwd), *clean)

    def test_the_variables_are_checked_too(self):
        self.assertBlocked(self.gh("api", "graphql", "-f", "query=" + self.MUTV, "-F", "b=" + PLANTED, cwd=self.other_cwd), "field 2:1: term 1")
        name, texts = self.decide("api", "graphql", "-F", "query=@" + self.file("q.graphql", self.MUTV), "-f", "b=" + PLANTED)
        self.assertEqual((name, PLANTED in texts["field 2"], "addComment" in texts["field 1"]), ("api graphql", True, True))
        name, texts = self.decide("api", "graphql", "-F", "query=@" + self.file("q2.graphql", self.MUT % PLANTED))
        self.assertIn(PLANTED, texts["field 1"])

    def test_json_input_on_stdin_or_in_a_file_is_parsed_and_its_query_and_variables_are_checked(self):
        body = json.dumps({"query": self.MUTV, "variables": {"b": PLANTED}})
        self.assertBlocked(self.gh("api", "graphql", "--input", "-", stdin=body, cwd=self.other_cwd), "term 1")
        self.assertBlocked(self.gh("api", "graphql", "--input", self.file("m.json", body), cwd=self.other_cwd), "term 1")
        clean = json.dumps({"query": self.MUTV, "variables": {"b": CLEAN}})
        done = self.gh("api", "graphql", "--input", "-", stdin=clean, cwd=self.other_cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.real_calls()[-1]["stdin"], clean)

    def test_a_query_passes_straight_through_and_stdin_it_read_goes_on_to_the_real_gh(self):
        q = "query { viewer { login } }  # %s" % PLANTED
        args = ["api", "graphql", "-f", "query=" + q]
        self.assertRan(self.gh(*args), *args)
        self.reset()
        body = json.dumps({"query": "query { viewer { login } }", "variables": {"x": PLANTED}})
        done = self.gh("api", "graphql", "--input", "-", stdin=body)
        self.assertRan(done, "api", "graphql", "--input", "-", stdin=body)
        self.assertEqual(self.claude_calls(), 0)

    def test_a_full_graphql_url_is_the_graphql_endpoint(self):
        for ep in ("https://api.github.com/graphql", "/graphql", "api/graphql"):
            name, texts = self.decide("api", ep, "-f", "query=" + self.MUT % PLANTED)
            self.assertEqual(name, "api graphql", ep)

    def test_the_skip_override_keeps_the_stdin_the_wrapper_read(self):
        done = self.gh("api", "graphql", "--input", "-", stdin="not json", env={"LEAK_GUARD_SKIP": "t"})
        self.assertRan(done, "api", "graphql", "--input", "-", stdin="not json")

    def test_the_word_mutation_in_a_comment_is_not_a_mutation(self):
        args = ["api", "graphql", "-f", "query=# a mutation would go here\nquery { viewer { login } }"]
        self.assertRan(self.gh(*args), *args)
        self.assertEqual(self.claude_calls(), 0)

    def test_an_unreadable_query_file_or_input_that_is_not_json_blocks(self):
        self.assertBlocked(self.gh("api", "graphql", "-F", "query=@" + str(self.files / "nope.graphql"), cwd=self.other_cwd), "cannot read")
        self.assertBlocked(self.gh("api", "graphql", "--input", "-", stdin="this is not json", cwd=self.other_cwd), "not a JSON object")


class WrapperUnrecognised(Decisions):
    def test_a_write_command_it_does_not_recognise_blocks_and_names_the_command(self):
        for args, named in ((["repo", "edit", "--description", "x"], "gh repo edit"), (["label", "create", "bug"], "gh label create"),
                            (["workflow", "run", "ci.yml"], "gh workflow run"), (["secret", "set", "X"], "gh secret set"), (["pr", "frobnicate"], "gh pr frobnicate"),
                            (["frobnicate", "now"], "gh frobnicate"), (["agent-task", "create", "do it"], "gh agent-task")):
            with self.subTest(args):
                self.assertIn(named, self.refused(*args))
        self.reset()
        done = self.gh("label", "create", "bug")
        self.assertBlocked(done, "gh label create")
        self.assertEqual(self.claude_calls(), 0)

    def test_known_write_commands_without_free_text_and_read_commands_pass(self):
        for args in (["pr", "ready", "5"], ["pr", "update-branch", "5"], ["pr", "lock", "5"], ["issue", "pin", "5"], ["run", "rerun", "7"], ["run", "cancel", "7"],
                     ["pr", "list"], ["pr", "view", "5"], ["pr", "diff", "5"], ["pr", "checks", "5"], ["pr", "status"], ["issue", "list"], ["issue", "view", "5"],
                     ["release", "view", "v1"], ["run", "list"], ["run", "view", "7"], ["repo", "view"], ["workflow", "list"], ["label", "list"],
                     ["auth", "status"], ["auth", "token", "-u", "someone"], ["search", "issues", "x"], ["browse"], ["pr"], ["pr", "create", "--help"], ["--version"]):
            with self.subTest(args):
                self.assertEqual(self.decide(*args), ("", None))
        done = self.gh("pr", "ready", "5")
        self.assertRan(done, "pr", "ready", "5")

    def test_a_bare_built_in_group_is_help_and_an_unknown_name_with_no_verb_is_not(self):
        self.assertEqual(self.decide("pr"), ("", None))
        self.assertEqual(self.decide("issue", "-h"), ("", None))
        for args in (["frobnicate"], ["frobnicate", "--draft"], ["prc"]):
            with self.subTest(args):
                self.assertIn("extension", self.refused(*args))
        self.assertEqual(self.decide("frobnicate", repo="someone/other"), ("", None))        # an extension for another repository runs as it is

    def test_an_alias_is_expanded_with_gh_alias_list_and_its_expansion_is_classified(self):
        self.aliases = "\n".join(["co: pr checkout", "prc: pr create --fill", "cm: pr comment $1 -R %s --body \"hello world\"" % GUARDED,
                                  "ship: pr comment -R %s" % GUARDED, "q: 'api graphql -f query=\"mutation { x }\"'", "sh: '!echo $1 | tr a b'",
                                  "it: 'pr comment 5 --body \"it''s fine\"'"])
        self.assertIn("--fill", self.refused("prc"))                                  # prc = pr create --fill
        self.assertIn("--fill", self.refused("prc", "--draft"))
        self.assertEqual(self.decide("co", "5"), ("", None))                          # an alias for a read passes
        name, texts = self.decide("cm", "7", repo="someone/other")                    # the repository is inside the alias
        self.assertEqual((name, texts), ("pr comment", {"body": "hello world"}))
        name, texts = self.decide("ship", "7", "-b", PLANTED, repo=None)              # extra arguments are appended to the expansion
        self.assertEqual((name, PLANTED in texts["body"]), ("pr comment", True))
        self.assertEqual(self.decide("q", repo="someone/other")[0], "api graphql")
        self.assertEqual(self.decide("it")[1], {"body": "it's fine"})
        self.assertIn("shell alias", self.refused("sh", "a"))                         # a shell alias on a guarded repository is refused
        self.assertEqual(self.decide("sh", "a", repo="someone/other"), ("", None))    # and runs for another one
        self.assertIn("more arguments", self.refused("cm"))                           # a $1 with no argument cannot be checked

    def test_an_alias_list_that_cannot_be_read_exactly_refuses(self):
        for aliases, exit_code in (("garbage without a colon", "0"), ("ok: pr list\nbad line", "0"), ("x: pr list", "1")):
            with self.subTest(aliases):
                self.aliases = aliases
                with mock.patch.dict(os.environ, {"FAKE_ALIASES_EXIT": exit_code}):
                    self.assertIn("alias", self.refused("whatever", repo=GUARDED))                       # aimed at a guarded repository: refused
                    self.assertEqual(self.decide("whatever", repo="someone/other"), ("", None))          # not aimed at one: an extension still runs

    def test_a_write_alias_with_only_flags_is_blocked_end_to_end_and_a_bare_group_passes(self):
        done = self.gh("prc", "--draft", env={"FAKE_ALIASES": "prc: pr create --fill"})
        self.assertBlocked(done, "--fill")
        self.reset()
        self.assertRan(self.gh("pr"), "pr")
        self.reset()
        self.assertBlocked(self.gh("some-extension", "run", cwd=self.guarded_cwd), "extension")
        self.reset()
        self.assertRan(self.gh("some-extension", "run", cwd=self.other_cwd), "some-extension", "run")

    def test_an_unrecognised_command_for_an_unguarded_repository_passes(self):
        for args in (["label", "create", "bug"], ["repo", "edit", "someone/other", "--description", "x"], ["some-extension"]):
            with self.subTest(args):
                self.reset()
                self.assertRan(self.gh(*args, cwd=self.other_cwd), *args)

    def test_flags_before_the_command_group_are_refused_when_any_target_is_guarded(self):
        # gh accepts `gh -R <repo> pr comment ...`; the group is not where the wrapper looks first, so the any-target rule decides
        ep = "repos/%s/issues/1/comments" % GUARDED
        url = "https://github.com/%s/pull/3" % GUARDED
        for args in (["-R", GUARDED, "pr", "comment", "3", "-b", "S"], ["--repo=" + GUARDED, "pr", "create", "-t", "T", "-b", "S"],
                     ["-b", "S", "pr", "comment", url], ["-X", "POST", "api", ep, "-f", "body=S"], ["--jq", ".id", "api", ep],
                     ["-R" + GUARDED, "issue", "comment", "3", "-b", "S"], ["--paginate", "api", "repos/%s" % GUARDED]):
            with self.subTest(args):
                self.assertIn("Put the command group first", self.refused(*args, repo="someone/other"))
        for args in (["-R", "someone/other", "pr", "comment", "3", "-b", "S"], ["-b", "S", "pr", "comment", "3"], ["-X", "POST", "api", "user/x"]):
            with self.subTest(args, context="guarded"):          # nothing on the line names it, but GH_REPO or the checkout is guarded
                self.assertIn("Put the command group first", self.refused(*args))
        self.reset()
        done = self.gh("-R", GUARDED, "pr", "comment", "3", "-b", PLANTED, cwd=self.other_cwd)
        self.assertBlocked(done, "Put the command group first")
        self.assertNotIn("fooco", done.stderr)          # the message never repeats the text
        self.reset()
        self.assertBlocked(self.gh("-b", "S", "pr", "comment", "3"), "Put the command group first")                # guarded checkout, nothing else names it
        self.assertEqual([r["command"] for r in self.gh_log()], ["unrecognised", "unrecognised"])

    def test_a_flags_first_command_with_only_unguarded_targets_passes_straight_through_untouched(self):
        for args in (["-R", "someone/other", "pr", "comment", "3", "-b", PLANTED], ["--repo=someone/other", "pr", "create", "-t", PLANTED],
                     ["-b", PLANTED, "pr", "comment", "https://github.com/someone/other/pull/3"], ["-X", "POST", "api", "repos/someone/other/issues/1/comments", "-f", "body=" + PLANTED]):
            with self.subTest(args):
                self.reset()
                done = self.gh(*args, cwd=self.other_cwd, stdin="stdin text\n", env={"FAKE_GH_EXIT": "4"})
                self.assertEqual(done.returncode, 4)
                self.assertEqual((self.real_calls()[0]["argv"], self.real_calls()[0]["stdin"]), (args, "stdin text\n"))
                self.assertIsNone(self.real_calls()[0]["prompt_disabled"])
                self.assertEqual(self.claude_calls(), 0)

    def test_a_lone_version_or_help_flag_passes_and_so_does_a_flags_first_line_when_help_is_all_there_is(self):
        for args in (["--version"], ["-h"], ["--help"]):
            with self.subTest(args):
                self.reset()
                self.assertRan(self.gh(*args), *args)
                self.assertEqual(self.decide(*args), ("", None))
        self.assertEqual(self.decide("--version", repo="someone/other"), ("", None))

    def test_a_subcommand_position_that_could_be_a_flag_value_is_refused_on_a_guarded_context(self):
        # gh takes the first non-flag argument as the subcommand; a flag in front of it makes any word after the flag's value a possible verb
        for args in (["pr", "-t", "view", "create", "-b", "SECRET"], ["pr", "-R", GUARDED, "create", "-b", "SECRET"], ["issue", "--repo", "x/y", "comment", "-b", "S"],
                     ["pr", "-t", "x", "list"]):
            with self.subTest(args):
                self.assertIn("right after", self.refused(*args))
        self.assertEqual(self.decide("pr", "-t", "view", "create", "-b", "SECRET", repo="someone/other"), ("", None))      # nothing guarded: gh runs as typed
        self.assertEqual(self.decide("pr", "--help"), ("", None))
        self.assertEqual(self.decide("pr", "create", "-b", "x", "-t", "y")[0], "pr create")                                # the subcommand first: no doubt

    def test_an_unknown_write_subcommand_is_not_taken_for_a_read_because_a_later_argument_is_a_read_verb(self):
        for args in (["release", "upload", "v1", "view"], ["pr", "revert", "3", "-t", "SECRET", "-b", "view"], ["issue", "frobnicate", "list"]):
            with self.subTest(args):
                self.assertIn("not a command this wrapper knows", self.refused(*args))

    def test_an_unknown_flag_does_not_hide_a_guarded_repository_named_after_it(self):
        self.assertIn("does not know", self.refused("pr", "create", "--newflag", "x", "-R", GUARDED, "-t", "T", "-b", "B", repo="someone/other"))
        self.assertIn("does not know", self.refused("pr", "create", "--newflag", "x", "-t", "T", "https://github.com/%s/pull/3" % GUARDED, repo="someone/other"))
        self.assertEqual(self.decide("pr", "create", "--newflag", "x", "-R", "someone/other", "-t", "T", repo="someone/other"), ("", None))

    def test_repo_commands_take_the_repository_from_their_argument_and_flags_before_the_verb_are_seen(self):
        self.assertBlocked(self.gh("repo", "edit", GUARDED, "--description", "x", cwd=self.other_cwd), "repo edit")
        self.assertBlocked(self.gh("pr", "-R", GUARDED, "create", "--body", PLANTED, cwd=self.other_cwd), "Put the subcommand right after")


class WrapperComposed(Decisions):
    def test_every_way_for_gh_to_write_the_text_itself_blocks_for_a_guarded_repository(self):
        cases = [["pr", "create", f] for f in ("--fill", "--fill-first", "--fill-verbose", "--web", "-w", "--editor", "-e")]
        cases += [["pr", "create", "--template", "t.md"], ["pr", "create", "-T", "t.md"], ["pr", "create", "--recover", "key"],
                  ["pr", "create", "--title", "t", "--body", CLEAN, "--fill"], ["issue", "create", "--template", "bug.md"], ["issue", "create", "--recover", "key"],
                  ["issue", "create", "-w"], ["pr", "comment", "5", "--edit-last"], ["pr", "comment", "5", "--editor"], ["issue", "comment", "5", "--web"],
                  ["pr", "comment", "5", "-e"]]
        for args in cases:
            with self.subTest(args):
                self.assertIn("--body-file", self.refused(*args))
        self.reset()
        self.assertBlocked(self.gh("pr", "create", "--fill"), "--body-file")
        self.assertEqual(self.claude_calls(), 0)

    def test_every_command_where_gh_would_prompt_for_text_is_refused_on_a_terminal_before_gh_runs(self):
        for args in (["pr", "edit", "5"], ["issue", "edit", "5"], ["pr", "edit", "5", "-R", GUARDED], ["pr", "create", "-t", "x"], ["issue", "create", "-t", "x"],
                     ["pr", "create", "-b", "x"], ["release", "create", "v1", "-t", "x"], ["release", "create", "v1"], ["pr", "merge", "5"],
                     ["pr", "comment", "5"], ["pr", "review", "5"], ["pr", "review", "5", "--comment"], ["pr", "review", "5", "--request-changes"]):
            with self.subTest(args):
                self.reset()
                done = self.gh_tty(*args)
                self.assertBlocked(done, "terminal")
                self.assertIn("--body-file" if args[0] != "pr" or args[1] != "merge" else "--squash", done.stderr)

    def test_commands_with_what_gh_needs_do_not_prompt_so_they_pass_on_a_terminal(self):
        for args in (["pr", "edit", "5", "--add-label", "bug"], ["pr", "create", "-t", "x", "-b", CLEAN], ["release", "create", "v1", "-t", "x", "-n", CLEAN],
                     ["release", "create", "v1", "--generate-notes"], ["pr", "merge", "5", "--squash"], ["pr", "merge", "5", "--merge", "--auto"],
                     ["pr", "review", "5", "--approve"], ["pr", "review", "5", "--comment", "-b", CLEAN], ["pr", "comment", "5", "-b", CLEAN],
                     ["issue", "close", "5"]):
            with self.subTest(args):
                self.reset()
                done = self.gh_tty(*args)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(len(self.real_calls()), 1)

    def test_the_real_gh_for_a_guarded_write_runs_with_prompts_switched_off_and_other_commands_are_left_alone(self):
        self.assertRan(self.gh("pr", "comment", "5", "--body", CLEAN), "pr", "comment", "5", "--body", CLEAN)
        self.assertEqual(self.real_calls()[0]["prompt_disabled"], "1")
        for args, cwd in ((["pr", "list"], self.guarded_cwd), (["pr", "comment", "5", "--body", CLEAN], self.other_cwd), (["pr", "merge", "5", "--squash"], self.other_cwd)):
            self.reset()
            self.gh(*args, cwd=cwd)
            self.assertIsNone(self.real_calls()[0]["prompt_disabled"], args)
        self.reset()
        self.gh("pr", "merge", "5", "--squash")                # a guarded write with no text still has prompts off
        self.assertEqual(self.real_calls()[0]["prompt_disabled"], "1")
        self.reset()
        self.gh("pr", "comment", "5", "--body", PLANTED, env={"LEAK_GUARD_SKIP": "r"})        # an override is plain gh
        self.assertIsNone(self.real_calls()[0]["prompt_disabled"])

    def test_the_same_flags_pass_for_an_unguarded_repository(self):
        for args in (["pr", "create", "--fill"], ["pr", "create", "--web"], ["pr", "comment", "5", "--edit-last"], ["issue", "create", "--template", "x"]):
            with self.subTest(args):
                self.reset()
                self.assertRan(self.gh(*args, cwd=self.other_cwd), *args)

    def test_a_title_and_a_body_file_pass_the_check(self):
        args = ["pr", "create", "--title", "t", "--body-file", self.file("ok.md", CLEAN)]
        self.assertRan(self.gh(*args), *args)


class WrapperPassThrough(WrapperBase):
    def test_arguments_stdin_and_exit_code_are_untouched_for_reads_and_unguarded_repositories(self):
        odd = ["pr", "list", "--search", "has space", "", "--json", "a,b", "--", "-x", "ünï", "--body", PLANTED]
        for args, cwd in ((odd, self.guarded_cwd), (["pr", "create", "--title", PLANTED, "--body", PLANTED], self.other_cwd), (["issue", "view", "5"], self.guarded_cwd)):
            with self.subTest(args):
                self.reset()
                done = self.gh(*args, cwd=cwd, stdin="stdin text\nline two\n", env={"FAKE_GH_EXIT": "7"})
                self.assertEqual(done.returncode, 7)
                self.assertEqual(done.stdout, "real gh out\n")
                self.assertEqual(done.stderr, "real gh err\n")
                calls = self.real_calls()
                self.assertEqual((calls[0]["argv"], calls[0]["stdin"]), (args, "stdin text\nline two\n"))
                self.assertEqual(self.claude_calls(), 0)
                self.assertEqual(self.gh_log(), [])

    def test_leak_guard_is_not_run_for_them(self):
        (self.tmp / "leak-guard").write_text("#!/bin/sh\necho RAN >> %s/guard-ran\nexit 1\n" % self.fake)
        self.gh("pr", "list")
        self.gh("pr", "comment", "5", "-R", "someone/other", "--body", PLANTED, cwd=self.other_cwd)
        self.assertFalse((self.fake / "guard-ran").exists())


class WrapperRealGh(WrapperBase):
    def test_copies_symlinks_and_duplicate_path_entries_are_skipped_and_the_real_gh_runs_once(self):
        link = self.tmp / "linkbin"
        link.mkdir()
        os.symlink(self.wbin / "gh", link / "gh")
        copy = self.tmp / "copybin"
        copy.mkdir()
        shutil.copy(self.wbin / "gh", copy / "gh")
        path = ":".join(str(p) for p in (self.wbin, self.wbin, link, copy)) + ":%s:%s:/usr/bin:/bin" % (self.realbin, self.cbin)
        done = self.gh("pr", "list", env={"PATH": path}, timeout=20)
        self.assertRan(done, "pr", "list")
        self.reset()
        done = self.gh("pr", "comment", "5", "--body", CLEAN, env={"PATH": path}, timeout=60)
        self.assertRan(done, "pr", "comment", "5", "--body", CLEAN)

    def test_a_gh_that_is_not_executable_is_skipped(self):
        dud = self.tmp / "dud"
        dud.mkdir()
        (dud / "gh").write_text("#!/bin/sh\nexit 9\n")
        (dud / "gh").chmod(stat.S_IRUSR | stat.S_IWUSR)
        done = self.gh("pr", "list", env={"PATH": "%s:%s:%s:/usr/bin:/bin" % (self.wbin, dud, self.realbin)})
        self.assertRan(done, "pr", "list")

    def test_no_real_gh_on_path_exits_127_with_a_message(self):
        done = self.gh("pr", "list", env={"PATH": "%s:/usr/bin:/bin" % self.wbin}, timeout=20)
        self.assertEqual(done.returncode, 127)
        self.assertIn("no real gh", done.stderr)


class WrapperFailClosed(WrapperBase):
    def test_leak_guard_missing_or_failing_blocks_and_the_real_gh_does_not_run(self):
        done = self.gh("pr", "comment", "5", "--body", CLEAN, env={"LEAK_GUARD_BIN": str(self.tmp / "no-such-leak-guard")})
        self.assertBlocked(done, "cannot be run")
        (self.tmp / "failing").write_text("#!/bin/sh\nexit 2\n")
        (self.tmp / "failing").chmod(0o755)
        done = self.gh("pr", "comment", "5", "--body", CLEAN, env={"LEAK_GUARD_BIN": str(self.tmp / "failing")})
        self.assertBlocked(done)

    def test_a_missing_claude_or_a_timeout_blocks_through_leak_guard(self):
        done = self.gh("pr", "comment", "5", "--body", CLEAN, env={"PATH": "%s:%s:/usr/bin:/bin" % (self.wbin, self.realbin)})
        self.assertBlocked(done, "claude CLI is not on PATH")
        done = self.gh("pr", "comment", "5", "--body", CLEAN, env={"FAKE_CLAUDE": "sleep", "LEAK_GUARD_TIMEOUT_S": "1"})
        self.assertBlocked(done, "timed out")

    def test_with_no_repos_file_or_an_empty_one_everything_passes_straight_through(self):
        repos = self.home / ".config" / "leak-guard" / "repos"
        for content in (None, "# nothing\n"):
            self.reset()
            if content is None:
                repos.unlink()
            else:
                repos.write_text(content)
            self.assertRan(self.gh("pr", "comment", "5", "--body", PLANTED), "pr", "comment", "5", "--body", PLANTED)
        self.assertEqual(self.claude_calls(), 0)

    def test_the_skip_override_runs_the_real_gh_and_is_logged_with_its_reason(self):
        done = self.gh("pr", "comment", "5", "--body", PLANTED, env={"LEAK_GUARD_SKIP": "test reason"})
        self.assertRan(done, "pr", "comment", "5", "--body", PLANTED)
        self.assertEqual(self.claude_calls(), 0)
        rec = self.gh_log()[-1]
        self.assertEqual((rec["verdict"], rec["layer"], rec["reason"]), ("skip", "override", "test reason"))
        self.reset()
        done = self.gh("repo", "edit", "--description", "x", env={"LEAK_GUARD_SKIP": "another"})
        self.assertRan(done, "repo", "edit", "--description", "x")


class WrapperLog(WrapperBase):
    def test_a_pass_a_block_and_a_wrapper_only_block_are_logged_without_text_term_path_or_repository(self):
        self.gh("pr", "create", "--title", "t", "--body-file", self.file("ok.md", CLEAN))
        self.gh("pr", "comment", "5", "--body", PLANTED)
        self.gh("repo", "edit", "--description", "secret words")
        self.gh("pr", "create", "--fill")
        self.gh("api", "graphql", "-f", "query=mutation { x(body: \"%s\") }" % CLEAN)
        rows = self.gh_log()
        self.assertEqual([(r["command"], r["verdict"], r["layer"], r["findings"]) for r in rows],
                         [("pr create", "pass", 2, 0), ("pr comment", "block", 1, 1), ("repo edit", "block", "wrapper", 0),
                          ("pr create", "block", "wrapper", 0), ("api graphql", "pass", 2, 0)])
        for r in rows:
            self.assertEqual(r["mode"], "gh")
            self.assertIn("duration_s", r)
            self.assertIn("utc", r)
        raw = (self.home / ".local" / "state" / "leak-guard" / "log.jsonl").read_text()
        for secret in ("fooco", "gardens", "secret words", "ok.md", "guarded", str(self.tmp)):
            self.assertNotIn(secret, raw)

    def test_a_pass_through_read_writes_no_log_line(self):
        self.gh("pr", "list")
        self.gh("pr", "view", "5", "-R", "someone/other")
        self.assertEqual(self.log(), [])

    def test_the_log_file_is_mode_600_in_a_700_directory(self):
        self.gh("pr", "comment", "5", "--body", CLEAN)
        d = self.home / ".local" / "state" / "leak-guard"
        self.assertEqual(stat.S_IMODE((d / "log.jsonl").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)


if __name__ == "__main__":
    unittest.main()
