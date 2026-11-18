"""The gh wrapper (scripts/gh-wrapper), as a process.

The wrapper is copied to a bin directory as `gh`, ahead of a fake real `gh` on PATH. leak-guard is the real script and `claude` is a fake one.
Every term and repository is invented: "fooco" is term 1, "bar.*baz" term 2, and `fooco-dev/guarded` the one guarded repository.
"""
import importlib.machinery
import importlib.util
import json
import os
import pty
import select
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
WRAPPER = ROOT / "scripts/gh-wrapper"
LIB = ROOT / "scripts/gh-wrapper-lib"
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
if os.environ.get("FAKE_GH_SLEEP"):
    with open(os.path.join(d, "gh.pid"), "w") as f:
        f.write(str(os.getpid()))
    import time
    time.sleep(float(os.environ["FAKE_GH_SLEEP"]))
if os.environ.get("FAKE_GH_SIGNAL"):
    os.kill(os.getpid(), int(os.environ["FAKE_GH_SIGNAL"]))
sys.stdout.write("real gh out\\n")
sys.stderr.write("real gh err\\n")
sys.exit(int(os.environ.get("FAKE_GH_EXIT", "0")))
''' % sys.executable


def lib_copy(dest):
    """The wrapper's lib directory, where the installed wrapper looks for it: ../lib next to its bin directory."""
    shutil.copytree(LIB, dest, ignore=shutil.ignore_patterns("__pycache__"))


def script_copy(src, dest):
    text = src.read_text().split("\n", 1)
    dest.write_text("#!%s\n%s" % (sys.executable, text[1]))
    dest.chmod(0o755)


def spawn_ready(test, argv, timeout=20, **kw):
    """Start a process and return it once it has said `ready` on its standard output, which it prints after it has started its program.
    Read /proc/<pid> or ps for a process only after this: until its exec finishes, the kernel gives it no command line (it reads as empty) and no
    environment. The process is killed and reaped when the test ends. A process that says nothing within `timeout` seconds fails the test."""
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, **kw)
    test.addCleanup(child.stdout.close)
    test.addCleanup(child.wait)
    test.addCleanup(child.kill)
    if not select.select([child.stdout], [], [], timeout)[0] or child.stdout.readline().strip() != "ready":
        test.fail("%s never said ready within %ss" % (argv, timeout))
    return child


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
        lib_copy(self.tmp / "lib")
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
            name, texts, _targets = self.W.decide(list(args), self.REPOS, None, str(self.realbin / "gh"))
        return name, ({l: d.decode() for l, d in texts.items} if texts else None)

    def refused(self, *args, repo=GUARDED):
        env = {"GH_HOST": "github.com", "FAKE_ALIASES": self.aliases, **({"GH_REPO": repo} if repo else {})}
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(self.W.Refuse) as caught:
                self.W.decide(list(args), self.REPOS, None, str(self.realbin / "gh"))
        return str(caught.exception)


def load_flags_script():
    loader = importlib.machinery.SourceFileLoader("leak_guard_gh_flags", str(ROOT / "scripts/leak-guard-gh-flags"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("leak_guard_gh_flags", loader))
    loader.exec_module(mod)
    return mod


# the help parser and the lookup of the installed gh are the regeneration script's: the table test and the script read gh the same way
FLAGS_SCRIPT = load_flags_script()
installed_gh, help_flags = FLAGS_SCRIPT.installed_gh, FLAGS_SCRIPT.help_flags


@unittest.skipUnless(installed_gh(), "needs the real gh")
class FlagTables(unittest.TestCase):
    """The wrapper's FLAGS table is gh's own flag list, as of the release named by FLAGS_FROM_GH. Where the installed gh is that release, the table must match
    it. Another release is reported and not compared: a newer gh may list flags the table does not, and the wrapper refuses an unknown flag for a guarded
    repository until the table is regenerated (docs/leak-guard.md, Limits). To compare against a particular gh, set LEAK_GUARD_TEST_GH to its path."""
    W = load_wrapper()

    def test_every_table_matches_what_the_installed_gh_lists_for_that_command(self):
        gh = installed_gh()
        version = subprocess.run([gh, "--version"], capture_output=True, text=True).stdout.split()[2]
        if version != self.W.FLAGS_FROM_GH:
            print("\nFlagTables: the installed gh is %s and the tables are from %s, so they are not compared; regenerate FLAGS from `gh <command> --help` of "
                  "the new release and set FLAGS_FROM_GH" % (version, self.W.FLAGS_FROM_GH), file=sys.stderr)
            return
        for (group, verb), spec in self.W.FLAGS.items():
            with self.subTest(group=group, verb=verb):
                ours = set()
                for item in spec.split(","):
                    short, _, rest = item.rpartition(":")
                    ours.add((short, rest.rstrip("="), rest.endswith("=")))
                command = (group,) + ((verb,) if verb else ())
                theirs = set(help_flags(gh, *command))
                # gh accepts -h for --help but does not list it
                ours = {("", l, t) if l == "help" else (s, l, t) for s, l, t in ours}
                self.assertEqual(ours, theirs, "the FLAGS table for `gh %s` no longer matches `gh %s --help` (gh %s)" % (" ".join(command), " ".join(command), version))

    def test_the_tables_name_the_gh_release_they_came_from(self):
        self.assertRegex(self.W.FLAGS_FROM_GH, r"^\d+\.\d+\.\d+$")


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


class WrapperTextTarget(WrapperBase):
    """The guard is told which repository the text is being posted to, so only that repository's published names can become the base (round 1, f1)."""

    def recording_guard(self):
        rec = self.tmp / "rec-guard"
        nl = chr(10)
        rec.write_text("#!/usr/bin/env python3" + nl
                       + "import json, sys" + nl
                       + "open(%s, 'w').write(json.dumps(sys.argv[1:]))" % json.dumps(str(self.fake / "guard-args")) + nl
                       + "exit(0)" + nl)
        rec.chmod(0o755)
        return rec

    def guard_args(self):
        return json.loads((self.fake / "guard-args").read_text())

    def test_a_text_command_aimed_at_one_guarded_repo_passes_it_as_repo(self):
        done = self.gh("pr", "comment", "5", "--body", CLEAN, env={"LEAK_GUARD_BIN": str(self.recording_guard())})
        self.assertEqual(done.returncode, 0, done.stderr)
        args = self.guard_args()
        self.assertIn("--repo", args)
        self.assertEqual(args[args.index("--repo") + 1], "github.com/%s" % GUARDED)
        self.assertIn("--result", args)

    def test_a_repo_named_by_both_repo_and_the_checkout_is_one_target_and_is_passed_as_repo(self):
        for spelling in (GUARDED, GUARDED.upper(), "https://github.com/%s.git" % GUARDED):
            done = self.gh("pr", "comment", "5", "--body", CLEAN, "--repo", spelling, env={"LEAK_GUARD_BIN": str(self.recording_guard())})
            self.assertEqual(done.returncode, 0, done.stderr)
            args = self.guard_args()
            self.assertIn("--repo", args, spelling)
            self.assertEqual(args[args.index("--repo") + 1], "github.com/%s" % GUARDED, spelling)

    def test_a_command_aimed_at_two_guarded_repos_passes_no_repo(self):
        (self.home / ".config" / "leak-guard" / "repos").write_text("%s\nfooco-dev/second\n" % GUARDED)
        done = self.gh("pr", "comment", "5", "--body", CLEAN, "--repo", "fooco-dev/second", env={"LEAK_GUARD_BIN": str(self.recording_guard())})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("--repo", self.guard_args(), "which of two guarded repos gh would pick cannot be told, so there is no base")


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

    def test_attach_uploads_files_whose_content_cannot_be_read_so_it_is_refused(self):
        for group, verb in (("pr", "create"), ("pr", "edit"), ("pr", "comment"), ("issue", "create"), ("issue", "edit"), ("issue", "comment")):
            for attach in (["--attach", "shot.png"], ["--attach=shot.png#alt text"]):
                with self.subTest(group=group, verb=verb, attach=attach):
                    title = [] if verb == "comment" else ["-t", "x"]
                    self.assertIn("--attach would upload", self.refused(group, verb, *title, "-b", CLEAN, *attach))
        self.assertEqual(self.decide("pr", "create", "-t", "x", "-b", CLEAN)[0], "pr create")        # without it, checked as usual

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
        for flag in ("--help", "-h"):      # help runs a help command the wrapper builds itself: see WrapperHelpNeverSkipsTheCheck
            with self.assertRaises(self.W.Help) as help_run:
                self.decide("pr", "create", flag)
            self.assertEqual(help_run.exception.argv, ["pr", "create", "--help"])
        name, texts = self.decide("pr", "create", "-t", "x", "--body", "-h")
        self.assertEqual((name, texts["body"]), ("pr create", "-h"))
        name, texts = self.decide("pr", "create", "-t", "-h", "--body", "y")
        self.assertEqual(texts["title"], "-h")
        self.assertEqual(self.decide("api", "repos/%s/issues/1/comments" % GUARDED, "-f", "body=-h")[0], "api")
        with self.assertRaises(self.W.Help) as help_run:
            self.decide("api", "repos/%s/issues/1/comments" % GUARDED, "-f", "body=x", "--help")
        self.assertEqual(help_run.exception.argv, ["api", "--help"])
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
            name, texts, _targets = self.W.decide(["api", "--hostname", "ghe.example.test", "repos/team/proj/issues", "-f", "body=x"], {("ghe.example.test", "team/proj")})
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
                     ["auth", "status"], ["auth", "token", "-u", "someone"], ["search", "issues", "x"], ["browse"], ["pr"], ["--version"]):
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
        for args in (["pr", "-t", "view", "create", "-b", "SECRET"], ["pr", "-t", "x", "list"], ["pr", "--", "view", "3"], ["pr", "--frob", "view", "3"],
                     ["issue", "-xR", "x/y", "comment", "-b", "S"]):
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
        self.assertBlocked(self.gh("pr", "-R", GUARDED, "create", "--body", PLANTED, cwd=self.other_cwd), "term 1")


def outcome(case, *args, repo=GUARDED):
    """What the wrapper decides for a command: ("refused", message), ("help", the argument list it would run instead, note) or ("ok", command name, gathered texts)."""
    try:
        return ("ok",) + case.decide(*args, repo=repo)
    except case.W.Refuse as r:
        return ("refused", str(r))
    except case.W.Help as h:
        return ("help", h.argv, h.note)


class WrapperGroupFlags(Decisions):
    """gh finds the subcommand after the flags of the group (`gh pr -R x view 3` is `gh pr view 3 -R x`). The wrapper reads the group's own flags from its table
    and decides on the command as if they stood after the verb."""
    VERBS = {"pr": [["view", "3"], ["list"], ["comment", "3", "-b", PLANTED], ["comment", "3", "-b", CLEAN], ["create", "-t", "T", "-b", "B"], ["create", "--fill"],
                    ["edit", "3", "-t", "T"], ["review", "3", "-r", "-b", PLANTED], ["merge", "3", "--squash"], ["ready", "3"], ["frobnicate", "x"],
                    ["close", "3", "-c", "hi"]],
             "issue": [["view", "3"], ["comment", "3", "-b", PLANTED], ["create", "-t", "T", "-b", "B"], ["frobnicate"]],
             "release": [["view", "v1"], ["create", "v1", "-n", PLANTED], ["upload", "v1", "f"]],
             "run": [["view", "7"], ["rerun", "7"]], "label": [["list"], ["create", "bug"]]}
    flag_forms = lambda self, repo: [["-R", repo], ["-R" + repo], ["-R=" + repo], ["--repo", repo], ["--repo=" + repo], ["-R", repo, "-R", repo]]

    def test_a_group_flag_before_the_verb_decides_like_the_same_flag_after_the_verb(self):
        seen = set()
        for group, verbs in self.VERBS.items():
            for verb in verbs:
                for target in (GUARDED, "someone/other"):
                    for flags in self.flag_forms(target):
                        with self.subTest(group=group, verb=verb, flags=flags):
                            before = outcome(self, group, *flags, *verb, repo="someone/other")
                            after = outcome(self, group, *verb, *flags, repo="someone/other")
                            self.assertEqual(before, after)
                            seen.add(before[0] + (":" + before[1] if before[0] == "ok" and before[2] else ""))
        self.assertEqual(seen, {"ok", "ok:pr comment", "ok:pr create", "ok:pr edit", "ok:pr review", "ok:pr close", "ok:issue comment", "ok:issue create", "ok:release create", "refused"})

    def test_only_the_repo_flag_is_accepted_before_the_verb(self):
        """Every flag of every group row but -R/--repo, in every form, makes the verb unknown: normalize_group_flags returns None, and the command is rebuilt as help
        (a help token) or refused on a guarded repository. Nothing but the five -R/--repo spellings is read."""
        W = self.W
        for spelling in (["-R", "x/y"], ["-Rx/y"], ["-R=x/y"], ["--repo", "x/y"], ["--repo=x/y"]):
            self.assertEqual(W.normalize_group_flags(["pr", *spelling, "view", "3"]), ["pr", "view", *spelling, "3"], spelling)
        for (group, verb), spec in W.FLAGS.items():
            if verb or group == "api":
                continue
            for item in spec.split(","):
                short, _, rest = item.rpartition(":")
                long, takes = rest.rstrip("="), rest.endswith("=")
                if long == "repo":
                    continue      # the one flag read: the five spellings above
                for spelling in ([["--" + long], ["--" + long + "=v"], ["--" + long, "v"], ["-" + short], ["-" + short + "=v"], ["-" + short, "v"], ["-" + short + "v"]] if short
                                 else [["--" + long], ["--" + long + "=v"], ["--" + long, "v"]]):
                    with self.subTest(group=group, flag=spelling):
                        self.assertIsNone(W.normalize_group_flags([group, *spelling, "view", "3"]))
        for spelling in (["--help"], ["--help=false"], ["-h"], ["-h", "--help"], ["--frob"]):
            result = outcome(self, "repo", *spelling, "view", "edit", GUARDED, "--description", PLANTED, repo="someone/other")
            self.assertIn(result[0], ("help", "refused"), spelling)
            if result[0] == "help":
                self.assertEqual(result[1][-1], "--help")

    def test_h_before_the_verb_is_never_a_switch_because_gh_takes_the_next_argument_as_its_value(self):
        """gh has no -h at group level: `gh pr -h view` shows `gh pr`'s help (view is skipped as -h's value), and `gh repo -h view edit ...` runs `repo edit` with
        `-h view` read as --homepage. So -h in that position, in every form, leaves the verb unknown: help is rebuilt, never the user's arguments."""
        for group, verb in (("repo", ["view", "edit", GUARDED, "--description", PLANTED]), ("pr", ["view", "comment", "3", "-b", PLANTED, "-R", GUARDED]), ("issue", ["view", "comment", "3", "-b", PLANTED, "-R", GUARDED])):
            for flag in (["-h"], ["-h=false"], ["-h=true"], ["-hview"], ["-h", "--help=false"], ["-R", GUARDED, "-h"]):
                with self.subTest(group=group, flag=flag):
                    result = outcome(self, group, *flag, *verb, repo="someone/other")
                    self.assertEqual(result[0], "help", result)
                    self.assertEqual(result[1][-1], "--help")
                    self.assertNotIn(PLANTED, " ".join(result[1]))
        self.assertEqual(outcome(self, "repo", "-h", "view", "edit", GUARDED, "--description", PLANTED, repo="someone/other")[0], "help")

    def test_end_to_end_the_reviewers_repo_h_view_edit_command_never_reaches_gh_with_its_arguments(self):
        for argv in (["repo", "-h", "view", "edit", GUARDED, "--description", PLANTED], ["repo", "-h=x", "view", "edit", GUARDED, "--description", PLANTED]):
            with self.subTest(argv):
                self.reset()
                done = self.gh(*argv, cwd=self.other_cwd)
                self.assertEqual([c["argv"] for c in self.real_calls()], [["repo", "view", "--help"]], done.stderr)
                self.assertEqual(self.claude_calls(), 0)

    def test_a_read_with_a_group_flag_before_the_verb_is_not_refused(self):
        for args in (["pr", "-R", GUARDED, "view", "3"], ["pr", "--repo=" + GUARDED, "list"], ["issue", "-R" + GUARDED, "view", "3"], ["run", "-R", GUARDED, "view", "7"],
                     ["pr", "-R", GUARDED, "ready", "3"], ["pr", "-R", GUARDED], ["pr", "-h", "view", "3"], ["pr", "--help", "view"]):
            with self.subTest(args):
                self.assertEqual(self.decide(*args, repo="someone/other"), ("", None))

    def test_a_write_after_a_group_flag_gathers_its_text_and_an_unknown_write_is_refused_as_before(self):
        name, texts = self.decide("pr", "-R", GUARDED, "comment", "3", "-b", PLANTED, repo="someone/other")
        self.assertEqual((name, texts), ("pr comment", {"body": PLANTED}))
        self.assertIn("not a command this wrapper knows", self.refused("pr", "-R", GUARDED, "frobnicate", repo="someone/other"))
        self.assertIn("--body-file", self.refused("pr", "-R", GUARDED, "create", "--fill", repo="someone/other"))

    def test_any_other_flag_or_a_double_dash_in_that_position_stays_refused(self):
        for args in (["pr", "--frob", "view", "3"], ["pr", "-t", "view", "3"], ["pr", "--", "view", "3"], ["pr", "-R", "x/y", "-t", "view", "3"], ["issue", "--title", "x", "comment", "3"],
                     ["repo", "-R", GUARDED, "view"]):          # `gh repo` has no -R of its own
            with self.subTest(args):
                self.assertIn("right after", self.refused(*args))

    def test_end_to_end_a_read_runs_untouched_and_a_write_is_checked_with_the_original_arguments(self):
        args = ["pr", "-R", GUARDED, "view", "3"]
        self.assertRan(self.gh(*args, cwd=self.other_cwd), *args)
        self.assertEqual((self.claude_calls(), self.gh_log()), (0, []))
        self.reset()
        self.assertBlocked(self.gh("pr", "-R", GUARDED, "comment", "3", "-b", PLANTED, cwd=self.other_cwd), "body:1: term 1")
        self.assertEqual([(r["command"], r["verdict"], r["layer"]) for r in self.gh_log()], [("pr comment", "block", 1)])
        self.reset()
        args = ["pr", "--repo=" + GUARDED, "comment", "3", "-b", CLEAN]
        done = self.gh(*args, cwd=self.other_cwd)
        self.assertRan(done, *args)
        self.assertEqual(self.real_calls()[0]["prompt_disabled"], "1")


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
        done = self.gh("pr", "list", env={"PATH": str(self.wbin)}, timeout=20)          # only the wrapper's own directory: a runner may have a gh in /usr/bin
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

class WrapperHelpValue(Decisions):
    """`--help=false` is not help (gh's flag library parses a boolean flag's value with strconv.ParseBool), so the command still sends its text. `-h=false` is
    different in gh: it has no -h flag, so any `-h` shows help. The wrapper reads `-h=false` like `--help=false` and checks the text, which is stricter and safe."""
    TRUE = ("true", "TRUE", "True", "t", "T", "1")
    NOT_TRUE = ("false", "FALSE", "False", "f", "F", "0", "no", "")      # the first six are false; "no" and "" gh rejects as invalid, and neither is help here

    def test_help_with_a_value_that_is_not_true_does_not_hide_the_text_in_any_position(self):
        for value in self.NOT_TRUE:
            for flag in ("--help=" + value, "-h=" + value):
                for args in (["pr", "comment", "3", flag, "-b", PLANTED], ["issue", "comment", "3", "-b", PLANTED, flag]):
                    with self.subTest(args):
                        result = outcome(self, *args)
                        self.assertEqual(result[:2], ("ok", args[0] + " comment"), result)
                        self.assertEqual(result[2]["body"], PLANTED)
                for args in (["pr", flag, "comment", "3", "-b", PLANTED], ["pr", "-R", GUARDED, flag, "comment", "3", "-b", PLANTED]):      # before the verb: not read at all
                    with self.subTest(args):
                        self.assertEqual(outcome(self, *args), ("help", ["pr", "comment", "--help"], None))

    def test_help_with_a_true_value_shows_the_commands_help_and_forwards_none_of_the_arguments(self):
        for flag in ["--help", "-h"] + ["--help=" + v for v in self.TRUE] + ["-h=" + v for v in self.TRUE]:
            for args in (["pr", "comment", "3", flag, "-b", PLANTED], ["issue", "comment", "3", "-b", PLANTED, flag]):
                with self.subTest(args):
                    self.assertEqual(outcome(self, *args), ("help", [args[0], "comment", "--help"], None))
        ep = "repos/%s/issues/1/comments" % GUARDED
        self.assertEqual(outcome(self, "api", ep, "-f", "body=" + PLANTED, "--help=false", repo="someone/other")[:2], ("ok", "api"))
        for flag in ("--help=true", "--help"):
            self.assertEqual(outcome(self, "api", ep, "-f", "body=" + PLANTED, flag, repo="someone/other"), ("help", ["api", "--help"], None))

    def test_end_to_end_help_false_is_checked_and_help_true_runs_the_rebuilt_help(self):
        for args in (["pr", "comment", "3", "--help=false", "-b", PLANTED, "-R", GUARDED],):
            with self.subTest(args):
                self.reset()
                self.assertBlocked(self.gh(*args, cwd=self.other_cwd), "term 1")
        for args in (["pr", "--help=true", "comment", "3", "-b", PLANTED, "-R", GUARDED], ["pr", "--help=false", "comment", "3", "-b", PLANTED, "-R", GUARDED],
                     ["pr", "comment", "3", "--help=true", "-b", PLANTED, "-R", GUARDED]):      # a help flag before the verb is never read: help is rebuilt
            with self.subTest(args):
                self.reset()
                self.assertRan(self.gh(*args, cwd=self.other_cwd), "pr", "comment", "--help")


class WrapperHelpNeverSkipsTheCheck(Decisions):
    """Guard for a mistake class that two review rounds found: the wrapper skipped its text check when it read a command as a help request, using its own copy
    of gh's help semantics (`--help=false`, a repeated `--help`, ...), and the copy drifted from gh. A help flag, in any spelling, count, order or position, must
    never make the wrapper skip checking the text a command carries. It may only relax the refusals that exist because gh would prompt for text."""
    SPELLINGS = ("--help", "-h", "--help=true", "--help=false", "--help=1", "--help=0", "--help=T", "--help=F", "-h=true", "-h=false", "--help=")
    PAIRS = [(a, b) for a in ("--help", "-h", "--help=true", "--help=false", "--help=1", "--help=0") for b in ("--help", "-h", "--help=true", "--help=false", "--help=0")]
    WHY = "help must never skip the text check: a help spelling made the wrapper run gh without checking the text. "
    BUILT_IN_WORDS = {w for g, verbs in (*Decisions.W.READ.items(), *Decisions.W.NOTEXT.items()) for w in (g, *verbs)} | {g for g, _ in Decisions.W.TEXT} | {v for _, v in Decisions.W.TEXT} | {"api", "--help"}

    def cases(self):
        """(label, argv) of every command that carries PLANTED, with help spelled every way before the verb, after it, or both."""
        helps = [(h,) for h in self.SPELLINGS] + self.PAIRS + [("--help", "--help=false", "-h"), ("--help=false", "--help=true", "--help=false")]
        for group, verb in (("pr", "comment"), ("issue", "comment")):
            for h in helps:
                for text in (["-b", PLANTED], ["--body", PLANTED], ["--body=" + PLANTED], ["-b" + PLANTED]):
                    yield "%s after the verb" % group, [group, verb, "3", *text, *h, "-R", GUARDED]
                    yield "%s before the verb" % group, [group, *h, verb, "3", *text, "-R", GUARDED]
                    yield "%s on both sides" % group, [group, h[0], verb, "3", *text, *h[1:], "-R", GUARDED]
                    yield "%s in group position after -R" % group, [group, "-R", GUARDED, *h, verb, "3", *text]
        ep = "repos/%s/issues/1/comments" % GUARDED
        for h in helps:
            for fields in (["-f", "body=" + PLANTED], ["--raw-field", "body=" + PLANTED], ["-F", "body=" + PLANTED], ["--field=body=" + PLANTED]):
                yield "gh api", ["api", ep, *fields, *h]
                yield "gh api (help first)", ["api", *h, ep, *fields]

    def blocked(self, argv):
        """True when the wrapper refuses the command, gathers the planted text for the check, or runs gh with an argument list of its own that holds only built-in
        names and --help; False when it would hand the planted text to gh without looking."""
        result = outcome(self, *argv, repo="someone/other")
        if result[0] == "help":
            return all(w in self.BUILT_IN_WORDS for w in result[1] or []) and (result[1] or ["--help"])[-1] == "--help"
        return result[0] == "refused" or any(PLANTED in text for text in (result[2] or {}).values())

    def test_a_help_flag_in_any_spelling_count_or_position_never_skips_the_text_check(self):
        unchecked = [(label, argv) for label, argv in self.cases() if not self.blocked(argv)]
        self.assertEqual(unchecked, [], self.WHY + "%d of the cases ran gh unchecked, e.g. %s" % (len(unchecked), unchecked[:3]))

    def test_end_to_end_a_planted_term_is_blocked_whatever_the_help_flags(self):
        for argv in (["pr", "comment", "3", "--help", "--help=false", "-b", PLANTED, "-R", GUARDED],
                     ["pr", "comment", "3", "--help=true", "--help=false", "--body", PLANTED, "-R", GUARDED],
                     ["api", "repos/%s/issues/1/comments" % GUARDED, "-f", "body=" + PLANTED, "--help", "--help=false"]):
            with self.subTest(argv):
                self.reset()
                self.assertBlocked(self.gh(*argv, cwd=self.other_cwd), "term 1")

    def test_a_plain_help_request_reaches_ghs_help_without_a_claude_call(self):
        for argv, ran in ((["pr", "comment", "--help", "-R", GUARDED], ["pr", "comment", "--help"]), (["pr", "comment", "-h", "-R", GUARDED], ["pr", "comment", "--help"]),
                          (["pr", "--help", "comment", "-R", GUARDED], ["pr", "comment", "--help"]), (["issue", "create", "--help", "-R", GUARDED], ["issue", "create", "--help"]),
                          (["pr", "create", "--help", "-R", GUARDED], ["pr", "create", "--help"]), (["repo", "edit", "--help", "-R", GUARDED], ["repo", "--help"]),
                          (["pr", "view", "--help"], ["pr", "view", "--help"]), (["pr", "--help"], ["pr", "--help"]), (["api", "--help"], ["api", "--help"])):
            with self.subTest(argv):
                self.reset()
                self.assertRan(self.gh(*argv, cwd=self.other_cwd), *ran)
                self.assertEqual(self.claude_calls(), 0)
        self.reset()
        logged = len(self.gh_log())
        self.assertRan(self.gh("pr", "view", "--help"), "pr", "view", "--help")      # in a guarded checkout too, and a read writes no log line
        self.assertEqual(len(self.gh_log()), logged)


class WrapperHelpRunsOnlyBuiltInNames(WrapperBase):
    """The rule behind WrapperHelpNeverSkipsTheCheck: when the wrapper reads a command on a guarded repository as a help request it never forwards the user's
    arguments. It runs gh with an argument list it builds itself, `<group> [<verb>] --help`, from built-in names only, with standard input closed. Each row is
    the exact argument list that reached the real gh (None: gh was not run) and the text of the refusal or note, if any."""
    ALIAS = {"sh": "sh: !echo hi", "prc": "prc: pr create --fill"}
    # label: (argv, environment, the argument list the real gh got, a word in what the wrapper printed)
    ROWS = [
        ("--help", ["pr", "comment", "3", "--help", "-b", PLANTED, "-R", GUARDED], {}, ["pr", "comment", "--help"], None),
        ("-h", ["pr", "comment", "3", "-h", "-b", PLANTED, "-R", GUARDED], {}, ["pr", "comment", "--help"], None),
        ("--help=true", ["pr", "comment", "3", "--help=true", "-b", PLANTED, "-R", GUARDED], {}, ["pr", "comment", "--help"], None),
        ("help flag before the verb", ["pr", "--help", "comment", "3", "-b", PLANTED, "-R", GUARDED], {}, ["pr", "comment", "--help"], None),
        ("-t --help", ["pr", "comment", "3", "-t", "--help", "-b", PLANTED, "-R", GUARDED], {}, ["pr", "comment", "--help"], None),
        ("-dh", ["pr", "comment", "3", "-dh", "-b", PLANTED, "-R", GUARDED], {}, ["pr", "comment", "--help"], None),
        ("review f1: repo -h view edit", ["repo", "-h", "view", "edit", GUARDED, "--description", PLANTED], {}, ["repo", "view", "--help"], None),
        ("--help then --help=false is checked", ["pr", "comment", "3", "--help", "--help=false", "-b", PLANTED, "-R", GUARDED], {}, None, "term"),
        ("--help=foo is checked", ["pr", "comment", "3", "--help=foo", "-b", PLANTED, "-R", GUARDED], {}, None, "term"),
        ("-- --help is a word, checked", ["pr", "comment", "3", "-b", PLANTED, "-R", GUARDED, "--", "--help"], {}, None, "term"),
        ("repo edit -d --help", ["repo", "edit", GUARDED, "-d", "--help"], {}, ["repo", "--help"], None),
        ("round 3: label create --color -h", ["label", "create", "foo", "--color", "-h", "--description", PLANTED, "-R", GUARDED], {}, ["label", "--help"], None),
        ("round 3: repo edit --homepage -h", ["repo", "edit", GUARDED, "--homepage", "-h", "--description", PLANTED], {}, ["repo", "--help"], None),
        ("an unrecognised write without help is refused", ["label", "create", "foo", "--description", PLANTED, "-R", GUARDED], {}, None, "not a command this wrapper knows"),
        ("gh api, true", ["api", "repos/%s/issues/1/comments" % GUARDED, "-f", "body=" + PLANTED, "--help"], {}, ["api", "--help"], None),
        ("gh api, last false is checked", ["api", "repos/%s/issues/1/comments" % GUARDED, "-f", "body=" + PLANTED, "--help", "--help=false"], {}, None, "term"),
        ("shell alias", ["sh", "--help", "-R", GUARDED], ALIAS, None, "sh = !echo hi"),
        ("non-shell alias", ["prc", "--help", "--title", PLANTED, "-R", GUARDED], ALIAS, ["pr", "create", "--help"], "prc = pr create --fill"),
        ("extension", ["some-extension", "--help", "-R", GUARDED], {}, None, "own code"),
    ]
    def test_each_command_reaches_the_real_gh_with_exactly_this_argument_list(self):
        for label, argv, extra, ran, said in self.ROWS:
            with self.subTest(label):
                self.reset()
                done = self.gh(*argv, cwd=self.other_cwd, env={"FAKE_ALIASES": self.ALIAS.get(argv[0], "co: pr checkout")} if extra else None)
                calls = self.real_calls()
                self.assertEqual([c["argv"] for c in calls], [ran] if ran else [], done.stderr)
                if ran:
                    self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertEqual(calls[0]["stdin"], "")
                    self.assertEqual(self.claude_calls(), 0)
                    self.assertTrue(ran[-1] == "--help" and all(w.isalpha() for w in ran[:-1]), "a help run holds only path words and --help: %r" % ran)
                if said:
                    self.assertIn(said, done.stdout + done.stderr)
                else:
                    self.assertNotIn("BLOCKED", done.stderr)

    def test_help_on_a_repository_that_is_not_guarded_is_not_rewritten(self):
        self.assertRan(self.gh("pr", "comment", "3", "--help", "-R", "someone/other", cwd=self.other_cwd), "pr", "comment", "3", "--help", "-R", "someone/other")


if __name__ == "__main__":
    unittest.main()
