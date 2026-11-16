"""The gh wrapper's budget guard (scripts/gh-wrapper-lib/gh_budget.py).

Pure tests drive the decision; process tests run the installed layout (bin/gh next to lib/) with a fake real gh that answers `gh api rate_limit` from the
environment, so they check what a caller sees: the refusal line, the exit code, whether the real gh ran, and the cache file.
"""
import json
import os
import sys
import time
import unittest

from test_gh_wrapper import FAKE_GH, LIB, WrapperBase

sys.path.insert(0, str(LIB))
import gh_budget as B      # noqa: E402

# The fake real gh: `api rate_limit` answers from FAKE_RATE (a JSON `resources`), FAKE_RATE_FAIL=1 exits 1, FAKE_RATE_SLEEP delays; everything else is FAKE_GH.
FAKE_RATE_GH = FAKE_GH.replace('d = os.environ["FAKE"]\n', '''d = os.environ["FAKE"]
if sys.argv[1:3] == ["api", "rate_limit"]:
    with open(os.path.join(d, "rate-calls.jsonl"), "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "token": os.environ.get("GH_TOKEN")}) + "\\n")
    if os.environ.get("FAKE_RATE_SLEEP"):
        import time
        time.sleep(float(os.environ["FAKE_RATE_SLEEP"]))
    if os.environ.get("FAKE_RATE_FAIL"):
        sys.stderr.write("dial tcp: connection refused\\n")
        sys.exit(1)
    print(json.dumps({"resources": json.loads(os.environ["FAKE_RATE"])}))
    sys.exit(0)
''', 1)


def rate(core=5000, graphql=5000, reset=None):
    reset = reset or int(time.time()) + 17 * 60
    return json.dumps({"core": {"limit": 5000, "remaining": core, "reset": reset}, "graphql": {"limit": 5000, "remaining": graphql, "reset": reset},
                       "search": {"limit": 30, "remaining": 0, "reset": reset}})


class Decision(unittest.TestCase):
    def test_a_write_and_the_environment_make_a_call_urgent(self):
        self.assertEqual(B.urgency(True, {}), "write")
        self.assertEqual(B.urgency(True, {"GH_URGENT": "1"}), "write")      # not counted as an urgent read
        self.assertEqual(B.urgency(False, {"GH_URGENT": "1"}), "env")
        self.assertEqual(B.urgency(False, {"GH_URGENT": "0"}), "no")
        self.assertEqual(B.urgency(False, {}), "no")

    def test_the_floor_is_600_unless_the_environment_sets_a_number(self):
        self.assertEqual(B.floor_from({}), 600)
        self.assertEqual(B.floor_from({"GH_BUDGET_FLOOR": "5001"}), 5001)
        self.assertEqual(B.floor_from({"GH_BUDGET_FLOOR": "0"}), 0)
        self.assertEqual(B.floor_from({"GH_BUDGET_FLOOR": "many"}), 600)

    def test_a_bucket_missing_or_misshapen_is_unknown(self):
        res = json.loads(rate(core=7))
        self.assertEqual(B.bucket_state(res, "core")[0], 7)
        self.assertIsNone(B.bucket_state(res, "nope"))
        self.assertIsNone(B.bucket_state({"core": {"limit": 5000}}, "core"))
        self.assertIsNone(B.bucket_state(None, "core"))

    def test_the_message_names_bucket_remaining_floor_reset_the_call_and_the_way_through(self):
        now = 1_800_000_000
        text = B.message("core", "run view", 212, 5000, 600, now + 17 * 60 - 5, now)
        for part in ("core budget low: 212 left of 5000 (floor 600)", "resets ", "in 17m", 'Refused "run view" (not urgent)', "GH_URGENT=1"):
            self.assertIn(part, text)
        self.assertEqual(text.count("\n"), 0)
        self.assertIn("in under a minute", B.message("core", "run view", 1, 5000, 600, now + 20, now))

    def test_the_cache_key_holds_the_host_and_a_hash_of_the_token_and_never_the_token(self):
        a, b = B.cache_key("github.com", {"GH_TOKEN": "secret-one"}), B.cache_key("github.com", {"GH_TOKEN": "secret-two"})
        self.assertNotEqual(a, b)
        self.assertNotIn("secret", a)
        self.assertNotEqual(B.cache_key("github.com", {}), B.cache_key("example.com", {}))


class Guard(WrapperBase):
    def setUp(self):
        super().setUp()
        (self.realbin / "gh").write_text(FAKE_RATE_GH)
        d = self.home / ".config" / "gh-wrapper"
        d.mkdir(parents=True)
        (d / "budget").write_text("on\n")
        self.state = self.tmp / "state"

    def run_gh(self, *args, env=None, core=5000, graphql=5000, keep_cache=False, **kw):
        """One call through the wrapper. Each call starts with no cache, as if 30 s had passed, unless `keep_cache`."""
        if not keep_cache:
            (self.state / "gh-wrapper" / "rate.json").unlink(missing_ok=True)
        e = {"XDG_STATE_HOME": str(self.state), "FAKE_RATE": rate(core, graphql), "GH_URGENT": "", "GH_BUDGET_FLOOR": ""}
        e.update(env or {})
        return self.gh(*args, cwd=self.other_cwd, env=e, **kw)

    def rate_calls(self):
        path = self.fake / "rate-calls.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def real_calls(self):
        path = self.fake / "gh-calls.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def cache(self):
        return json.loads((self.state / "gh-wrapper" / "rate.json").read_text())

    def test_a_read_under_the_floor_is_refused_with_75_and_the_one_line_and_gh_does_not_run(self):
        done = self.run_gh("run", "view", "9", core=212)
        self.assertEqual((done.returncode, done.stdout), (75, ""))
        self.assertEqual(done.stderr.count("\n"), 1)
        for part in ("core budget low: 212 left of 5000 (floor 600)", 'Refused "run view" (not urgent)', "GH_URGENT=1", "resets "):
            self.assertIn(part, done.stderr)
        self.assertEqual(self.real_calls(), [])

    def test_a_read_at_or_over_the_floor_passes(self):
        for left in (600, 4000):
            self.reset()
            done = self.run_gh("run", "view", "9", core=left)
            self.assertEqual((done.returncode, done.stdout), (0, "real gh out\n"), done.stderr)
            self.assertEqual(len(self.real_calls()), 1)

    def test_the_floor_can_be_set_and_urgent_reads_pass_under_it(self):
        self.assertEqual(self.run_gh("run", "list", core=4000, env={"GH_BUDGET_FLOOR": "5001"}).returncode, 75)
        self.reset()
        self.assertEqual(self.run_gh("run", "list", core=4000, env={"GH_BUDGET_FLOOR": "4000"}).returncode, 0)
        self.reset()
        done = self.run_gh("run", "list", core=0, env={"GH_URGENT": "1"})
        self.assertEqual((done.returncode, done.stdout), (0, "real gh out\n"), done.stderr)
        self.assertEqual(self.rate_calls(), [])      # an urgent call does not even read the budget

    def test_a_write_always_passes(self):
        for args in (["pr", "merge", "5"], ["workflow", "run", "ci.yml"], ["api", "-X", "POST", "repos/o/r/issues"], ["api", "-f", "a=b", "repos/o/r/issues"],
                     ["api", "graphql", "-f", "query=mutation { x }"], ["frobnicate"]):
            with self.subTest(args):
                self.reset()
                done = self.run_gh(*args, core=0, graphql=0)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(len(self.real_calls()), 1)

    def test_free_and_search_are_never_refused(self):
        for args in (["api", "rate_limit"], ["search", "prs", "x"], ["api", "search/issues", "-f", "q=x", "-X", "GET"]):
            with self.subTest(args):
                self.reset()
                done = self.run_gh(*args, core=0, graphql=0, env={"GH_BUDGET_FLOOR": "5001"})
                self.assertEqual(done.returncode, 0, done.stderr)

    def test_each_command_is_judged_on_its_own_bucket(self):
        env = {"GH_BUDGET_FLOOR": "100"}
        self.assertEqual(self.run_gh("run", "list", core=0, graphql=4000, env=env).returncode, 75)
        self.reset()
        self.assertEqual(self.run_gh("pr", "view", "5", core=0, graphql=4000, env=env).returncode, 0)      # GraphQL is fine while core is empty
        self.reset()
        done = self.run_gh("pr", "view", "5", core=4000, graphql=3, env=env)
        self.assertEqual(done.returncode, 75)
        self.assertIn("graphql budget low: 3 left", done.stderr)
        self.reset()
        self.assertEqual(self.run_gh("run", "list", core=4000, graphql=3, env=env).returncode, 0)

    def test_the_answer_is_cached_for_30_seconds_in_the_state_file_without_the_token(self):
        self.run_gh("run", "list", env={"GH_TOKEN": "tok-abc123"})
        self.run_gh("run", "list", env={"GH_TOKEN": "tok-abc123"}, keep_cache=True)
        self.assertEqual(len(self.rate_calls()), 1)
        self.assertEqual(self.rate_calls()[0]["argv"], ["api", "rate_limit", "--hostname", "github.com"])
        text = (self.state / "gh-wrapper" / "rate.json").read_text()
        self.assertNotIn("tok-abc123", text)
        self.run_gh("run", "list", env={"GH_TOKEN": "tok-other"}, keep_cache=True)      # another account is another answer
        self.assertEqual(len(self.rate_calls()), 2)
        data = self.cache()
        for k in data:
            data[k]["at"] -= 31
        (self.state / "gh-wrapper" / "rate.json").write_text(json.dumps(data))
        self.run_gh("run", "list", env={"GH_TOKEN": "tok-abc123"}, keep_cache=True)      # a stale answer is read again
        self.assertEqual(len(self.rate_calls()), 3)

    def test_the_cache_is_shared_by_calls_and_a_fresh_low_answer_refuses_without_a_new_read(self):
        self.assertEqual(self.run_gh("run", "list", core=50).returncode, 75)
        self.reset()
        done = self.run_gh("run", "view", "1", core=4000, keep_cache=True)      # GitHub would now say 4000; the cache still says 50
        self.assertEqual(done.returncode, 75)
        self.assertEqual(self.rate_calls(), [])      # self.reset() cleared the log; the second call read the cache, not GitHub

    def test_when_the_rate_read_fails_the_call_goes_through_and_the_failure_is_cached(self):
        for i in range(2):
            done = self.run_gh("run", "list", env={"FAKE_RATE_FAIL": "1"}, keep_cache=i > 0)
            self.assertEqual((done.returncode, done.stdout), (0, "real gh out\n"), done.stderr)
        self.assertEqual(len(self.rate_calls()), 1)
        self.assertEqual(len(self.real_calls()), 2)

    def test_a_slow_rate_read_is_cut_off_at_3_seconds_and_the_call_goes_through(self):
        t0 = time.time()
        done = self.run_gh("run", "list", env={"FAKE_RATE_SLEEP": "30"}, timeout=20)
        self.assertEqual((done.returncode, done.stdout), (0, "real gh out\n"), done.stderr)
        self.assertLess(time.time() - t0, 10)

    def test_a_rate_answer_in_a_shape_we_do_not_know_lets_the_call_through(self):
        done = self.run_gh("run", "list", env={"FAKE_RATE": "[1, 2]"})
        self.assertEqual(done.returncode, 0, done.stderr)
        done = self.run_gh("pr", "view", "5", env={"FAKE_RATE": "{}"})
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_host_other_than_github_com_is_skipped(self):
        for env in ({"GH_HOST": "ghe.example.com"},):
            done = self.run_gh("run", "list", core=0, env=env)
            self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.rate_calls(), [])
        for flag in (["--hostname", "ghe.example.com"], ["--hostname=ghe.example.com"]):
            done = self.run_gh("api", *flag, "repos/o/r", core=0)
            self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.rate_calls(), [])

    def test_a_low_reading_whose_reset_time_has_passed_does_not_refuse(self):
        gone = int(time.time()) - 5
        done = self.run_gh("run", "list", env={"FAKE_RATE": rate(core=3, reset=gone)})
        self.assertEqual((done.returncode, done.stdout), (0, "real gh out\n"), done.stderr)

    def test_the_budget_off_means_the_guard_does_not_run(self):
        (self.home / ".config" / "gh-wrapper" / "budget").write_text("off\n")
        done = self.run_gh("run", "list", core=0)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.rate_calls(), [])

    def test_the_real_gh_for_the_read_skips_the_wrapper_itself(self):
        # PATH starts with the wrapper's own directory: the rate read must find the fake real gh behind it, not loop back.
        done = self.run_gh("run", "list", core=10)
        self.assertEqual(done.returncode, 75, done.stderr)
        self.assertEqual(len(self.rate_calls()), 1)

    def test_the_layer_leaves_its_facts_in_call_notes_for_the_log(self):
        (self.lib_dir / "gh_log.py").write_text(
            "import json, os\n"
            "def after(call):\n"
            "    open(os.path.join(os.environ['FAKE'], 'notes.jsonl'), 'a').write(json.dumps(dict(call.notes, rc=call.rc, action=call.action)) + '\\n')\n")
        self.run_gh("run", "list", core=100)
        self.run_gh("run", "list", core=4000)
        self.run_gh("pr", "merge", "5", core=1, keep_cache=True)      # the fresh cache still says 4000: urgent calls log it but never read
        self.run_gh("run", "list", env={"GH_URGENT": "1"}, core=1, keep_cache=True)
        self.run_gh("run", "list", env={"FAKE_RATE_FAIL": "1", "XDG_STATE_HOME": str(self.tmp / "other-state")})
        notes = [json.loads(l) for l in (self.fake / "notes.jsonl").read_text().splitlines()]
        got = [(n["urgent"], n["budget"], n.get("budget_left"), n["rc"], n["action"]) for n in notes]
        self.assertEqual(got, [("no", "refused", 100, 75, "refused"), ("no", "ok", 4000, 0, "pass"), ("write", "unchecked", 4000, 0, "pass"),
                               ("env", "unchecked", 4000, 0, "pass"), ("no", "unread", None, 0, "pass")])

    @property
    def lib_dir(self):
        return self.tmp / "lib"


if __name__ == "__main__":
    unittest.main()
