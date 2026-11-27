"""The gh wrapper's classification and layer seam (scripts/gh-wrapper-lib/gh_classify.py, gh_layers.py), driven the way a caller drives them.

Pure tests map the command facts to a bucket and read/write. Process tests run the installed layout (bin/gh next to lib/) with a fake real gh and fake layer
modules dropped into lib/, and check what the layers saw and what the real gh got.
"""
import json
import os
import signal
import subprocess
import sys
import time
import unittest

from test_gh_wrapper import GUARDED, LIB, PLANTED, WrapperBase, load_wrapper

sys.path.insert(0, str(LIB))
import gh_classify as C      # noqa: E402
import gh_layers as G      # noqa: E402

RECORD = '''
import json, os
def rec(kind, call, **more):
    with open(os.path.join(os.environ["FAKE"], "layers.jsonl"), "a") as f:
        f.write(json.dumps(dict(kind=kind, layer=__name__, klass=call.klass, bucket=call.bucket, write=call.write, args=call.args, action=call.action, rc=call.rc, **more)) + "\\n")
'''
SEEING = RECORD + '''
def before(call): rec("before", call)
def after(call): rec("after", call)
'''


class Classify(unittest.TestCase):
    def test_commands_spend_the_bucket_the_design_table_names(self):
        for name, bucket in (("pr view", "graphql"), ("pr list", "graphql"), ("pr checks", "graphql"), ("pr status", "graphql"), ("issue view", "graphql"),
                             ("issue comment", "graphql"), ("run list", "core"), ("run watch", "core"), ("workflow run", "core"), ("search", "search"),
                             ("pr diff", "core"), ("pr merge", "core"), ("release list", "core"), ("unrecognised", "core")):
            with self.subTest(name):
                self.assertEqual(C.classify(name, True).bucket, bucket)

    def test_the_caller_says_what_is_a_read_and_everything_else_is_a_write(self):
        self.assertFalse(C.classify("pr view", True).write)
        self.assertTrue(C.classify("pr merge", False).write)
        self.assertTrue(C.classify("unrecognised", True).write)      # a command nobody could name is never treated as a read
        self.assertEqual(C.classify("pr view", True).klass, "pr view")

    def test_api_paths_pick_the_bucket_and_the_method_the_kind(self):
        for method, path, mutation, want in (
                ("GET", "rate_limit", None, ("api GET rate_limit", "free", False)),
                ("GET", "repos/a/b/commits/0123456789abcdef0123456789abcdef01234567", None, ("api GET repos/a/b/commits/*", "core", False)),
                ("GET", "repos/a/b/pulls/526?x=1", None, ("api GET repos/a/b/pulls/*", "core", False)),
                ("GET", "search/issues", None, ("api GET search/issues", "search", False)),
                ("POST", "repos/a/b/issues", None, ("api POST repos/a/b/issues", "core", True)),
                ("DELETE", "repos/a/b/git/refs/heads/x", None, ("api DELETE repos/a/b/git/refs/heads/x", "core", True)),
                ("POST", "graphql", False, ("api POST graphql", "graphql", False)),
                ("POST", "graphql", True, ("api POST graphql", "graphql", True)),
                ("POST", "graphql", None, ("api POST graphql", "graphql", True))):      # a query nobody could read counts as a write
            with self.subTest(method=method, path=path, mutation=mutation):
                self.assertEqual(tuple(C.classify("api", False, (method, path, mutation))), want)

    def test_api_arguments_that_could_not_be_read_count_as_a_core_write(self):
        self.assertEqual(tuple(C.classify("api", False, None)), ("api", "core", True))

    def test_words_that_look_like_ids_stay_and_ids_go(self):
        self.assertEqual(C.mask_path("repos/o/r/actions/runs/123/jobs"), "repos/o/r/actions/runs/*/jobs")
        self.assertEqual(C.mask_path("repos/o/r/git/ref/heads/added"), "repos/o/r/git/ref/heads/added")
        self.assertEqual(C.mask_path("repos/o/r/commits/abcdef1"), "repos/o/r/commits/*")


class Facts(unittest.TestCase):
    """What the wrapper hands to classify for `gh api`."""
    W = load_wrapper()

    def facts(self, *args):
        return self.W.api_facts(["api", *args])

    def test_method_path_and_mutation_come_from_the_arguments(self):
        self.assertEqual(self.facts("repos/a/b"), ("GET", "repos/a/b", None))
        self.assertEqual(self.facts("-X", "DELETE", "repos/a/b/issues/1"), ("DELETE", "repos/a/b/issues/1", None))
        self.assertEqual(self.facts("-f", "title=x", "repos/a/b/issues"), ("POST", "repos/a/b/issues", None))
        self.assertEqual(self.facts("-X", "GET", "-f", "q=x", "search/issues"), ("GET", "search/issues", None))
        self.assertEqual(self.facts("graphql", "-f", "query={ viewer { login } }"), ("POST", "graphql", False))
        self.assertEqual(self.facts("graphql", "-f", "query=mutation { x }"), ("POST", "graphql", True))

    def test_a_query_that_comes_from_a_file_or_input_is_not_known_to_be_a_read(self):
        self.assertEqual(self.facts("graphql", "-F", "query=@q.graphql"), ("POST", "graphql", None))
        self.assertEqual(self.facts("graphql", "--input", "q.json"), ("POST", "graphql", None))

    def test_arguments_the_flag_table_does_not_know_are_unreadable(self):
        self.assertIsNone(self.facts("--no-such-flag", "repos/a/b"))

    def test_the_exempt_groups_are_commands_that_leak_guard_lets_through_anyway(self):
        self.assertTrue(self.W.EXEMPT_GROUPS <= self.W.NOT_REPO)      # an exempt command never skips a check leak-guard would have made
        self.assertTrue(self.W.exempt(["auth", "git-credential", "get"]))
        self.assertTrue(self.W.exempt(["--version"]))
        self.assertFalse(self.W.exempt(["--version", "x"]))
        self.assertFalse(self.W.exempt(["pr", "view"]))
        self.assertFalse(self.W.exempt([]))


class Layers(WrapperBase):
    """The installed layout: tmp/wbin/gh and tmp/lib, with fake layer modules in lib."""

    def setUp(self):
        super().setUp()
        self.lib = self.tmp / "lib"
        for name in G.LAYERS:      # these tests drive the seam with fake layers; each real layer has its own test file
            (self.lib / (name + ".py")).unlink(missing_ok=True)

    def layer(self, name, source):
        (self.lib / (name + ".py")).write_text(source)

    def budget(self, value):
        d = self.home / ".config" / "gh-wrapper"
        d.mkdir(parents=True, exist_ok=True)
        (d / "budget").write_text(value + "\n")

    def seen(self):
        path = self.fake / "layers.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def test_with_no_budget_file_or_off_the_budget_layer_is_never_read_and_the_real_gh_runs(self):
        self.layer("gh_budget", SEEING)
        for setting in (None, "off", "", "yes"):
            with self.subTest(setting):
                self.reset()
                if setting is not None:
                    self.budget(setting)
                done = self.gh("pr", "view", "5", cwd=self.other_cwd)
                self.assertEqual((done.returncode, done.stdout), (0, "real gh out\n"), done.stderr)
                self.assertEqual(self.seen(), [])
                self.assertEqual(len(self.real_calls()), 1)
        (self.lib / "gh_budget.py").unlink()
        os.rename(self.lib, self.tmp / "lib-gone")
        done = self.gh("pr", "view", "5", cwd=self.other_cwd)      # no lib at all: the call still goes on (gh_rewrite is lost, the check is not)
        self.assertEqual((done.returncode, done.stderr), (0, "real gh err\n"))      # and with the switch off the wrapper says nothing about it, as before the layers existed

    def test_with_the_budget_off_a_broken_lib_is_still_reported(self):
        self.budget("off")
        (self.lib / "gh_layers.py").write_text("raise RuntimeError('broken on purpose')\n")
        done = self.gh("pr", "view", "5", cwd=self.other_cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("gh-wrapper: the layers could not start (RuntimeError", done.stderr)

    def test_with_the_budget_on_each_layer_sees_the_classified_call_before_and_after(self):
        self.layer("gh_budget", SEEING)
        self.budget("on")
        for args, want in ((["pr", "view", "5"], ("pr view", "graphql", False)), (["run", "list"], ("run list", "core", False)),
                           (["api", "rate_limit"], ("api GET rate_limit", "free", False)), (["pr", "merge", "5"], ("pr merge", "core", True)),
                           (["search", "prs", "x"], ("search", "search", False)), (["api", "-f", "a=b", "repos/o/r/issues"], ("api POST repos/o/r/issues", "core", True)),
                           (["frobnicate"], ("unrecognised", "core", True))):
            with self.subTest(args):
                self.reset()
                done = self.gh(*args, cwd=self.other_cwd)
                self.assertEqual(done.returncode, 0, done.stderr)
                before, after = self.seen()
                self.assertEqual((before["kind"], before["klass"], before["bucket"], before["write"]), ("before",) + want)
                self.assertEqual((after["kind"], after["rc"]), ("after", 0))
                self.assertEqual(self.real_calls()[0]["argv"], args)

    def test_the_work_rules_layer_runs_first_whatever_the_budget_file_says(self):
        self.layer("gh_policy", "from gh_layers import Stop\ndef before(call):\n    raise Stop(1, 'policy refused')\n")
        self.layer("gh_budget", SEEING)
        for setting in (None, "off", "on"):
            with self.subTest(setting):
                self.reset()
                if setting is not None:
                    self.budget(setting)
                done = self.gh("pr", "view", "5", cwd=self.other_cwd)
                self.assertEqual(done.returncode, 1, done.stderr)
                self.assertIn("policy refused", done.stderr)
                self.assertNotIn("before", [r["kind"] for r in self.seen()])      # the budget layer never judged the call: the rules come first
                self.assertEqual(self.real_calls(), [])

    def test_a_layer_is_given_the_real_gh_to_read_state_with(self):
        self.layer("gh_policy", RECORD + "def before(call): rec('before', call, real=call.real)\n")
        done = self.gh("pr", "view", "5", cwd=self.other_cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(os.path.realpath(self.seen()[0]["real"]), os.path.realpath(self.realbin / "gh"))

    def test_auth_and_version_skip_the_layers(self):
        self.layer("gh_budget", SEEING)
        self.budget("on")
        for args in (["auth", "git-credential", "get"], ["--version"]):
            done = self.gh(*args, cwd=self.other_cwd)
            self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.seen(), [])
        self.assertEqual(len(self.real_calls()), 2)

    def test_a_layer_can_change_the_arguments_and_the_real_gh_gets_the_new_ones(self):
        self.layer("gh_rewrite", "def before(call):\n    call.args = call.args + ['--interval', '60']\n    call.action = 'rewrite'\n")
        self.layer("gh_log", SEEING)
        self.budget("on")
        done = self.gh("run", "watch", "9", cwd=self.other_cwd)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.real_calls()[0]["argv"], ["run", "watch", "9", "--interval", "60"])
        self.assertEqual([(s["kind"], s["action"]) for s in self.seen()], [("before", "rewrite"), ("after", "rewrite")])

    def test_a_stop_refuses_the_call_with_its_exit_code_and_message_and_every_after_hook_still_runs(self):
        self.layer("gh_budget", "from gh_layers import Stop\ndef before(call):\n    raise Stop(75, 'gh-wrapper: refused for the test')\n")
        self.layer("gh_log", SEEING)
        self.budget("on")
        done = self.gh("run", "view", "1", cwd=self.other_cwd)
        self.assertEqual((done.returncode, done.stderr.strip()), (75, "gh-wrapper: refused for the test"))
        self.assertEqual(self.real_calls(), [])
        self.assertEqual([(s["kind"], s["action"], s["rc"]) for s in self.seen()], [("after", "refused", 75)])

    def test_a_layer_with_an_after_hook_keeps_gh_exit_code_output_and_standard_input(self):
        self.layer("gh_log", SEEING)
        self.budget("on")
        done = self.gh("pr", "view", "5", stdin="typed\n", cwd=self.other_cwd, env={"FAKE_GH_EXIT": "3"})
        self.assertEqual((done.returncode, done.stdout, done.stderr), (3, "real gh out\n", "real gh err\n"))
        self.assertEqual(self.real_calls()[0]["stdin"], "typed\n")
        self.assertEqual(self.seen()[-1]["rc"], 3)

    def test_a_leak_guard_block_still_reaches_the_after_hooks(self):
        self.layer("gh_log", SEEING)
        self.budget("on")
        done = self.gh("pr", "comment", "5", "--body", PLANTED)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("leak-guard gh: BLOCKED", done.stderr)
        self.assertEqual(self.real_calls(), [])
        self.assertEqual([(s["kind"], s["rc"]) for s in self.seen()], [("before", None), ("after", 1)])

    def test_a_layer_that_fails_never_changes_the_call(self):
        self.layer("gh_rewrite", "def before(call):\n    raise RuntimeError('boom')\n")
        self.layer("gh_budget", "def after(call):\n    raise RuntimeError('boom')\n")
        self.layer("gh_log", "this is not python\n")
        self.budget("on")
        done = self.gh("pr", "view", "5", cwd=self.other_cwd)
        self.assertEqual((done.returncode, done.stdout), (0, "real gh out\n"))
        self.assertEqual(len(self.real_calls()), 1)
        for name in ("gh_rewrite", "gh_budget", "gh_log"):
            self.assertIn("gh-wrapper: layer %s failed" % name, done.stderr)

    def test_a_signal_to_the_wrapper_reaches_gh_and_the_after_hooks_still_run(self):
        """With an after hook the wrapper is gh's parent, not gh itself, so a timeout's SIGTERM, a hangup or an interrupt (SIGINT) sent to the wrapper must be
        passed on to gh: an orphaned `gh run watch` would keep polling."""
        self.layer("gh_log", SEEING)
        self.budget("on")
        for sig, code in ((signal.SIGTERM, 143), (signal.SIGHUP, 129), (signal.SIGINT, 130)):
            with self.subTest(sig):
                self.reset()
                proc = subprocess.Popen([str(self.wbin / "gh"), "run", "watch", "9"], cwd=str(self.other_cwd), env=self.env({"FAKE_GH_SLEEP": "60"}), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                pidfile = self.fake / "gh.pid"
                deadline = time.time() + 20
                while not pidfile.exists() and time.time() < deadline:
                    time.sleep(0.02)
                gh_pid = int(pidfile.read_text())
                proc.send_signal(sig)
                proc.communicate(timeout=20)
                self.assertEqual(proc.returncode, code)
                self.assertFalse(os.path.exists("/proc/%d" % gh_pid) and "Z" not in open("/proc/%d/stat" % gh_pid).read().split(") ")[-1][:1], "gh outlived the wrapper")
                self.assertEqual([(s["kind"], s["rc"]) for s in self.seen()], [("before", None), ("after", code)])

    def test_with_the_budget_on_and_no_lib_the_call_goes_on_with_a_note_and_leak_guard_still_blocks(self):
        self.budget("on")
        os.rename(self.lib, self.tmp / "lib-gone")
        done = self.gh("pr", "view", "5", cwd=self.other_cwd)
        self.assertEqual((done.returncode, done.stdout), (0, "real gh out\n"))
        self.assertIn("gh-wrapper: the layers could not start (ModuleNotFoundError", done.stderr)
        done = self.gh("pr", "comment", "5", "--body", PLANTED)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(len(self.real_calls()), 1)

    def test_a_layer_with_no_file_is_skipped_quietly(self):
        self.budget("on")
        done = self.gh("pr", "view", "5", cwd=self.other_cwd)
        self.assertEqual((done.returncode, done.stderr), (0, "real gh err\n"))


if __name__ == "__main__":
    unittest.main()
