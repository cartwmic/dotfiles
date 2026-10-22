"""agent-events metrics: aggregate-only OTLP export, the always-on tick and the staleness check.

Only counts, durations, tokens, notional cost and fixed-vocabulary names leave the machine, grouped
by low-cardinality labels (project slug, kind, provider, model, tool, outcome). No session ids, no
paths, no message text, tool arguments or error text. Content stays in the session files.
"""
import fcntl
import gzip
import json
import os
import sqlite3
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import agent_events as ae

LLM_BOUNDS = (1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1200)             # seconds
TOOL_BOUNDS = (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1800)      # seconds
PHASES = ("llm", "explore", "edit", "run", "delegate", "owner", "other")
KIND_LABEL = {"top": "top", "child": "subagent"}
MAX_STALE_S = 900
LOG_LIMIT = 1_000_000


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


def collect(con):
    """Read the database and return metric families. Counters are cumulative totals since the data began."""
    project = ae.project_of
    metrics = []

    def counter(name, labels, rows, scale=1.0, index=0):
        pts = [({k: v for k, v in zip(labels, key)}, vals[index] * scale) for key, vals in sorted(rows.items())
               if vals[index]]
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
        rows_calls.append((pj, kind, r[2], r[3], r[4], r[5]))
        for tp, v in zip(("input", "cache_read", "cache_write", "output"), r[6:10]):
            rows_tok.append((pj, kind, r[2], r[3], tp, v))
        rows_cost.append((pj, kind, r[2], r[3], "call", r[10]))
    for r in con.execute(
            "SELECT s.cwd, s.kind, COALESCE(c.provider,'unknown'), COALESCE(c.model, 'unknown'), SUM(c.cost_usd)"
            " FROM calls c JOIN sessions s USING (path) WHERE c.kind='overhead' AND c.dup=0"
            " GROUP BY s.cwd, s.kind, c.provider, c.model"):
        rows_cost.append((project(r[0]), _kind(r[1]), r[2], r[3], "overhead", r[4]))
    counter("pi_llm_calls", ("project", "kind", "provider", "model", "outcome"), _sum_by(rows_calls, 5, 1))
    counter("pi_tokens", ("project", "kind", "provider", "model", "type"), _sum_by(rows_tok, 5, 1))
    counter("pi_notional_cost_usd", ("project", "kind", "provider", "model", "type"), _sum_by(rows_cost, 5, 1))

    # tools
    rows = [(r[0], "true" if r[1] == "nested" else "false", r[2], r[3]) for r in con.execute(
        "SELECT name, kind, status, COUNT(*) FROM calls WHERE kind IN ('tool','nested') AND dup=0"
        " GROUP BY name, kind, status")]
    counter("pi_tool_calls", ("tool", "nested", "outcome"), _sum_by(rows, 3, 1))

    cum = ", ".join(f"SUM(dur_ms <= {int(b * 1000)})" for b in TOOL_BOUNDS)
    thist = _hist([(r[0], "true" if r[1] == "nested" else "false", *r[2:]) for r in con.execute(
        f"SELECT name, kind, SUM(dur_ms IS NOT NULL), SUM(dur_ms), {cum} FROM calls"
        " WHERE kind IN ('tool','nested') AND dup=0 AND dur_ms IS NOT NULL GROUP BY name, kind")], TOOL_BOUNDS)
    metrics.append({"name": "pi_tool_call_duration_seconds", "type": "histogram", "bounds": TOOL_BOUNDS,
                    "points": [({"tool": k[0], "nested": k[1]}, v) for k, v in sorted(thist.items())]})
    cum = ", ".join(f"SUM(dur_ms <= {int(b * 1000)})" for b in LLM_BOUNDS)
    lhist = _hist([tuple(r) for r in con.execute(
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


def post(url, payload, timeout=30):
    body = gzip.compress(json.dumps(payload, separators=(",", ":")).encode())
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Content-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "replace")
        if resp.status != 200:
            raise RuntimeError(f"collector answered HTTP {resp.status}")
    try:
        rejected = ((json.loads(text) or {}).get("partialSuccess") or {}).get("rejectedDataPoints")
    except ValueError:
        rejected = None
    if rejected and int(rejected) > 0:
        raise RuntimeError(f"collector rejected {rejected} data points")
    return len(body)


def series_count(metrics):
    return sum(len(m["points"]) for m in metrics)


def export(con, db_path, status, url=None, now=None):
    """Collect, then push to the collector when a URL is given. Returns (families, series, bytes_sent)."""
    metrics = collect(con) + self_metrics(con, status, db_path)
    now_ns = int((now or time.time()) * 1e9)
    start_ns = int(status.get("epoch_ns") or now_ns)
    sent = 0
    if url:
        sent = post(url, otlp_payload(metrics, start_ns, now_ns))
    return metrics, sent


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
        log(f"build: database problem ({type(exc).__name__}); setting it aside and rebuilding from the session files")
        quarantine(db)
        return ae.build(sessions_dir, db)


def run_once(sessions_dir, db):
    """One tick: incremental build, then export. Never raises; returns the exit code."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("skipped: a previous run is still going")
            return 0
        return _tick(sessions_dir, db)


def _tick(sessions_dir, db):
    status = load_status()
    status.setdefault("epoch_ns", int(time.time() * 1e9))
    status["last_attempt_ts"] = time.time()
    code = 0
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
        status["consecutive_build_failures"] = status.get("consecutive_build_failures", 0) + 1
        status["last_build_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        log(f"build failed ({status['consecutive_build_failures']} in a row): {status['last_build_error']}")
        log(traceback.format_exc(limit=3).strip().splitlines()[-1])
        if status["consecutive_build_failures"] >= 3 and Path(db).exists():
            log("build: three failures in a row; setting the database aside so the next run rebuilds it")
            quarantine(db)
            status["consecutive_build_failures"] = 0
    url = endpoint()
    if url and Path(db).exists():
        try:
            con = ae.connect(db, readonly=True)
            try:
                metrics, sent = export(con, db, status, url)
            finally:
                con.close()
            status.update(last_export_ok_ts=time.time(), last_export_error=None,
                          last_export_series=series_count(metrics), last_export_bytes=sent)
        except Exception as exc:  # noqa: BLE001
            code = code or 1
            message = f"{type(exc).__name__}: {str(exc)[:200]}"
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
