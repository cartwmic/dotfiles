#!/usr/bin/env python3
"""Scriptable stdio MCP server used by the pi-mcp-lazy tests (stdlib only)."""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--marker", default="")
ap.add_argument("--toolset", default="a")
ap.add_argument("--grandchild", action="store_true")
ap.add_argument("--crash-file", default="")
ap.add_argument("--noise", action="store_true")
ap.add_argument("--escaped-helper", action="store_true", help="start a SIGTERM-ignoring helper in its own session; the server itself exits on SIGTERM")
ap.add_argument("--ignore-term", action="store_true", help="ignore SIGTERM (server and grandchild), so only SIGKILL stops them")
ap.add_argument("--resources", action="store_true")
ap.add_argument("--start-delay", type=float, default=0)
ap.add_argument("--name", default="fake")
ap.add_argument("--ping-every", type=float, default=0, help="send server-originated pings and log notifications this often")
a = ap.parse_args()

os.makedirs(a.dir, exist_ok=True)
if a.crash_file and os.path.exists(a.crash_file):
    sys.stderr.write("fake_server boom: cannot start (crash file present)\n")
    sys.stderr.flush()
    sys.exit(3)
if a.noise:
    for i in range(30):
        sys.stderr.write("fake_server noise line %d\n" % i)
    sys.stderr.flush()
if a.ignore_term:
    import signal
    def _term(signum, frame):  # note it (a test waits for this), then ignore it
        open(os.path.join(a.dir, "term.seen"), "w").write("1")
    signal.signal(signal.SIGTERM, _term)
if a.escaped_helper:
    import signal
    def _exit_on_term(signum, frame):
        open(os.path.join(a.dir, "term.seen"), "w").write("1")
        os._exit(0)
    signal.signal(signal.SIGTERM, _exit_on_term)
    h = subprocess.Popen([sys.executable, "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(300)", a.marker + "-helper"],
                         start_new_session=True)
    open(os.path.join(a.dir, "helper.pid"), "w").write(str(h.pid))
time.sleep(a.start_delay)
open(os.path.join(a.dir, "server.pid"), "w").write(str(os.getpid()))
with open(os.path.join(a.dir, "events.log"), "a") as f:
    f.write("start %d\n" % os.getpid())
if a.grandchild:
    code = ("import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);" if a.ignore_term else "import time;") + "time.sleep(300)"
    g = subprocess.Popen([sys.executable, "-c", code, a.marker + "-grandchild"])
    open(os.path.join(a.dir, "grandchild.pid"), "w").write(str(g.pid))

def _chatter():
    n = 0
    while True:
        time.sleep(a.ping_every)
        n += 1
        send({"jsonrpc": "2.0", "id": "srv-ping-%d" % n, "method": "ping"})
        send({"jsonrpc": "2.0", "method": "notifications/message", "params": {"level": "info", "data": "keep-alive %d" % n}})


TOOLS = {"a": ["echo", "slow", "roots"], "b": ["echo", "slow", "roots", "extra"]}[a.toolset]
out_lock = threading.Lock()
waiting = {}


def send(obj):
    with out_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def tool_def(n):
    return {"name": n, "description": "fake %s" % n, "inputSchema": {"type": "object", "properties": {}}}


def handle(msg):
    m, rid, p = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if m == "initialize":
        caps = {"tools": {"listChanged": True}}
        if a.resources:
            caps["resources"] = {}
        send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": p.get("protocolVersion", "2025-11-25"),
              "capabilities": caps, "serverInfo": {"name": a.name, "version": "1.0"}, "instructions": "fake server"}})
    elif m == "tools/list":
        send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [tool_def(n) for n in TOOLS]}})
    elif m == "ping":
        send({"jsonrpc": "2.0", "id": rid, "result": {}})
    elif m == "resources/read":
        send({"jsonrpc": "2.0", "id": rid, "result": {"contents": [{"uri": p.get("uri"), "text": "resource-text"}]}})
    elif m == "tools/call":
        n, args = p.get("name"), p.get("arguments") or {}
        if n == "echo":
            text = "echo:" + str(args.get("text", ""))
        elif n == "slow":
            time.sleep(float(args.get("seconds", 1)))
            if args.get("noreply"):
                return  # does the work, then never answers (a cancelled call on a server such as rea)
            text = "slow-done"
        elif n == "hang":
            # does the work, then never answers (like a server that drops the reply of a cancelled call)
            time.sleep(float(args.get("seconds", 0.2)))
            return
        elif n == "roots":
            ev = threading.Event()
            waiting["srv-1"] = [ev, None]
            send({"jsonrpc": "2.0", "id": "srv-1", "method": "roots/list"})
            ev.wait(10)
            text = "roots:" + json.dumps((waiting["srv-1"][1] or {}).get("roots"))
        else:
            return send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "unknown tool " + str(n)}})
        send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": text}]}})
    elif rid is not None:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}})


if a.ping_every:
    threading.Thread(target=_chatter, daemon=True).start()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "method" not in msg and str(msg.get("id", "")).startswith("srv-ping-"):
        continue
    if "method" not in msg and msg.get("id") in waiting:
        waiting[msg["id"]][1] = msg.get("result")
        waiting[msg["id"]][0].set()
        continue
    if "method" in msg and "id" not in msg:
        continue
    threading.Thread(target=handle, args=(msg,), daemon=True).start()
