"""Black-box tests for dot_local/bin/executable_workstream-rank.

The real script runs as a real process (sh), reading real files. The golden fixture
fixtures/rank/v1 is the exact v1 format from the design; the coordinator repo carries
the same file, so the writer and this reader are pinned to one shared example.

WORKSTREAM_RANK_SCRIPT points the suite at a mutated copy (see mutate.py).
"""
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get("WORKSTREAM_RANK_SCRIPT") or HERE.parents[1] / "dot_local/bin/executable_workstream-rank")
GOLDEN = HERE / "fixtures/rank/v1"
HEADER = "#workstream-rank v1\n"
T = "\t"


class WorkstreamRank(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.file = self.dir / "rank"

    def write(self, text):
        self.file.write_text(text)
        return self.file

    def run_rank(self, *args, rank_file="default", thread=None, herdr_pane=None, home=None, t3_db=None, state_dir=None):
        env = {"PATH": os.environ["PATH"], "HOME": str(home or self.dir)}
        if rank_file == "default":
            env["WORKSTREAM_RANK_FILE"] = str(self.file)
        elif rank_file is not None:
            env["WORKSTREAM_RANK_FILE"] = str(rank_file)
        if thread is not None:
            env["T3CODE_THREAD_ID"] = thread
        env["WORKSTREAM_RANK_STATE_DIR"] = str(state_dir or self.dir / "state")
        if t3_db is not None:
            env["WORKSTREAM_RANK_T3_DB"] = str(t3_db)
        if herdr_pane is not None:
            env["HERDR_PANE_ID"] = herdr_pane
        return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=20)

    def make_t3_db(self, tree):
        """A small T3 database holding {thread: parent thread or None}, in the shape T3 stores threads in."""
        path = self.dir / "statev2.sqlite"
        path.unlink(missing_ok=True)
        db = sqlite3.connect(path)
        db.execute("create table orchestration_v2_projection_threads(thread_id text primary key, title text, payload_json text)")
        for thread, parent in tree.items():
            payload = {"lineage": {"parentThreadId": parent}} if parent else {"lineage": None}
            db.execute("insert into orchestration_v2_projection_threads values(?, ?, ?)", (thread, thread, json.dumps(payload)))
        db.commit()
        db.close()
        return path

    def of(self, pane, **kw):
        p = self.run_rank("of", "--pane", pane, **kw)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def rows(self, *lines):
        return HEADER + "".join(line.replace("|", T) + "\n" for line in lines)

    # --- the golden fixture ---

    def test_golden_fixture_is_the_exact_v1_format(self):
        lines = GOLDEN.read_text().split("\n")
        self.assertEqual(lines[0], "#workstream-rank v1")
        self.assertTrue(lines[1].startswith("# "))
        self.assertEqual(lines[2], "1" + T + "Coordinator work instance (Matrix)" + T + "w1A:pG")
        self.assertEqual(lines[3], "2" + T + "Pi-Bolt runtime (dotfiles #56)" + T + "w1A:pK")

    def test_golden_fixture_ranks_by_pane(self):
        self.assertEqual(self.of("w1A:pG", rank_file=GOLDEN), "1\n")
        self.assertEqual(self.of("w1A:pK", rank_file=GOLDEN), "2\n")

    def test_golden_fixture_show_prints_the_stack(self):
        p = self.run_rank("show", rank_file=GOLDEN)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "1" + T + "Coordinator work instance (Matrix)" + T + "w1A:pG\n"
                         "2" + T + "Pi-Bolt runtime (dotfiles #56)" + T + "w1A:pK\n")
        self.assertEqual(p.stderr, "")

    # --- which pane, and what "unranked" means ---

    def test_an_unmatched_pane_is_unranked_1000(self):
        self.assertEqual(self.of("w9Z:p9", rank_file=GOLDEN), "1000\n")

    def test_the_pane_defaults_to_the_t3_thread_reference(self):
        # the three forms of thread id the coordinator writes after "t3:": a plain id, mcp:<uuid>, mcp:launch:<hex>
        self.write(self.rows("1|Plain|t3:aaaaaaaa-0000-0000-0000-000000000001",
                             "2|Lead|t3:mcp:bbbbbbbb-0000-0000-0000-000000000002",
                             "3|Launched|t3:mcp:launch:0123abcd0123abcd"))
        for thread, rank in (("aaaaaaaa-0000-0000-0000-000000000001", "1"),
                             ("mcp:bbbbbbbb-0000-0000-0000-000000000002", "2"),
                             ("mcp:launch:0123abcd0123abcd", "3")):
            with self.subTest(thread):
                p = self.run_rank("of", thread=thread)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, rank + "\n", ""))

    def test_a_thread_with_no_row_is_unranked(self):
        self.write(self.rows("1|Lead|t3:mcp:bbbbbbbb-0000-0000-0000-000000000002"))
        p = self.run_rank("of", thread="thread:delegated-task:command%3Amcp%3Abbbbbbbb", t3_db=self.make_t3_db({"x": None}))
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "1000\n", ""))

    def test_the_thread_id_is_matched_whole_with_its_t3_prefix(self):
        # a row holding the bare id (no "t3:") is not this thread's
        self.write(self.rows("1|Bare|bbbbbbbb-0000-0000-0000-000000000002"))
        p = self.run_rank("of", thread="bbbbbbbb-0000-0000-0000-000000000002")
        self.assertEqual(p.stdout, "1000\n")

    # --- a thread below a workstream's thread takes that workstream's rank ---

    LEAD = "bbbbbbbb-0000-0000-0000-000000000002"
    TREE = {
        LEAD: None,
        "thread:delegated-task:builder": LEAD,          # a builder the lead launched
        "thread:delegated-task:reviewer": "thread:delegated-task:builder",  # a helper of the builder
        "mcp:other-lead": None,
        "thread:delegated-task:stray": "mcp:other-lead",
        "mcp:inner-lead": LEAD,                          # a lead below a lead, with its own row
        "thread:delegated-task:inner-builder": "mcp:inner-lead",
    }

    def walk(self, thread, *rows, tree=None):
        self.write(self.rows(*rows))
        return self.run_rank("of", thread=thread, t3_db=self.make_t3_db(self.TREE if tree is None else tree))

    def test_a_child_of_a_ranked_thread_takes_its_rank(self):
        p = self.walk("thread:delegated-task:builder", "2|Lead|t3:" + self.LEAD)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "2\n", ""))

    def test_a_grandchild_takes_the_rank_too(self):
        p = self.walk("thread:delegated-task:reviewer", "2|Lead|t3:" + self.LEAD)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "2\n", ""))

    def test_the_nearest_ranked_thread_wins(self):
        rows = ("2|Lead|t3:" + self.LEAD, "9|Inner|t3:mcp:inner-lead")
        self.assertEqual(self.walk("thread:delegated-task:inner-builder", *rows).stdout, "9\n")
        self.assertEqual(self.walk("thread:delegated-task:builder", *rows).stdout, "2\n")

    def test_the_best_rank_among_rows_sharing_the_thread_wins_on_the_walk(self):
        p = self.walk("thread:delegated-task:builder", "5|A|t3:" + self.LEAD, "3|B|t3:" + self.LEAD)
        self.assertEqual(p.stdout, "3\n")

    def test_a_thread_under_no_ranked_thread_is_unranked(self):
        p = self.walk("thread:delegated-task:stray", "2|Lead|t3:" + self.LEAD)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "1000\n", ""))

    def test_a_thread_the_database_does_not_know_is_unranked_without_a_warning(self):
        p = self.walk("thread:delegated-task:nobody", "2|Lead|t3:" + self.LEAD)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "1000\n", ""))

    def test_a_row_without_the_t3_prefix_is_not_a_thread_on_the_walk(self):
        p = self.walk("thread:delegated-task:builder", "2|Bare|" + self.LEAD)
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))

    def test_a_loop_in_the_thread_tree_ends(self):
        p = self.walk("a", "2|Lead|t3:" + self.LEAD, tree={"a": "b", "b": "a"})
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))

    def test_the_threads_own_row_needs_no_database(self):
        self.write(self.rows("4|Lead|t3:" + self.LEAD))
        p = self.run_rank("of", thread=self.LEAD, t3_db=self.dir / "no-such.sqlite")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "4\n", ""))

    def test_an_unreadable_database_leaves_a_child_unranked_and_says_so_once(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        p = self.run_rank("of", thread="thread:delegated-task:builder", t3_db=self.dir / "no-such.sqlite")
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))
        self.assertIn("cannot find the workstream of thread", p.stderr)

    def test_a_database_without_the_threads_table_is_reported_not_guessed(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        empty = self.dir / "empty.sqlite"
        sqlite3.connect(empty).close()
        p = self.run_rank("of", thread="thread:delegated-task:builder", t3_db=empty)
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))
        self.assertIn("cannot read", p.stderr)

    # --- the walk leaves a record when its outcome changes ---

    def log_lines(self, state_dir=None):
        path = (state_dir or self.dir / "state") / "log.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_a_walk_that_cannot_run_is_logged_once_with_the_reason_and_the_thread(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        for _ in range(3):  # heavy-gate asks on every poll
            self.run_rank("of", thread="thread:delegated-task:builder", t3_db=self.dir / "no-such.sqlite")
        lines = self.log_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["event"], lines[0]["outcome"], lines[0]["thread"]), ("thread-walk", "failed", "thread:delegated-task:builder"))
        self.assertIn("cannot read", lines[0]["reason"])
        self.assertRegex(lines[0]["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_the_log_line_stays_valid_json_for_an_odd_thread_id_or_path(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        self.run_rank("of", thread='thread:"quoted\\back', t3_db=self.dir / 'no "such".sqlite')
        lines = self.log_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["outcome"], "failed")

    def test_a_recovery_is_logged_and_a_second_success_is_not(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        child = "thread:delegated-task:builder"
        self.run_rank("of", thread=child, t3_db=self.dir / "no-such.sqlite")
        for _ in range(2):
            self.run_rank("of", thread=child, t3_db=self.make_t3_db(self.TREE))
        self.assertEqual([line["outcome"] for line in self.log_lines()], ["failed", "ok"])

    def test_a_walk_that_cannot_run_for_want_of_the_helper_is_logged(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        bare = self.dir / "bare"
        (bare / "bin").mkdir(parents=True)
        (bare / "bin" / "workstream-rank").write_text(SCRIPT.read_text())   # no share/ beside it, and HOME has none
        env = {"PATH": os.environ["PATH"], "HOME": str(self.dir), "WORKSTREAM_RANK_FILE": str(self.file),
               "WORKSTREAM_RANK_STATE_DIR": str(self.dir / "state"), "T3CODE_THREAD_ID": "thread:delegated-task:builder"}
        p = subprocess.run(["sh", str(bare / "bin" / "workstream-rank"), "of"], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))
        self.assertEqual([(line["outcome"], "needs python3" in line["reason"]) for line in self.log_lines()], [("failed", True)])

    def test_a_thread_with_its_own_row_or_an_explicit_pane_walks_nothing_and_logs_nothing(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        self.run_rank("of", thread=self.LEAD, t3_db=self.dir / "no-such.sqlite")
        self.run_rank("of", "--pane", "t3:x", thread="thread:delegated-task:builder", t3_db=self.dir / "no-such.sqlite")
        self.assertEqual(self.log_lines(), [])

    def test_a_log_that_cannot_be_written_does_not_change_the_answer(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        blocked = self.dir / "blocked"
        blocked.write_text("a file, not a folder")
        p = self.run_rank("of", thread="thread:delegated-task:builder", t3_db=self.make_t3_db(self.TREE), state_dir=blocked / "state")
        self.assertEqual((p.returncode, p.stdout), (0, "2\n"))

    def test_an_explicit_pane_does_not_walk(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        p = self.run_rank("of", "--pane", "t3:thread:delegated-task:builder", thread="thread:delegated-task:builder",
                          t3_db=self.make_t3_db(self.TREE))
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))

    def test_the_database_is_found_under_t3code_home(self):
        self.write(self.rows("2|Lead|t3:" + self.LEAD))
        (self.dir / "userdata").mkdir()
        db = self.make_t3_db(self.TREE)
        db.rename(self.dir / "userdata" / "statev2.sqlite")
        env = {"PATH": os.environ["PATH"], "HOME": str(self.dir / "nohome"), "WORKSTREAM_RANK_FILE": str(self.file),
               "T3CODE_HOME": str(self.dir), "T3CODE_THREAD_ID": "thread:delegated-task:builder"}
        p = subprocess.run(["sh", str(SCRIPT), "of"], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "2\n", ""))

    def test_a_herdr_pane_id_alone_is_no_longer_a_key(self):
        p = self.run_rank("of", rank_file=GOLDEN, herdr_pane="w1A:pK")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "1000\n", ""))

    def test_an_empty_thread_id_is_unranked(self):
        self.write(self.rows("1|Odd|t3:"))
        p = self.run_rank("of", thread="")
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))

    def test_pane_option_beats_the_environment(self):
        p = self.run_rank("of", "--pane", "w1A:pG", rank_file=GOLDEN, thread="w1A:pK")
        self.assertEqual(p.stdout, "1\n")

    def test_no_pane_at_all_is_unranked(self):
        p = self.run_rank("of", rank_file=GOLDEN)
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))

    def test_an_empty_pane_is_unranked(self):
        self.write(self.rows("1|Lead|t3:w1A:pG"))
        p = self.run_rank("of", "--pane", "", thread="w1A:pG")
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))

    def test_a_row_with_no_pane_never_matches(self):
        self.write(self.rows("1|Nameless|-", "2|Also nameless|", "3|Short"))
        self.assertEqual(self.of("-"), "1000\n")
        self.assertEqual(self.of(""), "1000\n")

    # --- ordering ---

    def test_show_orders_by_number_not_by_file_order_or_text(self):
        self.write(self.rows("10|Ten|p10", "2|Two|p2", "1|One|p1", "9|Nine|p9"))
        p = self.run_rank("show")
        self.assertEqual(p.stdout, "".join(f"{r}{T}{n}{T}{pane}\n" for r, n, pane in
                                           [(1, "One", "p1"), (2, "Two", "p2"), (9, "Nine", "p9"), (10, "Ten", "p10")]))

    def test_the_rank_is_the_number_in_the_file_not_the_line_position(self):
        self.write(self.rows("7|Seven|p7", "3|Three|p3"))
        self.assertEqual(self.of("p7"), "7\n")
        self.assertEqual(self.of("p3"), "3\n")

    # --- shared pane: best rank wins ---

    def test_a_shared_pane_gets_the_best_rank_wherever_it_sits(self):
        self.write(self.rows("5|Late first in file|pX", "2|Best|pX", "3|Middle|pX", "1|Elsewhere|pY"))
        self.assertEqual(self.of("pX"), "2\n")

    def test_a_shared_pane_compares_numbers_not_text(self):
        self.write(self.rows("10|Ten|pX", "9|Nine|pX"))
        self.assertEqual(self.of("pX"), "9\n")

    def test_pane_must_match_exactly(self):
        self.write(self.rows("1|Prefix|w1A:pG2", "2|Real|w1A:pG"))
        self.assertEqual(self.of("w1A:pG"), "2\n")

    # --- missing or corrupt file: 1000, one warning, never an error ---

    def assert_unusable(self, rank_file="default"):
        p = self.run_rank("of", "--pane", "w1A:pG", rank_file=rank_file)
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"), p.stderr)
        self.assertEqual(len(p.stderr.splitlines()), 1, p.stderr)
        self.assertTrue(p.stderr.startswith("workstream-rank:"), p.stderr)
        s = self.run_rank("show", rank_file=rank_file)
        self.assertEqual((s.returncode, s.stdout), (0, ""), s.stderr)
        self.assertEqual(len(s.stderr.splitlines()), 1, s.stderr)

    def test_a_missing_file_is_unranked(self):
        self.assert_unusable(rank_file=self.dir / "nope")

    def test_a_directory_instead_of_a_file_is_unranked(self):
        self.assert_unusable(rank_file=self.dir)

    def test_an_empty_file_is_unranked(self):
        self.write("")
        self.assert_unusable()

    def test_a_missing_header_makes_the_whole_file_unusable(self):
        self.write("1" + T + "Coordinator" + T + "w1A:pG\n")
        self.assert_unusable()

    def test_an_unknown_major_version_is_unusable(self):
        for header in ("#workstream-rank v2", "#workstream-rank v10", "#workstream-rank", "workstream-rank v1", " #workstream-rank v1"):
            with self.subTest(header=header):
                self.write(header + "\n1" + T + "Coordinator" + T + "w1A:pG\n")
                self.assert_unusable()

    def test_the_header_must_be_on_line_one(self):
        self.write("# a comment first\n" + HEADER + "1" + T + "Coordinator" + T + "w1A:pG\n")
        self.assert_unusable()

    def test_a_missing_file_does_not_fall_back_to_the_default_path(self):
        home = self.dir / "home"
        (home / ".local/share/coordinator").mkdir(parents=True)
        (home / ".local/share/coordinator/rank").write_text(GOLDEN.read_text())
        p = self.run_rank("of", "--pane", "w1A:pG", rank_file=self.dir / "nope", home=home)
        self.assertEqual(p.stdout, "1000\n")

    # --- bad lines are skipped, good ones still count ---

    def test_malformed_lines_are_skipped(self):
        bad = ["abc|Word rank|pX", "|Empty rank|pX", "-1|Negative|pX", "0|Zero|pX", "1.5|Fraction|pX",
               " 1|Padded|pX", "1x|Suffix|pX", "1", "", "just text"]
        self.write(self.rows(*bad, "7|Good|pX"))
        self.assertEqual(self.of("pX"), "7\n")
        self.assertEqual(self.run_rank("show").stdout, "7" + T + "Good" + T + "pX\n")

    def test_ranks_have_no_upper_bound_and_compare_as_numbers(self):
        big, bigger = "99999999999999999999", "100000000000000000000"  # 20 and 21 digits
        huge = "1" + "0" * 40
        self.write(self.rows(f"{huge}|Huge|pH", f"{bigger}|Bigger|pS", f"{big}|Big|pS", "1000000000000000|Quadrillion|pQ",
                             "000000000000000000000000000002|PaddedTwo|pT",
                             "123456789|Nine|p9", "1234567890|Ten|p10", "12|Twelve|p12", "11|Eleven|p11",
                             "12345678901234567891|Later|pF", "12345678901234567890|Sooner|pF"))
        self.assertEqual(self.of("pF"), "12345678901234567890\n")  # differs beyond float precision
        self.assertEqual(self.of("pS"), big + "\n")
        self.assertEqual(self.of("pH"), huge + "\n")
        self.assertEqual(self.of("pQ"), "1000000000000000\n")
        self.assertEqual(self.of("pT"), "2\n")
        self.assertEqual([line.split(T)[0] for line in self.run_rank("show").stdout.splitlines()],
                         ["2", "11", "12", "123456789", "1234567890", "1000000000000000",
                          "12345678901234567890", "12345678901234567891", big, bigger, huge])

    def test_large_ranks_and_leading_zeros_are_fine(self):
        self.write(self.rows("1000000000|Billion|pB", "0000000001|Padded|pP", "999999999999999|Biggest|pM", "0000000000000001|LongPad|pL"))
        self.assertEqual(self.of("pL"), "1\n")
        self.assertEqual(self.of("pB"), "1000000000\n")
        self.assertEqual(self.of("pP"), "1\n")
        self.assertEqual(self.of("pM"), "999999999999999\n")

    def test_rows_sharing_a_rank_both_count(self):
        self.write(self.rows("1|First|pA", "1|Duplicate|pB"))
        self.assertEqual(self.of("pA"), "1\n")
        self.assertEqual(self.of("pB"), "1\n")

    def test_crlf_line_endings_and_a_missing_final_newline_are_tolerated(self):
        self.write("#workstream-rank v1\r\n1" + T + "Win" + T + "pX\r\n2" + T + "NoNewline" + T + "pY")
        self.assertEqual(self.of("pX"), "1\n")
        self.assertEqual(self.of("pY"), "2\n")
        self.assertEqual(self.run_rank("show").stdout, "1" + T + "Win" + T + "pX\n2" + T + "NoNewline" + T + "pY\n")

    def test_panes_are_literal_strings_not_patterns(self):
        self.write(self.rows("1|Glob|p[.*]\\q", "2|Plain|pAq", "3|Num|1", "4|Exp|1e3"))
        self.assertEqual(self.of("p[.*]\\q"), "1\n")
        self.assertEqual(self.of("pAq"), "2\n")
        self.assertEqual(self.of("01"), "1000\n")  # numeric-looking panes compare as text: 01 is not 1
        self.assertEqual(self.of("1000"), "1000\n")  # and 1e3 is not 1000 (UNRANKED here)
        self.assertEqual(self.of("1.0"), "1000\n")

    def test_a_row_with_two_fields_is_kept_but_has_no_pane(self):
        self.write(self.rows("1|Name only"))
        self.assertEqual(self.run_rank("show").stdout, "1" + T + "Name only" + T + "-\n")

    def test_hash_lines_are_ignored_even_if_they_look_like_rows(self):
        self.write(self.rows("#1|Commented out|pX", "# 1|Commented too|pX", "4|Real|pX"))
        self.assertEqual(self.of("pX"), "4\n")
        self.assertEqual(self.run_rank("show").stdout, "4" + T + "Real" + T + "pX\n")

    # --- v2 tolerance: additive changes never break a v1 reader ---

    def test_extra_trailing_fields_and_comments_are_ignored(self):
        self.write(("#workstream-rank v1 (written by a newer coordinator)\n# more\n# comment lines\n"
                   + "1|Coordinator|w1A:pG|cwd=/x|cmd=y|future\n"
                   + "2|Pi-Bolt|w1A:pK|\n"
                   + "# trailing comment\n").replace("|", T))
        self.assertEqual(self.of("w1A:pG"), "1\n")
        self.assertEqual(self.of("w1A:pK"), "2\n")
        self.assertEqual(self.run_rank("show").stdout,
                         "1" + T + "Coordinator" + T + "w1A:pG\n2" + T + "Pi-Bolt" + T + "w1A:pK\n")

    # --- where the file lives ---

    def test_the_default_path_is_under_home(self):
        home = self.dir / "home"
        (home / ".local/share/coordinator").mkdir(parents=True)
        (home / ".local/share/coordinator/rank").write_text(self.rows("3|Default path|pD"))
        p = self.run_rank("of", "--pane", "pD", rank_file=None, home=home)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "3\n", ""))

    def test_the_environment_file_beats_the_default_path(self):
        home = self.dir / "home"
        (home / ".local/share/coordinator").mkdir(parents=True)
        (home / ".local/share/coordinator/rank").write_text(self.rows("3|Default|pD"))
        self.write(self.rows("5|Env|pD"))
        p = self.run_rank("of", "--pane", "pD", home=home)
        self.assertEqual(p.stdout, "5\n")

    # --- options ---

    def test_cwd_and_cmd_are_accepted_and_ignored(self):
        p = self.run_rank("of", "--pane", "w1A:pK", "--cwd", "/some/where", "--cmd", "cargo test", rank_file=GOLDEN)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "2\n", ""))
        p = self.run_rank("of", "--cwd", "/some/where", "--cmd", "cargo test", rank_file=GOLDEN)
        self.assertEqual((p.returncode, p.stdout), (0, "1000\n"))

    def test_usage_mistakes_exit_2_and_say_so(self):
        for args in ([], ["bogus"], ["of", "--pane"], ["of", "--wat", "x"], ["of", "stray"], ["show", "extra"]):
            with self.subTest(args=args):
                p = self.run_rank(*args, rank_file=GOLDEN)
                self.assertEqual(p.returncode, 2, p.stdout)
                self.assertIn("usage:", p.stderr)

    def test_help_exits_0(self):
        p = self.run_rank("--help")
        self.assertEqual(p.returncode, 0)
        self.assertIn("1000", p.stdout)


if __name__ == "__main__":
    unittest.main()
