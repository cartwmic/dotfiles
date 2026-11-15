#!/usr/bin/env python3
"""Pick up what Kelsey sent from her shartifacts page and file it in the board's New box.

    kelsey_intake.py [--dry-run]

Her page (dot_local/share/kelsey-intake/page.html, a shartifacts html artifact) stores each submission as a document in its own
database: submissions/<id> = {text, ask, status, created}. Status is new, picked_up or answered. This script, run every 15 minutes
by kelsey-intake.timer, reads the documents with status new over the shartifacts /mcp endpoint (the artifact_db tool, no sign-in
on this network), files each as a BD line in the board (`board add BD --tag agent`, note names the submission), then sets the
document to picked_up with the board ref. Answering stays with the normal agent workflow: whoever answers sets status answered
and writes the answer into the document's `answer` field.

A submission whose line is already on the board (found by its id in the note) is not added again, so a run that failed between
the two steps finishes on the next tick. Log lines go to stdout (the journal): one line per action, each with the submission id.
Environment: KELSEY_PAGE_ID, SHARTIFACTS_URL, BOARD_DIR, BOARD_CLI, KELSEY_NODE. Python 3 standard library only.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
PAGE_ID = os.environ.get("KELSEY_PAGE_ID", "474a4545350b9e099b354152")
URL = os.environ.get("SHARTIFACTS_URL", "https://shartifacts.internal.cartwmic.com").rstrip("/")
BOARD_DIR = os.environ.get("BOARD_DIR", str(HOME / ".local/share/board"))
BOARD_CLI = os.environ.get("BOARD_CLI", str(HOME / ".local/share/agent-kit/node_modules/@cartwmic/agent-kit/dist/board/cli.js"))
NODE = os.environ.get("KELSEY_NODE") or str(HOME / ".local/share/mise/shims/node")


def log(sid, message):
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} [kelsey_intake] {sid or '-'} {message}", flush=True)


def tool(name, arguments):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}).encode()
    request = urllib.request.Request(
        f"{URL}/mcp", data=body, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "X-Origin": "personal"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        answer = json.load(response)
    if "error" in answer or answer["result"].get("isError"):
        raise RuntimeError(f"{name}: {json.dumps(answer.get('error') or answer['result'])[:300]}")
    return answer["result"].get("structuredContent") or {}


def board(*args):
    cmd = [NODE, BOARD_CLI, args[0], "--dir", BOARD_DIR, *args[1:]]
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"board {args[0]} exit {result.returncode}: {(result.stderr or result.stdout).strip()[:300]}")
    return result.stdout


def clean(text):
    """One line with no ' | ': a board note cannot hold a line break or the field separator."""
    return " ".join(str(text or "").split()).replace(" | ", " / ")


def note_for(sid, doc):
    parts = [f"from Kelsey via her shartifacts page, submission {sid}: {clean(doc.get('text'))}"]
    if clean(doc.get("ask")):
        parts.append(f"she wants to know: {clean(doc['ask'])}")
    parts.append(f"to answer, set status answered and answer on submissions/{sid} of page {PAGE_ID} (dot_local/share/kelsey-intake/README.md)")
    return "; ".join(parts)


def title_for(doc):
    text = clean(doc.get("text"))
    return "Kelsey: " + (text if len(text) <= 80 else text[:79] + "…")


def board_ref_for(sid):
    for item in json.loads(board("show", "--json") or "[]"):
        if f"submission {sid}:" in (item.get("note") or ""):
            return item["ref"]
    return None


def pick_up(sid, doc, dry):
    ref = board_ref_for(sid)
    if ref:
        log(sid, f"already on the board as {ref}; marking picked up")
    elif dry:
        log(sid, f"dry run: would add {title_for(doc)!r}")
        return
    else:
        out = board("add", "BD", "--title", title_for(doc), "--note", note_for(sid, doc), "--tag", "agent", "--event", f"kelsey-intake-{sid}")
        ref = out.split("add:", 1)[1].split("(")[0].strip() if "add:" in out else out.strip()
        log(sid, f"filed on the board as {ref} ({out.strip()})")
    if not dry:
        tool("artifact_db", {"id": PAGE_ID, "op": "update", "path": f"submissions/{sid}",
                             "data": {"status": "picked_up", "picked_up_at": int(time.time() * 1000), "board_ref": ref}})
        log(sid, "marked picked_up on the page")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true")
    dry = parser.parse_args().dry_run
    docs = tool("artifact_db", {"id": PAGE_ID, "op": "query", "collection": "submissions", "where": [["status", "==", "new"]], "order_by": "created"}).get("docs", [])
    log(None, f"{len(docs)} new submission(s)")
    failed = 0
    for doc in docs:
        try:
            pick_up(doc["id"], doc["data"], dry)
        except Exception as error:
            failed += 1
            log(doc["id"], f"ERROR: {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
