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
import json, os, sys
d = os.environ["FAKE"]
stdin = sys.stdin.read() if os.environ.get("FAKE_GH_STDIN") else ""
with open(os.path.join(d, "gh-calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin, "prompt_disabled": os.environ.get("GH_PROMPT_DISABLED")}) + "\\n")
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

    def decide(self, *args):
        with mock.patch.dict(os.environ, {"GH_REPO": GUARDED, "GH_HOST": "github.com"}):
            name, texts = self.W.decide(list(args), self.REPOS)
        return name, ({l: d.decode() for l, d in texts.items} if texts else None)

    def refused(self, *args):
        with mock.patch.dict(os.environ, {"GH_REPO": GUARDED, "GH_HOST": "github.com"}):
            with self.assertRaises(self.W.Refuse) as caught:
                self.W.decide(list(args), self.REPOS)
        return str(caught.exception)


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

    def test_dash_R_and_repo_name_the_repository_and_beat_the_current_directory(self):
        for flags in (["-R", GUARDED], ["--repo", GUARDED], ["--repo=" + GUARDED], ["-R" + GUARDED.upper()]):
            with self.subTest(flags):
                self.assertBlocked(self.gh("pr", "comment", "5", *flags, "--body", PLANTED, cwd=self.other_cwd), "term 1")
        self.assertRan(self.gh("pr", "comment", "5", "-R", "someone/other", "--body", PLANTED, cwd=self.guarded_cwd),
                       "pr", "comment", "5", "-R", "someone/other", "--body", PLANTED)

    def test_a_github_url_argument_names_the_repository_and_beats_the_current_directory(self):
        url = "https://github.com/%s/pull/5" % GUARDED
        self.assertBlocked(self.gh("pr", "comment", url, "--body", PLANTED, cwd=self.other_cwd), "term 1")
        other = "https://github.com/someone/other/pull/5"
        self.assertRan(self.gh("pr", "comment", other, "--body", PLANTED, cwd=self.guarded_cwd), "pr", "comment", other, "--body", PLANTED)

    def test_a_url_inside_the_body_text_does_not_name_the_repository(self):
        body = "see https://github.com/%s/pull/5 for details" % GUARDED
        self.assertRan(self.gh("pr", "comment", "5", "--body", body, cwd=self.other_cwd), "pr", "comment", "5", "--body", body)
        self.assertEqual(self.claude_calls(), 0)

    def test_gh_repo_names_the_repository_and_dash_R_beats_it(self):
        self.assertBlocked(self.gh("pr", "comment", "5", "--body", PLANTED, cwd=self.other_cwd, env={"GH_REPO": GUARDED}), "term 1")
        self.assertRan(self.gh("pr", "comment", "5", "-R", "someone/other", "--body", PLANTED, cwd=self.other_cwd, env={"GH_REPO": GUARDED}),
                       "pr", "comment", "5", "-R", "someone/other", "--body", PLANTED)

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

    def test_a_flag_cluster_that_may_hide_a_text_flag_blocks(self):
        self.assertBlocked(self.gh("pr", "create", "-dt", PLANTED), "cluster")


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
        self.assertBlocked(self.gh("api", self.EP, "-f", "body=" + PLANTED, cwd=self.other_cwd), "field body:1: term 1")
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
                self.assertEqual(self.decide(*args), ("", None))

    def test_an_uploads_host_url_names_the_repository_and_a_numeric_repository_id_is_refused_for_a_write(self):
        name, texts = self.decide("api", "https://uploads.github.com/%s/releases/1/assets" % self.EP.split("/issues")[0], "-f", "body=" + PLANTED)
        self.assertEqual(name, "api")
        self.assertIn("numeric id", self.refused("api", "repositories/123/issues/1/comments", "-f", "body=" + CLEAN))
        self.assertEqual(self.decide("api", "repositories/123/issues/1/comments"), ("", None))        # a read passes
        done = self.gh("api", "repositories/123/issues/1/comments", "-X", "POST", cwd=self.other_cwd)
        self.assertBlocked(done, "numeric id")

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
        self.assertBlocked(self.gh("api", "graphql", "-f", "query=" + self.MUTV, "-F", "b=" + PLANTED, cwd=self.other_cwd), "field b:1: term 1")
        name, texts = self.decide("api", "graphql", "-F", "query=@" + self.file("q.graphql", self.MUTV), "-f", "b=" + PLANTED)
        self.assertEqual((name, PLANTED in texts["field b"], "addComment" in texts["field query"]), ("api graphql", True, True))
        name, texts = self.decide("api", "graphql", "-F", "query=@" + self.file("q2.graphql", self.MUT % PLANTED))
        self.assertIn(PLANTED, texts["field query"])

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
                            (["frobnicate", "now"], "gh frobnicate"), (["co", "5"], "gh co"), (["agent-task", "create", "do it"], "gh agent-task")):
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

    def test_an_unrecognised_command_for_an_unguarded_repository_passes(self):
        for args in (["label", "create", "bug"], ["repo", "edit", "someone/other", "--description", "x"]):
            with self.subTest(args):
                self.reset()
                self.assertRan(self.gh(*args, cwd=self.other_cwd), *args)

    def test_repo_commands_take_the_repository_from_their_argument_and_flags_before_the_verb_are_seen(self):
        self.assertBlocked(self.gh("repo", "edit", GUARDED, "--description", "x", cwd=self.other_cwd), "repo edit")
        self.assertBlocked(self.gh("pr", "-R", GUARDED, "create", "--body", PLANTED, cwd=self.other_cwd), "term 1")


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
        self.gh("pr", "comment", "5", "-R", "someone/other", "--body", PLANTED)
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
