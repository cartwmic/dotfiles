"""agent-events show: read the content of one session, locally and on demand.

The database holds no content. This command goes back to the original Pi session file (read-only)
and prints the entries for a turn, a call or the error calls. Nothing it prints is stored or exported.
"""
import json
import time
from pathlib import Path

import agent_events as ae

NOTICE = "LOCAL CONTENT from the session file; it is not stored in events.sqlite and is never exported."


def _clip(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + f"... [+{len(text) - limit} chars]"


def _blocks(content, limit):
    if isinstance(content, str):
        return [_clip(content, limit)]
    parts = []
    for b in content if isinstance(content, list) else []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            parts.append(_clip(b.get("text", ""), limit))
        elif t == "toolCall":
            parts.append(f"-> {b.get('name')}({_clip(json.dumps(b.get('arguments'), default=str), limit)})")
        elif t == "thinking":
            parts.append("[thinking omitted]")
        elif t == "image":
            parts.append("[image]")
    return parts


def render(entry, limit):
    stamp = (entry.get("timestamp") or "")[11:19]
    m = entry.get("message") if isinstance(entry.get("message"), dict) else None
    if entry.get("type") == "compaction":
        return f"{stamp} compaction ({entry.get('tokensBefore')} tokens before)"
    if not m:
        return None
    role = m.get("role")
    if role == "user":
        return f"{stamp} USER: {' '.join(_blocks(m.get('content'), limit))}"
    if role == "assistant":
        tag = f"ASSISTANT ({m.get('model')}, {m.get('stopReason')})"
        body = " | ".join(_blocks(m.get("content"), limit))
        err = f"  ERROR: {_clip(m['errorMessage'], limit)}" if m.get("errorMessage") else ""
        return f"{stamp} {tag}: {body}{err}"
    if role == "toolResult":
        flag = " ERROR" if m.get("isError") else ""
        return f"{stamp} RESULT {m.get('toolName')}{flag}: {' '.join(_blocks(m.get('content'), limit))}"
    return None


def _entries(path):
    with open(path, "rb") as fh:
        for raw in fh:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if isinstance(e, dict):
                yield e


def cmd_show(con, args):
    s = ae._find_session(con, args.ref)
    path, limit = s["path"], args.chars
    if not Path(path).exists():
        raise SystemExit("the session file no longer exists; only its metadata is in the database")
    lines = [NOTICE, f"session {s['session_id']} ({s['kind']}) cwd={ae.project_of(s['cwd'])}", ""]
    if args.turn is not None:
        n, on = 0, False
        for e in _entries(path):
            m = e.get("message") if isinstance(e.get("message"), dict) else {}
            if m.get("role") == "user":
                n += 1
                on = n == args.turn
            if on and (text := render(e, limit)):
                lines.append(text)
        if len(lines) == 3:
            raise SystemExit(f"turn {args.turn} not found")
    elif args.call is not None:
        row = con.execute("SELECT entry_id FROM calls WHERE path=? AND seq=?", (path, args.call)).fetchone()
        if not row or not row["entry_id"]:
            raise SystemExit(f"no call {args.call} in that session")
        wanted = row["entry_id"]
        for e in _entries(path):
            if e.get("id") == wanted and (text := render(e, limit)):
                lines.append(text)
    else:
        ids = [r["entry_id"] for r in con.execute(
            "SELECT entry_id FROM calls WHERE path=? AND status='error' AND entry_id IS NOT NULL ORDER BY seq", (path,))]
        wanted = set(ids)
        for e in _entries(path):
            if e.get("id") in wanted and (text := render(e, limit)):
                lines.append(text)
        if len(lines) == 3:
            lines.append("no error calls in this session")
    return "\n".join(lines)
