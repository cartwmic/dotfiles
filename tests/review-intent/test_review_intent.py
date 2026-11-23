"""Black-box test for dot_local/bin/executable_review-intent against a scripted ledger.

The fake state dir holds pane-bin/ledger, a stand-in that answers `ledger show ask|decision|workstream X --json` from a JSON file, so nothing reads the
real ledger and nothing reaches GitHub.

    python3 -m unittest discover -s tests/review-intent -v
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_review-intent"

FAKE_LEDGER = """#!/usr/bin/env python3
import json, os, sys
db = json.load(open(os.path.join(os.environ["COORDINATOR_STATE_DIR"], "db.json")))
if sys.argv[1] == "list":
    print(json.dumps(list(db.get(sys.argv[2], {}).values())))  # `ledger list decisions --json`
    sys.exit(0)
_, kind, key, *flags = sys.argv[1:]
row = db.get(kind + "s", {}).get(key)
if row is None:
    print('ledger: no %s "%s"' % (kind, key), file=sys.stderr)
    sys.exit(1)
if "--json" in flags:
    print(json.dumps(row))  # like the real one, this leaves out the exchange
else:
    # the real `show ask N --history` prints these lines, with his follow-ups among them (and the coordinator's replies)
    print("#%s [relayed] two-way from x: %s" % (key, row.get("summary")))
    print("  question: %s" % row.get("question"))
    print("  1) Yes: do it")
    for r in row.get("exchange", []):
        print("  %s %s by %s: %s" % (r["kind"], r["at"], r["who"], r["text"]))
    print("  by coordinator at 2026-01-01T00:00:00.000Z: opened")
"""

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
d = json.load(open(os.path.join(os.environ["FAKE_GH_DIR"], "gh.json")))
a = sys.argv[1:]
if a[:2] == ["pr", "view"]:
    print(d["body"] if "body" in a else d["head"])
elif a[0] == "api" and "--paginate" in a:
    for p in d["files"]:
        print(p)
elif a[0] == "api":
    path = a[-1]
    name, ref = path.split("/contents/", 1)[1].split("?ref=")
    if name in d.get("fail", {}):
        print(d["fail"][name], file=sys.stderr)
        sys.exit(1)
    if ref != d["head"] or name not in d["contents"]:
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(d["contents"][name])
else:
    sys.exit(2)
"""


# A stand-in for pr-body-check: prints FAKE_PBC_DIR/out and exits with the code in FAKE_PBC_DIR/code (0 when there is no file), and logs its arguments.
FAKE_PBC = """#!/bin/sh
echo "$@" >> "$FAKE_PBC_DIR/args"
[ -f "$FAKE_PBC_DIR/out" ] && cat "$FAKE_PBC_DIR/out"
[ -f "$FAKE_PBC_DIR/err" ] && cat "$FAKE_PBC_DIR/err" >&2
[ -f "$FAKE_PBC_DIR/sleep" ] && exec sleep "$(cat "$FAKE_PBC_DIR/sleep")"
exit "$(cat "$FAKE_PBC_DIR/code" 2>/dev/null || echo 0)"
"""


def ask(n, **kw):
    row = {"id": n, "summary": "summary %d" % n, "question": "question %d?" % n, "options": [{"title": "Yes", "consequence": "do it"}, {"title": "No", "consequence": "do not"}],
           "answer_choice": None, "answer": None, "answer_other": None, "answered_at": "2026-01-01T00:00:00.000Z", "workstream": None, "state": "relayed", "updated_at": "T1"}
    row.update(kw)
    return row


def decision(n, **kw):
    row = {"id": n, "summary": "decision %d" % n, "question": "q?", "options": ["alpha", "beta"], "chose": 2, "why": "because", "ask_id": None, "voided_at": None, "at": "T1"}
    row.update(kw)
    return row


class ReviewIntent(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="review-intent-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "pane-bin").mkdir()
        (self.dir / "pane-bin/ledger").write_text(FAKE_LEDGER, encoding="utf-8")
        (self.dir / "pane-bin/ledger").chmod(0o755)
        (self.dir / "bin").mkdir()
        (self.dir / "bin/gh").write_text(FAKE_GH, encoding="utf-8")
        (self.dir / "bin/gh").chmod(0o755)
        (self.dir / "bin/pr-body-check").write_text(FAKE_PBC, encoding="utf-8")
        (self.dir / "bin/pr-body-check").chmod(0o755)
        self.db = {"asks": {}, "decisions": {}, "workstreams": {}}

    def put(self, *, asks=(), decisions=(), workstreams=()):
        for a in asks:
            self.db["asks"][str(a["id"])] = a
        for d in decisions:
            self.db["decisions"][str(d["id"])] = d
        for w in workstreams:
            self.db["workstreams"][w["name"]] = w
        (self.dir / "db.json").write_text(json.dumps(self.db), encoding="utf-8")

    def run_script(self, text=None, *args):
        argv = ["python3", str(SCRIPT), "--state-dir", str(self.dir), *args]
        if text is not None:
            f = self.dir / "body.md"
            f.write_text(text, encoding="utf-8")
            argv += ["--body-file", str(f)]
        env = dict(os.environ, PATH="%s:%s" % (self.dir / "bin", os.environ["PATH"]), FAKE_GH_DIR=str(self.dir), FAKE_PBC_DIR=str(self.dir), AGENT_TRACES_DIR=str(self.dir / "traces"))
        if self.path is not None:
            env["PATH"] = self.path
        return subprocess.run(argv, capture_output=True, text=True, timeout=60, env=env)

    path = None

    def put_pr(self, *, files, contents, body="", head="abc123", fail=None):
        (self.dir / "gh.json").write_text(json.dumps({"body": body, "files": files, "contents": contents, "head": head, "fail": fail or {}}), encoding="utf-8")

    @staticmethod
    def marker(out):
        m = re.search(r"^<!-- review-intent v1 asks=(\S+) decisions=(\S+) sha256=([0-9a-f]{64}) -->$", out, re.M)
        assert m, out
        return m.group(1), m.group(2), m.group(3)

    @staticmethod
    def body(out):
        return out.split("-->\n", 1)[1].rsplit("<!-- /review-intent -->", 1)[0]

    def test_a_range_collects_every_ask_and_quotes_his_words(self):
        self.put(asks=[ask(5, answer_choice=1, answer="exactly: a small set of tools"), ask(6), ask(7, answer_other="only this")])
        r = self.run_script("The owner approved asks #5–#7 (see the design).")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("## Owner intent (generated by review-intent)\n"))
        self.assertEqual(self.marker(r.stdout)[:2], ("5,6,7", "none"))
        self.assertIn("> exactly: a small set of tools", r.stdout)
        self.assertIn("Chosen option: 1) Yes: do it", r.stdout)
        self.assertIn("> only this", r.stdout)

    def test_his_follow_ups_are_quoted_and_the_coordinators_replies_are_not(self):
        self.put(asks=[ask(90, answer_choice=1, exchange=[
            {"kind": "follow-up", "at": "2026-01-02T00:00:00.000Z", "who": "michael (status page)", "text": "the idea was to support both"},
            {"kind": "reply", "at": "2026-01-02T00:01:00.000Z", "who": "coordinator", "text": "Checking: the lead is looking"},
            {"kind": "follow-up", "at": "2026-01-03T00:00:00.000Z", "who": "michael (status page)", "text": "line one\nline two: with a colon"},
        ])])
        r = self.run_script("ask #90")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("written 2026-01-02T00:00:00.000Z while the ask was open (verbatim):\n> the idea was to support both", r.stdout)
        self.assertIn("> line one\n> line two: with a colon", r.stdout)
        self.assertNotIn("Checking: the lead", r.stdout)
        self.assertLess(r.stdout.index("the idea was"), r.stdout.index("line one"))
        self.assertNotIn("none recorded", r.stdout)

    def test_an_other_answer_the_ledger_also_files_as_a_follow_up_is_quoted_once(self):
        self.put(asks=[ask(95, answer_other="small set of tools", exchange=[{"kind": "follow-up", "at": "2026-01-02T00:00:00.000Z", "who": "michael", "text": "small set of tools"}])])
        self.assertEqual(self.run_script("ask #95").stdout.count("small set of tools"), 1)

    def test_an_ask_with_no_words_of_his_says_so(self):
        self.put(asks=[ask(91, answer_choice=1)])
        self.assertIn("His words: none recorded", self.run_script("ask #91").stdout)

    def test_a_workstream_why_may_name_its_ask_without_a_hash(self):
        self.put(asks=[ask(92, workstream="Retro"), ask(870, answer="founding words"), ask(5)],
                 workstreams=[{"name": "Retro", "why": "Michael's Other answer on ask 870, and it ran for 5 minutes"}])
        r = self.run_script("ask #92")
        self.assertEqual(self.marker(r.stdout)[0], "92,870")
        self.assertIn("> founding words", r.stdout)

    def test_a_clock_time_after_an_ask_in_a_workstream_why_is_not_an_ask(self):
        self.put(asks=[ask(96, workstream="Audit"), ask(1175, answer="real founding"), ask(22, answer="unrelated"), ask(9, answer="nine")],
                 workstreams=[{"name": "Audit", "why": "Michael on ask #1175, 22:09Z: do it; waited ask 9 minutes; ask #1175 and 22"}])
        r = self.run_script("ask #96")
        self.assertEqual(self.marker(r.stdout)[0], "96,1175")
        self.assertNotIn("unrelated", r.stdout)

    def test_a_colon_or_a_unit_after_a_hashed_ask_still_counts_and_a_bare_unit_does_not(self):
        self.put(asks=[ask(96, workstream="A"), ask(98, workstream="B"), ask(99, workstream="C"), ask(100, workstream="D"),
                       ask(1175, answer="colon"), ask(5, answer="five"), ask(3, answer="three"), ask(2, answer="two"), ask(12, answer="twelve")],
                 workstreams=[{"name": "A", "why": "Michael on ask #1175: approve the audit"},
                              {"name": "B", "why": "ask #5 minutes later; ask 3 times; ask 2 weeks; ask 5pm; ask 12h"},
                              {"name": "C", "why": "asks #1175-#1175"},
                              {"name": "D", "why": "ask #5:30"}])
        self.assertEqual(self.marker(self.run_script("ask #96").stdout)[0], "96,1175")
        self.assertEqual(self.marker(self.run_script("ask #98").stdout)[0], "5,98")
        self.assertEqual(self.marker(self.run_script("ask #100").stdout)[0], "100")

    WHY_TABLE = [  # what a workstream's creation why gives: (why, the asks it names)
        ("Michael on ask #1175, 22:09Z: do it", [1175]),
        ("Michael on ask #1175: approve the audit", [1175]),
        ("ask #1175; then more", [1175]),
        ("ask #5 minutes later", [5]),
        ("(ask 1175)", [1175]),
        ("Michael approved ask 1175", [1175]),
        ("asks 1175-1176", [1175, 1176]),
        ("asks #1175, #1176 and #1177", [1175, 1176, 1177]),
        ("ask 1175, 2026-11-09", [1175]),
        ("it waited ask 5 minutes", []),
        ("ask 3 times and ask 2 weeks", []),
        ("ask 5pm, ask 5 pm, ask 12h, ask 30s", []),
        ("ask 10:30Z", []),
        ("asked 1175 questions", []),
        ("decision #1175 and PR #1176", []),
    ]

    def test_the_workstream_why_table(self):
        ids = {1175, 1176, 1177, 5, 3, 2, 12, 30, 10, 2026, 11, 9}
        for i, (why, want) in enumerate(self.WHY_TABLE):
            with self.subTest(why=why):
                self.put(asks=[ask(n, answer="a%d" % n) for n in ids] + [ask(500 + i, workstream="W%d" % i)],
                         workstreams=[{"name": "W%d" % i, "why": why}])
                got = sorted(int(x) for x in self.marker(self.run_script("ask #%d" % (500 + i)).stdout)[0].split(",") if int(x) != 500 + i)
                self.assertEqual(got, want)

    def put_record(self, item, text):
        f = self.dir / "traces/emitted/review" / item / "pr-record.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")

    def test_with_a_pr_record_its_ids_are_read_and_the_body_is_not(self):
        self.put(asks=[ask(7), ask(8)], decisions=[decision(40, ask_id=7), decision(41)])
        self.put_pr(files=[], contents={}, body="Does a thing. ask #8\n\nDecisions: #41")
        self.put_record("coordinator#900", "| ecd63156 | pass |\nask #7\nDecisions: #40\n")
        r = self.run_script(None, "--pr", "cartwmic/coordinator#900")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.marker(r.stdout)[:2], ("7", "40"))
        self.assertNotIn("Decision #41", r.stdout)

    def test_a_record_belongs_to_its_own_pr_only(self):
        self.put(asks=[ask(7), ask(8)])
        self.put_pr(files=[], contents={}, body="ask #8")
        self.put_record("coordinator#901", "ask #7")
        self.assertEqual(self.marker(self.run_script(None, "--pr", "cartwmic/coordinator#902").stdout)[0], "8")

    def test_the_body_is_read_when_the_pr_has_no_record(self):
        self.put(asks=[ask(8)], decisions=[decision(41)])
        self.put_pr(files=[], contents={}, body="ask #8\n\nDecisions: #41")
        r = self.run_script(None, "--pr", "cartwmic/coordinator#903")
        self.assertEqual((r.returncode, self.marker(r.stdout)[:2]), (0, ("8", "41")), r.stderr)

    def test_without_a_record_the_ledger_linked_decisions_are_not_added(self):
        self.put(asks=[ask(8)], decisions=[decision(60, pr="cartwmic/coordinator#906")])
        self.put_pr(files=[], contents={}, body="ask #8")
        r = self.run_script(None, "--pr", "cartwmic/coordinator#906")
        self.assertEqual((r.returncode, self.marker(r.stdout)[:2]), (0, ("8", "none")), r.stderr)

    def test_a_ledger_that_cannot_list_decisions_is_an_error_when_the_record_is_used(self):
        self.put(asks=[ask(7)])
        self.put_pr(files=[], contents={}, body="")
        self.put_record("coordinator#907", "ask #7")
        (self.dir / "pane-bin/ledger").write_text(FAKE_LEDGER.replace('if sys.argv[1] == "list":', 'if sys.argv[1] == "list":\n    print("boom", file=sys.stderr); sys.exit(1)\nif False:'), encoding="utf-8")
        r = self.run_script(None, "--pr", "cartwmic/coordinator#907")
        self.assertEqual(r.returncode, 2)
        self.assertIn("could not list decisions", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_decisions_the_ledger_links_to_the_pr_come_with_their_asks(self):
        self.put(asks=[ask(7, answer="exactly this")], decisions=[
            decision(50, ask_id=7, pr="cartwmic/coordinator#904"), decision(51, pr="cartwmic/coordinator#905"),
            decision(52, pr="cartwmic/coordinator#904", voided_at="T2"), decision(53, pr="Cartwmic/Coordinator#904")])
        self.put_pr(files=[], contents={}, body="")
        self.put_record("coordinator#904", "Decisions: none material\n")
        r = self.run_script(None, "--pr", "cartwmic/coordinator#904")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.marker(r.stdout)[:2], ("7", "50,53"))
        self.assertIn("Cited because: the ledger links it to this PR", r.stdout)
        self.assertIn("> exactly this", r.stdout)

    LEADS = '{"name":"retro","approved_by":[1109,1233]}'

    def test_a_pr_touching_a_lead_type_cites_that_types_approved_by_asks(self):
        self.put(asks=[ask(1109, answer="a small set of tools"), ask(1233, answer="accepted"), ask(7)])
        self.put_pr(files=["leads/retro.md", "src/x.ts"], contents={"leads/retro.json": self.LEADS}, body="Does a thing. ask #7")
        r = self.run_script(None, "--pr", "cartwmic/coordinator#782")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.marker(r.stdout)[0], "7,1109,1233")
        self.assertIn("Cited because: approved_by of the lead type retro (leads/retro.json at the PR head)", r.stdout)
        self.assertIn("> a small set of tools", r.stdout)

    def test_a_gh_failure_other_than_not_found_is_an_error_not_a_skip(self):
        self.put(asks=[ask(1109), ask(1233), ask(7)])
        self.put_pr(files=["leads/retro.json"], contents={"leads/retro.json": self.LEADS}, body="ask #7", fail={"leads/retro.json": "gh: API rate limit exceeded (HTTP 403)"})
        r = self.run_script(None, "--pr", "cartwmic/coordinator#4")
        self.assertEqual(r.returncode, 2)
        self.assertIn("could not read leads/retro.json", r.stderr)
        self.assertIn("HTTP 403", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_a_pr_that_touches_no_lead_type_adds_nothing(self):
        self.put(asks=[ask(1109), ask(7)])
        self.put_pr(files=["src/x.ts", "docs/leads/retro.md"], contents={"leads/retro.json": self.LEADS}, body="ask #7")
        self.assertEqual(self.marker(self.run_script(None, "--pr", "cartwmic/coordinator#1").stdout)[0], "7")

    def test_a_lead_type_without_approved_by_or_without_a_file_at_the_head_is_skipped(self):
        self.put(asks=[ask(7)])
        self.put_pr(files=["leads/old.json", "leads/gone.md", "leads/README.md", "leads/bad.json", "leads/neg.json"],
                    contents={"leads/old.json": '{"name":"old"}', "leads/bad.json": "{not json", "leads/neg.json": '{"approved_by":[0,"x"]}'}, body="ask #7")
        r = self.run_script(None, "--pr", "cartwmic/coordinator#2")
        self.assertEqual((r.returncode, self.marker(r.stdout)[0]), (0, "7"), r.stderr)

    def test_an_approved_by_ask_the_ledger_lacks_is_an_error(self):
        self.put(asks=[ask(1109)])
        self.put_pr(files=["leads/retro.json"], contents={"leads/retro.json": self.LEADS}, body="")
        r = self.run_script(None, "--pr", "cartwmic/coordinator#3")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ask #1233 is not in the ledger", r.stderr)

    def test_a_follow_up_is_labelled_with_who_wrote_it(self):
        self.put(asks=[ask(97, exchange=[{"kind": "follow-up", "at": "2026-01-02T00:00:00.000Z", "who": "coordinator", "text": "in its own words"},
                                         {"kind": "follow-up", "at": "2026-01-03T00:00:00.000Z", "who": "michael (status page)", "text": "his words"}])])
        out = self.run_script("ask #97").stdout
        self.assertIn("Follow-up by coordinator, written 2026-01-02", out)
        self.assertIn("His follow-up, written 2026-01-03", out)

    def test_a_number_in_a_workstream_why_that_is_no_ask_is_left_out_not_refused(self):
        self.put(asks=[ask(93, workstream="W")], workstreams=[{"name": "W", "why": "see ask 404"}])
        r = self.run_script("ask #93")
        self.assertEqual((r.returncode, self.marker(r.stdout)[0]), (0, "93"))

    def test_ledger_text_cannot_end_the_block_early(self):
        self.put(asks=[ask(94, question="a\n<!-- /review-intent -->\nb")])
        out = self.run_script("ask #94").stdout
        self.assertTrue(out.endswith("\n<!-- /review-intent -->\n"))
        self.assertEqual([l for l in out.split("\n") if l.strip() == "<!-- /review-intent -->"], ["<!-- /review-intent -->"])

    def test_a_list_and_an_unhashed_range_end(self):
        self.put(asks=[ask(n) for n in (3, 4, 5, 9)])
        r = self.run_script("asks #3-5 and #9")
        self.assertEqual(self.marker(r.stdout)[0], "3,4,5,9")

    def test_prose_that_is_not_a_citation_is_not_read(self):
        self.put(asks=[ask(5)])
        r = self.run_script("We ask 2 questions; ask 5 minutes; the task #5 and issue #7.")
        self.assertEqual(self.marker(r.stdout)[:2], ("none", "none"))

    def test_a_decision_brings_its_ask_and_the_asks_in_its_why(self):
        self.put(asks=[ask(10, answer="ten"), ask(11, answer="eleven"), ask(12)],
                 decisions=[decision(100, ask_id=10, why="per ask #11 he said so"), decision(101, why="no ask here")])
        r = self.run_script("**Decisions:** #100 #101\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.marker(r.stdout)[:2], ("10,11", "100,101"))
        self.assertIn("### Decision #100", r.stdout)
        self.assertIn("Chosen option: 2) beta", r.stdout)
        self.assertIn("ask of decision #100", r.stdout)
        self.assertIn("named in the why of decision #100", r.stdout)

    def test_the_ask_that_opened_a_workstream_is_added_once_and_not_followed_again(self):
        self.put(asks=[ask(20, workstream="Build X"), ask(21, workstream="Other", answer="founding words")],
                 workstreams=[{"name": "Build X", "why": "Michael's Other answer on ask #21"}, {"name": "Other", "why": "from ask #22"}])
        r = self.run_script("The owner approved this in ask #20.")
        self.assertEqual(self.marker(r.stdout)[0], "20,21")
        self.assertIn("> founding words", r.stdout)
        self.assertIn('opened the workstream "Build X" of ask #20', r.stdout)

    def test_a_workstream_that_cites_the_ask_itself_adds_nothing(self):
        self.put(asks=[ask(30, workstream="W")], workstreams=[{"name": "W", "why": "opened by ask #30"}])
        self.assertEqual(self.marker(self.run_script("asks #30").stdout)[0], "30")

    def test_nothing_cited_says_so_in_one_line(self):
        self.put()
        r = self.run_script("Decisions: none material")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.marker(r.stdout)[:2], ("none", "none"))
        self.assertEqual(len(self.body(r.stdout).strip().splitlines()), 1)
        self.assertIn("No ask or decision is cited", r.stdout)

    def test_the_sha_is_the_body_and_is_stable(self):
        self.put(asks=[ask(40, answer="words")])
        a = self.run_script("asks #40")
        b = self.run_script("asks #40")
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(self.marker(a.stdout)[2], hashlib.sha256(self.body(a.stdout).encode("utf-8")).hexdigest())
        self.db["asks"]["40"]["answer"] = "different words"
        self.put()
        self.assertNotEqual(self.marker(self.run_script("asks #40").stdout)[2], self.marker(a.stdout)[2])

    def test_an_edit_to_the_ledger_that_is_not_in_the_block_leaves_the_sha(self):
        self.put(asks=[ask(41, answer="words")])
        before = self.marker(self.run_script("asks #41").stdout)[2]
        self.db["asks"]["41"]["updated_at"] = "T2"
        self.put()
        self.assertEqual(self.marker(self.run_script("asks #41").stdout)[2], before)

    def test_an_earlier_block_in_a_body_file_is_not_read_as_a_citation(self):
        self.put(asks=[ask(50, answer="x"), ask(51)])
        first = self.run_script("asks #50").stdout
        r = self.run_script("Brief text.\n\n" + first + "\nMore text.\n")
        self.assertEqual(self.marker(r.stdout)[0], "none")

    def test_an_unknown_id_is_refused_and_named(self):
        self.put(asks=[ask(60)])
        r = self.run_script("asks #60 and #61\nDecisions: #70")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("ask #61 is not in the ledger", r.stderr)
        self.assertIn("decision #70 is not in the ledger", r.stderr)

    def test_ids_given_by_hand(self):
        self.put(asks=[ask(80)], decisions=[decision(81)])
        r = self.run_script(None, "--ask", "80", "--decision", "81")
        self.assertEqual(self.marker(r.stdout)[:2], ("80", "81"))

    # --- the record check: pr-body-check on the PR's agent record, before any brief is built ---

    def pbc(self, code, out="", err="", sleep=None):
        for name, text in (("code", str(code)), ("out", out), ("err", err)):
            (self.dir / name).write_text(text, encoding="utf-8")
        if sleep is not None:
            (self.dir / "sleep").write_text(str(sleep), encoding="utf-8")

    def pr_with_decision(self):
        self.put(asks=[ask(5)])
        self.put_pr(files=[], contents={}, body="")
        rec = self.dir / "traces/emitted/review/coordinator#930"
        rec.mkdir(parents=True, exist_ok=True)
        (rec / "pr-record.md").write_text("Decisions: none material\n", encoding="utf-8")

    def fail_with(self, head):
        return "pr-body-check: FAIL cartwmic/coordinator#930\n" + head + "\n  fix: do it\n"

    def test_a_record_that_passes_the_check_builds_the_brief(self):
        self.pr_with_decision()
        self.pbc(0, "pr-body-check: OK cartwmic/coordinator#930\n")
        r = self.run_script(None, "--pr", "cartwmic/coordinator#930")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("## Owner intent", r.stdout)
        self.assertEqual((self.dir / "args").read_text().strip(), "cartwmic/coordinator 930 --skip-intent-review")

    def test_a_bare_repo_name_is_checked_as_cartwmic_repo(self):
        self.pr_with_decision()
        self.run_script(None, "--pr", "coordinator#930")
        self.assertEqual((self.dir / "args").read_text().strip(), "cartwmic/coordinator 930 --skip-intent-review")

    def test_each_record_defect_refuses_with_the_tools_own_text_and_prints_nothing(self):
        heads = {
            "no record": "the PR has no agent record (the principles table, Decisions line and job ids are read from it)",
            "principles table": "the PR's agent record has no complete principles table (rule ecd63156)",
            "decisions line": "the PR's agent record has no Decisions line (rule ccc6c94b)",
            "decisions ledger": "pr-decisions-check: cartwmic/coordinator#930 FAILED: the Decisions line is missing a decision whose ledger record names this PR:",
        }
        for name, head in heads.items():
            with self.subTest(name):
                self.pr_with_decision()
                self.pbc(1, self.fail_with(head))
                r = self.run_script(None, "--pr", "cartwmic/coordinator#930")
                self.assertEqual(r.returncode, 3)
                self.assertEqual(r.stdout, "")
                self.assertIn(head, r.stderr)
                self.assertIn("fix: do it", r.stderr)
                self.assertIn("Fix the record, then build the brief", r.stderr)

    def test_a_defect_that_is_not_in_the_record_is_reported_and_does_not_refuse(self):
        self.pr_with_decision()
        for head in ("the description's Proven section does not name the PR head (playbook rule f5a367b5: the head commit the checks ran on)",
                     "a GitHub Actions run on the PR head is red or still running (merge rule: head-sha runs)",
                     "the PR names work by decision-log, mockup or task ids (rule 385acc43)"):
            with self.subTest(head):
                self.pbc(1, self.fail_with(head))
                r = self.run_script(None, "--pr", "cartwmic/coordinator#930")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("## Owner intent", r.stdout)
                self.assertIn(head, r.stderr)
                self.assertIn("not about the agent record", r.stderr)

    def test_a_record_defect_among_other_failures_still_refuses(self):
        self.pr_with_decision()
        self.pbc(1, "pr-body-check: FAIL x\na GitHub Actions run on the PR head is red or still running (merge rule: head-sha runs)\n  run 1\n"
                    "the PR's agent record has no Decisions line (rule ccc6c94b)\n  fix: add one\n")
        self.assertEqual(self.run_script(None, "--pr", "cartwmic/coordinator#930").returncode, 3)

    def test_a_check_that_cannot_run_does_not_block_the_review(self):
        self.pr_with_decision()
        cases = {"gh failed": (2, "", "could not read the pull request: gh: HTTP 502"), "bad exit": (127, "", "")}
        for name, (code, out, err) in cases.items():
            with self.subTest(name):
                self.pbc(code, out, err)
                r = self.run_script(None, "--pr", "cartwmic/coordinator#930")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("## Owner intent", r.stdout)
                self.assertIn("warning: pr-body-check could not check cartwmic/coordinator#930", r.stderr)
                self.assertIn("agent record was not checked", r.stderr)

    def test_a_missing_pr_body_check_does_not_block_the_review(self):
        self.pr_with_decision()
        (self.dir / "bin/pr-body-check").unlink()
        sh = shutil.which("python3")
        # a PATH with python3 and gh (the fake one) but no pr-body-check
        tools = self.dir / "tools"
        tools.mkdir()
        for name, target in (("python3", sh), ("gh", str(self.dir / "bin/gh"))):
            (tools / name).symlink_to(target)
        self.path = str(tools)
        r = self.run_script(None, "--pr", "cartwmic/coordinator#930")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("## Owner intent", r.stdout)
        self.assertIn("warning: pr-body-check is not on PATH", r.stderr)

    def test_a_check_that_hangs_does_not_block_the_review(self):
        self.pr_with_decision()
        self.pbc(0, sleep=30)
        src = SCRIPT.read_text(encoding="utf-8").replace("CHECK_SECONDS = 180", "CHECK_SECONDS = 1")
        quick = self.dir / "review-intent-quick"
        quick.write_text(src, encoding="utf-8")
        env = dict(os.environ, PATH="%s:%s" % (self.dir / "bin", os.environ["PATH"]), FAKE_GH_DIR=str(self.dir), FAKE_PBC_DIR=str(self.dir), AGENT_TRACES_DIR=str(self.dir / "traces"))
        r = subprocess.run(["python3", str(quick), "--state-dir", str(self.dir), "--pr", "cartwmic/coordinator#930"], capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("warning: pr-body-check could not run (timed out)", r.stderr)

    def test_skip_record_check_does_not_run_the_check(self):
        self.pr_with_decision()
        self.pbc(1, self.fail_with("the PR has no agent record (x)"))
        r = self.run_script(None, "--pr", "cartwmic/coordinator#930", "--skip-record-check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.dir / "args").exists())

    def test_no_pr_means_no_record_check(self):
        self.put(asks=[ask(5)])
        self.pbc(1, self.fail_with("the PR has no agent record (x)"))
        r = self.run_script("ask #5")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.dir / "args").exists())

    @unittest.skipUnless((Path.home() / "git/coordinator/scripts/pr-body-check.ts").is_file() and shutil.which("node"), "needs the coordinator checkout")
    def test_record_heads_match_pr_body_check(self):
        """The heads review-intent refuses on are the first lines pr-body-check really prints for those defects (read from the coordinator checkout)."""
        coord = Path.home() / "git/coordinator"
        js = """
import { problemBlocks } from './scripts/pr-body-check.ts';
import { prDecisionsFailure } from './src/ledger/pr-decisions.ts';
const base = { body: '', commits: [], files: ['a.ts'], diff: '' };
const blocks = [
  ...problemBlocks({ ...base, recordProblem: 'none' }, 8),
  ...problemBlocks({ ...base, record: 'no table, no decisions' }, 8),
  prDecisionsFailure({ pr: 'cartwmic/x#1', line: null, missing: [{ id: 1, summary: 's' }], notLive: [], noChoice: [] }),
];
console.log(JSON.stringify(blocks.map((b) => b.split('\\n')[0])));
"""
        r = subprocess.run(["node", "--experimental-strip-types", "--disable-warning=ExperimentalWarning", "--input-type=module", "-e", js], cwd=coord, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        firsts = json.loads(r.stdout.strip().splitlines()[-1])
        heads = re.search(r"RECORD_HEADS = \((.*?)\n\)", SCRIPT.read_text(encoding="utf-8"), re.S).group(1)
        heads = [json.loads(l.strip().rstrip(",")) for l in heads.splitlines() if l.strip()]
        for head in heads:
            self.assertTrue(any(f.startswith(head) for f in firsts), "no pr-body-check block starts with %r; it prints %r" % (head, firsts))

    def test_a_missing_ledger_is_a_usage_error(self):
        r = subprocess.run(["python3", str(SCRIPT), "--state-dir", str(self.dir / "nope")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no ledger at", r.stderr)


if __name__ == "__main__":
    unittest.main()
