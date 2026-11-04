"""agent-events review reader: the review log's ids, counts and enumerated values, read strictly.

Reads ${AGENT_TRACES_DIR:-~/.local/share/agent-traces}/emitted/review/<item>/findings.jsonl and the report.json beside it
(defined in findings-contract.md, "The report"). It computes no stuck trigger: whatever is derived (relations, dispositions,
skipped redesigns, state) comes from report.json. Stored in the database: item, log round, review round, stage, model name,
enumerated values, a demoted flag, cost, duration and the report's counts. Never stored: any free-text field (text, obligation,
evidence, consequence, component, head, reviewer, session, found_by ...), a session id or a component name.

Strict: every problem is counted per item under one reason and shown in status.json and in the gauge
pi_review_reader_problem_items. Nothing is skipped without a reason (entries whose name starts with "." are ignored).

Counters never fall because an item had a problem. While an item's report is not fresh (a confirmed problem, or a stale
look), the item keeps the report-derived values it last had from a fresh report (held, not withdrawn); only the true
difference is added when it recovers. An unreadable log likewise keeps its previous rows.
"""
import datetime as dt
import hashlib
import json
import math
import os
import re
from pathlib import Path

EVENTS = ("round", "finding", "label", "disposition", "redesign", "judge", "escape")
STAGES = ("mechanism", "intent", "plan", "design", "diff", "other")
VERDICTS = ("pass", "fail")
SEVERITIES = ("blocking", "note")
RELATIONS = ("new", "repeat", "follow-on")
OUTCOMES = ("fixed", "rejected", "residual")
ACTIONS = ("switched", "rang-michael", "kept-fixing")
IMPOSSIBLE = ("yes", "no")
JUDGE_VERDICTS = ("churning", "not-churning")
STATES = ("passed", "open")
# A reason is a fixed word. report_stale, report_missing and a partial last line are confirmed only after CONFIRM_LOOKS
# consecutive builds that looked at the folder (a skipped build counts): a tick that lands between a write and its report
# (or a tool's first round and its first report) is expected.
REASONS = ("findings_schema", "report_schema", "unknown_event", "bad_line", "report_missing", "report_stale",
           "orphan_ref", "stray_entry", "reader_error")
LOOKED = ("report_missing", "report_stale", "bad_line")  # confirmed on the second consecutive look (bad_line: an unfinished last line)
CONFIRM_LOOKS = 2

LOG_ID_RE = re.compile(r"r([0-9]+)\.(.*)", re.DOTALL)  # r<N>.<the return's own id>: any non-blank string, as the contract says
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}(?:[/:][A-Za-z0-9][A-Za-z0-9._-]{0,63})?")
REPO_RE = re.compile(r"[a-z][a-z0-9-]{0,40}")


def traces_root():
    base = os.environ.get("AGENT_TRACES_DIR") or str(Path.home() / ".local/share/agent-traces")
    return Path(base) / "emitted" / "review"


def _int(v, low=0):
    return type(v) is int and v >= low


def _num(v):
    return type(v) in (int, float) and math.isfinite(v) and v >= 0


def _log_round(v):
    """The log round in a log id r<N>.<id>, or None when v is not one."""
    m = LOG_ID_RE.fullmatch(v) if isinstance(v, str) else None
    return int(m.group(1)) if m and m.group(2).strip() else None


def _at_ms(v):
    try:
        d = dt.datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None
    return int(d.timestamp() * 1000) if d.tzinfo is not None else None


class Log:
    def __init__(self):
        self.lines = 0
        self.kinds = {k: 0 for k in EVENTS}
        self.unknown = self.bad = self.partial = self.unreadable = self.orphan = False
        self.rounds, self.findings, self.redesigns, self.escapes, self.refs = {}, {}, [], [], []


def _event(o):
    """The validated record for one parsed line, or None when it is malformed. Only fields the reader stores are checked."""
    k = o["event"]
    if _at_ms(o.get("at")) is None:
        return None
    ok = True
    if k == "round":
        model, dur, cost = o.get("model"), o.get("duration_ms"), o.get("cost_usd")
        ok = (_int(o.get("round"), 1) and _int(o.get("review_round"), 1) and o.get("stage") in STAGES
              and o.get("verdict") in VERDICTS and (model is None or isinstance(model, str))
              and (dur is None or _int(dur)) and (cost is None or _num(cost)))
        return {"round": o["round"], "review_round": o["review_round"], "stage": o["stage"], "verdict": o["verdict"],
                "model": None if model is None else (model if MODEL_RE.fullmatch(model) else "other"),
                "duration_ms": dur, "cost_usd": None if cost is None else float(cost), "at_ms": _at_ms(o["at"])} if ok else None
    if k == "finding":
        ok = (_int(o.get("round"), 1) and _log_round(o.get("id")) == o["round"] and o.get("severity") in SEVERITIES
              and o.get("effective") in SEVERITIES and not (o["severity"] == "note" and o["effective"] == "blocking"))
        return {"id": o["id"], "round": o["round"], "severity": o["severity"], "effective": o["effective"],
                "demoted": int(o["severity"] == "blocking" and o["effective"] == "note")} if ok else None
    if k == "label":
        ok = _log_round(o.get("id")) is not None and o.get("relation") in RELATIONS
    elif k == "disposition":
        ok = _log_round(o.get("id")) is not None and o.get("outcome") in OUTCOMES
    elif k == "redesign":
        ok = _int(o.get("round"), 1) and o.get("makes_impossible") in IMPOSSIBLE and o.get("action") in ACTIONS
        return {"round": o["round"], "action": o["action"], "makes_impossible": o["makes_impossible"]} if ok else None
    elif k == "judge":
        ok = _int(o.get("round"), 1) and o.get("verdict") in JUDGE_VERDICTS
    elif k == "escape":
        ok = _int(o.get("round"), 1)
        return {"round": o["round"], "at_ms": _at_ms(o["at"])} if ok else None
    return {} if ok else None


def _parse(raw):
    try:
        o = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):  # deep nesting is a bad line, never a failed build
        return None
    return o if isinstance(o, dict) and isinstance(o.get("event"), str) else None


def parse_log(path):
    log = Log()
    try:
        data = path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return log
    except OSError:  # unreadable: shown as a bad line, never a failed Pi build; the item keeps its previous rows
        log.bad = log.unreadable = True
        return log
    chunks = data.split(b"\n")
    tail = chunks.pop()  # b"" when the file ends with a newline
    lines = [c for c in chunks if c.strip()]
    if tail.strip():
        if _parse(tail) is None:  # a final line with no newline yet: ignored this tick, confirmed bad if it stays
            log.partial = True
        else:
            lines.append(tail)
    log.lines = len(lines)
    for raw in lines:
        o = _parse(raw)
        if o is None:
            log.bad = True
            continue
        kind = o["event"]
        if kind not in EVENTS:
            log.unknown = True
            continue
        rec = _event(o)
        if rec is None:
            log.bad = True
            continue
        log.kinds[kind] += 1
        if kind in ("label", "disposition"):
            log.refs.append(o["id"])
        if kind == "round":
            if rec["round"] in log.rounds:
                log.bad = True
                log.kinds[kind] -= 1
            else:
                log.rounds[rec["round"]] = rec
        elif kind == "finding":
            if rec["id"] in log.findings:
                log.bad = True
                log.kinds[kind] -= 1
            else:
                log.findings[rec["id"]] = rec
        elif kind == "redesign":
            log.redesigns.append(rec)
        elif kind == "escape":
            log.escapes.append(rec)
    for f in list(log.findings.values()):
        if f["round"] not in log.rounds:  # a finding whose round line is missing cannot be joined to a stage
            log.bad = True
            del log.findings[f["id"]]
    log.orphan = any(r not in log.findings for r in log.refs)  # a label or disposition that names no finding
    return log


def _valid_report(d, item):
    try:
        lg, sm, cn = d["log"], d["summarises"], d["counts"]
        return (d["item"] == item and _int(lg["lines"]) and isinstance(lg["events"], dict)
                and all(isinstance(k, str) and _int(v) for k, v in lg["events"].items())
                and isinstance(sm["events"], list) and all(isinstance(e, str) for e in sm["events"])
                and isinstance(d["findings"], list) and d["state"] in STATES
                and all(_int(cn[k]) for k in ("needs_component", "undisposed_blocking", "skipped_redesigns"))
                and all(isinstance(f, dict) and isinstance(f.get("id"), str) and _int(f.get("sequence"), 1)
                        and f.get("effective") in SEVERITIES and f.get("relation") in (None, *RELATIONS)
                        and f.get("outcome") in (None, *OUTCOMES) and type(f.get("has_component")) is bool
                        for f in d["findings"]))
    except (KeyError, TypeError):
        return False


def parse_report(path, item):
    """(report, None) or (None, reason) with reason in findings_schema, report_schema or missing."""
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None, "missing"
    except OSError:
        return None, "report_schema"
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, "report_schema"
    if not isinstance(d, dict) or type(d.get("report_schema")) is not int or d["report_schema"] != 1:
        return None, "report_schema"
    if type(d.get("findings_schema")) is not int or d["findings_schema"] != 1:
        return None, "findings_schema"
    return (d, None) if _valid_report(d, item) else (None, "report_schema")


def _stale(log, rep):
    """The report does not describe the log the reader counted (the report may be older, or the log was edited by hand)."""
    if rep["log"]["lines"] != log.lines or sum(rep["log"]["events"].values()) != log.lines:
        return True
    if any(n and k not in rep["summarises"]["events"] for k, n in log.kinds.items()):
        return True
    return {f["id"] for f in rep["findings"]} != set(log.findings)


def _repo(item):
    repo = item.split("#", 1)[0].lower() if "#" in item else None
    return repo if repo and REPO_RE.fullmatch(repo) else None


def _scan(root):
    """(item folders, stray entries). Entries whose name starts with '.' are ignored."""
    items, strays = [], []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if not p.name.startswith("."):
                (items if p.is_dir() else strays).append(p)
    return items, strays


def _signature(items, strays):
    sig = []
    for d in items:
        row = [d.name]
        for name in ("findings.jsonl", "report.json"):
            try:
                st = (d / name).stat()
                row += [st.st_size, st.st_mtime_ns]
            except OSError:
                row += [None, None]
        sig.append(row)
    return hashlib.sha256(json.dumps([sig, [p.name for p in strays]]).encode()).hexdigest()  # a stray name is free text: only its hash is kept


def _confirmed(hard, looks):
    out = set(hard) | {r for r, n in looks.items() if n >= CONFIRM_LOOKS}
    return [r for r in REASONS if r in out]


def _summary(con, extra=None):
    counts = dict(extra or {})
    for (problems,) in con.execute("SELECT problems FROM review_items WHERE problems != ''"):
        for r in problems.split(","):
            counts[r] = counts.get(r, 0) + 1
    row = con.execute("SELECT value FROM meta WHERE key='review_stray'").fetchone()
    if row and int(row[0]):
        counts["stray_entry"] = int(row[0])
    con.execute("DELETE FROM review_problems")
    con.executemany("INSERT INTO review_problems VALUES (?, ?)", sorted(counts.items()))
    return {"ok": not counts, "problems": {r: counts[r] for r in REASONS if r in counts}}


def _log_tables(con, item):
    for table in ("review_rounds", "review_findings", "review_redesigns", "review_escapes"):
        con.execute(f"DELETE FROM {table} WHERE item = ?", (item,))


def _read_item(con, d, old):
    """Replace one item's rows. old: its previous review_items row (a dict) or None. Report-derived values come from a fresh
    report only; otherwise the item keeps the ones it had."""
    item = d.name
    log = parse_log(d / "findings.jsonl")
    if log.unreadable and old:  # keep every previous row; only the reason changes
        hard = [r for r in REASONS if r in (set(filter(None, old["hard"].split(","))) | {"bad_line"})]
        con.execute("UPDATE review_items SET hard=?, problems=? WHERE item=?",
                    (",".join(hard), ",".join(_confirmed(hard, json.loads(old["looks"]))), item))
        return
    rep, why = parse_report(d / "report.json", item)
    hard = set()
    if log.unknown:
        hard.add("unknown_event")
    if log.bad:
        hard.add("bad_line")
    if log.orphan:
        hard.add("orphan_ref")
    if why and why != "missing":
        hard.add(why)
    now = set()
    if why == "missing" and log.kinds["round"]:
        now.add("report_missing")
    if rep is not None and _stale(log, rep):
        now.add("report_stale")
    if log.partial:
        now.add("bad_line")
    looks = {r: (json.loads(old["looks"]).get(r, 0) if old else 0) + 1 for r in now}
    fresh = rep is not None and not hard and "report_stale" not in now
    old_rows = {r[1]: r for r in con.execute("SELECT * FROM review_findings WHERE item = ?", (item,))}
    held = {i: r[6:] for i, r in old_rows.items()}  # sequence, relation, outcome, has_component
    _log_tables(con, item)
    hard = [r for r in REASONS if r in hard]
    cn = rep["counts"] if fresh else {}
    keep = old or {}
    con.execute("INSERT OR REPLACE INTO review_items VALUES (?,?,?,?,?,?,?,?,?,?)",
                (item, _repo(item), log.lines, rep["state"] if fresh else keep.get("state"), ",".join(hard),
                 ",".join(_confirmed(hard, looks)), json.dumps(looks),
                 cn.get("skipped_redesigns") if fresh else keep.get("skipped_redesigns"),
                 cn.get("needs_component") if fresh else keep.get("needs_component"),
                 cn.get("undisposed_blocking") if fresh else keep.get("undisposed_blocking")))
    for r in log.rounds.values():
        con.execute("INSERT INTO review_rounds VALUES (?,?,?,?,?,?,?,?,?)",
                    (item, r["round"], r["review_round"], r["stage"], r["verdict"], r["model"],
                     r["duration_ms"], r["cost_usd"], r["at_ms"]))
    by_id = {f["id"]: (f["sequence"], f["relation"], f["outcome"], int(f["has_component"])) for f in rep["findings"]} if fresh else held
    for f in log.findings.values():
        x = by_id.get(f["id"], (None, None, None, None))
        con.execute("INSERT INTO review_findings VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (item, f["id"], f["round"], f["severity"], f["effective"], f["demoted"], *x))
    if not fresh:  # a finding the log no longer yields (its line was lost or broke) keeps the row it had: the counters never fall
        for i, r in old_rows.items():
            if i not in log.findings:
                con.execute("INSERT INTO review_findings VALUES (?,?,?,?,?,?,?,?,?,?)", r)
    for i, r in enumerate(log.redesigns):
        con.execute("INSERT INTO review_redesigns VALUES (?,?,?,?,?)", (item, i, r["round"], r["action"], r["makes_impossible"]))
    for i, r in enumerate(log.escapes):
        con.execute("INSERT INTO review_escapes VALUES (?,?,?,?)", (item, i, r["round"], r["at_ms"]))


def update(con, root=None):
    """Read the review folder and bring the review tables up to date. Returns {"ok": bool, "problems": {reason: items}}.
    Never raises for anything found in the folder: a failure while reading an item is that item's reader_error.

    Every build calls this and counts as one look at the folder, rebuilt or not: when nothing changed in size or mtime,
    the tables are kept and only the look counters advance."""
    root = Path(root) if root else traces_root()
    try:
        items, strays = _scan(root)
        sig = _signature(items, strays)
    except Exception:  # the folder could not be listed: keep every table and say so
        with con:
            return _summary(con, {"reader_error": 1})
    with con:
        row = con.execute("SELECT value FROM meta WHERE key='review_sig'").fetchone()
        if row and row[0] == sig:
            for item, hard, looks in con.execute("SELECT item, hard, looks FROM review_items").fetchall():
                looks = {r: n + 1 for r, n in json.loads(looks).items()}
                con.execute("UPDATE review_items SET looks=?, problems=? WHERE item=?",
                            (json.dumps(looks), ",".join(_confirmed([r for r in hard.split(",") if r], looks)), item))
            return _summary(con)
        cur = con.execute("SELECT * FROM review_items")
        names = [c[0] for c in cur.description]
        olds = {r[0]: dict(zip(names, r)) for r in cur.fetchall()}
        present = {d.name for d in items}
        for gone in set(olds) - present:
            _log_tables(con, gone)
            con.execute("DELETE FROM review_items WHERE item = ?", (gone,))
        for d in items:
            con.execute("SAVEPOINT item")
            try:
                _read_item(con, d, olds.get(d.name))
            except Exception:  # noqa: BLE001 - one bad item must not fail the Pi build; its previous rows are kept
                con.execute("ROLLBACK TO item")
                old = olds.get(d.name)
                hard = sorted(set(filter(None, (old or {}).get("hard", "").split(","))) | {"reader_error"})
                con.execute("INSERT OR REPLACE INTO review_items VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (d.name, _repo(d.name), (old or {}).get("log_lines", 0), (old or {}).get("state"), ",".join(hard),
                             ",".join(hard), "{}", (old or {}).get("skipped_redesigns"), (old or {}).get("needs_component"),
                             (old or {}).get("undisposed_blocking")))
            con.execute("RELEASE item")
        con.execute("INSERT OR REPLACE INTO meta VALUES ('review_stray', ?)", (str(len(strays)),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('review_sig', ?)", (sig,))
        return _summary(con)


# ---------------------------------------------------------------- series (see agent_events_metrics.collect / export)

def _has_tables(con):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE name='review_items'").fetchone())


def _family(name, kind, labels, rows, approved):
    """rows: (repo, label values..., value); repos outside the approved set merge into 'other'."""
    acc = {}
    for r in rows:
        key = ((r[0] if r[0] in approved else "other"),) + tuple(r[1:-1])
        acc[key] = acc.get(key, 0) + r[-1]
    return {"name": name, "type": kind, "points": [(dict(zip(labels, k)), float(v)) for k, v in sorted(acc.items())]}


def counters(con, approved):
    """The pi_review_* counters, as cumulative totals recomputed from the tables. The two that come from report.json
    (relations, dispositions) count what each item last had from a fresh report: held while it is unhealthy, so a total
    never falls because of a problem."""
    if not _has_tables(con):
        return []
    q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
    rb = "CASE WHEN r.review_round >= 4 THEN '4+' ELSE CAST(r.review_round AS TEXT) END"
    return [
        _family("pi_review_rounds_total", "sum", ("project", "verdict", "stage", "model"), q(
            "SELECT i.repo, r.verdict, r.stage, COALESCE(r.model, 'unknown'), COUNT(*) FROM review_rounds r "
            "JOIN review_items i USING (item) GROUP BY 1, 2, 3, 4"), approved),
        _family("pi_review_findings_total", "sum", ("project", "review_round", "effective", "stage"), q(
            f"SELECT i.repo, {rb}, f.effective, r.stage, COUNT(*) FROM review_findings f "
            "JOIN review_rounds r ON r.item = f.item AND r.round = f.round JOIN review_items i ON i.item = f.item "
            "GROUP BY 1, 2, 3, 4"), approved),
        _family("pi_review_demoted_total", "sum", ("project",), q(
            "SELECT i.repo, COUNT(*) FROM review_findings f JOIN review_items i USING (item) WHERE f.demoted = 1 GROUP BY 1"),
            approved),
        _family("pi_review_redesigns_total", "sum", ("project", "action", "makes_impossible"), q(
            "SELECT i.repo, d.action, d.makes_impossible, COUNT(*) FROM review_redesigns d "
            "JOIN review_items i USING (item) GROUP BY 1, 2, 3"), approved),
        _family("pi_review_escapes_total", "sum", ("project",), q(
            "SELECT i.repo, COUNT(*) FROM review_escapes e JOIN review_items i USING (item) GROUP BY 1"), approved),
        _family("pi_review_cost_usd_total", "sum", ("project", "stage", "model"), q(
            "SELECT i.repo, r.stage, COALESCE(r.model, 'unknown'), SUM(r.cost_usd) FROM review_rounds r "
            "JOIN review_items i USING (item) WHERE r.cost_usd IS NOT NULL GROUP BY 1, 2, 3"), approved),
        _family("pi_review_relations_total", "sum", ("project", "relation"), q(
            "SELECT i.repo, f.relation, COUNT(*) FROM review_findings f JOIN review_items i USING (item) "
            "WHERE f.relation IS NOT NULL GROUP BY 1, 2"), approved),
        _family("pi_review_dispositions_total", "sum", ("project", "outcome"), q(
            "SELECT i.repo, f.outcome, COUNT(*) FROM review_findings f JOIN review_items i USING (item) "
            "WHERE f.outcome IS NOT NULL GROUP BY 1, 2"), approved),
    ]


def gauges(con, approved):
    if not _has_tables(con):
        return []
    have = dict(con.execute("SELECT reason, items FROM review_problems").fetchall())
    return [
        _family("pi_review_skipped_redesigns", "gauge", ("project",), con.execute(
            "SELECT repo, SUM(skipped_redesigns) FROM review_items WHERE state IS NOT NULL GROUP BY 1").fetchall(),
            approved),
        _family("pi_review_items", "gauge", ("project", "state"), con.execute(
            "SELECT repo, state, COUNT(*) FROM review_items WHERE state IS NOT NULL GROUP BY 1, 2").fetchall(),
            approved),
        {"name": "pi_review_reader_problem_items", "type": "gauge",
         "points": [({"reason": r}, float(have.get(r, 0))) for r in REASONS]},
    ]
