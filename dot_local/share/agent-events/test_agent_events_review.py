"""Tests for the review reader (agent_events_review). Review logs here are scripted: the golden pairs, plus logs written by the tests."""
import copy
import hashlib
import json
import os
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

GOLDEN = HERE / "fixtures" / "review-golden"
MANIFEST_SHA256 = "e1a464299898aa6871d8103a1d8f38c0367f7d21a4b7c3267c3bdaf144cdc980"  # change the golden pairs and this pin together
SENTINEL = base.SENTINEL
APPROVED = "proj:coordinator:cartwmic-homelab-v2:agent-kit:loop-engine"
NAMES = ("treadmill", "clean-pass", "design-then-diff", "redesign-switch", "missing-component", "hand-written")


def read_lines(name):
    return [json.loads(x) for x in (GOLDEN / name / "findings.jsonl").read_text().splitlines()]


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
        prior = {k: os.environ.get(k) for k in ("AGENT_TRACES_DIR", "AGENT_EVENTS_PROJECTS")}
        os.environ["AGENT_TRACES_DIR"] = str(self.traces)
        os.environ["AGENT_EVENTS_PROJECTS"] = APPROVED
        ae._GIT_ROOTS = set()  # the approved projects are exactly the scripted ones
        self.addCleanup(lambda: setattr(ae, "_GIT_ROOTS", None))
        self.addCleanup(lambda: [os.environ.__setitem__(k, v) if v is not None else os.environ.pop(k, None) for k, v in prior.items()])

    def place(self, *names):
        for n in names:
            shutil.copytree(GOLDEN / n, self.review / item_of(n), dirs_exist_ok=True)

    def tables(self, sql, *params):
        return [tuple(r) for r in self.q(sql, *params)]

    def families(self):
        con = ae.connect(self.db, readonly=True)
        try:
            return am.collect(con), am.review_reader.gauges(con, ae.approved_projects())
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
            lines = (GOLDEN / n / "findings.jsonl").read_text().splitlines()
            self.assertEqual(rep["log"]["lines"], len(lines), n)
            self.assertEqual(sum(rep["log"]["events"].values()), len(lines), n)
            self.assertEqual(len(rep["findings"]), rep["log"]["events"]["finding"], n)


class Series(ReviewBase):
    def test_every_golden_pair_gives_the_series_worked_out_from_the_log(self):
        self.place(*NAMES)
        res = self.problems()
        self.assertEqual(res, {"ok": True, "problems": {}})
        fams, _ = self.families()
        items = {item_of(n): read_lines(n) for n in NAMES}
        want = expected_from_log(items, set(APPROVED.split(":")))
        for key, name in FAMILY.items():
            got = series_of(fams, name)
            self.assertEqual(set(got), set(want[key]), name)
            for k, v in want[key].items():
                self.assertAlmostEqual(got[k], v, places=9, msg=(name, k))
        self.assertIn(("coordinator", "fail", "diff", "claude-opus-5-5"), series_of(fams, FAMILY["rounds"]))
        self.assertEqual(series_of(fams, FAMILY["rounds"])[("loop-engine", "pass", "diff", "unknown")], 1)  # no model: unknown
        self.assertEqual(series_of(fams, FAMILY["relations"])[("coordinator", "repeat")], 2)  # coordinator#217 and coordinator#216
        self.assertEqual(series_of(fams, FAMILY["demoted"]), {("coordinator",): 1})
        self.assertEqual(series_of(fams, FAMILY["escapes"]), {("other",): 1})  # d40:... has no '#'
        self.assertEqual(series_of(fams, FAMILY["findings"])[("coordinator", "3", "blocking", "diff")], 1)

    def test_gauges_come_from_the_reports(self):
        self.place(*NAMES)
        self.build()
        _, gauges = self.families()
        by = {m["name"]: series_of(gauges, m["name"]) for m in gauges}
        self.assertEqual(by["pi_review_skipped_redesigns"][("coordinator",)], 1)  # treadmill: coordinator#217; coordinator#216 is 0
        self.assertEqual(by["pi_review_items"], {("coordinator", "open"): 1, ("coordinator", "passed"): 1, ("loop-engine", "passed"): 1,
                                                 ("cartwmic-homelab-v2", "open"): 1, ("agent-kit", "open"): 1, ("other", "open"): 1})
        self.assertEqual(by["pi_review_reader_problem_items"], {(r,): 0.0 for r in rv.REASONS})

    def test_tables_hold_ids_numbers_and_enumerated_values_only(self):
        self.place("treadmill")
        self.build()
        self.assertEqual(self.tables("SELECT round, review_round, stage, verdict, model, duration_ms, cost_usd FROM review_rounds ORDER BY round"),
                         [(1, 1, "diff", "fail", "claude-opus-5-5", 91000, 0.42), (2, 2, "diff", "fail", "claude-opus-5-5", 80000, 0.38),
                          (3, 3, "diff", "fail", "claude-opus-5-5", 77000, 0.35)])
        self.assertEqual(self.tables("SELECT id, round, severity, effective, demoted, sequence, relation, outcome, has_component FROM review_findings ORDER BY id"),
                         [("r1.f1", 1, "blocking", "blocking", 0, 1, "new", "fixed", 1), ("r1.f2", 1, "blocking", "blocking", 0, 1, "new", "fixed", 1),
                          ("r2.f1", 2, "blocking", "blocking", 0, 1, "repeat", "fixed", 1), ("r2.f2", 2, "blocking", "note", 1, 1, None, None, 1),
                          ("r3.f1", 3, "blocking", "blocking", 0, 1, "follow-on", None, 1), ("r3.n1", 3, "note", "note", 0, 1, None, None, 0)])
        self.assertEqual(self.tables("SELECT item, repo, state, skipped_redesigns, needs_component, undisposed_blocking, problems FROM review_items"),
                         [("coordinator#217", "coordinator", "open", 1, 0, 1, "")])

    def test_project_label_rules(self):
        self.place("design-then-diff", "hand-written")
        write_log(self.review / "unknownrepo#5", read_lines("clean-pass"), json.loads((GOLDEN / "clean-pass" / "report.json").read_text()) | {"item": "unknownrepo#5"})
        self.build()
        fams, _ = self.families()
        projects = {k[0] for k in series_of(fams, FAMILY["rounds"])}
        self.assertEqual(projects, {"cartwmic-homelab-v2", "other"})  # the hyphenated approved repo is a project; the rest are other

    def test_a_missing_directory_is_no_rows_and_no_problem(self):
        self.assertEqual(self.problems(), {"ok": True, "problems": {}})
        self.assertEqual(self.tables("SELECT COUNT(*) FROM review_items"), [(0,)])
        fams, gauges = self.families()
        self.assertTrue(all(not m["points"] for m in fams if m["name"].startswith("pi_review_")))
        self.assertEqual({m["name"] for m in gauges}, {"pi_review_skipped_redesigns", "pi_review_items", "pi_review_reader_problem_items"})

    def test_an_old_database_without_the_review_tables_exports_without_them(self):
        con = sqlite3.connect(":memory:")
        self.assertEqual(rv.counters(con, set()), [])
        self.assertEqual(rv.gauges(con, set()), [])


class Strict(ReviewBase):
    """Each problem shows in the build result, in status.json (through a tick) and in the gauge; nothing is skipped silently."""

    def setup_item(self, name="treadmill"):
        self.place(name)
        return self.review / item_of(name)

    def assert_reported(self, reason):
        """The first build reports the reason alone; the tick (a second look) may add report_stale, because a log with a
        problem line never matches a report written before it. status.json and the gauge carry the reason either way."""
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
        rep = json.loads((GOLDEN / "treadmill" / "report.json").read_text())
        rep["item"] = "someone-else#1"
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assertEqual(self.problems()["problems"], {"report_schema": 1})  # a report for another item
        rep["item"] = "coordinator#217"
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
        self.assertEqual(self.tables("SELECT log_lines FROM review_items"), [(6,)])

    def test_report_missing(self):
        d = self.setup_item()
        (d / "report.json").unlink()
        self.assert_reported("report_missing")
        fams, gauges = self.families()
        self.assertEqual(sum(series_of(fams, FAMILY["rounds"]).values()), 3)  # the raw counts stay
        self.assertEqual(series_of(fams, FAMILY["relations"]), {})  # the report-derived ones go
        self.assertEqual(series_of(gauges, "pi_review_items"), {})

    def test_an_item_with_no_round_yet_needs_no_report(self):
        write_log(self.review / "coordinator#300", [])
        (self.review / "coordinator#301").mkdir(parents=True)
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
        self.d = self.review / "coordinator#217"
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
        self.assertEqual(self.tables("SELECT stale_looks FROM review_items"), [(0,)])

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
                  "kind not summarised": lambda r: r["summarises"]["events"].remove("judge"),
                  "finding ids": lambda r: r["findings"][0].update(id="r1.zz")}
        for what, fn in mutate.items():
            rep = json.loads((GOLDEN / "treadmill" / "report.json").read_text())
            fn(rep)
            (self.d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
            self.problems()
            self.assertEqual(self.problems()["problems"], {"report_stale": 1}, what)

    def test_unhealthy_items_lose_only_their_report_derived_series(self):
        self.place("clean-pass")
        self.hand_append(self.d)
        self.problems()
        self.problems()
        fams, gauges = self.families()
        self.assertEqual(series_of(fams, FAMILY["relations"]), {("loop-engine", "new"): 1})  # clean-pass only
        self.assertEqual(sum(series_of(fams, FAMILY["rounds"]).values()), 5)  # raw counts: 3 + 2
        self.assertEqual(series_of(gauges, "pi_review_items"), {("loop-engine", "passed"): 1})


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
        item = "coordinator#400"
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
        self.assertEqual(rounds, {("coordinator", "fail", "diff", "claude-opus-5-5"): 0.0, ("loop-engine", "fail", "diff", "claude-opus-5-5"): 0.0,
                                  ("loop-engine", "pass", "diff", "unknown"): 0.0})
        for fam in FAMILY.values():
            self.assertTrue(all(v == 0 for v in points(first, fam).values()), fam)
        self.assertIn("pi_review", self.state_file()["seeded_families"])
        # a restart does not re-baseline: the same history is still 0
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertTrue(all(v == 0 for v in points(c.requests[-1], FAMILY["rounds"]).values()))
        # the next round adds exactly one
        d = self.review / "coordinator#217"
        extra = {"event": "round", "at": "2026-11-03T00:00:00Z", "round": 4, "review_round": 4, "stage": "diff", "verdict": "pass", "model": "claude-opus-5-5", "cost_usd": 0.1}
        with open(d / "findings.jsonl", "a") as fh:
            fh.write(json.dumps(extra) + "\n")
        rep = json.loads((d / "report.json").read_text())
        rep["log"]["lines"] += 1
        rep["log"]["events"]["round"] += 1
        rep["state"] = "passed"
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(am.run_once(self.root, self.db), 0)
        key = ("coordinator", "pass", "diff", "claude-opus-5-5")  # a new combination: sent as 0 first, then its growth
        got = points(c.requests[-1], FAMILY["rounds"])
        self.assertEqual(got[key], 1.0)
        self.assertEqual(got[("coordinator", "fail", "diff", "claude-opus-5-5")], 0.0)
        # a series that already existed goes up by exactly one
        with open(d / "findings.jsonl", "a") as fh:
            fh.write(json.dumps(dict(extra, round=5, review_round=5, verdict="fail")) + "\n")
        rep["log"]["lines"] += 1
        rep["log"]["events"]["round"] += 1
        (d / "report.json").write_text(json.dumps(rep, indent=2) + "\n")
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(points(c.requests[-1], FAMILY["rounds"])[("coordinator", "fail", "diff", "claude-opus-5-5")], 1.0)
        self.assertAlmostEqual(points(c.requests[-1], FAMILY["cost"])[("coordinator", "diff", "claude-opus-5-5")], 0.2)  # two rounds of 0.1

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
        self.assertEqual(after["seeded_families"], ["pi_review"])
        for fam in ("pi_sessions", "pi_llm_calls", "pi_tokens"):
            self.assertEqual(points(c.requests[-1], fam), points(c.requests[0], fam), fam)

    def test_a_by_hand_log_backfilled_after_the_marker_counts_as_activity_once(self):
        c = self.collector()
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.place("clean-pass")
        self.assertEqual(am.run_once(self.root, self.db), 0)  # the new series are created at 0
        self.assertEqual(am.run_once(self.root, self.db), 0)
        self.assertEqual(sum(points(c.requests[-1], FAMILY["rounds"]).values()), 2.0)

    def test_a_tick_without_a_good_build_does_not_set_the_marker(self):
        state = {}
        am.account([], state, business=False, fp="x")
        self.assertNotIn("seeded_families", state)

    def test_a_state_marker_that_is_not_a_list_baselines_again(self):
        state = {"seeded": True, "fp": "x", "seeded_families": "pi_review", "series": {}}
        metrics = [{"name": "pi_review_rounds_total", "type": "sum", "points": [({"project": "p"}, 4.0)]}]
        _, fams = am.account(metrics, state, True, "x")
        self.assertEqual(fams[0]["points"][0][1], 0)
        self.assertEqual(state["seeded_families"], ["pi_review"])


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
        for name in list(FAMILY.values()) + ["pi_review_skipped_redesigns", "pi_review_items", "pi_review_reader_problem_items"]:
            self.assertIn(name, ex.stdout)


if __name__ == "__main__":
    unittest.main()
