"""The rewrites of scripts/gh-wrapper-lib/gh_rewrite.py (docs/gh-wrapper.md, "Cheaper by default"): the planning as pure functions, the layer hook with the
call it exposes, and the installed wrapper driven the way a caller drives it, with a fake real gh that records the arguments it gets.
"""
import json
import os
import sys
import unittest
from unittest import mock

from test_gh_wrapper import GUARDED, LIB, PLANTED, WrapperBase, load_wrapper

sys.path.insert(0, str(LIB))
import gh_layers as L        # noqa: E402
import gh_rewrite as R       # noqa: E402

RUN, CHECKS, CACHE = ("run watch", "core"), ("pr checks", "graphql"), ("api GET repos/a/b", "core")

# Test-only layer modules, dropped into the installed lib: RECORDER logs the arguments each layer saw; ADD_BODY adds a text to a guarded comment, which only
# the leak-guard check can see.
RECORDER = (
    "import json, os\n"
    "def before(call):\n"
    "    with open(os.path.join(os.environ['FAKE'], 'layers.jsonl'), 'a') as f:\n"
    "        f.write(json.dumps([__name__, call.args]) + '\\n')\n"
)
ADD_BODY = (
    "def before(call):\n"
    "    if call.klass == 'pr comment':\n"
    "        call.args = call.args + ['--body', %r]\n"
    "        call.action = 'rewrite'\n"
) % PLANTED


def plan(klass_bucket, *args, urgent=False, budget_on=True):
    return R.plan(klass_bucket[0], klass_bucket[1], list(args), urgent, budget_on)


class Table(unittest.TestCase):
    def test_the_api_row_is_the_wrappers_own_row(self):
        self.assertEqual(R.table(R.API), load_wrapper().flag_table("api", ""))


class Watch(unittest.TestCase):
    def test_no_interval_gets_the_default_and_the_exposed_interval_is_the_default(self):
        self.assertEqual(plan(RUN, "run", "watch", "9"), (["run", "watch", "9", "--interval", "60"], "interval 60", 60))

    def test_a_caller_interval_is_honoured_in_every_form_and_never_changed(self):
        for tail in (["-i", "3"], ["--interval", "3"], ["--interval=3"], ["-i3"], ["-i=3"]):
            with self.subTest(tail):
                self.assertEqual(plan(RUN, "run", "watch", "9", *tail), (["run", "watch", "9", *tail], None, 3))

    def test_the_last_interval_is_the_one_gh_keeps(self):
        self.assertEqual(plan(RUN, "run", "watch", "9", "-i", "3", "-i", "5")[2], 5)

    def test_a_repository_value_with_an_i_in_it_is_a_value_and_not_an_interval(self):
        self.assertEqual(plan(RUN, "run", "watch", "9", "-Rcartwmic/dotfiles")[1], "interval 60")
        self.assertEqual(plan(RUN, "run", "watch", "9", "-Rcartwmic/x", "-i", "5"), (["run", "watch", "9", "-Rcartwmic/x", "-i", "5"], None, 5))

    def test_the_switches_do_not_stop_the_default(self):
        self.assertEqual(plan(RUN, "run", "watch", "9", "--compact", "--exit-status")[1], "interval 60")

    def test_the_default_goes_before_a_bare_double_dash(self):
        self.assertEqual(plan(RUN, "run", "watch", "--", "9")[0], ["run", "watch", "--interval", "60", "--", "9"])

    def test_a_call_with_a_flag_the_table_does_not_know_is_left_alone_and_not_exposed(self):
        self.assertEqual(plan(RUN, "run", "watch", "9", "--no-such-flag"), (["run", "watch", "9", "--no-such-flag"], None, None))

    def test_a_value_flag_with_no_value_is_left_alone(self):
        self.assertEqual(plan(RUN, "run", "watch", "9", "-i"), (["run", "watch", "9", "-i"], None, None))
        self.assertEqual(plan(RUN, "run", "watch", "9", "--interval"), (["run", "watch", "9", "--interval"], None, None))

    def test_run_commands_that_are_not_watch_are_untouched(self):
        self.assertEqual(plan(("run list", "core"), "run", "list"), (["run", "list"], None, None))

    def test_the_watch_default_does_not_wait_for_the_budget_switch(self):
        self.assertEqual(plan(RUN, "run", "watch", "9", budget_on=False), (["run", "watch", "9", "--interval", "60"], "interval 60", 60))
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "--watch", budget_on=False)[1], "interval 60")


class PrChecks(unittest.TestCase):
    def test_without_watch_nothing_is_added_or_exposed(self):
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "-i", "5"), (["pr", "checks", "5", "-i", "5"], None, None))
        self.assertEqual(plan(CHECKS, "pr", "checks", "5"), (["pr", "checks", "5"], None, None))

    def test_watch_gets_the_default_interval(self):
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "--watch"), (["pr", "checks", "5", "--watch", "--interval", "60"], "interval 60", 60))

    def test_w_is_web_not_watch(self):
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "-w"), (["pr", "checks", "5", "-w"], None, None))

    def test_watch_false_is_not_a_watch_and_the_last_watch_value_counts(self):
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "--watch=false")[1], None)
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "--watch", "--watch=false")[1], None)
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "--watch=false", "--watch")[1], "interval 60")

    def test_a_caller_interval_on_a_watch_is_honoured(self):
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "--watch", "-i", "5"), (["pr", "checks", "5", "--watch", "-i", "5"], None, 5))

    def test_value_flags_before_watch_do_not_hide_it(self):
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "--json", "name", "-q", ".x", "--watch")[1], "interval 60")
        self.assertEqual(plan(CHECKS, "pr", "checks", "5", "-R", "o/i-x", "--watch")[1], "interval 60")


class Cache(unittest.TestCase):
    def test_a_plain_get_read_gets_the_cache(self):
        self.assertEqual(plan(CACHE, "api", "repos/a/b"), (["api", "repos/a/b", "--cache", "15s"], "cache 15s", None))

    def test_an_explicit_get_and_flags_that_do_not_send_anything_keep_it(self):
        for tail in (["-X", "GET"], ["--method=get"], ["-H", "Accept: application/vnd.github.raw"], ["--jq", ".x"], ["-i"], ["--paginate"]):
            with self.subTest(tail):
                self.assertEqual(plan(CACHE, "api", "repos/a/b", *tail)[1], "cache 15s")

    def test_search_reads_get_it_too(self):
        self.assertEqual(plan(("api GET search/issues", "search"), "api", "search/issues")[1], "cache 15s")

    def test_a_call_that_is_not_a_plain_read_is_left_alone(self):
        for tail in (["-X", "POST"], ["-X", "DELETE"], ["-f", "title=x"], ["-F", "n=1"], ["--field", "a=b"], ["--raw-field", "a=b"],
                     ["--input", "f.json"], ["-X", "GET", "-f", "q=x"], ["--cache", "5m"], ["--cache=5m"], ["--help"], ["-h"]):
            with self.subTest(tail):
                self.assertEqual(plan(CACHE, "api", "repos/a/b", *tail), (["api", "repos/a/b", *tail], None, None))

    def test_urgent_reads_stay_fresh(self):
        self.assertEqual(plan(CACHE, "api", "repos/a/b", urgent=True), (["api", "repos/a/b"], None, None))

    def test_the_cache_waits_for_the_budget_switch(self):
        self.assertEqual(plan(CACHE, "api", "repos/a/b", budget_on=False), (["api", "repos/a/b"], None, None))
        self.assertEqual(plan(("api GET search/issues", "search"), "api", "search/issues", budget_on=False)[1], None)

    def test_rate_limit_graphql_and_no_endpoint_are_never_touched(self):
        self.assertEqual(plan(("api GET rate_limit", "free"), "api", "rate_limit")[1], None)
        self.assertEqual(plan(("api POST graphql", "graphql"), "api", "graphql", "-f", "query={viewer{login}}")[1], None)
        self.assertEqual(plan(CACHE, "api")[1], None)

    def test_a_write_klass_is_not_a_plain_get(self):
        self.assertEqual(plan(("api HEAD repos/a/b", "core"), "api", "-X", "HEAD", "repos/a/b")[1], None)

    def test_a_flag_the_table_does_not_know_is_left_alone(self):
        self.assertEqual(plan(CACHE, "api", "repos/a/b", "--no-such-flag")[1], None)


class Hook(unittest.TestCase):
    def call(self, klass, bucket, *args, budget_on=True):
        return L.Call(list(args), (klass, bucket, False), budget_on=budget_on)

    def test_with_the_budget_off_the_watch_default_is_exposed_and_the_cache_is_not(self):
        call = self.call("run watch", "core", "run", "watch", "9", budget_on=False)
        R.before(call)
        self.assertEqual((call.args, call.action, call.rewrite, call.notes), (["run", "watch", "9", "--interval", "60"], "rewrite", "interval 60", {"interval": 60}))
        call = self.call("api GET repos/a/b", "core", "api", "repos/a/b", budget_on=False)
        with mock.patch.dict(os.environ, {"GH_URGENT": ""}):
            R.before(call)
        self.assertEqual((call.args, call.action, call.rewrite), (["api", "repos/a/b"], "pass", None))

    def test_a_rewrite_sets_the_action_and_what_it_was(self):
        call = self.call("run watch", "core", "run", "watch", "9")
        R.before(call)
        self.assertEqual((call.args, call.action, call.rewrite), (["run", "watch", "9", "--interval", "60"], "rewrite", "interval 60"))
        self.assertEqual(call.notes, {"interval": 60})

    def test_a_caller_interval_is_exposed_without_a_rewrite(self):
        call = self.call("run watch", "core", "run", "watch", "9", "-i", "3")
        R.before(call)
        self.assertEqual((call.args, call.action, call.rewrite, call.notes), (["run", "watch", "9", "-i", "3"], "pass", None, {"interval": 3}))

    def test_a_cache_rewrite_is_exposed_and_urgent_reads_are_not_changed(self):
        call = self.call("api GET repos/a/b", "core", "api", "repos/a/b")
        with mock.patch.dict(os.environ, {"GH_URGENT": "1"}):
            R.before(call)
        self.assertEqual((call.args, call.action, call.rewrite, call.notes), (["api", "repos/a/b"], "pass", None, {}))
        call = self.call("api GET repos/a/b", "core", "api", "repos/a/b")
        with mock.patch.dict(os.environ, {"GH_URGENT": ""}):
            R.before(call)
        self.assertEqual((call.args, call.action, call.rewrite), (["api", "repos/a/b", "--cache", "15s"], "rewrite", "cache 15s"))


class Wrapper(WrapperBase):
    """The installed layout with the budget on, as on the personal profile. GH_URGENT is pinned in every call."""

    def setUp(self):
        super().setUp()
        self.lib = self.tmp / "lib"
        d = self.home / ".config" / "gh-wrapper"
        d.mkdir(parents=True, exist_ok=True)
        (d / "budget").write_text("on\n")

    def recorded(self):
        path = self.fake / "layers.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def run_gh(self, *args, cwd=None, urgent=False):
        done = self.gh(*args, cwd=cwd or self.other_cwd, env={"GH_URGENT": "1" if urgent else ""})
        self.assertEqual(done.returncode, 0, done.stderr)
        return self.real_calls()[-1]["argv"]

    def test_watch_commands_get_the_default_interval_and_keep_the_callers(self):
        self.assertEqual(self.run_gh("run", "watch", "9"), ["run", "watch", "9", "--interval", "60"])
        self.assertEqual(self.run_gh("run", "watch", "9", "-i", "3"), ["run", "watch", "9", "-i", "3"])
        self.assertEqual(self.run_gh("pr", "checks", "5", "--watch"), ["pr", "checks", "5", "--watch", "--interval", "60"])
        self.assertEqual(self.run_gh("pr", "checks", "5"), ["pr", "checks", "5"])

    def test_plain_api_reads_get_the_cache_unless_urgent(self):
        self.assertEqual(self.run_gh("api", "repos/a/b/branches/main"), ["api", "repos/a/b/branches/main", "--cache", "15s"])
        self.assertEqual(self.run_gh("api", "repos/a/b/branches/main", urgent=True), ["api", "repos/a/b/branches/main"])
        self.assertEqual(self.run_gh("api", "rate_limit"), ["api", "rate_limit"])

    def test_writes_and_bodies_are_left_alone(self):
        self.assertEqual(self.run_gh("api", "-X", "POST", "repos/a/b/issues", "-f", "title=x"), ["api", "-X", "POST", "repos/a/b/issues", "-f", "title=x"])
        self.assertEqual(self.run_gh("api", "repos/a/b/issues", "--input", "x.json", "-X", "GET"), ["api", "repos/a/b/issues", "--input", "x.json", "-X", "GET"])

    def test_a_read_of_a_guarded_repository_is_rewritten_and_still_runs(self):
        self.assertEqual(self.run_gh("api", "repos/%s/branches/main" % GUARDED, cwd=self.guarded_cwd),
                         ["api", "repos/%s/branches/main" % GUARDED, "--cache", "15s"])

    def test_with_the_budget_off_only_the_watch_default_runs_and_the_budget_and_log_layers_are_not_read(self):
        (self.lib / "gh_budget.py").write_text(RECORDER)
        (self.lib / "gh_log.py").write_text(RECORDER)
        budget = self.home / ".config" / "gh-wrapper" / "budget"
        self.run_gh("api", "repos/a/b")      # budget on (set in setUp): both recording layers run
        self.assertEqual(sorted({name for name, _ in self.recorded()}), ["gh_budget", "gh_log"])
        for setting in ("off", None):       # `off`, and no file at all, which the wrapper also reads as off
            with self.subTest(setting):
                self.reset()
                if setting is None:
                    budget.unlink()
                else:
                    budget.write_text("off\n")
                self.assertEqual(self.run_gh("run", "watch", "9"), ["run", "watch", "9", "--interval", "60"])
                self.assertEqual(self.run_gh("api", "repos/a/b"), ["api", "repos/a/b"])
                self.assertEqual(self.recorded(), [])

    def test_a_later_layer_sees_what_was_rewritten(self):
        (self.lib / "gh_log.py").write_text(
            "import json, os\n"
            "def after(call):\n"
            "    with open(os.path.join(os.environ['FAKE'], 'layers.jsonl'), 'a') as f:\n"
            "        f.write(json.dumps(dict(action=call.action, rewrite=call.rewrite, interval=call.notes.get('interval'), rc=call.rc)) + '\\n')\n")
        self.run_gh("run", "watch", "9")
        self.run_gh("run", "watch", "9", "-i", "3")
        seen = [json.loads(l) for l in (self.fake / "layers.jsonl").read_text().splitlines()]
        self.assertEqual(seen, [{"action": "rewrite", "rewrite": "interval 60", "interval": 60, "rc": 0},
                                {"action": "pass", "rewrite": None, "interval": 3, "rc": 0}])


    def test_a_rewritten_guarded_read_reaches_gh_with_the_rewrite(self):
        self.assertEqual(self.run_gh("run", "watch", "9", cwd=self.guarded_cwd), ["run", "watch", "9", "--interval", "60"])

    def test_the_leak_guard_check_runs_on_the_arguments_a_layer_left(self):
        """Layers run before the leak-guard check, and the check reads the arguments they leave (docs/gh-wrapper.md, "What a call goes through"). A
        test-only layer adds a body to a guarded comment: the same comment passes without the layer and is blocked with it, and gh never runs the
        blocked one. Only the check's verdict is asserted here, so a check that read the pre-layer arguments would fail on the BLOCKED line."""
        call = ["pr", "comment", "5"]
        done = self.gh(*call, cwd=self.guarded_cwd, env={"GH_URGENT": ""})
        self.assertEqual(done.returncode, 0, done.stderr)      # no text in the arguments: nothing for the check to read, gh runs
        self.assertEqual(self.real_calls()[-1]["argv"], call)
        (self.lib / "gh_budget.py").write_text(ADD_BODY)
        done = self.gh(*call, cwd=self.guarded_cwd, env={"GH_URGENT": ""})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("leak-guard gh: BLOCKED", done.stderr)
        self.assertEqual(len(self.real_calls()), 1, "the blocked comment reached gh")


if __name__ == "__main__":
    unittest.main()
