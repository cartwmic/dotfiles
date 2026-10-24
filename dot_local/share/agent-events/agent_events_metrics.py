"""agent-events metrics: aggregate-only OTLP export, the always-on tick and the staleness check.

Only counts, durations, tokens, notional cost and fixed-vocabulary names leave the machine, grouped
by low-cardinality labels (project slug, kind, provider, model, tool, outcome). No paths, no message text,
tool arguments or error text. The one exception to "no session ids" is the three pi_cache_*_30m gauges, which carry a
short session prefix for sessions active in the last 30 minutes only (see cache_gauges). Content stays in the session files.
"""
import contextlib
import errno
import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import agent_events as ae

LLM_BOUNDS = (1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1200)             # seconds
TOOL_BOUNDS = (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1800)      # seconds
PHASES = ("llm", "explore", "edit", "run", "delegate", "owner", "other")
KIND_LABEL = {"top": "top", "child": "subagent"}
MAX_STALE_S = 900
CACHE_WINDOW_S = 1800           # trailing window for the per-session cache gauges
FULL_MISS_WRITE_TOKENS = 50_000  # a "full miss": more than this many cache-write tokens ...
FULL_MISS_READ_SHARE = 0.2       # ... while under this share of the prompt was read from cache
SESSION_LABEL_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z-]{0,12}")
LOG_LIMIT = 1_000_000
TICK_LIMIT_S = 1200


class TickTimeout(BaseException):
    """Raised by the watchdog alarm; a BaseException so the tick's own 'except Exception' cannot swallow it."""


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(os.environ.get("AGENT_EVENTS_STATE_DIR") or Path(base) / "agent-events")


def endpoint():
    return os.environ.get("AGENT_EVENTS_OTLP_ENDPOINT") or None


# ---------------------------------------------------------------- aggregation

def _kind(value):
    return KIND_LABEL.get(value, "top")


def _sum_by(rows, label_len, value_len):
    """rows: (label..., value...) tuples; labels already mapped. Returns {labels: [sums]}."""
    out = {}
    for r in rows:
        acc = out.setdefault(tuple(r[:label_len]), [0.0] * value_len)
        for i in range(value_len):
            acc[i] += r[label_len + i] or 0
    return out


def _hist(rows, bounds):
    """rows: (labels..., n_timed, sum_ms, le_0, le_1, ... ) -> {labels: (counts, sum_s, n)}."""
    out = {}
    for r in rows:
        labels = tuple(r[:-(2 + len(bounds))])
        n, sum_ms, *cum = r[-(2 + len(bounds)):]
        counts = [cum[0]] + [cum[i] - cum[i - 1] for i in range(1, len(cum))] + [n - cum[-1]]
        acc = out.setdefault(labels, [[0] * (len(bounds) + 1), 0.0, 0])
        acc[0] = [a + b for a, b in zip(acc[0], counts)]
        acc[1] += (sum_ms or 0) / 1000.0
        acc[2] += n
    return out


NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}(?:[/:][A-Za-z0-9][A-Za-z0-9._-]{0,63})?")


def export_name(value):
    """Provider, model and tool names leave the machine only when they look like an identifier
    (name, vendor/name or name:tag). A filesystem path or any other string becomes 'other'."""
    return value if isinstance(value, str) and NAME_RE.fullmatch(value) else "other"


def collect(con):
    """Read the database and return metric families. Values are cumulative totals recomputed from the
    current database; account() turns them into a monotonic series before they are sent."""
    project = ae.export_project
    metrics = []

    def counter(name, labels, rows, scale=1.0, index=0):
        pts = [({k: v for k, v in zip(labels, key)}, vals[index] * scale) for key, vals in sorted(rows.items())]
        metrics.append({"name": name, "type": "sum", "points": pts})

    # per project and kind: sessions, turns, time
    rows = [(project(r[0]), _kind(r[1]), r[2], r[3], r[4], r[5], r[6], r[7]) for r in con.execute(
        "SELECT cwd, kind, COUNT(*), SUM(turns), SUM(active_ms), SUM(llm_ms), SUM(tool_ms), SUM(owner_wait_ms)"
        " FROM sessions GROUP BY cwd, kind")]
    agg = _sum_by(rows, 2, 6)
    for i, (name, scale) in enumerate((("pi_sessions", 1), ("pi_turns", 1), ("pi_active_seconds", 0.001),
                                        ("pi_llm_seconds", 0.001), ("pi_tool_seconds", 0.001),
                                        ("pi_owner_wait_seconds", 0.001))):
        counter(name, ("project", "kind"), agg, scale, i)

    # turn phase time
    rows = []
    for r in con.execute("SELECT s.cwd, s.kind, " + ", ".join(f"SUM(t.{p}_ms)" for p in PHASES) +
                         " FROM turns t JOIN sessions s USING (path) GROUP BY s.cwd, s.kind"):
        for p, v in zip(PHASES, r[2:]):
            rows.append((project(r[0]), _kind(r[1]), p, v))
    agg = _sum_by(rows, 3, 1)
    counter("pi_phase_seconds", ("project", "kind", "phase"), agg, 0.001)

    # LLM calls: tokens and notional cost per project, kind, model; calls per model and outcome
    rows_tok, rows_cost, rows_calls = [], [], []
    for r in con.execute(
            "SELECT s.cwd, s.kind, c.provider, c.model, c.status, COUNT(*), SUM(c.fresh_input_tokens),"
            " SUM(c.cache_read_tokens), SUM(c.cache_write_tokens), SUM(c.output_tokens), SUM(c.cost_usd)"
            " FROM calls c JOIN sessions s USING (path) WHERE c.kind='llm' AND c.dup=0"
            " GROUP BY s.cwd, s.kind, c.provider, c.model, c.status"):
        pj, kind = project(r[0]), _kind(r[1])
        prov, mdl = export_name(r[2]), export_name(r[3])
        rows_calls.append((pj, kind, prov, mdl, r[4], r[5]))
        for tp, v in zip(("input", "cache_read", "cache_write", "output"), r[6:10]):
            rows_tok.append((pj, kind, prov, mdl, tp, v))
        rows_cost.append((pj, kind, prov, mdl, "call", r[10]))
    for r in con.execute(
            "SELECT s.cwd, s.kind, COALESCE(c.provider,'unknown'), COALESCE(c.model, 'unknown'), SUM(c.cost_usd)"
            " FROM calls c JOIN sessions s USING (path) WHERE c.kind='overhead' AND c.dup=0"
            " GROUP BY s.cwd, s.kind, c.provider, c.model"):
        rows_cost.append((project(r[0]), _kind(r[1]), export_name(r[2]), export_name(r[3]), "overhead", r[4]))
    counter("pi_llm_calls", ("project", "kind", "provider", "model", "outcome"), _sum_by(rows_calls, 5, 1))
    counter("pi_tokens", ("project", "kind", "provider", "model", "type"), _sum_by(rows_tok, 5, 1))
    counter("pi_notional_cost_usd", ("project", "kind", "provider", "model", "type"), _sum_by(rows_cost, 5, 1))

    # tools
    rows = [(export_name(r[0]), "true" if r[1] == "nested" else "false", r[2], r[3]) for r in con.execute(
        "SELECT name, kind, status, COUNT(*) FROM calls WHERE kind IN ('tool','nested') AND dup=0"
        " GROUP BY name, kind, status")]
    counter("pi_tool_calls", ("tool", "nested", "outcome"), _sum_by(rows, 3, 1))

    cum = ", ".join(f"SUM(dur_ms <= {int(b * 1000)})" for b in TOOL_BOUNDS)
    thist = _hist([(export_name(r[0]), "true" if r[1] == "nested" else "false", *r[2:]) for r in con.execute(
        f"SELECT name, kind, SUM(dur_ms IS NOT NULL), SUM(dur_ms), {cum} FROM calls"
        " WHERE kind IN ('tool','nested') AND dup=0 AND dur_ms IS NOT NULL GROUP BY name, kind")], TOOL_BOUNDS)
    metrics.append({"name": "pi_tool_call_duration_seconds", "type": "histogram", "bounds": TOOL_BOUNDS,
                    "points": [({"tool": k[0], "nested": k[1]}, v) for k, v in sorted(thist.items())]})
    cum = ", ".join(f"SUM(dur_ms <= {int(b * 1000)})" for b in LLM_BOUNDS)
    lhist = _hist([(export_name(r[0]), export_name(r[1]), *r[2:]) for r in con.execute(
        f"SELECT provider, model, SUM(dur_ms IS NOT NULL), SUM(dur_ms), {cum} FROM calls"
        " WHERE kind='llm' AND dup=0 AND dur_ms IS NOT NULL GROUP BY provider, model")], LLM_BOUNDS)
    metrics.append({"name": "pi_llm_call_duration_seconds", "type": "histogram", "bounds": LLM_BOUNDS,
                    "points": [({"provider": k[0], "model": k[1]}, v) for k, v in sorted(lhist.items())]})

    # events: errors, retries, aborts, compactions...
    rows = []
    for r in con.execute(
            "SELECT s.cwd, s.kind, e.kind, CASE WHEN e.kind='llm.error' THEN json_extract(e.attrs, '$.bucket')"
            " ELSE '' END, COUNT(*) FROM events e JOIN sessions s USING (path) WHERE e.dup=0"
            " GROUP BY s.cwd, s.kind, e.kind, 4"):
        rows.append((project(r[0]), _kind(r[1]), r[2], r[3] or "", r[4]))
    counter("pi_events", ("project", "kind", "event", "detail"), _sum_by(rows, 4, 1))
    return metrics


def cache_gauges(con, now):
    """Prompt-cache health per session and model over the trailing CACHE_WINDOW_S, as gauges.

    pi_cache_hit_ratio_30m        cacheRead / (cacheRead + cacheWrite + fresh input), token weighted
    pi_cache_calls_30m            LLM calls in the window (calls that report no usage are left out)
    pi_cache_full_miss_calls_30m  calls with cacheWrite > FULL_MISS_WRITE_TOKENS and cacheRead under
                                  FULL_MISS_READ_SHARE of the prompt
    The window ends at now, so the result depends only on the database and now (the replay of past hours relies on it).
    Labels: session (the first 13 characters of the session id: a Pi session id is a UUID whose prefix is its start
    time in milliseconds, so it names the session for 'agent-events session <prefix>' and carries no content),
    project, model. Only sessions with a call in the window are sent, so the series count follows what is running
    now and a finished session's series disappear. Gauges, not counters: the window is the whole state."""
    since_ms = int((now - CACHE_WINDOW_S) * 1000)
    rows = con.execute(
        "SELECT s.session_id, s.cwd, c.model, COUNT(*), SUM(COALESCE(c.cache_read_tokens,0)),"
        " SUM(COALESCE(c.cache_write_tokens,0)), SUM(COALESCE(c.fresh_input_tokens,0)),"
        " SUM(COALESCE(c.cache_write_tokens,0) > ? AND COALESCE(c.cache_read_tokens,0) <"
        " ? * (COALESCE(c.cache_read_tokens,0) + COALESCE(c.cache_write_tokens,0) + COALESCE(c.fresh_input_tokens,0)))"
        " FROM calls c JOIN sessions s USING (path)"
        " WHERE c.kind='llm' AND c.dup=0 AND c.end_ms > ? AND c.end_ms <= ?"
        " AND COALESCE(c.cache_read_tokens,0) + COALESCE(c.cache_write_tokens,0) + COALESCE(c.fresh_input_tokens,0) > 0"
        " GROUP BY s.session_id, s.cwd, c.model",
        (FULL_MISS_WRITE_TOKENS, FULL_MISS_READ_SHARE, since_ms, int(now * 1000))).fetchall()
    acc = {}
    for sid, cwd, model, n, cr, cw, fi, miss in rows:
        label = (sid or "")[:13]
        key = (label if SESSION_LABEL_RE.fullmatch(label) else "other", ae.export_project(cwd), export_name(model))
        a = acc.setdefault(key, [0, 0, 0, 0, 0])
        for i, v in enumerate((n, cr, cw, fi, miss)):
            a[i] += v or 0
    ratio, calls, misses = [], [], []
    for (session, project, model), (n, cr, cw, fi, miss) in sorted(acc.items()):
        labels = {"session": session, "project": project, "model": model}
        ratio.append((labels, cr / (cr + cw + fi)))
        calls.append((labels, float(n)))
        misses.append((labels, float(miss)))
    return [{"name": "pi_cache_hit_ratio_30m", "type": "gauge", "points": ratio},
            {"name": "pi_cache_calls_30m", "type": "gauge", "points": calls},
            {"name": "pi_cache_full_miss_calls_30m", "type": "gauge", "points": misses}]


def self_metrics(con, status, db_path):
    now = time.time()
    n_sessions = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    g = [("pi_agent_events_last_build_success_timestamp_seconds", status.get("last_build_ok_ts") or 0),
         ("pi_agent_events_build_duration_seconds", status.get("last_build_seconds") or 0),
         ("pi_agent_events_consecutive_build_failures", status.get("consecutive_build_failures") or 0),
         ("pi_agent_events_sessions_indexed", n_sessions),
         ("pi_agent_events_database_bytes", size),
         ("pi_agent_events_export_timestamp_seconds", now)]
    return [{"name": n, "type": "gauge", "points": [({}, float(v))]} for n, v in g]


# ---------------------------------------------------------------- OTLP/JSON

def _attrs(labels):
    return [{"key": k, "value": {"stringValue": str(v)}} for k, v in labels.items()]


def otlp_payload(metrics, start_ns, now_ns):
    out = []
    for m in metrics:
        if not m["points"]:
            continue
        pts = []
        for labels, value in m["points"]:
            base = {"attributes": _attrs(labels), "timeUnixNano": str(now_ns)}
            if m["type"] == "gauge":
                pts.append({**base, "asDouble": value})
                continue
            base["startTimeUnixNano"] = str(start_ns)
            if m["type"] == "sum":
                pts.append({**base, "asDouble": value})
            else:
                counts, total, n = value
                pts.append({**base, "count": str(int(n)), "sum": total, "bucketCounts": [str(int(c)) for c in counts],
                            "explicitBounds": list(m["bounds"])})
        if m["type"] == "gauge":
            body = {"gauge": {"dataPoints": pts}}
        elif m["type"] == "sum":
            body = {"sum": {"aggregationTemporality": 2, "isMonotonic": True, "dataPoints": pts}}
        else:
            body = {"histogram": {"aggregationTemporality": 2, "dataPoints": pts}}
        out.append({"name": m["name"], **body})
    resource = {"attributes": [{"key": "service.name", "value": {"stringValue": "agent-events"}}]}
    return {"resourceMetrics": [{"resource": resource, "scopeMetrics": [
        {"scope": {"name": "agent-events"}, "metrics": out}]}]}


def _own(message):
    exc = RuntimeError(message)
    exc.own_message = True  # text written by this module, safe to log
    return exc


def post(url, payload, timeout=30):
    body = gzip.compress(json.dumps(payload, separators=(",", ":")).encode())
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Content-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "replace")
        if resp.status != 200:
            raise _own(f"collector answered HTTP {resp.status}")
    try:
        rejected = ((json.loads(text) or {}).get("partialSuccess") or {}).get("rejectedDataPoints")
    except ValueError:
        rejected = None
    if rejected and int(rejected) > 0:
        raise _own(f"collector rejected {rejected} data points")
    return len(body)


def series_count(metrics):
    return sum(len(m["points"]) for m in metrics)


def _vector(m, value):
    return list(value[0]) + [value[1], value[2]] if m["type"] == "histogram" else [value]


def _unvector(kind, vec):
    return (vec[:-2], vec[-2], vec[-1]) if kind == "histogram" else vec[0]


def fingerprint():
    """Changes when the project map or the schema changes: such a change moves history between series."""
    text = "|".join(sorted(ae.approved_projects())) + f"#{ae.SCHEMA_VERSION}"
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def account(metrics, state, business=True, fp=""):
    """Make the series monotonic and replace business points with the accounted values.

    The database is recomputed on every build, so a total can fall (a removed file, a moved dedupe owner, an
    unknown duration). Prometheus would read a fall as a counter reset and invent activity, so the exported
    value only rises by the positive change since the last tick; a fall is a baseline correction.

    Baseline (first run, lost state, or a changed project map/schema): current totals become the reference and the
    exported value starts at 0, so history is never activity. After that a new series is real activity: it is
    sent as 0 first ('ok' false until that POST succeeds) and its growth is added on later ticks. Every known
    series is sent on every tick, so one that vanishes keeps its value and one that returns is still alive."""
    series = state.setdefault("series", {})
    baseline = business and (not state.get("seeded") or state.get("fp") != fp)
    if business:
        created = set()
        relayout = set()  # histogram families whose buckets changed: every retained sibling is retired too
        for m in metrics:
            if m["type"] == "histogram" and m["points"]:
                bounds = list(m.get("bounds", ()))
                stale = [k for k, e in series.items() if e["n"] == m["name"] and e["b"] != bounds]
                for k in stale:
                    del series[k]
                if stale:
                    relayout.add(m["name"])
        for m in metrics:
            if m["type"] == "gauge":
                continue
            for labels, value in m["points"]:
                key = m["name"] + "|" + json.dumps(sorted(labels.items()))
                cur = _vector(m, value)
                e = series.get(key)
                layout_changed = m["name"] in relayout or (
                    e is not None and (len(e["seen"]) != len(cur) or e["b"] != list(m.get("bounds", ()))))
                if e is None or layout_changed:  # a new series, or a histogram whose buckets changed: start over at zero
                    series[key] = {"n": m["name"], "t": m["type"], "l": labels, "b": list(m.get("bounds", ())),
                                   "last": list(cur) if (baseline or layout_changed) else [0] * len(cur),
                                   "sent": [0] * len(cur), "seen": cur, "ok": False}
                    created.add(key)
                else:
                    e["seen"] = cur
        for key, e in series.items():  # every known series, present or not: a vanished one still owes its increment
            if baseline:
                e["last"] = list(e["seen"])
            elif e["ok"] and key not in created:
                if all(c >= l for c, l in zip(e["seen"], e["last"])):
                    e["sent"] = [s + (c - l) for s, c, l in zip(e["sent"], e["seen"], e["last"])]
                e["last"] = list(e["seen"])
        state["seeded"], state["fp"] = True, fp
    families = {}
    for key in sorted(series):
        e = series[key]
        fam = families.setdefault(e["n"], {"name": e["n"], "type": e["t"], "points": []})
        if e["t"] == "histogram":
            fam["bounds"] = tuple(e["b"])
        fam["points"].append((e["l"], _unvector(e["t"], e["sent"])))
    return [m for m in metrics if m["type"] == "gauge"], list(families.values())


def mark_delivered(state):
    for e in state.get("series", {}).values():
        e["ok"] = True


STATE_LIMIT = 1e15  # counts, seconds, tokens and dollars are far below this; sums of such values cannot overflow


def _finite(x):
    """A usable state number: a real int/float within STATE_LIMIT (rejects bool, NaN, infinities and huge ints)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(x) and abs(x) <= STATE_LIMIT
    except OverflowError:
        return False


def _valid_state(state):
    try:
        if not isinstance(state, dict) or not isinstance(state.get("series"), dict):
            return False
        for e in state["series"].values():
            if not (isinstance(e, dict) and isinstance(e["l"], dict) and e["t"] in ("sum", "histogram")
                    and isinstance(e["n"], str) and isinstance(e["ok"], bool)):
                return False
            if not (isinstance(e.get("b"), list) and all(_finite(x) for x in e["b"])):
                return False
            width = len(e["b"]) + 3 if e["t"] == "histogram" else 1
            if e["t"] == "histogram" and not e["b"]:
                return False
            for k in ("last", "sent", "seen"):
                if len(e[k]) != width:
                    return False
            for k in ("last", "sent", "seen"):
                if not (isinstance(e[k], list) and e[k] and all(_finite(x) for x in e[k])):
                    return False
            if not (len(e["last"]) == len(e["sent"]) == len(e["seen"])):
                return False
        return True
    except (KeyError, TypeError):
        return False


def load_state():
    """Returns (state, lost). Lost means a file existed but could not be used: the exporter then starts a new
    accounting epoch (see _tick) instead of exporting raw totals that might look like a counter reset."""
    path = state_dir() / "export_state.json"
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {}, False
    except (OSError, ValueError):  # unreadable, or not valid UTF-8
        return {}, True
    try:
        state = json.loads(raw)
    except ValueError:
        return {}, True
    try:
        usable = _valid_state(state)
    except Exception:  # noqa: BLE001 - any surprise in a state file means: start a new epoch
        usable = False
    return (state, False) if usable else ({}, True)


def save_state(state):
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "export_state.json.tmp"
    with open(tmp, "w") as fh:
        fh.write(json.dumps(state, separators=(",", ":")))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, d / "export_state.json")


def export(con, db_path, status, url=None, now=None, state=None, business=True, persist=False):
    """Collect and, when a URL is given, push. business=False (the build failed or the database is dirty) skips
    collection and sends the last accounted values plus the health gauges. state=None sends raw totals and is
    the preview used by 'agent-events export'. With persist, the proposed values are checkpointed before the POST
    (so a crash can never let a later, lower value go out) and delivery is recorded after it."""
    gauges_src = self_metrics(con, status, db_path)
    if business:
        gauges_src = gauges_src + cache_gauges(con, now or time.time())
    if state is None:
        metrics = (collect(con) if business else []) + gauges_src
    else:
        gauges, families = account(collect(con) if business else [], state, business, fingerprint())
        metrics = families + gauges_src
        if persist:
            save_state(state)
    now_ns = int((now or time.time()) * 1e9)
    start_ns = int(status.get("epoch_ns") or now_ns)
    sent = 0
    if url:
        sent = post(url, otlp_payload(metrics, start_ns, now_ns))
        if state is not None:
            mark_delivered(state)
            if persist:
                save_state(state)
    return metrics, sent


def safe_error(exc):
    """A description of a failure that cannot contain a path, an id or message text: type and code only."""
    name = type(exc).__name__
    if isinstance(exc, sqlite3.Error):
        return f"{name}: {getattr(exc, 'sqlite_errorname', '') or 'sqlite'}"
    if isinstance(exc, urllib.error.HTTPError):
        return f"{name}: HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        code = errno.errorcode.get(getattr(reason, "errno", None) or 0, "")
        return f"{name}: {type(reason).__name__} {code}".strip()
    if isinstance(exc, OSError):
        return f"{name}: {errno.errorcode.get(exc.errno or 0, 'error')}"
    if isinstance(exc, RuntimeError) and getattr(exc, "own_message", False):
        return str(exc)
    return name


def is_busy(exc):
    text = str(exc).lower()
    return getattr(exc, "sqlite_errorname", "") in ("SQLITE_BUSY", "SQLITE_LOCKED") or "locked" in text or "busy" in text


def is_corrupt(exc):
    if not isinstance(exc, sqlite3.DatabaseError) or is_busy(exc):
        return False
    text = str(exc).lower()
    return (getattr(exc, "sqlite_errorname", "") in ("SQLITE_NOTADB", "SQLITE_CORRUPT")
            or "not a database" in text or "malformed" in text)


@contextlib.contextmanager
def build_lock(blocking=True):
    """One build at a time across the scheduled tick and a manual 'agent-events build'."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


# ---------------------------------------------------------------- state, tick, status

def load_status():
    try:
        return json.loads((state_dir() / "status.json").read_text())
    except (OSError, ValueError):
        return {}


def save_status(status):
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "status.json.tmp"
    tmp.write_text(json.dumps(status, indent=1, sort_keys=True))
    os.replace(tmp, d / "status.json")


def log(msg):
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / "agent.log"
    try:
        if path.exists() and path.stat().st_size > LOG_LIMIT:
            os.replace(path, d / "agent.log.1")
    except OSError:
        pass
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    with open(path, "a") as fh:
        fh.write(line + "\n")
    if sys.stderr.isatty():
        print(line, file=sys.stderr)


def quarantine(db):
    """Set a database that will not open aside; derived data is rebuilt from the session files."""
    db = Path(db)
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = Path(str(db) + suffix)
        if p.exists():
            os.replace(p, Path(str(db) + suffix + ".corrupt"))


def _build_with_healing(sessions_dir, db, status):
    try:
        return ae.build(sessions_dir, db)
    except sqlite3.DatabaseError as exc:
        if not is_corrupt(exc):  # busy/locked or another failure: report it, never rename a healthy database
            raise
        log(f"build: the database is corrupt ({safe_error(exc)}); setting it aside and rebuilding from the session files")
        quarantine(db)
        return ae.build(sessions_dir, db)


def run_once(sessions_dir, db):
    """One tick: incremental build, then export. Never raises; returns the exit code."""
    with build_lock(blocking=False) as got:
        if not got:
            log("skipped: a previous run or a manual build is still going")
            return 0
        # A hung tick would hold the lock and silence every later one: give up after TICK_LIMIT_S.
        def on_alarm(*_):
            raise TickTimeout()
        try:
            limit = int(os.environ.get("AGENT_EVENTS_TICK_LIMIT_S") or TICK_LIMIT_S)
        except ValueError:
            limit = TICK_LIMIT_S
        if limit <= 0:
            limit = TICK_LIMIT_S
        previous = signal.signal(signal.SIGALRM, on_alarm)
        try:
            signal.alarm(limit)
            return _tick(sessions_dir, db)
        except TickTimeout:
            log("tick: gave up after the time limit; the next scheduled run starts clean")
            return 1
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)


def _tick(sessions_dir, db):
    status = load_status()
    status.setdefault("epoch_ns", int(time.time() * 1e9))
    status["last_attempt_ts"] = time.time()
    code = 0
    build_failed = False
    t0 = time.time()
    try:
        res = _build_with_healing(sessions_dir, db, status)
        status.update(last_build_ok_ts=time.time(), last_build_seconds=round(time.time() - t0, 2),
                      consecutive_build_failures=0, last_build_error=None, last_parsed=res["parsed"],
                      sessions=res["sessions"])
        if res["parsed"] or res["removed"]:
            log(f"build ok: {res['parsed']} parsed, {res['removed']} removed, {res['sessions']} sessions "
                f"in {time.time() - t0:.1f}s")
    except Exception as exc:  # noqa: BLE001 - the tick must survive anything and report it
        code = 1
        build_failed = True
        status["last_build_error"] = safe_error(exc)  # type and code only: never a path or message text
        if is_busy(exc):
            log(f"build: database busy ({status['last_build_error']}); trying again next tick")
        else:
            status["consecutive_build_failures"] = status.get("consecutive_build_failures", 0) + 1
            log(f"build failed ({status['consecutive_build_failures']} in a row): {status['last_build_error']}")
        if status.get("consecutive_build_failures", 0) >= 3 and Path(db).exists():
            log("build: three failures in a row; setting the database aside so the next run rebuilds it")
            quarantine(db)
            status["consecutive_build_failures"] = 0
    url = endpoint()
    if url and Path(db).exists():
        try:
            con = ae.connect(db, readonly=True)
            state, lost = load_state()
            if lost:  # a new accounting epoch: counters restart at 0 with a new start time, history is no activity
                status["epoch_ns"] = int(time.time() * 1e9)
                log("export state was unusable; starting a new accounting epoch")
            try:
                dirty = (con.execute("SELECT value FROM meta WHERE key='dirty'").fetchone() or ("0",))[0] == "1"
                metrics, sent = export(con, db, status, url, state=state, business=not (dirty or build_failed), persist=True)
            finally:
                con.close()
            status.update(last_export_ok_ts=time.time(), last_export_error=None,
                          last_export_series=series_count(metrics), last_export_bytes=sent)
        except Exception as exc:  # noqa: BLE001
            code = code or 1
            message = safe_error(exc)
            if message != status.get("last_export_error"):  # one line per distinct failure, not one per tick
                log(f"export failed: {message}")
            status["last_export_error"] = message
    save_status(status)
    return code


def cmd_status(max_age=MAX_STALE_S):
    status = load_status()
    now = time.time()

    def age(key):
        return None if not status.get(key) else now - status[key]

    def show(a):
        return "never" if a is None else ae.fmt_ms(a * 1000) + " ago"

    build_age, export_age = age("last_build_ok_ts"), age("last_export_ok_ts")
    lines = [f"last successful build : {show(build_age)}",
             f"last successful export: {show(export_age)}" + ("" if endpoint() else "  (no OTLP endpoint configured here)"),
             f"sessions indexed      : {status.get('sessions', 'unknown')}",
             f"last build took       : {status.get('last_build_seconds', 'unknown')}s"]
    if status.get("last_build_error"):
        lines.append(f"last build error      : {status['last_build_error']}")
    if status.get("last_export_error"):
        lines.append(f"last export error     : {status['last_export_error']}")
    stale = build_age is None or build_age > max_age
    lines.append(("STALE: " if stale else "fresh: ") + f"limit is {ae.fmt_ms(max_age * 1000)}")
    return "\n".join(lines), (1 if stale else 0)
