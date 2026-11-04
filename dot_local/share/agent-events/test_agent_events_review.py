"""Tests for the review reader (agent_events_review). Review logs here are scripted: the golden pairs, plus logs written by the tests."""
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_events as ae  # noqa: E402
import agent_events_metrics as am  # noqa: E402
import agent_events_review as rv  # noqa: E402
import test_agent_events as base  # noqa: E402

# The golden pairs are the kit's, vendored byte for byte from agent-kit tag v0.17.0 (49ff9f00), src/traces/fixtures/golden/ (six pairs and
# MANIFEST.sha256). To take a newer set, copy the files, pin the new manifest sha256 below, and update the counts the tests assert.
GOLDEN = HERE / "fixtures" / "review-golden"
MANIFEST_SHA256 = "82af2bff6dec642318e9fbe33a6a873b4d76d3bf15d165f3ba56f383de993242"  # change the golden pairs and this pin together
SENTINEL = base.SENTINEL
APPROVED = "proj:golden:cartwmic-homelab-v2"
T, C, R, M, D, H = ("golden#treadmill", "golden#clean-pass", "golden#redesign-switch", "golden#missing-component", "golden#design-then-diff", "golden#hand-written")
NAMES = ("treadmill", "clean-pass", "design-then-diff", "redesign-switch", "missing-component", "hand-written")


def read_lines(name):
    return [json.loads(x) for x in (GOLDEN / name / "findings.jsonl").read_text().splitlines() if x.strip()]  # hand-written has a blank line


def tag_log(text, tag):
    """The golden logs reuse synthetic heads (1111111...) in every item; real items never share a head. A scratch copy gets its item's tag
    in each head so ledger keys (repo, head, round or id) do not collide between the items one test places side by side."""
    return re.sub(r'("head"\s*:\s*")', lambda m: m.group(1) + tag + ":", text)


def item_of(name):
    return json.loads((GOLDEN / name / "report.json").read_text())["item"]


def write_log(path, events, report=None):
    path.mkdir(parents=True, exist_ok=True)
    (path / "findings.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if report is not None:
        (path / "report.json").write_text(json.dumps(report, indent=2) + "\n")


def expected_from_log(items, approved):
    """The pi_review_* totals worked out from the log lines alone, never from a report. items: {item: [events]}."""
    out = {k: {} for k in ("rounds", "findings", "demoted", "redesigns", "escapes", "cost", "relations", "dispositions")}

    def add(fam, key, v=1):
        out[fam][key] = out[fam].get(key, 0) + v

    for item, ev in items.items():
        repo = item.split("#")[0].lower() if "#" in item else None
        proj = repo if repo in approved else "other"
        rounds = {e["round"]: e for e in ev if e["event"] == "round"}
        rel, outc = {}, {}
        for e in ev:
            if e["event"] == "label":
                rel[e["id"]] = e["relation"]
            if e["event"] == "disposition":
                outc[e["id"]] = e["outcome"]
        for r in rounds.values():
            model = r.get("model", "unknown")
            add("rounds", (proj, r["verdict"], r["stage"], model))
            if "cost_usd" in r:
                add("cost", (proj, r["stage"], model), r["cost_usd"])
        for e in ev:
            if e["event"] == "finding":
                r = rounds[e["round"]]
                add("findings", (proj, str(min(r["review_round"], 4)).replace("4", "4+"), e["effective"], r["stage"]))
                if e["severity"] == "blocking" and e["effective"] == "note":
                    add("demoted", (proj,))
                if e["effective"] == "blocking" and e["id"] in rel:
                    add("relations", (proj, rel[e["id"]]))
                if e["effective"] == "blocking" and e["id"] in outc:
                    add("dispositions", (proj, outc[e["id"]]))
            if e["event"] == "redesign":
                add("redesigns", (proj, e["action"], e["makes_impossible"]))
            if e["event"] == "escape":
                add("escapes", (proj,))
    return out


FAMILY = {"rounds": "pi_review_rounds_total", "findings": "pi_review_findings_total", "demoted": "pi_review_demoted_total",
          "redesigns": "pi_review_redesigns_total", "escapes": "pi_review_escapes_total", "cost": "pi_review_cost_usd_total",
          "relations": "pi_review_relations_total", "dispositions": "pi_review_dispositions_total"}


def series_of(families, name):
    for m in families:
        if m["name"] == name:
            return {tuple(v for _, v in sorted(l.items(), key=lambda kv: LABEL_ORDER[name].index(kv[0]))): val for l, val in m["points"]}
    return {}


LABEL_ORDER = {FAMILY["rounds"]: ["project", "verdict", "stage", "model"], FAMILY["findings"]: ["project", "review_round", "effective", "stage"],
               FAMILY["demoted"]: ["project"], FAMILY["redesigns"]: ["project", "action", "makes_impossible"],
               FAMILY["escapes"]: ["project"], FAMILY["cost"]: ["project", "stage", "model"],
               FAMILY["relations"]: ["project", "relation"], FAMILY["dispositions"]: ["project", "outcome"],
               "pi_review_skipped_redesigns": ["project"], "pi_review_items": ["project", "state"], "pi_review_reader_problem_items": ["reason"]}


class ReviewBase(base.Tick):
    """A scratch AGENT_TRACES_DIR, a scratch state dir, no Pi sessions of interest beyond the standard one."""

    def setUp(self):
        super().setUp()
        self.traces = Path(self._tmp.name) / "traces"
        self.review = self.traces / "emitted" / "review"
        self.gold = Path(self._tmp.name) / "gold"  # the golden pairs with each item's heads tagged (see tag_log)
        for n in NAMES:
            (self.gold / n).mkdir(parents=True)
            shutil.copy(GOLDEN / n / "report.json", self.gold / n / "report.json")
            (self.gold / n / "findings.jsonl").write_text(tag_log((GOLDEN / n / "findings.jsonl").read_text(), item_of(n)))
        prior = {k: os.environ.get(k) for k in ("AGENT_TRACES_DIR", "AGENT_EVENTS_PROJECTS")}
        os.environ["AGENT_TRACES_DIR"] = str(self.traces)
        os.environ["AGENT_EVENTS_PROJECTS"] = APPROVED
        ae._GIT_ROOTS = set()  # the approved projects are exactly the scripted ones
        self.addCleanup(lambda: setattr(ae, "_GIT_ROOTS", None))
        self.addCleanup(lambda: [os.environ.__setitem__(k, v) if v is not None else os.environ.pop(k, None) for k, v in prior.items()])

    def place(self, *names, as_item=None, tag=None):
        """Copy golden pairs into the scratch review folder under their own item names; as_item renames one copy (its report too)."""
        for n in names:
            if as_item is None:
                shutil.copytree(self.gold / n, self.review / item_of(n), dirs_exist_ok=True)
                continue
            dest = self.review / as_item
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "findings.jsonl").write_text(tag_log((GOLDEN / n / "findings.jsonl").read_text(), tag or as_item))
            (dest / "report.json").write_text(json.dumps(json.loads((GOLDEN / n / "report.json").read_text()) | {"item": as_item}, indent=2) + "\n")

    def tables(self, sql, *params):
        return [tuple(r) for r in self.q(sql, *params)]

    def families(self):
        """The review counters and gauges as a tick would produce them: a ledger that lives as long as the test is applied to the
        tables each call (so a total that fell on disk is held by it, as in production)."""
        led = self.__dict__.setdefault("ledger", rv.new_ledger())
        approved = ae.approved_projects()
        con = ae.connect(self.db, readonly=True)
        try:
            rv.apply(con, led, approved)
            return rv.counters(led), rv.gauges(con, approved, led)
        finally:
            con.close()

    def reader(self):
        return json.loads((self.state / "status.json").read_text())["review_reader"]

    def problems(self):
        return self.build()["review"]


class GoldenPairs(unittest.TestCase):
    def test_manifest_pin_and_bytes(self):
        manifest = (GOLDEN / "MANIFEST.sha256").read_bytes()
        self.assertEqual(hashlib.sha256(manifest).hexdigest(), MANIFEST_SHA256)
        listed = {}
        for line in manifest.decode().splitlines():
            digest, path = line.split("  ", 1)
            listed[path] = digest
        self.assertEqual(set(listed), {f"{n}/{f}" for n in NAMES for f in ("findings.jsonl", "report.json")})
        for path, digest in listed.items():
            self.assertEqual(hashlib.sha256((GOLDEN / path).read_bytes()).hexdigest(), digest, path)

    def test_reports_are_in_canonical_bytes_and_account_for_their_log(self):
        for n in NAMES:
            raw = (GOLDEN / n / "report.json").read_text()
            rep = json.loads(raw)
            self.assertEqual(raw, json.dumps(rep, indent=2) + "\n", n)  # JSON.stringify(report, null, 2) + "\n"
            self.assertEqual(list(rep)[:3], ["report_schema", "findings_schema", "item"])
            lines = [x for x in (GOLDEN / n / "findings.jsonl").read_text().splitlines() if x.strip()]
            self.assertEqual(rep["log"]["lines"], len(lines), n)
            self.assertEqual(sum(rep["log"]["events"].values()), len(lines), n)
            self.assertEqual(len(rep["findings"]), rep["log"]["events"]["finding"], n)


class Series(ReviewBase):
    def test_every_golden_pair_gives_the_series_worked_out_from_the_log(self):
        self.place(*NAMES)
        res = self.problems()
        self.assertEqual(res, {"ok": True, "problems": {}})
        fams, _ = self.families()
        items = {item_of(n): read_lines(n) for n in NAMES}  # heads are not part of any counted label
        want = expected_from_log(items, set(APPROVED.split(":")))
        for key, name in FAMILY.items():
            got = series_of(fams, name)
            self.assertEqual(set(got), set(want[key]), name)
            for k, v in want[key].items():
                self.assertAlmostEqual(got[k], v, places=9, msg=(name, k))
        rounds = series_of(fams, FAMILY["rounds"])
        self.assertEqual(rounds[("golden", "fail", "diff", "claude-opus-5-5")], 3 + 0)  # treadmill's three rounds
        self.assertEqual(rounds[("golden", "fail", "plan", "unknown")], 1)  # hand-written has no model: unknown
        self.assertEqual(sum(rounds.values()), 3 + 1 + 4 + 5 + 3 + 2)
        self.assertEqual(series_of(fams, FAMILY["relations"])[("golden", "repeat")], 3 + 1 + 1)  # treadmill, redesign-switch, missing-component
        self.assertEqual(series_of(fams, FAMILY["demoted"]), {})  # none of the pairs has a demoted finding
        self.assertEqual(series_of(fams, FAMILY["escapes"]), {("golden",): 1})  # hand-written
        self.assertEqual(series_of(fams, FAMILY["redesigns"]), {("golden", "switched", "yes"): 1})
        self.assertEqual(series_of(fams, FAMILY["findings"])[("golden", "3", "blocking", "diff")], 4 + 2 + 1)  # review round 3: treadmill r3, missing-component r3, redesign-switch r3
        self.assertAlmostEqual(series_of(fams, FAMILY["cost"])[("golden", "diff", "claude-opus-5-5")], 1.5 + 1.25 + 1.5 + 0.42)

    def test_gauges_come_from_the_reports(self):
        self.place(*NAMES)
        self.build()
        _, gauges = self.families()
        by = {m["name"]: series_of(gauges, m["name"]) for m in gauges}
        self.assertEqual(by["pi_review_skipped_redesigns"], {("golden",): 2 + 1})  # treadmill 2, missing-component 1
        self.assertEqual(by["pi_review_items"], {("golden", "open"): 2, ("golden", "passed"): 4})
        self.assertEqual(by["pi_review_reader_problem_items"], {(r,): 0.0 for r in rv.REASONS})

    def test_tables_hold_ids_numbers_and_enumerated_values_only(self):
        self.place("treadmill")
        self.build()
        self.assertEqual(self.tables("SELECT round, review_round, stage, verdict, model, duration_ms, cost_usd FROM review_rounds ORDER BY round"),
                         [(1, 1, "diff", "fail", "claude-opus-5-5", None, 1.5), (2, 2, "diff", "fail", "claude-opus-5-5", None, 1.25),
                          (3, 3, "diff", "fail", "claude-opus-5-5", None, 1.5)])
        rows = self.tables("SELECT id, round, severity, effective, demoted, sequence, relation, outcome, has_component FROM review_findings ORDER BY round, id")
        self.assertEqual(len(rows), 14)
        self.assertEqual(rows[0], ("r1.f1", 1, "blocking", "blocking", 0, 1, "new", "fixed", 1))
        self.assertEqual(rows[5], ("r1.n1", 1, "note", "note", 0, 1, None, None, 1))
        self.assertEqual(rows[10], ("r3.f1", 3, "blocking", "blocking", 0, 1, "follow-on", None, 1))
        self.assertEqual(self.tables("SELECT item, repo, state, skipped_redesigns, needs_component, undisposed_blocking, problems FROM review_items"),
                         [(T, "golden", "open", 2, 0, 4, "")])
        self.assertEqual(self.tables("SELECT relation, COUNT(*) FROM review_findings WHERE relation IS NOT NULL GROUP BY 1 ORDER BY 1"),
                         [("follow-on", 4), ("new", 6), ("repeat", 3)])

    def test_project_label_rules(self):
        self.place("clean-pass", as_item="cartwmic-homelab-v2#94")
        self.place("clean-pass", as_item="unknownrepo#5")
        self.place("clean-pass", as_item="d40:rule-pages")  # no '#'
        self.place("clean-pass")
        self.build()
        fams, _ = self.families()
        rounds = series_of(fams, FAMILY["rounds"])
        self.assertEqual({k[0]: v for k, v in rounds.items()}, {"cartwmic-homelab-v2": 1, "other": 2, "golden": 1})  # a hyphenated approved repo is a project

    def test_a_missing_directory_is_no_rows_and_no_problem(self):
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})
        self.assertEqual(self.tables("SELECT COUNT(*) FROM review_items"), [(0,)])
        fams, gauges = self.families()
        self.assertTrue(all(not m["points"] for m in fams if m["name"].startswith("pi_review_")))
        self.assertEqual({m["name"] for m in gauges}, {"pi_review_skipped_redesigns", "pi_review_items", "pi_review_reader_problem_items"})

    def test_an_old_database_without_the_review_tables_exports_without_them(self):
        con = sqlite3.connect(":memory:")
        led = rv.new_ledger()
        rv.apply(con, led, set())
        self.assertEqual(rv.counters(led), [])
        self.assertEqual(rv.gauges(con, set(), led), [])


class Strict(ReviewBase):
    """Each problem shows in the build result, in status.json (through a tick) and in the gauge; nothing is skipped silently."""

    def setup_item(self, name="treadmill"):
        self.place(name)
        return self.review / item_of(name)

    def assert_reported(self, reason):
        """The first build reports the reason alone (a look-confirmed reason needs a second build); the tick may add
        report_stale, because a log with a problem line never matches a report written before it. status.json and the gauge
        carry the reason either way."""
        if reason in ("report_missing", "report_stale"):
            self.assertTrue(self.problems()["ok"])
        res = self.problems()
        self.assertEqual(res, {"ok": False, "problems": {reason: 1}})
        self.assertEqual(am.run_once(self.root, self.db), 0)
        reader = self.reader()
        self.assertFalse(reader["ok"])
        self.assertEqual(reader["problems"][reason], 1)
        self.assertIn('review reader: problems {"', (self.state / "agent.log").read_text())
        _, gauges = self.families()
        self.assertEqual(series_of(gauges, "pi_review_reader_problem_items")[(reason,)], 1.0)
        return res

    def test_unknown_findings_schema(self):
        d = self.setup_item()
        rep = json.loads((d / "report.json").read_text())
        rep["findings_schema"] = 2
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assert_reported("findings_schema")

    def test_unknown_report_schema(self):
        d = self.setup_item()
        for bad in (2, "1", None, True, 1.0):
            rep = json.loads((d / "report.json").read_text())
            rep["report_schema"] = bad
            (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
            self.assertEqual(self.problems()["problems"], {"report_schema": 1}, bad)
        (d / "report.json").write_text("{not json")
        self.assertEqual(self.problems()["problems"], {"report_schema": 1})  # an unreadable report is not a v1 report
        rep = json.loads((self.gold / "treadmill" / "report.json").read_text())
        rep["item"] = "someone-else#1"
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assertEqual(self.problems()["problems"], {"report_schema": 1})  # a report for another item
        rep["item"] = T
        rep["findings"][0]["relation"] = "sideways"
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assert_reported("report_schema")

    def test_unknown_event_kind(self):
        d = self.setup_item()
        with open(d / "findings.jsonl", "a") as fh:
            fh.write(json.dumps({"event": "teleport", "at": "2026-11-02T00:00:00Z", "text": SENTINEL}) + "\n")
        res = self.problems()
        self.assertEqual(res["problems"]["unknown_event"], 1)
        # the report says 17 lines and the log now has 18: stale as well, but only once it persists
        self.assertNotIn("report_stale", res["problems"])
        res = self.problems()
        self.assertEqual(res["problems"], {"unknown_event": 1, "report_stale": 1})

    def test_an_event_listed_by_the_report_but_unknown_to_the_reader_is_still_unknown(self):
        d = self.setup_item()
        rep = json.loads((d / "report.json").read_text())
        rep["summarises"]["events"].append("teleport")
        rep["log"]["events"]["teleport"] = 1
        rep["log"]["lines"] += 1
        with open(d / "findings.jsonl", "a") as fh:
            fh.write(json.dumps({"event": "teleport", "at": "2026-11-02T00:00:00Z"}) + "\n")
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assert_reported("unknown_event")

    def test_bad_lines(self):
        lines = {"garbage": "{this is not json", "a json array": "[1, 2]", "no event": '{"at": "2026-11-02T00:00:00Z"}',
                 "bad enum": json.dumps({"event": "round", "at": "2026-11-02T00:00:00Z", "round": 9, "review_round": 1, "stage": "vibes", "verdict": "pass"}),
                 "bad at": json.dumps({"event": "judge", "at": "yesterday", "round": 1, "verdict": "churning"}),
                 "bad cost": json.dumps({"event": "round", "at": "2026-11-02T00:00:00Z", "round": 9, "review_round": 1, "stage": "diff", "verdict": "pass", "cost_usd": -1}),
                 "orphan finding": json.dumps({"event": "finding", "at": "2026-11-02T00:00:00Z", "id": "r9.f1", "round": 9, "severity": "note", "effective": "note"}),
                 "duplicate round": json.dumps({"event": "round", "at": "2026-11-02T00:00:00Z", "round": 1, "review_round": 1, "stage": "diff", "verdict": "pass"})}
        for what, line in lines.items():
            shutil.rmtree(self.review, ignore_errors=True)
            d = self.setup_item()
            with open(d / "findings.jsonl", "a") as fh:
                fh.write(line + "\n")
            self.assertEqual(self.problems()["problems"].get("bad_line"), 1, what)
        shutil.rmtree(self.review)
        d = self.setup_item()
        with open(d / "findings.jsonl", "ab") as fh:
            fh.write(b'{"event": "judge", "at": "2026-11-02T00:00:00Z", "round": 3, "verdict": "churning", "x": "\xff"}\n')
        self.assertEqual(self.problems()["problems"].get("bad_line"), 1)  # not UTF-8

    def test_bad_lines_are_not_counted_and_the_good_ones_still_are(self):
        d = self.setup_item()
        with open(d / "findings.jsonl", "a") as fh:
            fh.write("garbage\n")
        self.assertEqual(self.assert_reported("bad_line"), {"ok": False, "problems": {"bad_line": 1}})
        fams, _ = self.families()
        self.assertEqual(sum(series_of(fams, FAMILY["rounds"]).values()), 3)

    def test_a_final_line_with_no_newline_is_ignored_this_tick_and_reported_if_it_stays(self):
        d = self.setup_item()
        with open(d / "findings.jsonl", "a") as fh:
            fh.write('{"event": "round", "at": "2026-11-02T00:00:00Z", "round": 4, "review_r')
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})  # being written: nothing yet
        self.assertEqual(self.problems(), {"ok": False, "problems": {"bad_line": 1}})  # unchanged on the next look: stuck
        with open(d / "findings.jsonl", "a") as fh:  # the writer finishes: the line is complete and counts
            fh.write('ound": 1, "stage": "diff", "verdict": "pass"}\n')
        self.assertEqual(self.tables("SELECT COUNT(*) FROM review_rounds"), [(3,)])  # not read yet
        self.assertEqual(self.problems()["problems"], {})  # one stale look only
        self.assertEqual(self.tables("SELECT COUNT(*) FROM review_rounds"), [(4,)])

    def test_a_complete_final_line_without_a_newline_is_a_line(self):
        d = self.setup_item("clean-pass")
        text = (d / "findings.jsonl").read_text().rstrip("\n")
        (d / "findings.jsonl").write_text(text)  # an editor that saves no trailing newline
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})
        self.assertEqual(self.tables("SELECT log_lines FROM review_items"), [(2,)])

    def test_report_missing_is_confirmed_on_the_second_look_only(self):
        d = self.setup_item()
        (d / "report.json").unlink()
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})  # a tool's first round, before its first report
        self.assertEqual(self.problems(), {"ok": False, "problems": {"report_missing": 1}})
        shutil.copy(self.gold / "treadmill" / "report.json", d / "report.json")
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})
        (d / "report.json").unlink()
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})  # the count starts again

    def test_report_missing(self):
        d = self.setup_item()
        (d / "report.json").unlink()
        self.assert_reported("report_missing")
        fams, gauges = self.families()
        self.assertEqual(sum(series_of(fams, FAMILY["rounds"]).values()), 3)  # the raw counts stay
        self.assertEqual(series_of(fams, FAMILY["relations"]), {})  # the report-derived ones go
        self.assertEqual(series_of(gauges, "pi_review_items"), {})

    def test_an_item_with_no_round_yet_needs_no_report(self):
        write_log(self.review / "golden#t300", [])
        (self.review / "golden#t301").mkdir(parents=True)
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})


class Staleness(ReviewBase):
    """report_stale is confirmed on the second consecutive build that looks at the folder; a build that skips the rebuild
    because nothing changed still counts as a look (kit-review-2 note 3)."""

    def hand_append(self, d):
        with open(d / "findings.jsonl", "a") as fh:
            fh.write(json.dumps({"event": "judge", "at": "2026-11-02T00:00:00Z", "round": 3, "session": "s", "verdict": "not-churning"}) + "\n")

    def setUp(self):
        super().setUp()
        self.place("treadmill")
        self.d = self.review / T
        self.build()

    def test_a_hand_appended_line_is_reported_on_the_second_build_even_though_that_build_rebuilds_nothing(self):
        self.hand_append(self.d)
        reads = []
        real = rv.parse_log
        rv.parse_log = lambda p: (reads.append(p), real(p))[1]
        self.addCleanup(lambda: setattr(rv, "parse_log", real))
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})  # first look: expected, nothing shown
        self.assertEqual(len(reads), 1)
        res = self.problems()  # the log and the report are byte for byte what they were: the tables are not rebuilt
        self.assertEqual(len(reads), 1, "the second build must skip the rebuild")
        self.assertEqual(res, {"ok": False, "problems": {"report_stale": 1}})
        self.assertEqual(self.problems(), {"ok": False, "problems": {"report_stale": 1}})  # and it stays until a report is written
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(self.reader(), {"ok": False, "problems": {"report_stale": 1}})

    def test_a_report_written_between_two_looks_reports_nothing(self):
        self.hand_append(self.d)
        self.assertTrue(self.problems()["ok"])  # a tick that lands between a log append and its report
        rep = json.loads((self.d / "report.json").read_text())
        rep["log"]["lines"] += 1
        rep["log"]["events"]["judge"] += 1
        (self.d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})
        self.assertEqual(self.tables("SELECT looks FROM review_items"), [("{}",)])

    def test_it_clears_when_the_report_catches_up(self):
        self.hand_append(self.d)
        self.problems()
        self.assertFalse(self.problems()["ok"])
        rep = json.loads((self.d / "report.json").read_text())
        rep["log"]["lines"] += 1
        rep["log"]["events"]["judge"] += 1
        (self.d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})

    def test_each_kind_of_mismatch_is_stale(self):
        mutate = {"lines": lambda r: r["log"].update(lines=r["log"]["lines"] - 1),
                  "event sum": lambda r: r["log"]["events"].update(finding=r["log"]["events"]["finding"] + 1),
                  "kind not summarised": lambda r: r["summarises"]["events"].remove("label"),
                  "finding ids": lambda r: r["findings"][0].update(id="r1.zz")}
        for what, fn in mutate.items():
            rep = json.loads((self.gold / "treadmill" / "report.json").read_text())
            fn(rep)
            (self.d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
            self.problems()
            self.assertEqual(self.problems()["problems"], {"report_stale": 1}, what)

    def test_a_stale_item_keeps_the_report_derived_values_it_last_had(self):
        self.place("clean-pass")
        self.build()
        before = self.families()
        self.hand_append(self.d)
        self.problems()
        self.assertEqual(self.problems()["problems"], {"report_stale": 1})
        after = self.families()
        for name in (FAMILY["relations"], FAMILY["dispositions"]):
            self.assertEqual(series_of(after[0], name), series_of(before[0], name), name)
        self.assertEqual(series_of(after[1], "pi_review_items"), series_of(before[1], "pi_review_items"))
        self.assertEqual(series_of(after[1], "pi_review_skipped_redesigns"), series_of(before[1], "pi_review_skipped_redesigns"))
        self.assertEqual(series_of(after[0], FAMILY["relations"]), {("golden", "new"): 6, ("golden", "repeat"): 3, ("golden", "follow-on"): 4})  # treadmill's, still there
        self.assertEqual(sum(series_of(after[0], FAMILY["rounds"]).values()), 4)  # raw counts: 3 + 1

    def test_a_log_that_breaks_after_its_report_was_written_is_stale(self):
        """K2 refuses an item whose log breaks and leaves the old report.json in place. The reader sees it by comparing the report's
        log.lines with the non-empty lines it counts (a bad line counts as a line), and never reads the old report as current."""
        held = self.families()
        log = self.d / "findings.jsonl"
        good = log.read_text()
        rep = json.loads((self.d / "report.json").read_text())
        self.assertEqual(rep["log"]["lines"], len([x for x in good.splitlines() if x.strip()]))
        cases = {"a bad line appended": good + "this is not json\n",
                 "a line replaced by garbage": good.replace(good.splitlines()[5], "garbage", 1),
                 "a line lost": "\n".join(good.splitlines()[:-1]) + "\n",
                 "a blank line added": good + "\n\n   \n"}
        for what, text in cases.items():
            log.write_text(text)
            self.problems()
            res = self.problems()["problems"]
            if what == "a blank line added":
                self.assertEqual(res, {}, what)  # blank lines are not lines: the report still matches
            else:
                self.assertIn("report_stale", res, what)
                for name in (FAMILY["relations"], FAMILY["dispositions"]):  # and the report-derived values are held
                    self.assertEqual(series_of(self.families()[0], name), series_of(held[0], name), (what, name))
        log.write_text(good)
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})

    def test_a_row_with_no_report_yet_has_no_report_derived_values(self):
        shutil.rmtree(self.review)
        write_log(self.review / "golden#t901", [json.loads(x) for x in (self.gold / "treadmill" / "findings.jsonl").read_text().splitlines()])  # a log, and no report yet
        self.build()
        self.build()
        fams, gauges = self.families()
        self.assertEqual(series_of(fams, FAMILY["relations"]), {})
        self.assertEqual(series_of(fams, FAMILY["dispositions"]), {})
        self.assertEqual(series_of(gauges, "pi_review_items"), {})
        self.assertEqual(sum(series_of(fams, FAMILY["rounds"]).values()), 3)


class Sentinel(ReviewBase):
    """A sentinel in every free-text field of the log and in both files of a saved round reaches nothing the reader writes."""

    def free(self):
        s = SENTINEL
        base_at = "2026-11-02T00:00:00Z"
        return [
            {"event": "round", "at": base_at, "round": 1, "review_round": 1, "stage": "diff", "head": s, "reviewer": s, "verdict": "fail", "session": s,
             "model": "claude-opus-5-5", "duration_ms": 10, "cost_usd": 0.5},
            {"event": "finding", "at": base_at, "id": "r1.f1", "round": 1, "head": s, "reviewer": s, "severity": "blocking", "effective": "blocking",
             "component": s, "text": s, "obligation": s, "evidence": s, "consequence": s, "demoted_reason": s},
            {"event": "finding", "at": base_at, "id": "r1.f2", "round": 1, "head": s, "reviewer": s, "severity": "blocking", "effective": "note",
             "demoted_reason": f"demoted: {s}", "component": s, "text": s},
            {"event": "label", "at": base_at, "id": "r1.f1", "relation": "new", "of": s, "component": s},
            {"event": "disposition", "at": base_at, "id": "r1.f1", "outcome": "fixed", "sha": s, "reason": s, "accepted_by": s},
            {"event": "redesign", "at": base_at, "component": s, "round": 1, "blind_session": s, "comparer_session": s, "makes_impossible": "yes", "action": "switched"},
            {"event": "judge", "at": base_at, "round": 1, "session": s, "verdict": "churning"},
            {"event": "escape", "at": base_at, "item": s, "head": s, "round": 1, "found_by": s, "text": s, "of": s},
        ]

    def test_nothing_free_reaches_the_database_the_export_the_payload_status_or_the_log(self):
        item = "golden#sentinel"
        report = {"report_schema": 1, "findings_schema": 1, "item": item, "log": {"lines": 8, "events": {"round": 1, "finding": 2, "label": 1, "disposition": 1, "redesign": 1, "judge": 1, "escape": 1}},
                  "summarises": {"events": list(rv.EVENTS), "fields": {}}, "sequences": [{"sequence": 1, "first_round": 1, "last_round": 1, "stage": "diff"}],
                  "findings": [{"id": "r1.f1", "round": 1, "sequence": 1, "effective": "blocking", "relation": "new", "outcome": "fixed", "has_component": True},
                               {"id": "r1.f2", "round": 1, "sequence": 1, "effective": "note", "relation": None, "outcome": None, "has_component": True}],
                  "stuck": [], "counts": {"needs_component": 0, "undisposed_blocking": 0, "skipped_redesigns": 0}, "state": "open"}
        d = self.review / item
        write_log(d, self.free(), report)
        with open(d / "findings.jsonl", "a") as fh:  # the bad and unknown lines carry free text too
            fh.write(json.dumps({"event": "teleport", "at": "2026-11-02T00:00:00Z", "text": SENTINEL}) + "\n")
            fh.write(f'{{"event": "round", "text": "{SENTINEL}" garbage\n')
        for sub in ("round-1",):  # both files of a saved round
            (d / sub).mkdir()
            (d / sub / "findings.json").write_text(json.dumps({"findings": [{"id": "f1", "text": SENTINEL}]}))
            (d / sub / "REVIEW.md").write_text(f"VERDICT: FAIL {SENTINEL}\n")
        c = self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(self.reader()["problems"].get("unknown_event"), 1)
        self.assertEqual(self.reader()["problems"].get("bad_line"), 1)
        con = sqlite3.connect(self.db)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()
        files = [p for p in list(self.db.parent.iterdir()) + list(self.state.iterdir()) if p.is_file()]
        self.assertTrue(any(p.name == "status.json" for p in files) and any(p.name == "agent.log" for p in files))
        for p in files:
            self.assertNotIn(SENTINEL.encode(), p.read_bytes(), p.name)
            self.assertNotIn(b"hunter2", p.read_bytes(), p.name)
        for req in c.requests:
            self.assertNotIn(SENTINEL, json.dumps(req["body"]))
        env = dict(os.environ, AGENT_EVENTS_STATE_DIR=str(self.state))
        for args in (["export"], ["sql", "SELECT * FROM review_items"], ["sql", "SELECT * FROM review_findings"], ["status"]):
            out = subprocess.run([sys.executable, str(base.CLI), "--db", str(self.db), *args], capture_output=True, text=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertNotIn(SENTINEL, out.stdout + out.stderr)
        self.assertEqual(self.tables("SELECT COUNT(*) FROM review_findings"), [(2,)])  # the reader did read the log


def points(req, name):
    for m in req["body"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]:
        if m["name"] == name:
            dp = (m.get("sum") or m.get("gauge"))["dataPoints"]
            order = LABEL_ORDER.get(name)
            return {tuple(a["value"]["stringValue"] for a in sorted(p["attributes"], key=lambda a: (order.index(a["key"]) if order else 0, a["key"]))): p["asDouble"] for p in dp}
    return {}


class Baseline(ReviewBase):
    """The pi_review_* series have their own one-time baseline; no other series is touched."""

    def state_file(self):
        return json.loads((self.state / "export_state.json").read_text())

    def test_history_present_and_no_marker_exports_zero_then_exactly_one_more(self):
        self.place("treadmill", "clean-pass")
        c = self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)
        first = c.requests[-1]
        rounds = points(first, FAMILY["rounds"])
        self.assertEqual(rounds, {("golden", "fail", "diff", "claude-opus-5-5"): 0.0, ("golden", "pass", "diff", "claude-opus-5-5"): 0.0})
        for fam in FAMILY.values():
            self.assertTrue(all(v == 0 for v in points(first, fam).values()), fam)
        self.assertIn("pi_review@1", self.state_file()["seeded_families"])
        # a restart does not re-baseline: the same history is still 0
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertTrue(all(v == 0 for v in points(c.requests[-1], FAMILY["rounds"]).values()))
        # the next round adds exactly one
        d = self.review / T
        extra = {"event": "round", "at": "2026-11-03T00:00:00Z", "round": 4, "review_round": 4, "stage": "diff", "verdict": "pass", "model": "claude-sonnet-5-5", "cost_usd": 0.1}
        with open(d / "findings.jsonl", "a") as fh:
            fh.write(json.dumps(extra) + "\n")
        rep = json.loads((d / "report.json").read_text())
        rep["log"]["lines"] += 1
        rep["log"]["events"]["round"] += 1
        rep["state"] = "passed"
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(am.run_once(self.root, self.db), 0)
        key = ("golden", "pass", "diff", "claude-sonnet-5-5")  # a new combination: sent as 0 first, then its growth
        got = points(c.requests[-1], FAMILY["rounds"])
        self.assertEqual(got[key], 1.0)
        self.assertEqual(got[("golden", "fail", "diff", "claude-opus-5-5")], 0.0)
        # a series that already existed goes up by exactly one
        with open(d / "findings.jsonl", "a") as fh:
            fh.write(json.dumps(dict(extra, round=5, review_round=5)) + "\n")
        rep["log"]["lines"] += 1
        rep["log"]["events"]["round"] += 1
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(points(c.requests[-1], FAMILY["rounds"])[key], 2.0)
        self.assertAlmostEqual(points(c.requests[-1], FAMILY["cost"])[("golden", "diff", "claude-sonnet-5-5")], 0.2)  # two rounds of 0.1

    def test_the_pi_series_and_the_fingerprint_are_not_disturbed(self):
        c = self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)
        before = self.state_file()
        pi_before = {k: v for k, v in before["series"].items() if not v["n"].startswith("pi_review")}
        self.assertTrue(pi_before)
        # an existing deployment: Pi series are in the state, there is no marker, and review history is already on disk
        del before["seeded_families"]
        (self.state / "export_state.json").write_text(json.dumps(before, separators=(",", ":")))
        self.place("treadmill", "redesign-switch")
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(am.run_once(self.root, self.db), 0)  # the history must not arrive one tick later either
        after = self.state_file()
        self.assertEqual(after["fp"], before["fp"])
        self.assertEqual({k: v for k, v in after["series"].items() if not v["n"].startswith("pi_review")}, pi_before)
        review = {k: v for k, v in after["series"].items() if v["n"].startswith("pi_review")}
        self.assertTrue(review)
        self.assertTrue(all(all(x == 0 for x in e["sent"]) for e in review.values()))
        self.assertEqual(after["seeded_families"], ["pi_review@1"])
        for fam in ("pi_sessions", "pi_llm_calls", "pi_tokens"):
            self.assertEqual(points(c.requests[-1], fam), points(c.requests[0], fam), fam)

    def test_a_by_hand_log_backfilled_after_the_marker_counts_as_activity_once(self):
        c = self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.place("clean-pass")
        self.assertEqual(am.run_once(self.root, self.db), 0)  # the new series are created at 0
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(sum(points(c.requests[-1], FAMILY["rounds"]).values()), 1.0)  # clean-pass: one round

    def test_a_tick_without_a_good_build_does_not_set_the_marker(self):
        state = {}
        am.account([], state, business=False, fp="x")
        self.assertNotIn("seeded_families", state)

    def test_a_state_marker_that_is_not_a_list_baselines_again(self):
        state = {"seeded": True, "fp": "x", "seeded_families": "pi_review@1", "series": {}}
        metrics = [{"name": "pi_review_rounds_total", "type": "sum", "points": [({"project": "p"}, 4.0)]}]
        _, fams = am.account(metrics, state, True, "x")
        self.assertEqual(fams[0]["points"][0][1], 0)
        self.assertEqual(state["seeded_families"], ["pi_review@1"])


class Hold(ReviewBase):
    """B1 of review round 1: withdrawing an unhealthy item's report-derived values made a project's counter fall, account()
    re-took its baseline, and the item's recovery was counted as new activity. The ledger counts each event once, so the
    exported value is the same before, during and after the problem (the Disturbances class covers every other path)."""

    def sent(self, name):
        st = json.loads((self.state / "export_state.json").read_text())
        return {tuple(v for _, v in sorted(e["l"].items())): e["sent"][0] for e in st["series"].values() if e["n"] == name}

    def exported(self, c, name):
        return points(c.requests[-1], name)

    def test_the_reviewers_repro_totals_hold_across_stale_and_recovery(self):
        """The round 1 repro: two healthy items in one project, one gets a hand-appended line, spends two looks stale, and its
        report is rewritten. Treadmill counts new 6, repeat 3, follow-on 4; redesign-switch new 2, repeat 1, follow-on 1."""
        self.place("treadmill", "redesign-switch")
        c = self.collector()
        for _ in range(2):  # the baseline: existing history exports 0
            self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(self.exported(c, FAMILY["relations"]), {("golden", "new"): 0.0, ("golden", "repeat"): 0.0, ("golden", "follow-on"): 0.0})
        # a third healthy item arrives with a report: the totals rise by exactly its contribution (treadmill again: 6 / 3 / 4)
        self.place("treadmill", as_item="golden#t500")
        for _ in range(2):
            self.assertEqual(am.run_once(self.root, self.db), 0)
        base = {("golden", "new"): 6.0, ("golden", "repeat"): 3.0, ("golden", "follow-on"): 4.0}
        self.assertEqual(self.exported(c, FAMILY["relations"]), base)
        d = self.review / T
        with open(d / "findings.jsonl", "a") as fh:  # the hand-appended line of the repro
            fh.write(json.dumps({"event": "escape", "at": "2026-11-03T00:00:00Z", "item": T, "head": "x", "round": 3, "found_by": "dogfood", "text": "hand"}) + "\n")
        seen = []
        for _ in range(3):  # one look, two looks (confirmed stale), a third
            self.assertEqual(am.run_once(self.root, self.db), 0)
            seen.append(self.exported(c, FAMILY["relations"]))
        self.assertEqual(self.reader()["problems"], {"report_stale": 1})
        self.assertTrue(all(x == base for x in seen), seen)  # held: neither withdrawn nor changed
        rep = json.loads((d / "report.json").read_text())
        rep["log"]["lines"] += 1
        rep["log"]["events"]["escape"] += 1
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        for _ in range(3):
            self.assertEqual(am.run_once(self.root, self.db), 0)
            self.assertEqual(self.exported(c, FAMILY["relations"]), base)  # recovery adds the true delta, which is 0
        self.assertEqual(self.reader(), {"ok": True, "problems": {}})
        self.assertEqual(self.sent(FAMILY["relations"]), base)

    def test_dispositions_and_the_two_gauges_are_held_too(self):
        self.place("treadmill", "redesign-switch")
        c = self.collector()
        for _ in range(2):
            self.assertEqual(am.run_once(self.root, self.db), 0)
        gauge = lambda n: points(c.requests[-1], n)  # noqa: E731
        items, skipped = gauge("pi_review_items"), gauge("pi_review_skipped_redesigns")
        self.assertEqual(items, {("golden", "open"): 1.0, ("golden", "passed"): 1.0})
        self.assertEqual(skipped, {("golden",): 2.0})
        disp = self.exported(c, FAMILY["dispositions"])
        d = self.review / T
        for how in ("schema", "unknown_event", "bad_line", "stale", "missing"):
            shutil.copy(self.gold / "treadmill" / "report.json", d / "report.json")
            shutil.copy(self.gold / "treadmill" / "findings.jsonl", d / "findings.jsonl")
            for _ in range(2):
                self.assertEqual(am.run_once(self.root, self.db), 0)
            if how == "schema":
                rep = json.loads((d / "report.json").read_text())
                rep["report_schema"] = 2
                (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
            elif how == "unknown_event":
                with open(d / "findings.jsonl", "a") as fh:
                    fh.write('{"event": "teleport", "at": "2026-11-03T00:00:00Z"}\n')
            elif how == "bad_line":
                with open(d / "findings.jsonl", "a") as fh:
                    fh.write("garbage\n")
            elif how == "stale":
                with open(d / "findings.jsonl", "a") as fh:
                    fh.write(json.dumps({"event": "judge", "at": "2026-11-03T00:00:00Z", "round": 3, "session": "s", "verdict": "churning"}) + "\n")
            else:
                (d / "report.json").unlink()
            for look in (1, 2):
                self.assertEqual(am.run_once(self.root, self.db), 0)
                if look == 2 or how in ("schema", "unknown_event", "bad_line"):
                    self.assertFalse(self.reader()["ok"], how)  # stale and missing are confirmed on the second look
                self.assertEqual(self.exported(c, FAMILY["dispositions"]), disp, how)
                self.assertEqual(gauge("pi_review_items"), items, how)
                self.assertEqual(gauge("pi_review_skipped_redesigns"), skipped, how)
        self.assertEqual(self.sent(FAMILY["relations"]), {("golden", "new"): 0.0, ("golden", "repeat"): 0.0, ("golden", "follow-on"): 0.0})

    def test_an_unreadable_log_reads_as_nothing_on_disk_and_the_ledger_keeps_the_totals(self):
        self.place("treadmill")
        self.build()
        before = self.families()
        log = self.review / T / "findings.jsonl"
        os.chmod(log, 0)
        self.addCleanup(lambda: os.chmod(log, 0o644))
        if os.access(log, os.R_OK):
            self.skipTest("running as a user that can read a mode 0 file")
        (log.parent / "report.json").touch()  # something changed, so the folder is read again
        res = self.build()["review"]
        self.assertEqual(res["problems"], {"bad_line": 1})
        self.assertEqual(self.tables("SELECT COUNT(*) FROM review_rounds"), [(0,)])  # the tables show the disk
        self.assertEqual(self.families()[0], before[0])  # the totals are the ledger's
        os.chmod(log, 0o644)
        self.build()
        self.assertEqual(self.families()[0], before[0])  # and what comes back is not counted again


class Guarded(ReviewBase):
    """n1: nothing in the review folder may fail the Pi build."""

    def test_deep_nesting_in_the_log_or_the_report_is_a_bad_line_or_report_schema_and_the_pi_build_goes_on(self):
        self.place("treadmill", "clean-pass")
        with open(self.review / T / "findings.jsonl", "a") as fh:
            fh.write("[" * 100000 + "\n")
        (self.review / C / "report.json").write_text("[" * 100000)
        res = self.build()
        self.assertEqual(res["sessions"], 1)  # the Pi session was ingested
        self.assertEqual(res["review"]["problems"], {"report_schema": 1, "bad_line": 1})
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertIsNone(self.status()["last_build_error"])

    def test_anything_else_that_goes_wrong_reading_an_item_is_its_reader_error(self):
        self.place("treadmill", "clean-pass")
        real = rv.parse_report
        def boom(path, item):
            if item == T:
                raise RuntimeError(SENTINEL)
            return real(path, item)
        rv.parse_report = boom
        self.addCleanup(lambda: setattr(rv, "parse_report", real))
        res = self.build()
        self.assertEqual(res["sessions"], 1)
        self.assertEqual(res["review"], {"ok": False, "problems": {"reader_error": 1}})
        self.assertEqual(self.tables("SELECT item FROM review_items ORDER BY item"), [(C,), (T,)])
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertNotIn(SENTINEL, (self.state / "agent.log").read_text() + (self.state / "status.json").read_text())

    def test_a_folder_that_cannot_be_listed_is_a_reader_error_and_not_a_failed_build(self):
        self.place("clean-pass")
        self.build()
        real = rv._scan
        rv._scan = lambda root: (_ for _ in ()).throw(PermissionError(13, "denied", SENTINEL))
        self.addCleanup(lambda: setattr(rv, "_scan", real))
        res = self.build()
        self.assertEqual(res["review"], {"ok": False, "problems": {"reader_error": 1}})
        self.assertEqual(self.tables("SELECT COUNT(*) FROM review_items"), [(1,)])  # the tables are kept
        self.assertEqual(am.run_once(self.root, self.db), 0)

    def test_an_outer_failure_in_the_reader_is_a_reader_error_too(self):
        real = rv.update
        ae.review_reader.update = lambda con: (_ for _ in ()).throw(RuntimeError("x"))
        self.addCleanup(lambda: setattr(ae.review_reader, "update", real))
        res = self.build()
        self.assertEqual((res["sessions"], res["review"]), (1, {"ok": False, "problems": {"reader_error": 1}}))


class Unreferenced(ReviewBase):
    """n3: a reference to no finding and an entry that is not an item each get a counted reason; dot entries are ignored."""

    def test_a_label_or_disposition_that_names_no_finding_is_orphan_ref(self):
        for kind, line in (("label", {"event": "label", "id": "r9.zz", "relation": "new"}),
                           ("disposition", {"event": "disposition", "id": "r1.zz", "outcome": "fixed"})):
            shutil.rmtree(self.review, ignore_errors=True)
            self.place("treadmill")
            with open(self.review / T / "findings.jsonl", "a") as fh:
                fh.write(json.dumps({"at": "2026-11-03T00:00:00Z", **line}) + "\n")
            self.assertEqual(self.problems()["problems"].get("orphan_ref"), 1, kind)

    def test_a_stray_file_in_the_review_folder_is_a_stray_entry_and_is_noticed_when_nothing_else_changes(self):
        self.place("clean-pass")
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})
        (self.review / "notes.txt").write_text(SENTINEL)
        self.assertEqual(self.problems(), {"ok": False, "problems": {"stray_entry": 1}})
        (self.review / "more.md").write_text("x")
        self.assertEqual(self.problems(), {"ok": False, "problems": {"stray_entry": 2}})
        (self.review / "notes.txt").unlink()
        (self.review / "more.md").unlink()
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})

    def test_dot_entries_are_ignored(self):
        self.place("clean-pass")
        (self.review / ".DS_Store").write_text("x")
        (self.review / ".hidden").mkdir()
        write_log(self.review / ".scratch#1", [json.loads(x) for x in (self.gold / "clean-pass" / "findings.jsonl").read_text().splitlines()])
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})
        self.assertEqual(self.tables("SELECT item FROM review_items"), [(C,)])

    def test_the_stray_text_reaches_nothing(self):
        (self.review).mkdir(parents=True)
        (self.review / f"{SENTINEL}.txt").write_text(SENTINEL)
        self.assertEqual(self.problems()["problems"], {"stray_entry": 1})
        self.assertEqual(am.run_once(self.root, self.db), 0)
        for p in list(self.db.parent.iterdir()) + list(self.state.iterdir()):
            self.assertNotIn(SENTINEL.encode(), p.read_bytes(), p.name)


class Ids(ReviewBase):
    """n4: a log id is r<N>. followed by the return's own id, any non-blank string; the reader is not stricter."""

    def write(self, ids):
        ev = [{"event": "round", "at": "2026-11-03T00:00:00Z", "round": 1, "review_round": 1, "stage": "diff", "verdict": "fail"}]
        for i in ids:
            ev.append({"event": "finding", "at": "2026-11-03T00:00:00Z", "id": f"r1.{i}", "round": 1, "severity": "note", "effective": "note"})
        write_log(self.review / "golden#ids", ev)

    def test_ids_with_spaces_hashes_unicode_and_dots_are_accepted(self):
        ids = ["a b", "item #3", "é", "f1.2", "x" * 200, "-1", "has\nnewline"]
        self.write(ids)
        self.assertNotIn("bad_line", self.problems()["problems"])
        self.assertEqual(self.tables("SELECT COUNT(*) FROM review_findings"), [(len(ids),)])

    def test_a_blank_id_or_one_without_the_prefix_is_still_a_bad_line(self):
        for bad in ("r1.", "r1.   ", "f1", "x1.f1", "r.f1"):
            self.write([])
            with open(self.review / "golden#ids" / "findings.jsonl", "a") as fh:
                fh.write(json.dumps({"event": "finding", "at": "2026-11-03T00:00:00Z", "id": bad, "round": 1, "severity": "note", "effective": "note"}) + "\n")
            self.assertEqual(self.problems()["problems"].get("bad_line"), 1, bad)

    def test_the_id_must_name_its_round(self):
        self.write([])
        with open(self.review / "golden#ids" / "findings.jsonl", "a") as fh:
            fh.write(json.dumps({"event": "finding", "at": "2026-11-03T00:00:00Z", "id": "r2.f1", "round": 1, "severity": "note", "effective": "note"}) + "\n")
        self.assertEqual(self.problems()["problems"].get("bad_line"), 1)


class Disturbances(ReviewBase):
    """Every disturbance in the blind design, plus both reviewers' repro scripts (round 1 doublecount.sh, round 2 r2paths.py), driven
    through real ticks. After every tick: no pi_review_* counter fell (and none vanished). At the end: the totals are exactly the
    true activity, worked out from the log lines. The base is two items baselined at 0, then one item of real activity."""

    def setUp(self):
        super().setUp()
        self.place("treadmill", "design-then-diff")
        self.c = self.collector()
        self.prev, self.falls = {}, []
        self.tick(2)  # the baseline: the history on disk exports 0
        self.place("missing-component")
        self.tick(2)
        self.d = self.review / T
        self.log = self.d / "findings.jsonl"
        self.rep = self.d / "report.json"
        self.orig_log, self.orig_rep = self.log.read_bytes(), self.rep.read_bytes()
        self.want = self.worked_out("missing-component")
        self.check(self.want)

    # -- the property
    def tick(self, n=2):
        for _ in range(n):
            self.assertEqual(am.run_once(self.root, self.db), 0)
            self.record()

    def record(self):
        st = json.loads((self.state / "export_state.json").read_text())
        cur = {k: e["sent"][0] for k, e in st["series"].items() if e["n"].startswith("pi_review")}
        for k, v in self.prev.items():
            if cur.get(k) is None or cur[k] < v - 1e-9:
                self.falls.append((k, v, cur.get(k)))
        self.prev = cur

    def totals(self):
        st = json.loads((self.state / "export_state.json").read_text())
        out = {}
        for e in st["series"].values():
            if e["n"].startswith("pi_review") and e["t"] == "sum" and e["sent"][0]:
                lab = tuple(v for _, v in sorted(e["l"].items(), key=lambda kv: LABEL_ORDER[e["n"]].index(kv[0])))
                out.setdefault(e["n"], {})[lab] = round(e["sent"][0], 9)
        return out

    def worked_out(self, *names):
        """The true counters for these golden items, from their log lines alone."""
        want = expected_from_log({item_of(n): read_lines(n) for n in names}, set(APPROVED.split(":")))
        return {FAMILY[k]: {lab: round(v, 9) for lab, v in d.items() if v} for k, d in want.items() if d}

    def check(self, want, what=""):
        self.assertEqual(self.falls, [], what)
        self.assertEqual(self.totals(), want, what)

    def edit_first_line(self):
        lines = self.orig_log.split(b"\n")
        lines[0] = lines[0][:-3]
        self.log.write_bytes(b"\n".join(lines))

    # -- the disturbances
    def test_a_line_appended_by_hand_then_the_report_rewritten(self):  # round 1: doublecount.sh
        with open(self.log, "a") as fh:
            fh.write(json.dumps({"event": "escape", "at": "2026-11-03T00:00:00Z", "item": T, "head": "x", "round": 3, "found_by": "dogfood", "text": "hand"}) + "\n")
        self.tick(3)  # one look, two (confirmed stale), a third
        self.assertEqual(self.reader()["problems"], {"report_stale": 1})
        rep = json.loads(self.rep.read_text())
        rep["log"]["lines"] += 1
        rep["log"]["events"]["escape"] += 1
        self.rep.write_text(json.dumps(rep, indent=2) + "\n")
        self.tick(3)
        self.assertEqual(self.reader(), {"ok": True, "problems": {}})
        self.check({**self.want, FAMILY["escapes"]: {("golden",): 1.0}})  # the one true new event, counted once

    def test_a_round_line_broken_then_repaired(self):  # round 2: breakround
        self.edit_first_line()
        self.tick(3)
        self.assertIn("bad_line", self.reader()["problems"])
        self.log.write_bytes(self.orig_log)
        self.tick(3)
        self.assertEqual(self.reader(), {"ok": True, "problems": {}})
        self.check(self.want)

    def test_a_finding_line_broken_then_repaired(self):  # round 2: breakfinding
        lines = self.orig_log.split(b"\n")
        i = next(n for n, l in enumerate(lines) if b'"finding"' in l)
        lines[i] = lines[i][:-3]
        self.log.write_bytes(b"\n".join(lines))
        self.tick(3)
        self.log.write_bytes(self.orig_log)
        self.tick(3)
        self.check(self.want)

    def test_a_log_truncated_to_nothing_then_restored(self):  # round 2: truncate
        self.log.write_bytes(b"")
        self.tick(3)
        self.log.write_bytes(self.orig_log)
        self.tick(3)
        self.check(self.want)

    def test_a_log_cut_to_fifteen_lines_then_restored(self):  # round 2: truncate-partial
        self.log.write_bytes(b"\n".join(self.orig_log.split(b"\n")[:15]) + b"\n")
        self.tick(3)
        self.log.write_bytes(self.orig_log)
        self.tick(3)
        self.check(self.want)

    def test_a_log_that_loses_its_last_line_without_a_newline_then_returns(self):
        self.log.write_bytes(self.orig_log.rstrip(b"\n")[:-5])  # a crash mid-write
        self.tick(3)
        self.log.write_bytes(self.orig_log)
        self.tick(3)
        self.check(self.want)

    def test_a_report_malformed_missing_and_stale_then_recovered(self):
        self.rep.write_text("{not json")
        self.tick(3)
        self.assertEqual(self.reader()["problems"], {"report_schema": 1})
        self.rep.write_bytes(self.orig_rep)
        self.tick(2)
        self.rep.unlink()
        self.tick(3)
        self.assertEqual(self.reader()["problems"], {"report_missing": 1})
        self.rep.write_bytes(self.orig_rep)
        self.tick(2)
        rep = json.loads(self.orig_rep)
        rep["log"]["lines"] -= 1
        self.rep.write_text(json.dumps(rep, indent=2) + "\n")
        self.tick(3)
        self.assertEqual(self.reader()["problems"], {"report_stale": 1})
        self.rep.write_bytes(self.orig_rep)
        self.tick(3)
        self.assertEqual(self.reader(), {"ok": True, "problems": {}})
        self.check(self.want)

    def test_a_report_with_an_unknown_schema_then_recovered(self):
        for field in ("report_schema", "findings_schema"):
            rep = json.loads(self.orig_rep)
            rep[field] = 2
            self.rep.write_text(json.dumps(rep, indent=2) + "\n")
            self.tick(3)
            self.assertEqual(self.reader()["problems"], {field: 1})
            self.rep.write_bytes(self.orig_rep)
            self.tick(2)
        self.check(self.want)

    def test_a_folder_moved_away_and_back(self):  # round 2: rmdir
        def open_items():
            return sum(points(self.c.requests[-1], "pi_review_items").values())
        before = open_items()
        shutil.move(str(self.d), str(Path(self._tmp.name) / "parked"))
        self.tick(3)
        self.assertEqual(open_items(), before - 1)  # a gauge is right to drop
        shutil.move(str(Path(self._tmp.name) / "parked"), str(self.d))
        self.tick(3)
        self.assertEqual(open_items(), before)
        self.check(self.want)

    def test_the_database_deleted_and_rebuilt(self):
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(str(self.db) + suffix).unlink(missing_ok=True)
        self.tick(3)
        self.assertEqual(self.tables("SELECT COUNT(*) FROM review_items"), [(3,)])  # rebuilt from the files
        self.check(self.want)

    def test_a_database_set_aside_as_corrupt_and_rebuilt(self):
        self.db.write_bytes(b"this is not a database" * 100)
        self.tick(3)
        self.check(self.want)

    def test_an_unknown_event_kind_appears_and_goes(self):
        with open(self.log, "a") as fh:
            fh.write('{"event": "teleport", "at": "2026-11-03T00:00:00Z"}\n')
        self.tick(3)
        self.assertIn("unknown_event", self.reader()["problems"])
        self.log.write_bytes(self.orig_log)
        self.tick(3)
        self.check(self.want)

    def test_the_log_replaced_by_another_and_the_original_restored(self):  # round 2: replace
        sub = tag_log((GOLDEN / "clean-pass" / "findings.jsonl").read_text(), "substitute")
        self.log.write_text(sub)
        self.rep.write_text(json.dumps(json.loads((GOLDEN / "clean-pass" / "report.json").read_text()) | {"item": T}, indent=2) + "\n")
        self.tick(3)
        self.log.write_bytes(self.orig_log)
        self.rep.write_bytes(self.orig_rep)
        self.tick(3)
        # the substitute is a different review (other head): its round and its finding are real activity, counted once and kept
        extra = self.worked_out("clean-pass")
        want = {fam: {lab: round(self.want.get(fam, {}).get(lab, 0) + extra.get(fam, {}).get(lab, 0), 9)
                      for lab in set(self.want.get(fam, {})) | set(extra.get(fam, {}))} for fam in set(self.want) | set(extra)}
        want = {fam: d for fam, d in want.items() if d}
        want.pop(FAMILY["cost"], None) if FAMILY["cost"] not in extra else None
        self.check(want)

    def test_a_folder_renamed_from_a_placeholder_to_its_number(self):  # round 2: rename; the live coordinator#PR
        new = self.review / "golden#9001"
        shutil.move(str(self.d), str(new))
        rep = json.loads((new / "report.json").read_text())
        (new / "report.json").write_text(json.dumps(rep | {"item": "golden#9001"}, indent=2) + "\n")
        self.tick(3)
        shutil.move(str(new), str(self.d))
        (self.d / "report.json").write_bytes(self.orig_rep)
        self.tick(3)
        self.check(self.want)  # neither recounted nor dropped, one way or the other

    def test_a_reused_placeholder_name_counts_its_new_reviews(self):  # the comparer's case
        ph = self.review / "golden#PR"
        self.place("clean-pass", as_item="golden#PR")  # the first PR to use the name
        self.tick(3)
        first = self.worked_out("clean-pass")
        shutil.rmtree(ph)
        self.place("hand-written", as_item="golden#PR", tag="the-next-PR")  # the next PR reuses the name; its reviews have other heads
        self.tick(3)
        second = self.worked_out("hand-written")
        want = {}
        for part in (self.want, first, second):
            for fam, d in part.items():
                for lab, v in d.items():
                    want.setdefault(fam, {})[lab] = round(want.get(fam, {}).get(lab, 0) + v, 9)
        self.check(want)

    def test_the_same_item_under_two_names_counts_once(self):
        self.place("missing-component", as_item="golden#9002")  # the same log, copied to another folder name
        shutil.copy(self.gold / "missing-component" / "findings.jsonl", self.review / "golden#9002" / "findings.jsonl")
        self.tick(3)
        self.check(self.want)

    # -- the ledger itself
    def ledger(self):
        return json.loads((self.state / "export_state.json").read_text())["review"]

    def two_escapes(self, first=("2026-11-03T01:00:00Z", "first defect"), second=("2026-11-03T02:00:00Z", "second defect")):
        """Round 3 review: one PR finds two defects traced to the same passed round. Same head, round and found_by; the lines differ in
        their own `at` and `text`. The report is rewritten to match, as the tool would."""
        with open(self.log, "a") as fh:
            for at, text in (first, second):
                fh.write(json.dumps({"event": "escape", "at": at, "item": T, "head": "abc1234", "round": 3, "found_by": "dotfiles#160", "text": text}) + "\n")
        self.tick(3)
        rep = json.loads(self.rep.read_text())
        rep["log"]["lines"] += 2
        rep["log"]["events"]["escape"] += 2
        self.rep.write_text(json.dumps(rep, indent=2) + "\n")
        self.tick(3)
        self.assertEqual(self.reader(), {"ok": True, "problems": {}})

    def test_two_escapes_from_one_finder_against_one_round_count_as_two(self):  # round 3, B1
        self.two_escapes()
        self.check({**self.want, FAMILY["escapes"]: {("golden",): 2.0}})

    def test_two_escapes_in_the_same_second_are_told_apart_by_their_text(self):
        self.two_escapes(first=("2026-11-03T01:00:00Z", "first defect"), second=("2026-11-03T01:00:00Z", "second defect"))
        self.check({**self.want, FAMILY["escapes"]: {("golden",): 2.0}})

    def test_the_same_escape_line_written_twice_is_one_escape(self):
        self.two_escapes(first=("2026-11-03T01:00:00Z", "one defect"), second=("2026-11-03T01:00:00Z", "one defect"))
        self.check({**self.want, FAMILY["escapes"]: {("golden",): 1.0}})

    def test_red_control_the_old_escape_key_counts_two_escapes_as_one(self):
        real = rv._key
        rv._key = lambda kind, scope, *parts: real(kind, scope, *(parts[:3] if kind == "escape" else parts))  # repo, head, round, found_by
        self.addCleanup(lambda: setattr(rv, "_key", real))
        self.two_escapes()
        self.assertEqual(self.totals()[FAMILY["escapes"]], {("golden",): 1.0})  # the second defect is lost: the test above would fail

    def test_a_ledger_whose_label_key_is_not_json_does_not_stop_the_export(self):  # round 3, N1
        pi_before = self.pi_series()
        posts = len(self.c.requests)
        epoch = self.status()["epoch_ns"]
        for junk in ({"pi_review_rounds_total": {"notjson": 1}}, {"pi_review_rounds_total": {"[]": 1}}, {"pi_review_rounds_total": {"{\"a\": 1}": 1}},
                     {"pi_review_rounds_total": {"{\"a\": \"b\"": 1}}, {"pi_review_rounds_total": {"\u0000": 1}}, {"x": {"[" * 100000: 1}}):
            st = json.loads((self.state / "export_state.json").read_text())
            st["review"]["tot"] = junk
            (self.state / "export_state.json").write_text(json.dumps(st, separators=(",", ":")))
            self.tick(2)  # tick() asserts rc 0
            self.assertIsNone(self.status()["last_export_error"], junk)
            self.assertEqual(self.pi_series(), pi_before, junk)
            self.assertEqual(self.status()["epoch_ns"], epoch, junk)
        self.assertGreater(len(self.c.requests), posts)  # Pi export went on
        st = json.loads((self.state / "export_state.json").read_text())
        st["review"]["cost"] = {"cost:k": [1.0, "notjson"]}
        (self.state / "export_state.json").write_text(json.dumps(st, separators=(",", ":")))
        self.tick(2)
        self.assertIsNone(self.status()["last_export_error"])
        self.check(self.want)

    def test_a_missing_ledger_baselines_only_the_review_series(self):
        pi_before = self.pi_series()
        st = json.loads((self.state / "export_state.json").read_text())
        epoch = self.status()["epoch_ns"]
        del st["review"]
        (self.state / "export_state.json").write_text(json.dumps(st, separators=(",", ":")))
        self.tick(3)
        self.check(self.want)  # what was exported does not fall and is not counted again
        self.assertEqual(self.pi_series(), pi_before)
        self.assertEqual(self.status()["epoch_ns"], epoch)  # not a lost state
        self.assertTrue(self.ledger()["seen"])  # rebuilt from the files
        self.assertIn("pi_review@1", json.loads((self.state / "export_state.json").read_text())["seeded_families"])

    def test_a_bad_ledger_baselines_only_the_review_series(self):
        pi_before = self.pi_series()
        epoch = self.status()["epoch_ns"]
        for junk in ("text", [], {"v": 2}, {"v": 1, "seen": [], "tot": {}, "cost": {}, "g": {}}, {"v": 1, "seen": {}, "tot": {"x": {"y": -1}}, "cost": {}, "g": {}},
                     {"v": 1, "seen": {}, "tot": {}, "cost": {"k": [1]}, "g": {}}):
            st = json.loads((self.state / "export_state.json").read_text())
            st["review"] = junk
            (self.state / "export_state.json").write_text(json.dumps(st, separators=(",", ":")))
            self.tick(2)
            self.assertEqual(self.pi_series(), pi_before, junk)
            self.assertEqual(self.status()["epoch_ns"], epoch, junk)
        self.check(self.want)

    def test_new_activity_after_a_ledger_rebuild_is_counted_once(self):
        st = json.loads((self.state / "export_state.json").read_text())
        del st["review"]
        (self.state / "export_state.json").write_text(json.dumps(st, separators=(",", ":")))
        self.tick(2)
        self.place("hand-written")
        self.tick(3)
        self.check(self.merge(self.want, self.worked_out("hand-written")))

    def test_the_ledger_holds_hashes_and_numbers_only(self):
        led = self.ledger()
        text = json.dumps(led)
        for forbidden in ("1111111", "session-", "reviewer-", "undo", T, "golden#"):
            self.assertNotIn(forbidden, text)
        self.assertTrue(all(len(k.split(":", 1)[1]) == 20 for k in led["seen"]))

    def test_the_preview_changes_no_state(self):
        before = (self.state / "export_state.json").read_bytes()
        env = dict(os.environ, AGENT_EVENTS_STATE_DIR=str(self.state))
        out = subprocess.run([sys.executable, str(base.CLI), "--db", str(self.db), "export"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual((self.state / "export_state.json").read_bytes(), before)

    def test_the_order_of_items_does_not_matter(self):
        self.place("hand-written")
        self.tick(2)
        shutil.rmtree(self.review / item_of("hand-written"))
        self.tick(2)
        self.place("hand-written")
        self.tick(2)
        self.check(self.merge(self.want, self.worked_out("hand-written")))

    # -- helpers for the ledger tests
    def pi_series(self):
        st = json.loads((self.state / "export_state.json").read_text())
        return {k: v for k, v in st["series"].items() if not v["n"].startswith("pi_review")}

    @staticmethod
    def merge(*wants):
        out = {}
        for part in wants:
            for fam, d in part.items():
                for lab, v in d.items():
                    out.setdefault(fam, {})[lab] = round(out.get(fam, {}).get(lab, 0) + v, 9)
        return out

    def test_red_control_totals_recomputed_from_the_files_on_disk_are_caught(self):
        """The mechanism the ledger replaced: totals are whatever is on disk now. The same property must catch it."""
        real = rv.ledger_for
        def from_disk(state):  # a fresh ledger every tick: totals are recomputed from the files, the marker is kept
            led = state["review"] = rv.new_ledger()
            return led
        rv.ledger_for = from_disk
        self.addCleanup(lambda: setattr(rv, "ledger_for", real))
        self.edit_first_line()
        self.tick(3)
        self.log.write_bytes(self.orig_log)
        self.tick(3)
        self.assertTrue(self.falls or self.totals() != self.want, "the property did not notice totals recomputed from disk")
        self.assertNotEqual(self.totals(), self.want)  # the comeback was counted again


class Keys(ReviewBase):
    """Two distinct real events must not share a ledger key (they would count as one); the same line must always give the same key."""

    def log_of(self, item, events):
        write_log(self.review / item, events)

    def count(self, name):
        self.build()
        return series_of(self.families()[0], name)

    ROUND = {"event": "round", "at": "2026-11-03T00:00:00Z", "round": 1, "review_round": 1, "stage": "diff", "head": "abc", "verdict": "fail"}
    FINDING = {"event": "finding", "at": "2026-11-03T00:00:01Z", "id": "r1.f1", "round": 1, "severity": "note", "effective": "note"}

    def test_two_redesigns_of_one_component_in_one_round_are_two_events(self):
        base = {"event": "redesign", "at": "2026-11-03T00:00:02Z", "component": "gate", "round": 1, "blind_session": "b", "comparer_session": "c"}
        self.log_of("golden#k1", [self.ROUND, {**base, "makes_impossible": "no", "action": "rang-michael"},
                                  {**base, "at": "2026-11-03T00:05:00Z", "makes_impossible": "yes", "action": "switched"}])
        self.assertEqual(self.count(FAMILY["redesigns"]), {("golden", "rang-michael", "no"): 1, ("golden", "switched", "yes"): 1})
        # even in one second, with the same component and round, a different decision is a different event
        self.log_of("golden#k2", [self.ROUND, {**base, "makes_impossible": "no", "action": "kept-fixing"}, {**base, "makes_impossible": "yes", "action": "switched"}])
        self.assertEqual(sum(self.count(FAMILY["redesigns"]).values()), 4)

    def test_two_items_of_one_repo_at_the_same_head_and_round_number_both_count(self):
        late = {**self.ROUND, "at": "2026-11-03T05:00:00Z"}
        self.log_of("golden#k1", [self.ROUND, self.FINDING])
        self.log_of("golden#k2", [late, {**self.FINDING, "at": "2026-11-03T05:00:01Z"}])  # another PR reviewed at the same commit, round 1, finding f1
        self.assertEqual(sum(self.count(FAMILY["rounds"]).values()), 2)
        self.assertEqual(sum(self.count(FAMILY["findings"]).values()), 2)

    def test_the_same_lines_always_give_the_same_keys(self):
        self.log_of("golden#k1", [self.ROUND, self.FINDING])
        first = self.count(FAMILY["rounds"])
        shutil.move(str(self.review / "golden#k1"), str(self.review / "golden#k9"))  # a rename
        self.build()
        self.assertEqual(self.count(FAMILY["rounds"]), first)
        self.assertEqual(sum(self.count(FAMILY["findings"]).values()), 1)

    def test_red_control_the_old_keys_merge_distinct_events(self):
        real = rv._key
        old = {"round": 2, "finding": 2, "redesign": 3, "escape": 3}  # how many parts each key had before `at`, `text` and `action` joined them
        rv._key = lambda kind, scope, *parts: real(kind, scope, *parts[:old.get(kind, len(parts))])
        self.addCleanup(lambda: setattr(rv, "_key", real))
        late = {**self.ROUND, "at": "2026-11-03T05:00:00Z"}
        self.log_of("golden#k1", [self.ROUND, self.FINDING])
        self.log_of("golden#k2", [late, {**self.FINDING, "at": "2026-11-03T05:00:01Z"}])
        self.assertEqual(sum(self.count(FAMILY["rounds"]).values()), 1)  # the second review at the same head is lost: the test above would fail


class Cli(ReviewBase):
    def test_build_export_and_status_show_the_reader(self):
        self.place("treadmill")
        os.environ.pop("AGENT_EVENTS_OTLP_ENDPOINT", None)
        env = dict(os.environ, AGENT_EVENTS_STATE_DIR=str(self.state), PI_CODING_AGENT_DIR=str(self.root.parent), XDG_DATA_HOME=str(Path(self._tmp.name) / "xdg"))
        cli = [sys.executable, str(base.CLI)]
        out = subprocess.run(cli + ["build"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("review log: ok", out.stdout)
        out = subprocess.run(cli + ["run"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        st = subprocess.run(cli + ["status"], capture_output=True, text=True, env=env)
        self.assertIn("review reader         : ok", st.stdout)
        ex = subprocess.run(cli + ["export"], capture_output=True, text=True, env=env)
        for name in ["pi_review_rounds_total", "pi_review_findings_total", "pi_review_cost_usd_total", "pi_review_relations_total",
                     "pi_review_dispositions_total", "pi_review_skipped_redesigns", "pi_review_items", "pi_review_reader_problem_items"]:
            self.assertIn(name, ex.stdout)  # a counter family with nothing counted yet (demoted, redesigns, escapes) is not listed
        self.assertFalse(Path(self.state / "export_state.json").exists() and "review" in json.loads((self.state / "export_state.json").read_text()),
                         "the preview must not write the ledger")


if __name__ == "__main__":
    unittest.main()
