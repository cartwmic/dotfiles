"""agent-events review reader: the review log's ids, counts and enumerated values, read strictly.

Reads ${AGENT_TRACES_DIR:-~/.local/share/agent-traces}/emitted/review/<item>/findings.jsonl and the report.json beside it
(defined in findings-contract.md, "The report"). It computes no stuck trigger: whatever is derived (relations, dispositions,
skipped redesigns, state) comes from report.json. The database holds what is on disk now (ids, log round, review round, stage, model
name, enumerated values, a demoted flag, cost, duration, the report's counts, and a hash key per event); it is rebuilt from the
files and is for local queries. Never stored anywhere: any free-text field (text, obligation, evidence, consequence, component,
head, reviewer, session, found_by ...), a session id or a component name.

Strict: every problem is counted per item under one reason and shown in status.json and in the gauge
pi_review_reader_problem_items. Nothing is skipped without a reason (entries whose name starts with "." are ignored).

Accounting: the exported totals are sums over a ledger in export_state.json (state["review"]), written by the same atomic save as
the series. An event is counted once, under a key made from a hash of its repo, its round's head and its round or id; a key is never
removed. So a total never falls, however the files change (a broken line, a truncated log, a moved folder, a rebuilt database), and
what comes back is not counted again. The ledger is the only mechanism: the tables are not held, and account() never sees a fall.
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


def _s(v):
    """A field that is only hashed into a key: a string as it is, anything else as its JSON, missing as ''."""
    return "" if v is None else (v if isinstance(v, str) else json.dumps(v, sort_keys=True))


def _scope(item):
    """The repo part of <repo>#<pr>, lower-cased; an item with no '#' is its own scope. Keys use this, not the folder name,
    so renaming <repo>#PLACEHOLDER to <repo>#217 neither recounts nor drops anything."""
    return item.split("#", 1)[0].lower() if "#" in item else item


def _key(kind, scope, *parts):
    return hashlib.sha256(json.dumps([kind, scope, *parts]).encode()).hexdigest()[:20]


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
        self.unknown = self.bad = self.partial = self.orphan = False
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
                "model": None if model is None else (model if MODEL_RE.fullmatch(model) else "other"), "head": _s(o.get("head")),
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
        return {"round": o["round"], "action": o["action"], "makes_impossible": o["makes_impossible"],
                "component": _s(o.get("component"))} if ok else None
    elif k == "judge":
        ok = _int(o.get("round"), 1) and o.get("verdict") in JUDGE_VERDICTS
    elif k == "escape":
        ok = _int(o.get("round"), 1)
        return {"round": o["round"], "at_ms": _at_ms(o["at"]), "head": _s(o.get("head")), "found_by": _s(o.get("found_by"))} if ok else None
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
    except OSError:  # unreadable: shown as a bad line, never a failed Pi build
        log.bad = True
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
    for rd in list(log.redesigns):
        if rd["round"] not in log.rounds:  # a redesign whose round line is missing has no key yet
            log.orphan = True
            log.redesigns.remove(rd)
    log.orphan = log.orphan or any(r not in log.findings for r in log.refs)  # a label or disposition that names no finding
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


def _read_item(con, d, old_looks):
    """Replace one item's rows with what is on disk now. old_looks: its look counters from the last rebuild ({} if none).
    Report-derived values are taken from a fresh report only. Nothing is held: the ledger keeps what was counted."""
    item = d.name
    log = parse_log(d / "findings.jsonl")
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
    looks = {r: old_looks.get(r, 0) + 1 for r in now}
    fresh = rep is not None and not hard and "report_stale" not in now
    _log_tables(con, item)
    hard = [r for r in REASONS if r in hard]
    cn = rep["counts"] if fresh else {}
    scope = _scope(item)
    con.execute("INSERT OR REPLACE INTO review_items VALUES (?,?,?,?,?,?,?,?,?,?)",
                (item, _repo(item), log.lines, rep["state"] if fresh else None, ",".join(hard),
                 ",".join(_confirmed(hard, looks)), json.dumps(looks),
                 cn.get("skipped_redesigns"), cn.get("needs_component"), cn.get("undisposed_blocking")))
    for r in log.rounds.values():
        con.execute("INSERT INTO review_rounds VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (item, r["round"], r["review_round"], r["stage"], r["verdict"], r["model"],
                     r["duration_ms"], r["cost_usd"], r["at_ms"], _key("round", scope, r["head"], r["round"])))
    by_id = {f["id"]: (f["sequence"], f["relation"], f["outcome"], int(f["has_component"])) for f in rep["findings"]} if fresh else {}
    for f in log.findings.values():
        x = by_id.get(f["id"], (None, None, None, None))
        con.execute("INSERT INTO review_findings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (item, f["id"], f["round"], f["severity"], f["effective"], f["demoted"], *x,
                     _key("finding", scope, log.rounds[f["round"]]["head"], f["id"])))
    for i, r in enumerate(log.redesigns):
        con.execute("INSERT INTO review_redesigns VALUES (?,?,?,?,?,?)",
                    (item, i, r["round"], r["action"], r["makes_impossible"],
                     _key("redesign", scope, log.rounds[r["round"]]["head"], r["round"], r["component"])))
    for i, r in enumerate(log.escapes):
        con.execute("INSERT INTO review_escapes VALUES (?,?,?,?,?)",
                    (item, i, r["round"], r["at_ms"], _key("escape", scope, r["head"], r["round"], r["found_by"])))


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
        olds = {item: json.loads(looks) for item, looks in con.execute("SELECT item, looks FROM review_items")}
        present = {d.name for d in items}
        for gone in set(olds) - present:
            _log_tables(con, gone)
            con.execute("DELETE FROM review_items WHERE item = ?", (gone,))
        for d in items:
            con.execute("SAVEPOINT item")
            try:
                _read_item(con, d, olds.get(d.name, {}))
            except Exception:  # noqa: BLE001 - one bad item must not fail the Pi build
                con.execute("ROLLBACK TO item")
                con.execute("INSERT OR REPLACE INTO review_items VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (d.name, _repo(d.name), 0, None, "reader_error", "reader_error", "{}", None, None, None))
            con.execute("RELEASE item")
        con.execute("INSERT OR REPLACE INTO meta VALUES ('review_stray', ?)", (str(len(strays)),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('review_sig', ?)", (sig,))
        return _summary(con)


# ---------------------------------------------------------------- the ledger and the series

LEDGER_VERSION = 1
MARKER = f"pi_review@{LEDGER_VERSION}"  # the review series' baseline marker in export_state.json["seeded_families"]; bump with the ledger


def new_ledger():
    """seen: {event key: 1}, every event ever counted. tot: {series: {labels (JSON): total}}. cost: {round key: [usd, labels]}.
    g: {hash of the item name: [state, skipped_redesigns]}, the last values from a fresh report, for the gauges."""
    return {"v": LEDGER_VERSION, "seen": {}, "tot": {}, "cost": {}, "g": {}}


def valid_ledger(led):
    try:
        return (isinstance(led, dict) and led.get("v") == LEDGER_VERSION and isinstance(led["seen"], dict) and isinstance(led["tot"], dict)
                and all(isinstance(v, dict) and all(isinstance(k, str) and _num(x) for k, x in v.items()) for v in led["tot"].values())
                and isinstance(led["cost"], dict) and all(isinstance(v, list) and len(v) == 2 and _num(v[0]) and isinstance(v[1], str)
                                                         for v in led["cost"].values())
                and isinstance(led["g"], dict) and all(isinstance(v, list) and len(v) == 2 for v in led["g"].values()))
    except (KeyError, TypeError):
        return False


def ledger_for(state):
    """The ledger in the persistent state, valid. A missing or bad one is replaced by an empty one and the review baseline marker is
    cleared, so only the review series start a baseline (account() keeps what they already sent); nothing else is affected."""
    led = state.get("review")
    if not valid_ledger(led):
        led = state["review"] = new_ledger()
        marks = state.get("seeded_families")
        if isinstance(marks, list):
            state["seeded_families"] = [m for m in marks if m != MARKER]
    return led


def _project(item, approved):
    repo = _repo(item)
    return repo if repo in approved else "other"


def _add(led, name, labels, value=1):
    series = led["tot"].setdefault(name, {})
    k = json.dumps(labels, sort_keys=True)
    series[k] = series.get(k, 0) + value


def _once(led, key):
    """True the first time a key is seen; it is then in the ledger for good."""
    if key in led["seen"]:
        return False
    led["seen"][key] = 1
    return True


def apply(con, led, approved):
    """Count into the ledger what the tables hold that it has not counted. Idempotent, and it only adds. A bounded cost: a pass
    over the rows on disk now."""
    if not _has_tables(con):
        return
    for item, key, verdict, stage, model, cost in con.execute(
            "SELECT item, key, verdict, stage, model, cost_usd FROM review_rounds ORDER BY item, round").fetchall():
        project, model = _project(item, approved), model or "unknown"
        if _once(led, "round:" + key):
            _add(led, "pi_review_rounds_total", {"project": project, "verdict": verdict, "stage": stage, "model": model})
        if cost is not None:  # counted once; a later, higher value adds only the difference, a lower one is ignored
            prev = led["cost"].get("cost:" + key)
            labels = json.dumps({"project": project, "stage": stage, "model": model}, sort_keys=True)
            if prev is None:
                led["cost"]["cost:" + key] = [cost, labels]
                _add_json(led, "pi_review_cost_usd_total", labels, cost)
            elif cost > prev[0]:
                _add_json(led, "pi_review_cost_usd_total", prev[1], cost - prev[0])
                prev[0] = cost
    for item, key, effective, demoted, relation, outcome, review_round, stage in con.execute(
            "SELECT f.item, f.key, f.effective, f.demoted, f.relation, f.outcome, r.review_round, r.stage FROM review_findings f "
            "JOIN review_rounds r ON r.item = f.item AND r.round = f.round ORDER BY f.item, f.round, f.id").fetchall():
        project = _project(item, approved)
        if _once(led, "finding:" + key):
            _add(led, "pi_review_findings_total", {"project": project, "review_round": "4+" if review_round >= 4 else str(review_round),
                                                   "effective": effective, "stage": stage})
        if demoted and _once(led, "demoted:" + key):
            _add(led, "pi_review_demoted_total", {"project": project})
        if relation and _once(led, "relation:" + key):  # first seen wins: a later relabel does not move a counted finding
            _add(led, "pi_review_relations_total", {"project": project, "relation": relation})
        if outcome and _once(led, "outcome:" + key):
            _add(led, "pi_review_dispositions_total", {"project": project, "outcome": outcome})
    for item, key, action, impossible in con.execute("SELECT item, key, action, makes_impossible FROM review_redesigns").fetchall():
        if _once(led, "redesign:" + key):
            _add(led, "pi_review_redesigns_total", {"project": _project(item, approved), "action": action, "makes_impossible": impossible})
    for item, key in con.execute("SELECT item, key FROM review_escapes").fetchall():
        if _once(led, "escape:" + key):
            _add(led, "pi_review_escapes_total", {"project": _project(item, approved)})
    present = {}
    for item, state, skipped in con.execute("SELECT item, state, skipped_redesigns FROM review_items").fetchall():
        k = _key("item", item)
        present[k] = led["g"].get(k)
        if state is not None:  # only a fresh report moves the gauges' inputs
            present[k] = [state, skipped]
    led["g"] = {k: v for k, v in present.items() if v is not None}


def _add_json(led, name, labels_json, value):
    series = led["tot"].setdefault(name, {})
    series[labels_json] = series.get(labels_json, 0) + value


def _has_tables(con):
    return bool(con.execute("SELECT 1 FROM sqlite_master WHERE name='review_items'").fetchone())


def counters(led):
    """The pi_review_* counters: the ledger's totals. They only ever grow."""
    return [{"name": name, "type": "sum", "points": [(json.loads(k), float(v)) for k, v in sorted(series.items())]}
            for name, series in sorted(led["tot"].items())]


def gauges(con, approved, led):
    """Current state: folders present now (a moved-away folder is gone, which is right for a gauge), with the last good values."""
    if not _has_tables(con):
        return []
    have = dict(con.execute("SELECT reason, items FROM review_problems").fetchall())
    items, skipped = {}, {}
    for item in (r[0] for r in con.execute("SELECT item FROM review_items")):
        g = led["g"].get(_key("item", item))
        if g is None:
            continue
        p = _project(item, approved)
        items[(p, g[0])] = items.get((p, g[0]), 0) + 1
        skipped[p] = skipped.get(p, 0) + (g[1] or 0)
    return [
        {"name": "pi_review_skipped_redesigns", "type": "gauge", "points": [({"project": p}, float(v)) for p, v in sorted(skipped.items())]},
        {"name": "pi_review_items", "type": "gauge", "points": [({"project": p, "state": st}, float(n)) for (p, st), n in sorted(items.items())]},
        {"name": "pi_review_reader_problem_items", "type": "gauge", "points": [({"reason": r}, float(have.get(r, 0))) for r in REASONS]},
    ]
