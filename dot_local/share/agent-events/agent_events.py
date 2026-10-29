#!/usr/bin/env python3
"""agent-events: read-only, metadata-only tables over Pi session files.

Builds a rebuildable SQLite database (sessions, turns, calls, events) from Pi
session JSONL. It never writes to the session store, makes no network calls,
and stores no message text, tool arguments/results or error text: only ids,
timestamps, durations, token counts, notional cost, names and rule-derived
event kinds. Cost is notional (API-equivalent price table), never a bill.
"""
import argparse
import datetime as dt
import errno
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

SCHEMA_VERSION = 4  # 4: owner wait, active and tool time are nested-aware (a wait inside codemode is owner wait)
CONTENT_POLICY = "no prompts, assistant text, tool args/results or error text are stored"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
  depth INTEGER NOT NULL, started_at_ms INTEGER);
CREATE TABLE IF NOT EXISTS sessions (
  path TEXT PRIMARY KEY, session_id TEXT, kind TEXT NOT NULL, cwd TEXT,
  parent_session_id TEXT, child_id TEXT, run_index INTEGER,
  started_at_ms INTEGER, ended_at_ms INTEGER, wall_ms INTEGER,
  timing_quality TEXT, timing_complete INTEGER, calls_timed INTEGER, calls_untimed INTEGER,
  active_ms INTEGER, llm_ms INTEGER, tool_ms INTEGER, owner_wait_ms INTEGER,
  unaccounted_ms INTEGER,
  user_msgs INTEGER, turns INTEGER, llm_calls INTEGER, tool_calls INTEGER,
  nested_calls INTEGER, llm_errors INTEGER, llm_aborts INTEGER, tool_errors INTEGER,
  input_tokens INTEGER, fresh_input_tokens INTEGER, cache_read_tokens INTEGER,
  cache_write_tokens INTEGER, output_tokens INTEGER,
  notional_cost_usd REAL, overhead_cost_usd REAL, inherited_cost_usd REAL,
  models TEXT);
CREATE TABLE IF NOT EXISTS turns (
  path TEXT NOT NULL, turn_idx INTEGER NOT NULL, user_key TEXT, inherited INTEGER DEFAULT 0,
  started_at_ms INTEGER, ended_at_ms INTEGER, wall_ms INTEGER, idle_after_ms INTEGER, timing_complete INTEGER, prompt_ms INTEGER,
  active_ms INTEGER, llm_ms INTEGER, explore_ms INTEGER, edit_ms INTEGER, run_ms INTEGER,
  delegate_ms INTEGER, owner_ms INTEGER, other_ms INTEGER,
  llm_calls INTEGER, tool_calls INTEGER, errors INTEGER,
  input_tokens INTEGER, output_tokens INTEGER, notional_cost_usd REAL,
  last_stop_reason TEXT, PRIMARY KEY (path, turn_idx));
CREATE TABLE IF NOT EXISTS calls (
  path TEXT NOT NULL, seq INTEGER NOT NULL, entry_id TEXT, kind TEXT NOT NULL,
  name TEXT, phase TEXT, turn_idx INTEGER, start_ms INTEGER, end_ms INTEGER,
  dur_ms INTEGER, timing_source TEXT, status TEXT, call_id TEXT, parent_call_id TEXT,
  provider TEXT, model TEXT, thinking TEXT, ttfc_ms INTEGER,
  input_tokens INTEGER, fresh_input_tokens INTEGER, cache_read_tokens INTEGER,
  cache_write_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
  dedupe_key TEXT, dup INTEGER DEFAULT 0, PRIMARY KEY (path, seq));
CREATE INDEX IF NOT EXISTS calls_key ON calls(dedupe_key);
CREATE TABLE IF NOT EXISTS events (
  path TEXT NOT NULL, seq INTEGER NOT NULL, ts_ms INTEGER, turn_idx INTEGER,
  kind TEXT NOT NULL, severity TEXT, attrs TEXT, call_seq INTEGER, dup INTEGER DEFAULT 0,
  dedupe_key TEXT, PRIMARY KEY (path, seq));
CREATE VIEW IF NOT EXISTS family AS
  SELECT p.path, p.session_id, p.started_at_ms, p.notional_cost_usd AS own_cost_usd,
         COALESCE(SUM(c.notional_cost_usd),0) AS children_cost_usd,
         p.notional_cost_usd + COALESCE(SUM(c.notional_cost_usd),0) AS family_cost_usd,
         COUNT(c.path) AS child_runs
  FROM sessions p LEFT JOIN sessions c
    ON c.kind='child' AND c.parent_session_id = p.session_id
  WHERE p.kind='top' GROUP BY p.path;
"""

EXPLORE = {"read", "grep", "find", "ls", "web_search", "web_fetch", "session_search",
           "session_read", "session_list", "find_roots", "observe_ui", "expand_ui",
           "search_ui", "inspect_ui", "read_text", "_Read"}
EDIT = {"edit", "write"}
RUN = {"bash", "codemode", "mcpScript", "typesafe_evaluate", "launch_browser",
       "navigate_browser", "evaluate_browser", "wait_for"}
DELEGATE = {"subagent", "subagent_supervisor", "subagent_wait", "_subagent_wait",
            "subagents_enable", "intercom", "contact_supervisor"}
OWNER = {"ask_user_question", "_ask_user_question", "notify_owner"}
PHASES = ("llm", "explore", "edit", "run", "delegate", "owner", "other")

ERROR_BUCKETS = (
    ("rate_limit", r"rate limit|429|quota|overloaded|529"),
    ("timeout", r"timeout|timed out|idle"),
    ("abort", r"abort"),
    ("context", r"context|too long|prompt is too long|token"),
    ("auth", r"401|403|auth|credential"),
    ("network", r"econn|network|fetch failed|socket|503|502|500"),
    ("empty", r"empty"),
)
SLEEP_RE = re.compile(r"^\s*sleep\s+(\d+(?:\.\d+)?)\b")
MINIMAL_REPLY_TOKENS = 12


def phase_of(tool):
    if tool in EXPLORE:
        return "explore"
    if tool in EDIT:
        return "edit"
    if tool in RUN:
        return "run"
    if tool in DELEGATE:
        return "delegate"
    if tool in OWNER:
        return "owner"
    return "other"


SAFE_NAME = re.compile(r"[A-Za-z0-9_.:/@+\-]{1,80}")
STATUS_WORDS = {
    "ok": ("ok", "success", "succeeded", "completed", "complete"),
    "error": ("error", "failed", "failure"),
    "aborted": ("aborted", "abort", "cancelled", "canceled"),
    "timeout": ("timeout", "timed_out", "timedout"),
    "unfinished": ("unfinished", "running", "pending"),
}


def safe_name(value):
    """Names come from the file; anything that is not a plain identifier becomes 'unknown'."""
    return value if isinstance(value, str) and SAFE_NAME.fullmatch(value) else "unknown"


_PROJECT_BASES = None
_GIT_ROOTS = None


def _project_bases():
    home = str(Path.home())
    return ("/Volumes/Workshop/macbook/git/", "/Volumes/Workshop/macbook/", f"{home}/git/", "/private/tmp/",
            "/tmp/", f"{home}/.local/share/", f"{home}/Documents/", f"{home}/")


def _git_roots():
    """Names of the repositories on this machine (a .git directory, so worktrees do not count)."""
    global _GIT_ROOTS
    if _GIT_ROOTS is None:
        roots = {"chezmoi", "loop-engine"}
        env = os.environ.get("AGENT_EVENTS_PROJECT_ROOTS")
        dirs = env.split(":") if env is not None else [str(Path.home() / "git"), "/Volumes/Workshop/macbook/git"]
        for d in filter(None, dirs):
            try:
                roots.update(p.name.lower() for p in Path(d).iterdir() if (p / ".git").is_dir())
            except OSError:
                pass
        _GIT_ROOTS = roots
    return _GIT_ROOTS


def project_of(cwd):
    """Low-cardinality workstream slug from a working directory: the repository, not the worktree or run dir."""
    global _PROJECT_BASES
    if not isinstance(cwd, str) or not cwd:
        return "unknown"
    path = cwd.rstrip("/")
    if path == str(Path.home()):
        return "home"
    if _PROJECT_BASES is None:
        _PROJECT_BASES = _project_bases()
    name = path.rsplit("/", 1)[-1]
    for base in _PROJECT_BASES:
        if path == base.rstrip("/") and base != f"{Path.home()}/":
            return "scratch" if "tmp" in base else "workspace"
        if path.startswith(base) and path != base.rstrip("/"):
            name = path[len(base):].split("/")[0]
            break
    name = name.lower().lstrip("_")
    if name == "dotfiles" or name.startswith("dotfiles-wt"):
        return "chezmoi"
    best = max((r for r in _git_roots() | _extra_slugs() if name == r or name.startswith(r + "-")), key=len, default=None)
    if best:
        return best
    token = re.split(r"[-.]", name, maxsplit=1)[0]
    return token if re.fullmatch(r"[a-z][a-z0-9]{0,30}", token) else "other"


_EXPORT_SLUGS = {"home", "workspace", "scratch", "unknown", "other"}
_SLUG_RE = re.compile(r"[a-z][a-z0-9-]{0,40}")


def _extra_slugs():
    return {s for s in (os.environ.get("AGENT_EVENTS_PROJECTS") or "").split(":") if _SLUG_RE.fullmatch(s)}


def approved_projects():
    return {r for r in _git_roots() if _SLUG_RE.fullmatch(r)} | _extra_slugs()


def export_project(cwd):
    """The only project names that leave the machine: repositories found on this machine (plus extras from
    AGENT_EVENTS_PROJECTS) and a few fixed buckets. Any other directory is 'other', so a scratch or temp
    directory name can never become a label."""
    slug = project_of(cwd)
    return slug if slug in approved_projects() or slug in _EXPORT_SLUGS else "other"


def norm_status(value):
    """Fixed vocabulary only: arbitrary status text is never stored."""
    s = value.lower() if isinstance(value, str) else ""
    for name, words in STATUS_WORDS.items():
        if s in words:
            return name
    return "unknown"


def error_bucket(text):
    s = (text or "").lower()
    for name, pattern in ERROR_BUCKETS:
        if re.search(pattern, s):
            return name
    return "other"


def iso_ms(value):
    try:
        return int(dt.datetime.fromisoformat(value).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def as_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def union_ms(intervals):
    total, cur_s, cur_e = 0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def classify_path(root, path):
    """Return (kind, depth, parent_session_id, child_id, run_index) or None to skip.

    subagent-artifacts/*.jsonl are copies of child-run history and are skipped.
    """
    parts = path.relative_to(root).parts
    if len(parts) == 2 and parts[1].endswith(".jsonl"):
        return "top", 1, None, None, None
    if len(parts) == 5 and parts[4] == "session.jsonl" and re.fullmatch(r"run-\d+", parts[3]):
        return "child", 2, parts[1].rsplit("_", 1)[-1], parts[2], int(parts[3][4:])
    return None


def default_sessions_dir():
    return Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi/agent") / "sessions"


def default_db():
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "agent-events" / "events.sqlite"


# ---------------------------------------------------------------- parsing

class Parsed:
    def __init__(self):
        self.header = {}
        self.calls = []
        self.turns = {}
        self.events = []
        self.last_ts = None
        self.malformed = 0


def parse_session(path):
    """One pass over a session file; keeps only metadata and discards content."""
    out = Parsed()
    turn = 0
    stamps_llm, stamps_tool = {}, {}
    consecutive_err = 0
    minimal_streak = 0
    last_model_change = None
    seen_thinking = False
    with open(path, "rb") as fh:
        for raw in fh:
            try:
                entry = json.loads(raw)
            except ValueError:
                out.malformed += 1
                continue
            if not isinstance(entry, dict):
                continue
            etype = entry.get("type")
            ts_entry = iso_ms(entry.get("timestamp"))
            if ts_entry is not None:
                out.last_ts = max(out.last_ts or 0, ts_entry)
            eid = entry.get("id") if isinstance(entry.get("id"), str) else None
            if etype == "session":
                out.header = {"id": entry.get("id"), "cwd": entry.get("cwd"), "ts": ts_entry}
            elif etype == "custom" and entry.get("customType") == "pi-stamp":
                d = entry.get("data") if isinstance(entry.get("data"), dict) else {}
                if d.get("kind") == "tool" and isinstance(d.get("toolCallId"), str):
                    stamps_tool[d["toolCallId"]] = d
                elif d.get("role") == "assistant" and as_int(d.get("timestamp")) is not None:
                    stamps_llm[d["timestamp"]] = d
            elif etype == "message" and isinstance(entry.get("message"), dict):
                m = entry["message"]
                role = m.get("role")
                if role == "user":
                    turn += 1
                    out.turns[turn] = {"user_key": f"id:{eid}" if eid else None,
                                       "start": as_int(m.get("timestamp")) or ts_entry}
                    consecutive_err = 0
                    minimal_streak = 0
                elif role == "assistant":
                    consecutive_err, minimal_streak = _assistant(
                        out, m, eid, ts_entry, turn, consecutive_err, minimal_streak, path)
                elif role == "toolResult":
                    _tool_result(out, m, eid, ts_entry, turn)
            elif etype == "usage" and entry.get("kind") == "cache_warm":
                _overhead(out, entry, eid, ts_entry, turn, "cache_warm")
            elif etype == "compaction":
                _overhead(out, entry, eid, ts_entry, turn, "compaction")
                out.events.append({"ts": ts_entry, "turn": turn, "kind": "context.compaction",
                                   "severity": "info", "key": f"id:{eid}" if eid else None,
                                   "attrs": {"tokens_before": as_int(entry.get("tokensBefore")),
                                             "from_hook": bool(entry.get("fromHook"))}})
            elif etype == "model_change":
                to = f"{safe_name(entry.get('provider'))}/{safe_name(entry.get('modelId'))}"
                if last_model_change is not None:  # the first entry is the initial selection, not a switch
                    out.events.append({"ts": ts_entry, "turn": turn, "kind": "model.switch",
                                       "severity": "info", "key": f"id:{eid}" if eid else None,
                                       "attrs": {"from": last_model_change, "to": to}})
                last_model_change = to
            elif etype == "thinking_level_change":
                level = entry.get("thinkingLevel")
                if seen_thinking:  # the first entry is the initial level, not a change
                    out.events.append({"ts": ts_entry, "turn": turn, "kind": "thinking.change",
                                       "severity": "info", "key": f"id:{eid}" if eid else None,
                                       "attrs": {"level": safe_name(level) if isinstance(level, str) else None}})
                seen_thinking = True
    _resolve_timing(out, stamps_llm, stamps_tool)
    return out


def _usage_fields(u):
    u = u if isinstance(u, dict) else {}
    fresh = as_int(u.get("input")) or 0
    cr = as_int(u.get("cacheRead")) or 0
    cw = as_int(u.get("cacheWrite")) or 0
    cost = u.get("cost")
    total = cost.get("total") if isinstance(cost, dict) else None
    total = float(total) if isinstance(total, (int, float)) and not isinstance(total, bool) else 0.0
    return {"fresh": fresh, "cr": cr, "cw": cw, "out": as_int(u.get("output")) or 0,
            "input": fresh + cr + cw, "cost": total}


def _key(eid, path, ts, tokens):
    return f"id:{eid}" if eid else f"fallback:{path}:{ts}:{tokens}"


def _assistant(out, m, eid, ts_entry, turn, consec, minimal, path):
    ts = as_int(m.get("timestamp")) or ts_entry
    u = _usage_fields(m.get("usage"))
    stop = m.get("stopReason") if isinstance(m.get("stopReason"), str) else None
    content = m.get("content") if isinstance(m.get("content"), list) else []
    has_tool_call = any(isinstance(c, dict) and c.get("type") == "toolCall" for c in content)
    status = {"error": "error", "aborted": "aborted", "length": "length"}.get(stop, "ok")
    call = {"kind": "llm", "entry_id": eid, "name": safe_name(m.get("model")), "phase": "llm", "turn": turn,
            "ts": ts, "dur": as_int(m.get("durationMs")), "status": status,
            "provider": safe_name(m.get("provider")), "model": safe_name(m.get("model")),
            "thinking": safe_name(m.get("thinkingLevel")) if isinstance(m.get("thinkingLevel"), str) else None,
            "usage": u, "key": _key(eid, path, ts, u["input"] + u["out"])}
    out.calls.append(call)
    base = {"ts": ts, "turn": turn, "key": call["key"], "call": len(out.calls) - 1}
    if stop == "error":
        consec += 1
        # only the bucket survives; the error text itself is discarded
        out.events.append({**base, "kind": "llm.error", "severity": "warn",
                           "attrs": {"bucket": error_bucket(m.get("errorMessage")), "model": call["model"]}})
        if consec >= 2:
            out.events.append({**base, "kind": "llm.retry_loop", "severity": "warn", "attrs": {"streak": consec}})
    else:
        consec = 0
    if stop == "aborted":
        out.events.append({**base, "kind": "llm.aborted", "severity": "info", "attrs": {}})
    if stop == "length":
        out.events.append({**base, "kind": "llm.length_cutoff", "severity": "warn", "attrs": {}})
    if stop == "stop" and not has_tool_call and u["out"] <= MINIMAL_REPLY_TOKENS:
        minimal += 1
        out.events.append({**base, "kind": "reply.minimal", "severity": "info",
                           "attrs": {"output_tokens": u["out"], "streak": minimal}})
    else:
        minimal = 0
    return consec, minimal


def _tool_result(out, m, eid, ts_entry, turn):
    ts_end = as_int(m.get("timestamp")) or ts_entry
    name = safe_name(m.get("toolName"))
    call_id = m.get("toolCallId") if isinstance(m.get("toolCallId"), str) else None
    is_err = bool(m.get("isError"))
    details = m.get("details") if isinstance(m.get("details"), dict) else {}
    call = {"kind": "tool", "entry_id": eid, "name": name, "phase": phase_of(name), "turn": turn,
            "end": ts_end, "dur": as_int(m.get("durationMs")), "status": "error" if is_err else "ok",
            "call_id": call_id, "key": f"id:{eid}" if eid else f"fallback:tool:{call_id}:{ts_end}",
            "nested": []}
    nc = m.get("nestedCalls") if isinstance(m.get("nestedCalls"), dict) else {}
    for n in nc.get("calls") if isinstance(nc.get("calls"), list) else []:
        if not isinstance(n, dict):
            continue
        args = n.get("arguments") if isinstance(n.get("arguments"), dict) else {}
        cmd = args.get("command") if isinstance(args.get("command"), str) else ""
        sleep = SLEEP_RE.match(cmd) if n.get("name") == "bash" else None
        call["nested"].append({
            "id": n.get("id") if isinstance(n.get("id"), str) else None,
            "name": safe_name(n.get("name")),
            "dur": as_int(n.get("durationMs")),
            "status": norm_status(n.get("status")),
            "sleep_s": float(sleep.group(1)) if sleep else None})
        # the command text is discarded here; only the sleep length survives
    out.calls.append(call)
    base = {"ts": ts_end, "turn": turn, "key": call["key"], "call": len(out.calls) - 1}
    if is_err:
        out.events.append({**base, "kind": "tool.error", "severity": "warn", "attrs": {"tool": name}})
    if phase_of(name) == "owner":
        out.events.append({**base, "kind": "owner.asked", "severity": "info",
                           "attrs": {"tool": name, "cancelled": bool(details.get("cancelled")),
                                     "wait_ms": call["dur"]}})
    for n in call["nested"]:
        if n["sleep_s"] is not None:
            out.events.append({**base, "key": f"{call['key']}/{n['id']}", "kind": "tool.sleep_poll", "severity": "info",
                               "attrs": {"sleep_s": n["sleep_s"], "dur_ms": n["dur"]}})


def _overhead(out, entry, eid, ts_entry, turn, name):
    u = _usage_fields(entry.get("usage"))
    key = f"id:{eid}" if eid else f"fallback:{name}:{ts_entry}:{u['input'] + u['out']}"
    out.calls.append({"kind": "overhead", "entry_id": eid, "name": name, "phase": "other",
                      "turn": turn, "ts": ts_entry, "dur": None, "status": "ok",
                      "provider": safe_name(entry.get("provider")), "model": safe_name(entry.get("model")),
                      "usage": u, "key": key})
    if name == "cache_warm":
        out.events.append({"ts": ts_entry, "turn": turn, "kind": "spend.cache_warm",
                           "severity": "info", "key": key, "call": len(out.calls) - 1,
                           "attrs": {"notional_cost_usd": u["cost"]}})


def _resolve_timing(out, stamps_llm, stamps_tool):
    for c in out.calls:
        c.setdefault("start", None)
        c.setdefault("end", None)
        c["source"] = None
        if c["kind"] == "llm":
            st = stamps_llm.get(c["ts"])
            c["start"] = c["ts"]
            if st and as_int(st.get("completedAt")) is not None:
                c["end"] = st["completedAt"]
                c["dur"] = c["end"] - c["start"]
                fc = as_int(st.get("firstContentAt"))
                c["ttfc"] = fc - c["start"] if fc is not None else None
                c["source"] = "stamp"
            elif c["dur"] is not None:
                c["end"] = c["start"] + c["dur"]
                c["source"] = "duration"
        elif c["kind"] == "tool":
            st = stamps_tool.get(c.get("call_id"))
            if st and as_int(st.get("startedAt")) is not None and as_int(st.get("completedAt")) is not None:
                c["start"], c["end"] = st["startedAt"], st["completedAt"]
                c["dur"] = c["end"] - c["start"]
                c["source"] = "stamp"
                outcome = norm_status(st.get("outcome"))
                if c["status"] == "ok" and outcome not in ("ok", "unknown"):
                    c["status"] = outcome
            elif c["dur"] is not None and c["end"] is not None:
                c["start"] = c["end"] - c["dur"]
                c["source"] = "duration"
        else:
            c["start"] = c.get("ts")


# ---------------------------------------------------------------- storage

SCHEMA_STATEMENTS = [s.strip() for s in SCHEMA.split(";\n") if s.strip()]


def _init_schema(con):
    """Create the schema, discarding derived data from another version, in one transaction.

    DDL is transactional in SQLite, so an interruption leaves either the old database or the new one.
    """
    previous = con.isolation_level
    con.isolation_level = None  # explicit BEGIN/COMMIT; executescript would commit early
    con.execute("BEGIN IMMEDIATE")
    try:
        old = None
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone():
            row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            old = row[0] if row else "unversioned"  # meta exists but no version row: an interrupted init
        elif con.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') LIMIT 1").fetchone():
            old = "unversioned"
        if old is not None and old != str(SCHEMA_VERSION):
            for name, kind in con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view')").fetchall():
                con.execute(f"DROP {kind.upper()} IF EXISTS {name}")
        for statement in SCHEMA_STATEMENTS:
            con.execute(statement)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.isolation_level = previous


def connect(db_path, readonly=False):
    db_path = Path(db_path)
    if readonly:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db_path)
        _init_schema(con)
    con.row_factory = sqlite3.Row
    con.create_function("project", 1, project_of, deterministic=True)
    return con


def _delete_file(con, path):
    for table_name in ("calls", "turns", "events", "sessions", "files"):
        con.execute(f"DELETE FROM {table_name} WHERE path = ?", (path,))


def _insert(con, path, info, parsed, size, mtime_ns):
    kind, depth, parent, child_id, run_index = info
    p = str(path)
    started = parsed.header.get("ts") or (parsed.turns.get(1) or {}).get("start")
    con.execute("INSERT INTO files VALUES (?,?,?,?,?)", (p, size, mtime_ns, depth, started))
    timed = [c for c in parsed.calls if c["kind"] in ("llm", "tool")]
    n_timed = sum(1 for c in timed if c["source"])
    sources = {c["source"] for c in timed if c["source"]}
    quality = "stamped" if "stamp" in sources else ("duration" if sources else "none")
    con.execute("INSERT INTO sessions (path, session_id, kind, cwd, parent_session_id, child_id, run_index,"
                " started_at_ms, ended_at_ms, timing_quality, calls_timed, calls_untimed)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (p, parsed.header.get("id"), kind, parsed.header.get("cwd"), parent, child_id, run_index,
                 started, parsed.last_ts, quality, n_timed, len(timed) - n_timed))
    for idx, t in sorted(parsed.turns.items()):
        con.execute("INSERT INTO turns (path, turn_idx, user_key, started_at_ms, prompt_ms) VALUES (?,?,?,?,?)",
                    (p, idx, t["user_key"], t["start"], t["start"]))
    seq_of, seq = {}, 0
    for i, c in enumerate(parsed.calls):
        seq_of[i] = seq
        u = c.get("usage")
        con.execute(
            "INSERT INTO calls (path, seq, entry_id, kind, name, phase, turn_idx, start_ms, end_ms, dur_ms,"
            " timing_source, status, call_id, provider, model, thinking, ttfc_ms, input_tokens,"
            " fresh_input_tokens, cache_read_tokens, cache_write_tokens, output_tokens, cost_usd, dedupe_key)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p, seq, c["entry_id"], c["kind"], c["name"], c["phase"], c["turn"], c["start"], c["end"],
             c["dur"], c["source"], c["status"], c.get("call_id"), c.get("provider"), c.get("model"),
             c.get("thinking"), c.get("ttfc"),
             u["input"] if u else None, u["fresh"] if u else None, u["cr"] if u else None,
             u["cw"] if u else None, u["out"] if u else None, u["cost"] if u else None, c["key"]))
        seq += 1
        for n in c.get("nested", ()):
            con.execute(
                "INSERT INTO calls (path, seq, entry_id, kind, name, phase, turn_idx, dur_ms, timing_source,"
                " status, call_id, parent_call_id, dedupe_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p, seq, c["entry_id"], "nested", n["name"], phase_of(n["name"]), c["turn"], n["dur"],
                 "nested" if n["dur"] is not None else None, n["status"], n["id"], c.get("call_id"),
                 f"n:{c['key']}/{n['id']}"))
            seq += 1
    eseq = 0
    for e in parsed.events:
        con.execute("INSERT INTO events (path, seq, ts_ms, turn_idx, kind, severity, attrs, call_seq, dedupe_key)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (p, eseq, e["ts"], e["turn"], e["kind"], e["severity"],
                     json.dumps(e["attrs"], sort_keys=True), seq_of.get(e.get("call")),
                     f"e:{e['kind']}:{e['key']}" if e.get("key") else None))
        eseq += 1
    if run_index:
        con.execute("INSERT INTO events (path, seq, ts_ms, turn_idx, kind, severity, attrs)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (p, eseq, started, 0, "subagent.retry", "warn", json.dumps({"run_index": run_index})))


def build(sessions_dir, db_path, since_ms=None, progress=None):
    sessions_dir = Path(sessions_dir)
    con = connect(db_path)
    known = {r["path"]: (r["size"], r["mtime_ns"]) for r in con.execute("SELECT path, size, mtime_ns FROM files")}
    dirty = (con.execute("SELECT value FROM meta WHERE key='dirty'").fetchone() or ("0",))[0] == "1"
    seen, parsed_n, skipped, malformed = set(), 0, 0, 0
    changed = set()
    candidates = sorted(sessions_dir.glob("*/**/*.jsonl")) if sessions_dir.is_dir() else []
    for path in candidates:
        info = classify_path(sessions_dir, path)
        if info is None:
            continue
        try:
            st = path.stat()
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENOTDIR):
                raise
            continue
        if since_ms is not None and st.st_mtime * 1000 < since_ms:
            continue
        seen.add(str(path))
        if known.get(str(path)) == (st.st_size, st.st_mtime_ns):
            skipped += 1
            continue
        try:
            parsed = parse_session(path)
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENOTDIR):
                raise  # permission or I/O trouble is a failed build, never a silent removal
            seen.discard(str(path))  # it vanished between listing and reading; the next build sees the new state
            continue
        malformed += parsed.malformed
        with con:
            _delete_file(con, str(path))
            _insert(con, path, info, parsed, st.st_size, st.st_mtime_ns)
            con.execute("INSERT OR REPLACE INTO meta VALUES ('dirty', '1')")  # same transaction as the ingest
        changed.add(str(path))
        parsed_n += 1
        if progress and parsed_n % 200 == 0:
            progress(f"parsed {parsed_n} files")
    removed = 0
    if since_ms is None:
        for gone in set(known) - seen:
            with con:
                _delete_file(con, gone)
                con.execute("INSERT OR REPLACE INTO meta VALUES ('dirty', '1')")
            removed += 1
    if parsed_n or removed or dirty:
        with con:  # cleared only if finalize succeeds; a crash leaves the marker for the next build
            finalize(con, None if dirty else changed)
            con.execute("INSERT OR REPLACE INTO meta VALUES ('dirty', '0')")
    n_sessions = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    con.close()
    return {"parsed": parsed_n, "unchanged": skipped, "removed": removed, "refinalized": bool(dirty and not parsed_n and not removed),
            "malformed_lines": malformed, "sessions": n_sessions}


def _duplicate_set(con, select_sql):
    """Rows whose key was already claimed by an earlier row in the select's order."""
    seen, dups = set(), set()
    for r in con.execute(select_sql):
        if r[2] in seen:
            dups.add((r[0], r[1]))
        else:
            seen.add(r[2])
    return dups


def _apply_flag(con, table, column, key_col, new, old_sql):
    """Write only the flag changes; return the paths whose flags moved."""
    old = {(r[0], r[1]) for r in con.execute(old_sql)}
    for path, k in new - old:
        con.execute(f"UPDATE {table} SET {column} = 1 WHERE path = ? AND {key_col} = ?", (path, k))
    for path, k in old - new:
        con.execute(f"UPDATE {table} SET {column} = 0 WHERE path = ? AND {key_col} = ?", (path, k))
    return {path for path, _ in new ^ old}


def finalize(con, changed_paths=None):
    """Cross-file dedupe, then rebuild rollups for every session whose inputs moved.

    An entry copied into another file (fork, copied child history) is counted once:
    the shallowest, earliest file owns it, matching pi-token-usage's entry-id rule.
    changed_paths=None (an interrupted earlier build) rolls up every session.
    """
    moved = set()
    moved |= _apply_flag(
        con, "calls", "dup", "seq",
        _duplicate_set(con, "SELECT c.path, c.seq, c.dedupe_key FROM calls c JOIN files f ON f.path = c.path"
                            " ORDER BY f.depth, f.started_at_ms, c.path, c.seq"),
        "SELECT path, seq FROM calls WHERE dup = 1")
    moved |= _apply_flag(
        con, "events", "dup", "seq",
        _duplicate_set(con, "SELECT e.path, e.seq, e.dedupe_key FROM events e JOIN files f ON f.path = e.path"
                            " WHERE e.dedupe_key IS NOT NULL ORDER BY f.depth, f.started_at_ms, e.path, e.seq"),
        "SELECT path, seq FROM events WHERE dup = 1")
    moved |= _apply_flag(
        con, "turns", "inherited", "turn_idx",
        _duplicate_set(con, "SELECT t.path, t.turn_idx, t.user_key FROM turns t JOIN files f ON f.path = t.path"
                            " WHERE t.user_key IS NOT NULL ORDER BY f.depth, f.started_at_ms, t.path, t.turn_idx"),
        "SELECT path, turn_idx FROM turns WHERE inherited = 1")
    if changed_paths is None:
        todo = [r[0] for r in con.execute("SELECT path FROM sessions")]
    else:
        todo = sorted((moved | set(changed_paths)) & {r[0] for r in con.execute("SELECT path FROM sessions")})
    for path in todo:
        _rollup_session(con, path)
    return len(todo)


def _call_phase_ms(call, nested):
    """Inclusive phase milliseconds for one tool call -> (known_parts, unknown_phases).

    A call with nested calls (a codemode script) reports each nested call's own duration under
    its phase, unscaled: nested calls can run in parallel, so these may sum to more than the
    wrapper. "other" is a lower bound on wrapper time no nested call accounts for; it is unknown
    when the wrapper or any nested call has no duration. A nested call without a duration makes
    its own phase unknown, whatever the wrapper's duration.
    """
    dur = call["dur_ms"]
    if not nested:
        return ({call["phase"]: dur}, set()) if dur is not None else ({}, {call["phase"]})
    parts, unknown = {}, set()
    for n in nested:
        if n["dur_ms"] is None:
            unknown.add(n["phase"])
        else:
            parts[n["phase"]] = parts.get(n["phase"], 0) + n["dur_ms"]
    if dur is None or unknown:
        unknown.add("other")
    else:
        rest = dur - sum(parts.values())
        if rest > 0:
            parts["other"] = parts.get("other", 0) + rest
    return parts, unknown


def _agg(cs, nested_by_parent):
    llm = [c for c in cs if c["kind"] == "llm"]
    tools = [c for c in cs if c["kind"] == "tool"]
    phase = {p: 0 for p in PHASES}
    unknown = set()       # phases with an unknown contribution, nested ones included
    top_unknown = set()   # phases of top-level calls with no recorded duration
    nested_owner = 0      # owner time inside codemode scripts: nested calls have a duration but no timestamps
    nested_owner_in_span = 0  # the part of it that sits inside a wrapper with a known interval
    nested_owner_unknown = False
    tool_own = 0          # top-level tool time minus the owner time nested inside it
    for c in llm:
        if c["dur_ms"] is None:
            unknown.add("llm")
            top_unknown.add("llm")
        else:
            phase["llm"] += c["dur_ms"]
    for c in tools:
        parts, unk = _call_phase_ms(c, nested_by_parent.get(c["call_id"], []))
        unknown |= unk
        if c["dur_ms"] is None:
            top_unknown.add(c["phase"])
        for ph, ms in parts.items():
            phase[ph] += ms
        w = 0
        for n in nested_by_parent.get(c["call_id"], []):
            if n["phase"] == "owner":
                if n["dur_ms"] is None:
                    nested_owner_unknown = True
                else:
                    w += n["dur_ms"]
        nested_owner += w
        if c["phase"] != "owner" and c["dur_ms"] is not None:
            tool_own += max(0, c["dur_ms"] - w)
        if w and c["phase"] != "owner" and c["start_ms"] is not None and c["end_ms"] is not None:
            nested_owner_in_span += min(w, c["end_ms"] - c["start_ms"])
    spans = [c for c in llm + tools if c["start_ms"] is not None and c["end_ms"] is not None]
    iv_active = [(c["start_ms"], c["end_ms"]) for c in spans if c["phase"] != "owner"]
    iv_owner = [(c["start_ms"], c["end_ms"]) for c in spans if c["phase"] == "owner"]
    return {
        "complete": not unknown and not top_unknown,
        "top_complete": not top_unknown,
        "phase": {p: (None if p in unknown else v) for p, v in phase.items()},
        # A wait inside codemode sits inside the wrapper's span, so it is taken out of active and tool time and
        # added to owner wait. Nested calls have no timestamps, so this subtracts a duration, not an interval.
        "active": (max(0, union_ms(iv_active) - nested_owner_in_span)
                   if not ((top_unknown - {"owner"}) or nested_owner_unknown) else None),
        "owner": ((union_ms(iv_owner) + nested_owner)
                  if ("owner" not in top_unknown and not nested_owner_unknown) else None),
        "tool_ms": None if ((top_unknown - {"owner", "llm"}) or nested_owner_unknown) else tool_own,
        "llm_calls": len(llm), "tool_calls": len(tools),
        "errors": sum(1 for c in llm + tools if c["status"] == "error"),
        "input": sum(c["input_tokens"] or 0 for c in llm),
        "output": sum(c["output_tokens"] or 0 for c in llm),
        "cost": sum(c["cost_usd"] or 0.0 for c in llm),
        "ends": [c["end_ms"] for c in cs if c["end_ms"] is not None],
        "starts": [c["start_ms"] for c in llm + tools if c["start_ms"] is not None],
        "intervals": [(c["start_ms"], c["end_ms"]) for c in spans],
        "stop": llm[-1]["status"] if llm else None,
    }


def _rollup_session(con, path):
    calls = [dict(r) for r in con.execute("SELECT * FROM calls WHERE path = ? AND dup = 0 ORDER BY seq", (path,))]
    nested_by_parent = {}
    for c in calls:
        if c["kind"] == "nested":
            nested_by_parent.setdefault(c["parent_call_id"], []).append(c)
    ses = con.execute("SELECT * FROM sessions WHERE path = ?", (path,)).fetchone()
    turns = [dict(r) for r in con.execute("SELECT * FROM turns WHERE path = ? ORDER BY turn_idx", (path,))]
    by_turn = {}
    for c in calls:
        by_turn.setdefault(c["turn_idx"], []).append(c)
    # A turn whose user entry was copied from another file keeps its own non-duplicate work;
    # only a turn with nothing of its own left is blanked.
    live, aggs = [], {}
    for t in turns:
        own = by_turn.get(t["turn_idx"], [])
        if t["inherited"] and not any(c["kind"] in ("llm", "tool") for c in own):
            con.execute("UPDATE turns SET ended_at_ms=NULL, wall_ms=NULL, idle_after_ms=NULL, timing_complete=NULL,"
                        " active_ms=NULL, llm_ms=NULL, explore_ms=NULL, edit_ms=NULL, run_ms=NULL,"
                        " delegate_ms=NULL, owner_ms=NULL, other_ms=NULL, llm_calls=0, tool_calls=0, errors=0,"
                        " input_tokens=0, output_tokens=0, notional_cost_usd=0, last_stop_reason=NULL"
                        " WHERE path=? AND turn_idx=?", (path, t["turn_idx"]))
            continue
        a = _agg(own, nested_by_parent)
        start = t["prompt_ms"]  # as ingested; started_at_ms is the derived effective start
        if t["inherited"]:  # the prompt happened earlier, elsewhere; time starts at this file's own work
            start = min(a["starts"], default=None)
        aggs[t["turn_idx"]] = (t, a, start)
        live.append((t["turn_idx"], start))
    for idx, (t, a, start) in aggs.items():
        end = None
        if a["top_complete"] and (a["ends"] or start is not None):
            end = max(a["ends"] + ([start] if start is not None else []))
        later = [s for i, s in live if i > idx and s is not None]
        idle = (later[0] - end) if (later and end is not None and later[0] >= end) else None
        ph = [a["phase"][p] for p in PHASES]
        con.execute(
            "UPDATE turns SET started_at_ms=?, ended_at_ms=?, wall_ms=?, idle_after_ms=?, timing_complete=?,"
            " active_ms=?, llm_ms=?, explore_ms=?, edit_ms=?, run_ms=?, delegate_ms=?, owner_ms=?, other_ms=?,"
            " llm_calls=?, tool_calls=?, errors=?, input_tokens=?, output_tokens=?, notional_cost_usd=?,"
            " last_stop_reason=? WHERE path=? AND turn_idx=?",
            (start, end, (end - start) if (end is not None and start is not None) else None, idle,
             1 if a["complete"] else 0, a["active"], *ph, a["llm_calls"], a["tool_calls"], a["errors"],
             a["input"], a["output"], a["cost"], a["stop"], path, t["turn_idx"]))

    whole = _agg(calls, nested_by_parent)
    started = ses["started_at_ms"]
    ended = max([e for e in [ses["ended_at_ms"]] + whole["ends"] if e is not None], default=None)
    wall = (ended - started) if (ended is not None and started is not None) else None
    covered = union_ms(whole["intervals"]) if whole["top_complete"] else None
    unaccounted = max(0, wall - covered) if (wall is not None and covered is not None) else None
    cost_rows = con.execute(
        "SELECT kind, dup, SUM(cost_usd) cost, SUM(input_tokens) i, SUM(fresh_input_tokens) f,"
        " SUM(cache_read_tokens) cr, SUM(cache_write_tokens) cw, SUM(output_tokens) o FROM calls"
        " WHERE path=? AND kind IN ('llm','overhead') GROUP BY kind, dup", (path,)).fetchall()
    own_row = next((r for r in cost_rows if r["kind"] == "llm" and r["dup"] == 0), None)
    inherited = sum((r["cost"] or 0.0) for r in cost_rows if r["dup"] == 1)
    overhead = sum((r["cost"] or 0.0) for r in cost_rows if r["kind"] == "overhead" and r["dup"] == 0)
    models = sorted({c["model"] for c in calls if c["kind"] == "llm" and c["model"]})

    def val(key):
        return (own_row[key] if own_row else 0) or 0

    con.execute(
        "UPDATE sessions SET ended_at_ms=?, wall_ms=?, timing_complete=?, active_ms=?, llm_ms=?, tool_ms=?,"
        " owner_wait_ms=?, unaccounted_ms=?, user_msgs=?, turns=?, llm_calls=?, tool_calls=?, nested_calls=?,"
        " llm_errors=?, llm_aborts=?, tool_errors=?, input_tokens=?, fresh_input_tokens=?, cache_read_tokens=?,"
        " cache_write_tokens=?, output_tokens=?, notional_cost_usd=?, overhead_cost_usd=?,"
        " inherited_cost_usd=?, models=? WHERE path=?",
        (ended, wall, 1 if whole["complete"] else 0, whole["active"], whole["phase"]["llm"], whole["tool_ms"],
         whole["owner"], unaccounted, len(live), len(live), whole["llm_calls"], whole["tool_calls"],
         sum(1 for c in calls if c["kind"] == "nested"),
         sum(1 for c in calls if c["kind"] == "llm" and c["status"] == "error"),
         sum(1 for c in calls if c["kind"] == "llm" and c["status"] == "aborted"),
         sum(1 for c in calls if c["kind"] == "tool" and c["status"] == "error"),
         val("i"), val("f"), val("cr"), val("cw"), val("o"), val("cost"), overhead, inherited,
         ",".join(models), path))


# ---------------------------------------------------------------- reporting

def fmt_ms(v):
    if v is None:
        return "unknown"
    s = v / 1000
    if s < 90:
        return f"{s:.1f}s"
    if s < 5400:
        return f"{s / 60:.1f}m"
    return f"{s / 3600:.1f}h"


def fmt_cost(v):
    return "n/a" if v is None else f"{v:.2f}"


def fmt_ts(ms):
    if ms is None:
        return "unknown"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def table(rows, headers):
    cells = [[str(c) for c in r] for r in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths))]
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths)) for r in cells]
    return "\n".join(lines)


def pct(values, q):
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(q * len(v)))]


def parse_since(text):
    if not text:
        return None
    m = re.fullmatch(r"(\d+)([dh])", text)
    if m:
        delta = dt.timedelta(**{"days" if m.group(2) == "d" else "hours": int(m.group(1))})
        return int((dt.datetime.now(dt.timezone.utc) - delta).timestamp() * 1000)
    try:
        d = dt.datetime.fromisoformat(text)
    except ValueError:
        raise SystemExit(f"--since must look like 7d, 12h or 2026-10-01 (got {text!r})")
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000)


NOTIONAL_NOTE = "notional$ = API-equivalent price-table cost from Pi's usage records; it is not a bill."


def cmd_sessions(con, args):
    since = parse_since(args.since)
    order = {"cost": "notional_cost_usd", "wall": "wall_ms", "active": "active_ms",
             "recent": "started_at_ms"}[args.sort]
    where, params = ["1=1"], []
    if since is not None:
        where.append("started_at_ms >= ?")
        params.append(since)
    if not args.children:
        where.append("kind = 'top'")
    rows = con.execute(
        f"SELECT * FROM sessions WHERE {' AND '.join(where)} ORDER BY {order} DESC LIMIT ?",
        (*params, args.limit)).fetchall()
    body = table([(Path(r["path"]).name[:34], r["kind"], fmt_ts(r["started_at_ms"]), fmt_ms(r["wall_ms"]),
                   fmt_ms(r["active_ms"]), fmt_ms(r["owner_wait_ms"]), r["turns"], r["llm_calls"], r["tool_calls"],
                   fmt_cost(r["notional_cost_usd"]), r["timing_quality"]) for r in rows],
                 ["session", "kind", "started", "wall", "active", "owner-wait", "turns", "llm", "tools",
                  "notional$", "timing"])
    return body + "\n" + NOTIONAL_NOTE + " 'unknown' = no timing recorded."


def _find_session(con, ref):
    rows = con.execute("SELECT * FROM sessions WHERE path = ? OR path LIKE ? OR session_id LIKE ?"
                       " ORDER BY started_at_ms DESC", (ref, f"%{ref}%", f"{ref}%")).fetchall()
    if not rows:
        raise SystemExit(f"no session matches {ref!r}")
    if len(rows) > 1:
        tops = [r for r in rows if r["kind"] == "top"]
        if len(tops) == 1:
            return tops[0]
        names = "\n".join(f"  {Path(r['path']).name}" for r in rows[:10])
        raise SystemExit(f"{ref!r} matches {len(rows)} sessions; be more specific:\n{names}")
    return rows[0]


def _tool_table(con, where, params, limit):
    rows = con.execute(f"SELECT c.kind, c.name, c.dur_ms, c.status FROM calls c {where}"
                       " AND c.kind IN ('tool','nested')", params).fetchall()
    stats = {}
    for r in rows:
        d = stats.setdefault((r["kind"], r["name"]), {"n": 0, "err": 0, "durs": []})
        d["n"] += 1
        d["err"] += 1 if r["status"] == "error" else 0
        if r["dur_ms"] is not None:
            d["durs"].append(r["dur_ms"])
    ordered = sorted(stats.items(), key=lambda kv: -sum(kv[1]["durs"]))[:limit]
    return table([(("nested:" if k[0] == "nested" else "") + k[1], d["n"], d["err"],
                   fmt_ms(sum(d["durs"])) if d["durs"] else "unknown", fmt_ms(pct(d["durs"], 0.5)),
                   fmt_ms(pct(d["durs"], 0.95)), fmt_ms(max(d["durs"]) if d["durs"] else None))
                  for k, d in ordered], ["tool", "n", "errors", "total", "p50", "p95", "max"])


def cmd_session(con, args):
    s = _find_session(con, args.ref)
    p = s["path"]
    kind = s["kind"] + (f" (child {s['child_id']}, run {s['run_index']})" if s["kind"] == "child" else "")
    o = [f"session   {Path(p).name}", f"kind      {kind}", f"cwd       {s['cwd']}",
         f"started   {fmt_ts(s['started_at_ms'])}   wall {fmt_ms(s['wall_ms'])}",
         f"timing    {s['timing_quality']}, {'complete' if s['timing_complete'] else 'partial: totals with an untimed call are unknown'}"
         f"   ({s['calls_timed']} calls timed, {s['calls_untimed']} untimed)",
         f"time      active {fmt_ms(s['active_ms'])} | llm {fmt_ms(s['llm_ms'])} (inclusive) | "
         f"tools {fmt_ms(s['tool_ms'])} (inclusive) | owner-wait {fmt_ms(s['owner_wait_ms'])} | "
         f"unaccounted {fmt_ms(s['unaccounted_ms'])}",
         f"counts    {s['turns']} turns, {s['llm_calls']} llm calls, {s['tool_calls']} tool calls "
         f"({s['nested_calls']} nested), {s['llm_errors']} llm errors, {s['llm_aborts']} aborts, "
         f"{s['tool_errors']} tool errors",
         f"tokens    input {s['input_tokens']} (fresh {s['fresh_input_tokens']}, cache-read "
         f"{s['cache_read_tokens']}, cache-write {s['cache_write_tokens']}) | output {s['output_tokens']}",
         f"cost      notional USD {fmt_cost(s['notional_cost_usd'])} (+ {fmt_cost(s['overhead_cost_usd'])} overhead; "
         f"{fmt_cost(s['inherited_cost_usd'])} inherited from other files and not counted) [notional, not a bill]",
         f"models    {s['models']}"]
    fam = con.execute("SELECT * FROM family WHERE path = ?", (p,)).fetchone()
    if fam and fam["child_runs"]:
        o.append(f"family    {fam['child_runs']} child runs, notional USD {fmt_cost(fam['children_cost_usd'])} in "
                 f"children, {fmt_cost(fam['family_cost_usd'])} total")
    turns = con.execute("SELECT * FROM turns WHERE path=? ORDER BY turn_idx", (p,)).fetchall()
    o.append("\nturns (phase times are inclusive; parallel work can exceed wall)")
    o.append(table([(t["turn_idx"], "inherited" if t["inherited"] else fmt_ts(t["started_at_ms"]),
                     fmt_ms(t["wall_ms"]), fmt_ms(t["active_ms"]), fmt_ms(t["llm_ms"]), fmt_ms(t["explore_ms"]),
                     fmt_ms(t["edit_ms"]), fmt_ms(t["run_ms"]), fmt_ms(t["delegate_ms"]), fmt_ms(t["owner_ms"]),
                     fmt_ms(t["other_ms"]), "-" if t["idle_after_ms"] is None else fmt_ms(t["idle_after_ms"]), t["llm_calls"], t["tool_calls"],
                     fmt_cost(t["notional_cost_usd"])) for t in turns[: args.max_turns]],
                   ["#", "started", "wall", "active", "llm", "explore", "edit", "run", "delegate", "owner",
                    "other", "idle-after", "llm#", "tool#", "notional$"]))
    if len(turns) > args.max_turns:
        o.append(f"... {len(turns) - args.max_turns} more turns (use --max-turns)")
    o.append("\ntools (durations where known; nested = calls inside codemode)")
    o.append(_tool_table(con, "WHERE c.path = ? AND c.dup = 0", (p,), 12))
    top = con.execute("SELECT kind, name, dur_ms, status FROM calls WHERE path=? AND dup=0 AND dur_ms IS NOT NULL"
                      " AND kind IN ('llm','tool','nested') AND NOT (kind='tool' AND name='codemode')"
                      " ORDER BY dur_ms DESC LIMIT 6", (p,)).fetchall()
    o.append("\nlongest operations (codemode wrappers excluded; their nested calls are listed)")
    o.append(table([(r["kind"], r["name"], fmt_ms(r["dur_ms"]), r["status"]) for r in top],
                   ["kind", "name", "dur", "status"]))
    ev = con.execute("SELECT kind, COUNT(*) n FROM events WHERE path=? AND dup=0 GROUP BY kind ORDER BY n DESC",
                     (p,)).fetchall()
    o.append("\nevents: " + (", ".join(f"{r['kind']} x{r['n']}" for r in ev) or "none"))
    kids = con.execute("SELECT * FROM sessions WHERE kind='child' AND parent_session_id=? ORDER BY started_at_ms",
                       (s["session_id"],)).fetchall() if s["kind"] == "top" and s["session_id"] else []
    if kids:
        o.append("\nchild runs")
        o.append(table([((k["child_id"] or "")[:8], f"run-{k['run_index']}", fmt_ts(k["started_at_ms"]),
                         fmt_ms(k["wall_ms"]), k["llm_calls"], fmt_cost(k["notional_cost_usd"]), k["models"])
                        for k in kids[:20]], ["child", "run", "started", "wall", "llm#", "notional$", "models"]))
    o.append("\n" + NOTIONAL_NOTE + " Metadata only: no message text, tool arguments or results are stored.")
    return "\n".join(o)


def cmd_tools(con, args):
    since = parse_since(args.since)
    where, params = "WHERE c.dup = 0", ()
    if since is not None:
        where += " AND c.path IN (SELECT path FROM sessions WHERE started_at_ms >= ?)"
        params = (since,)
    return _tool_table(con, where, params, args.limit) + "\n(durations only where timing was recorded)"


def cmd_projects(con, args):
    since = parse_since(args.since)
    # attribute cost to when the call happened, not when its session started: sessions run for days
    where, params = ["c.dup = 0", "c.kind IN ('llm','overhead')"], []
    if since is not None:
        where.append("COALESCE(c.end_ms, c.start_ms) >= ?")
        params.append(since)
    rows = con.execute(f"SELECT s.cwd, s.kind, COUNT(DISTINCT s.path) n, SUM(c.cost_usd) cost,"
                       f" SUM(c.kind='llm') calls, SUM(c.status='error') errs FROM calls c JOIN sessions s USING (path)"
                       f" WHERE {' AND '.join(where)} GROUP BY s.cwd, s.kind", params).fetchall()
    agg = {}
    for r in rows:
        a = agg.setdefault(project_of(r["cwd"]), [0, 0.0, 0, 0, 0.0])
        a[0] += r["n"]
        a[1] += r["cost"] or 0
        a[2] += r["calls"] or 0
        a[3] += r["errs"] or 0
        a[4] += (r["cost"] or 0) if r["kind"] == "child" else 0
    ordered = sorted(agg.items(), key=lambda kv: -kv[1][1])[:args.limit]
    note = "notional$ = API-equivalent price-table cost by when each call happened; it is not a bill. 'subagents' is the part spent by subagent runs."
    return table([(k, v[0], v[2], v[3], fmt_cost(v[1]), fmt_cost(v[4])) for k, v in ordered],
                 ["project", "sessions", "llm calls", "errors", "notional$", "subagents"]) + "\n" + note


def cmd_events(con, args):
    since = parse_since(args.since)
    where, params = ["e.dup = 0"], []
    if since is not None:
        where.append("e.ts_ms >= ?")
        params.append(since)
    if args.kind:
        where.append("e.kind = ?")
        params.append(args.kind)
    if args.list:
        rows = con.execute(f"SELECT e.ts_ms, e.kind, e.attrs, s.path, s.session_id, s.cwd, e.turn_idx FROM events e"
                           f" JOIN sessions s USING (path) WHERE {' AND '.join(where)} ORDER BY e.ts_ms DESC LIMIT ?",
                           params + [args.limit]).fetchall()
        return table([(fmt_ts(r["ts_ms"]), r["kind"], project_of(r["cwd"]), (r["session_id"] or "")[:13],
                       r["turn_idx"], r["attrs"]) for r in rows],
                     ["time", "event", "project", "session", "turn", "attrs"]) + (
            "\nread the content locally: agent-events show <session> --turn N | --errors")
    rows = con.execute(f"SELECT e.kind, COUNT(*) n, COUNT(DISTINCT e.path) s FROM events e"
                       f" WHERE {' AND '.join(where)} GROUP BY e.kind ORDER BY n DESC", params).fetchall()
    return table([(r["kind"], r["n"], r["s"]) for r in rows], ["event", "count", "sessions"])


_ALLOWED_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE, sqlite3.SQLITE_FUNCTION}


def _read_only_authorizer(action, *_):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def cmd_sql(con, args):
    # mode=ro protects only the main file: ATTACH and VACUUM INTO can still create files, so the
    # statement must be a plain SELECT/WITH and every operation is checked by an allow-list.
    if not re.match(r"\s*(select|with)\b", args.query, re.IGNORECASE):
        raise sqlite3.DatabaseError("only SELECT or WITH queries are allowed")
    con.set_authorizer(_read_only_authorizer)
    cur = con.execute(args.query)
    rows = cur.fetchall()
    head = [d[0] for d in cur.description or []]
    return "\n".join(["\t".join(head)] + ["\t".join("" if v is None else str(v) for v in r) for r in rows])


def export_cmd(metrics, con, db, args):
    status = metrics.load_status()
    families, _ = metrics.export(con, db, status)  # never sends: the scheduled 'run' is the only sender
    rows = [(m["name"], m["type"], len(m["points"])) for m in families]
    where = metrics.endpoint() or "no endpoint set (AGENT_EVENTS_OTLP_ENDPOINT); this machine does not send"
    return "what the next scheduled run would send (nothing is sent by this command)\n" + table(rows, ["metric", "type", "series"]) + \
        f"\n{metrics.series_count(families)} series. Aggregates only: counts, seconds, tokens, notional cost; " + \
        f"labels are project, kind, provider, model, tool, outcome. The pi_cache_* gauges also carry the session id " + \
        f"(UUIDs only) of sessions active in the last 30 minutes.\nendpoint: {where}" + \
        f"\nmachine: {metrics.machine() or 'not set (AGENT_EVENTS_MACHINE); the scheduled run refuses to send'}"


def make_parser():
    ap = argparse.ArgumentParser(prog="agent-events", description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=None, help="database path (default: $XDG_DATA_HOME/agent-events/events.sqlite)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="read Pi session files and (re)build the tables")
    b.add_argument("--sessions-dir", default=None)
    b.add_argument("--since", default=None, help="only files modified since 7d / 12h / 2026-10-01")
    s = sub.add_parser("sessions", help="one row per session")
    s.add_argument("--since")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--sort", choices=["cost", "wall", "active", "recent"], default="recent")
    s.add_argument("--children", action="store_true", help="include subagent child runs")
    one = sub.add_parser("session", help="breakdown of one session (path fragment or session id prefix)")
    one.add_argument("ref")
    one.add_argument("--max-turns", type=int, default=30)
    t = sub.add_parser("tools", help="tool call counts and latency")
    t.add_argument("--since")
    t.add_argument("--limit", type=int, default=15)
    e = sub.add_parser("events", help="rule-derived event counts")
    e.add_argument("--since")
    e.add_argument("--kind", help="only this event kind, e.g. llm.error")
    e.add_argument("--list", action="store_true", help="list individual events instead of counting")
    e.add_argument("--limit", type=int, default=30)
    pr = sub.add_parser("projects", help="spend and errors per project (workstream)")
    pr.add_argument("--since", default="1d")
    pr.add_argument("--limit", type=int, default=25)
    sh = sub.add_parser("show", help="print the content of a turn, a call or the error calls, from the session file")
    sh.add_argument("ref")
    sh.add_argument("--turn", type=int, help="the Nth user prompt and everything up to the next one")
    sh.add_argument("--call", type=int, help="a call by its seq number (see: session, sql)")
    sh.add_argument("--chars", type=int, default=400)
    sub.add_parser("run", help="one always-on tick: incremental build, then export when an endpoint is configured")
    ex = sub.add_parser("export", help="show what the scheduled 'run' would send (series per metric); sends nothing")
    ex.add_argument("--dry-run", action="store_true", help="accepted for compatibility; export never sends")
    st = sub.add_parser("status", help="age of the last successful build and export; exit 1 when stale")
    st.add_argument("--max-age", type=int, default=900, help="seconds")
    q = sub.add_parser("sql", help="read-only SQL against the database")
    q.add_argument("query")
    return ap


def main(argv=None):
    args = make_parser().parse_args(argv)
    db = Path(args.db) if args.db else default_db()
    if args.cmd == "build":
        started = time.time()
        sessions_dir = Path(args.sessions_dir) if args.sessions_dir else default_sessions_dir()
        import agent_events_metrics as metrics
        with metrics.build_lock():  # waits for a running scheduled build instead of racing it
            res = build(sessions_dir, db, since_ms=parse_since(args.since), progress=lambda m: print(m, file=sys.stderr))
        print(f"built {db}: {res['parsed']} parsed, {res['unchanged']} unchanged, {res['removed']} removed, "
              f"{res['sessions']} sessions, {res['malformed_lines']} malformed lines skipped "
              f"in {time.time() - started:.1f}s")
        print(f"read-only over {sessions_dir}; {CONTENT_POLICY}.")
        return 0
    if args.cmd == "run":
        import agent_events_metrics as metrics
        return metrics.run_once(default_sessions_dir(), db)
    if args.cmd == "status":
        import agent_events_metrics as metrics
        text, code = metrics.cmd_status(args.max_age)
        print(text)
        return code
    if not db.exists():
        print(f"no database at {db}; run 'agent-events build' first", file=sys.stderr)
        return 2
    con = connect(db, readonly=True)
    if args.cmd == "show":
        import agent_events_show as drill
        handlers = {"show": drill.cmd_show}
    elif args.cmd == "export":
        import agent_events_metrics as metrics
        handlers = {"export": lambda c, a: export_cmd(metrics, c, db, a)}
    else:
        handlers = {"sessions": cmd_sessions, "session": cmd_session, "tools": cmd_tools,
                    "events": cmd_events, "projects": cmd_projects, "sql": cmd_sql}
    handler = handlers[args.cmd]
    try:
        print(handler(con, args))
    except sqlite3.Error as exc:
        print(f"sql error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
