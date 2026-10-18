#!/usr/bin/env python3
"""Black-box proof of the lazy MCP stand-in through a real Pi session (RPC mode) with a scripted model.

Every scenario renders the Pi MCP entries with the real apply script (apply_harness_config.sh pi), starts a
real Pi in a throwaway HOME, and drives it with scripted codemode tool calls: discovery without starting a
server (four copy states), first use and its timing, idle stop and restart, a long call across the idle
period, start failure and retry, /mcp and 'pi mcp list' with six servers, a remote HTTP server, and process
cleanup on exit. Nothing from the owner's configuration, credentials or sessions is read or written.

Run from the dotfiles root:  python3 tests/pi-mcp-lazy/proof.py [--evidence DIR] [--idle SECONDS]
Exit status 0 only if every check passed; a check that cannot run is a failure.
"""
import argparse
import http.server
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from harness import FAKE, STANDIN, procs, wait_until  # noqa: E402

APPLY = ROOT / "dot_local" / "user_scripts" / "executable_apply_harness_config.sh"
TIMEOUT = 90
CODES = {}
RESULTS = []


# ----------------------------------------------------------------------------- scripted model
class Model(http.server.BaseHTTPRequestHandler):
    errors = []

    def log_message(self, *_a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            messages = body["messages"]
            idx = max(i for i, m in enumerate(messages) if m["role"] == "user")
            user = messages[idx]["content"]
            if isinstance(user, list):
                user = "".join(p.get("text", "") for p in user)
            results = [m for m in messages[idx + 1:] if m["role"] == "tool"]
            if not results:
                delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "proof-call", "type": "function",
                         "function": {"name": "codemode", "arguments": json.dumps({"code": CODES[user.strip()]})}}]}
                reason = "tool_calls"
            else:
                parts = []
                for r in results:
                    c = r["content"]
                    parts.append(c if isinstance(c, str) else "".join(p.get("text", "") for p in c))
                delta, reason = {"role": "assistant", "content": "OUT:" + "\n".join(parts)[:20000]}, "stop"
        except Exception as e:  # report through the answer so the check fails visibly
            self.errors.append(repr(e))
            delta, reason = {"role": "assistant", "content": "OUT:PROOF-MODEL-ERROR " + repr(e)}, "stop"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        common = {"id": "scripted", "object": "chat.completion.chunk", "created": 1, "model": "proof-model"}
        for chunk in ({**common, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {**common, "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}):
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


# ----------------------------------------------------------------------------- remote HTTP stub
class Remote(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_GET(self):
        self.send_response(405)
        self.end_headers()

    def do_DELETE(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if "id" not in msg:
            self.send_response(202)
            self.end_headers()
            return
        m, p = msg.get("method"), msg.get("params") or {}
        if m == "initialize":
            res = {"protocolVersion": p.get("protocolVersion", "2025-11-25"), "capabilities": {"tools": {}},
                   "serverInfo": {"name": "remote-stub", "version": "1"}}
        elif m == "tools/list":
            res = {"tools": [{"name": "echo", "description": "remote echo", "inputSchema": {"type": "object", "properties": {}}}]}
        elif m == "tools/call":
            res = {"content": [{"type": "text", "text": "remote-echo:" + str((p.get("arguments") or {}).get("text"))}]}
        else:
            res = {}
        data = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": res}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ----------------------------------------------------------------------------- Pi over RPC
class Rpc:
    def __init__(self, cmd, env, cwd):
        self.p = subprocess.Popen(cmd + ["--mode", "rpc"], env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, start_new_session=True)
        self.q, self.events, self.err, self.n = queue.Queue(), [], bytearray(), 0
        threading.Thread(target=self._out, daemon=True).start()
        threading.Thread(target=self._err, daemon=True).start()

    def _out(self):
        for line in self.p.stdout:
            try:
                self.q.put(json.loads(line))
            except ValueError:
                self.q.put({"invalid_output": line.decode(errors="replace")})

    def _err(self):
        for line in self.p.stderr:
            self.err.extend(line)

    def send(self, rec):
        self.p.stdin.write(json.dumps(rec).encode() + b"\n")
        self.p.stdin.flush()

    def until(self, pred, timeout=TIMEOUT):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                rec = self.q.get(timeout=min(1, max(0.01, end - time.monotonic())))
            except queue.Empty:
                if self.p.poll() is not None:
                    raise AssertionError("Pi exited: " + self.err.decode(errors="replace")[-800:])
                continue
            self.events.append(rec)
            if rec.get("type") == "extension_ui_request" and rec.get("method") == "confirm":
                self.send({"type": "extension_ui_response", "id": rec["id"], "confirmed": True})
            if pred(rec):
                return rec
        raise AssertionError("timed out waiting for Pi: " + self.err.decode(errors="replace")[-800:])

    def command(self, kind, **fields):
        self.n += 1
        rid = str(self.n)
        self.send({"id": rid, "type": kind, **fields})
        reply = self.until(lambda r: r.get("type") == "response" and r.get("id") == rid)
        if not reply.get("success"):
            raise AssertionError(str(reply)[:500])
        return reply.get("data", {})

    def start_prompt(self, message):
        d = self.command("prompt", message=message)
        if d.get("disposition") != "started":
            raise AssertionError("prompt did not start: %r" % d)

    def settle(self, timeout=TIMEOUT):
        self.until(lambda r: r.get("type") == "agent_settled", timeout)
        return self.command("get_last_assistant_text")["text"]

    def prompt(self, message, timeout=TIMEOUT):
        self.start_prompt(message)
        return self.settle(timeout)

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(self.p.pid, signal.SIGKILL)
            self.p.wait()
            raise AssertionError("Pi did not shut down cleanly")


# ----------------------------------------------------------------------------- world
def ps_rows():
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,rss=,command="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        p = line.split(None, 3)
        if len(p) >= 3 and all(x.isdigit() for x in p[:3]):
            rows.append((int(p[0]), int(p[1]), int(p[2]), p[3] if len(p) > 3 else ""))
    return rows


def tree(pid):
    rows = ps_rows()
    kids = {}
    for r in rows:
        kids.setdefault(r[1], []).append(r)
    out, stack = [], [pid]
    while stack:
        for r in kids.get(stack.pop(), []):
            out.append(r)
            stack.append(r[0])
    return out


def mcp_side_rss_kb(pi_pid):
    """Resident memory of everything Pi started (stand-ins, real servers, helpers); Pi itself excluded."""
    return sum(r[2] for r in tree(pi_pid))


def pi_rss_kb(pi_pid):
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pi_pid)], capture_output=True, text=True).stdout.strip()
    return int(out) if out else 0


class Fake:
    """One scripted stand-in-fronted server: its own marker, fake-server directory and extra arguments."""

    def __init__(self, tmp, name, *args):
        self.name, self.args = name, list(args)
        self.marker = "pmlproof" + uuid.uuid4().hex[:8]
        self.dir = tmp / ("fake-" + name)

    def cmd(self):
        return [sys.executable, FAKE, "--dir", str(self.dir), "--marker", self.marker, "--name", self.name] + self.args

    def procs(self):
        return procs(self.marker)

    def starts(self):
        p = self.dir / "events.log"
        return p.read_text().count("start ") if p.exists() else 0


class World:
    def __init__(self, root, label, idle, fakes, remotes=(), fail_refresh=False, extra_env=None):
        self.tmp = Path(tempfile.mkdtemp(prefix="pmlproof-" + label + "-", dir=root))
        self.home, self.project = self.tmp / "home", self.tmp / "project"
        self.agent = self.home / ".pi" / "agent"
        self.agent.mkdir(parents=True)
        self.project.mkdir()
        self.fakes = {f.name: f for f in fakes}
        self.idle, self.label = idle, label
        canon = self.tmp / "canonical"
        (canon / "mcp").mkdir(parents=True)
        (canon / "skills").mkdir()
        (self.tmp / "adapters").mkdir()
        servers = {f.name: {"command": f.cmd()[0], "args": f.cmd()[1:]} for f in fakes}
        for name, url in remotes:
            servers[name] = {"type": "http", "url": url}
        (canon / "mcp" / "servers.json").write_text(json.dumps({"mcpServers": servers}))
        lst = self.tmp / "servers.list"
        lst.write_text("\n".join(f.name for f in fakes) + "\n")
        binp = STANDIN
        if fail_refresh:
            real = self.tmp / "bin" / "pi-mcp-lazy-real"
            real.parent.mkdir()
            shutil.copy2(STANDIN, real)
            wrapper = self.tmp / "bin" / "pi-mcp-lazy"
            wrapper.write_text('#!/bin/sh\n[ "$1" = "--refresh" ] && { echo "simulated refresh failure" >&2; exit 1; }\nexec "$(dirname "$0")/pi-mcp-lazy-real" "$@"\n')
            wrapper.chmod(0o755)
            binp = str(wrapper)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "PI_CODING_AGENT_DIR": str(self.agent), "PI_OFFLINE": "1",
                    "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0", "PI_MCP_LAZY_GRACE": "1", "PI_MCP_LAZY_START_TIMEOUT": "30"}
        self.env.update(extra_env or {})
        apply_env = dict(self.env, AGENT_HARNESS_CANONICAL_ROOT=str(canon), AGENT_HARNESS_GENERATED_ROOT=str(self.tmp / "generated"),
                         AGENT_HARNESS_ADAPTERS_ROOT=str(self.tmp / "adapters"), AGENT_HARNESS_EXTERNAL_ROOT=str(self.tmp / "ext"),
                         AGENT_HARNESS_APPLY_CLAUDE_MCP="0", PI_MCP_LAZY_LIST=str(lst), PI_MCP_LAZY_BIN=binp,
                         PI_MCP_LAZY_IDLE=str(idle))
        r = subprocess.run(["sh", str(APPLY), "pi"], env=apply_env, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise AssertionError("apply failed: " + r.stderr[-500:])
        self.apply_log = r.stdout
        (self.agent / "settings.json").write_text(json.dumps({
            "defaultProvider": "scripted", "defaultModel": "proof-model", "enabledModels": [], "packages": [],
            "defaultThinkingLevel": "off", "defaultTools": ["+codemode"], "codemode": {"mode": "only"}, "theme": "dark"}))
        self.state = self.home / ".local" / "state" / "pi-mcp-lazy"
        self.seed = self.home / ".local" / "share" / "pi-mcp-lazy" / "seed"

    def servers_config(self):
        return json.loads((self.agent / "mcp.json").read_text())["mcpServers"]

    def write_models(self, port):
        (self.agent / "models.json").write_text(json.dumps({"providers": {"scripted": {
            "baseUrl": "http://127.0.0.1:%d/v1" % port, "api": "openai-completions", "apiKey": "proof-only",
            "models": [{"id": "proof-model", "reasoning": False, "input": ["text"], "contextWindow": 100000, "maxTokens": 4096,
                        "compat": {"supportsStrictMode": False}}]}}}))

    def pi(self):
        pi = shutil.which(os.environ.get("PI_BIN", "pi"))
        if not pi:
            raise AssertionError("Pi CLI unavailable")
        return [pi, "--no-session", "--offline", "--no-context-files"]

    def open(self):
        return Rpc(self.pi(), self.env, self.project)

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- checks
def check(name):
    def deco(fn):
        def run(*a, **k):
            t0 = time.monotonic()
            try:
                detail = fn(*a, **k) or {}
                RESULTS.append({"check": name, "ok": True, "seconds": round(time.monotonic() - t0, 1), **detail})
                print("PASS %-58s %s" % (name, json.dumps(detail)[:200]))
            except Exception as e:
                RESULTS.append({"check": name, "ok": False, "error": "".join(traceback.format_exception_only(type(e), e)).strip()[:600],
                                "seconds": round(time.monotonic() - t0, 1)})
                print("FAIL %-58s %s" % (name, str(e)[:300]))
        return run
    return deco


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


def js_names(prefix):
    return ("const found = await searchTools('echo', {namespace:'mcp__%s'});"
            "const desc = await describeTool('mcp__%s__echo');"
            "const names = ALL_TOOLS.filter(t => t.name.startsWith('mcp__%s__')).map(t => t.name).sort();"
            "text(JSON.stringify({found: found.map(t=>t.name), described: !!desc, names}));") % (prefix, prefix, prefix)


def register_codes(name):
    CODES["discover-" + name] = js_names(name)
    CODES["echo-" + name] = "const r = await tools.mcp__%s__echo({text:'hi'}); text('RESULT:' + r.content[0].text);" % name
    CODES["slow-" + name] = "const r = await tools.mcp__%s__slow({seconds:%d}); text('RESULT:' + r.content[0].text);" % (name, 14)
    CODES["try-echo-" + name] = ("try { const r = await tools.mcp__%s__echo({text:'x'}); text('OK:' + r.content[0].text); }"
                                 " catch (e) { text('ERR:' + String(e && e.message || e)); }") % name


CODES["noop"] = "text('noop');"
CODES["remote"] = "const r = await tools.mcp__hindsight__echo({text:'remote'}); text('RESULT:' + r.content[0].text);"
EXPECTED = ["mcp__%s__echo", "mcp__%s__roots", "mcp__%s__slow"]


def discovery_check(name, root, port, idle, mutate=None, fail_refresh=False):
    """Discover the server's tools in a fresh Pi without starting it, in one copy state."""
    f = Fake(Path(root), "furi")
    w = World(root, name, idle, [f], fail_refresh=fail_refresh)
    try:
        w.write_models(port)
        base = f.starts()  # the apply step's refresh started the server once, on purpose, before any session
        if mutate:
            mutate(w)
        rpc = w.open()
        try:
            out = rpc.prompt("discover-furi")
            require("OUT:" in out, out[:300])
            data = json.loads(out.split("OUT:", 1)[1].strip().splitlines()[-1])
            require(data["names"] == sorted(n % "furi" for n in EXPECTED), "tools listed: %r" % data["names"])
            require(data["described"] and "mcp__furi__echo" in data["found"], "search/describe failed: %r" % data)
            require(f.procs() == [] and f.starts() == base, "a real server was started by discovery: %r" % f.procs())
        finally:
            rpc.close()
        require(wait_until(lambda: f.procs() == [], 10), "processes left after Pi exit")
        return {"tools": len(data["names"]), "real_server_processes": 0, "session_server_starts": f.starts() - base}
    finally:
        w.cleanup()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default="")
    ap.add_argument("--idle", type=int, default=6)
    ap.add_argument("--only", default="", help="comma list of: discovery, lifecycle, failure, six, real")
    a = ap.parse_args()
    only = {x for x in a.only.split(",") if x} or {"discovery", "lifecycle", "failure", "six", "real"}
    root = tempfile.mkdtemp(prefix="pmlproof-root-")
    handler = type("M", (Model,), {"errors": []})
    model = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    remote = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Remote)
    threading.Thread(target=remote.serve_forever, daemon=True).start()
    port, idle = model.server_port, a.idle
    for n in ("furi", "playwright", "rea"):
        register_codes(n)
    CODES["discover-furi"] = js_names("furi")

    def stale(w):
        p = w.state / "furi.json"
        head, _, rest = p.read_text().partition("\n")
        d = json.loads(head)
        d["key"] = "built for another command line"
        p.write_text(json.dumps(d) + "\n" + rest)

    def no_state(w):  # the shipped seed stands in: a copy of what the refresh produced
        w.seed.mkdir(parents=True)
        shutil.copy2(w.state / "furi.json", w.seed / "furi.json")
        shutil.rmtree(w.state)

    try:
        if "discovery" in only:
            discovery(root, port, idle, stale, no_state)
        if "lifecycle" in only:
            lifecycle(root, port, idle)
        if "failure" in only:
            failure_and_retry(root, port, idle)
        if "six" in only:
            six_servers(root, port, remote.server_port, idle)
        if "real" in only:
            real_calls(root, port)
    finally:
        model.shutdown()
        remote.shutdown()
        shutil.rmtree(root, ignore_errors=True)
        try:
            (Path(tempfile.gettempdir()) / "pml-seed-for-failed.json").unlink()
        except OSError:
            pass
    check("scripted model saw no protocol error")(lambda: require(not handler.errors, str(handler.errors)))()
    ok = all(r["ok"] for r in RESULTS)
    summary = {"idle_seconds": idle, "ok": ok, "checks": RESULTS}
    if a.evidence:
        d = Path(a.evidence)
        d.mkdir(parents=True, exist_ok=True)
        (d / "proof-results.json").write_text(json.dumps(summary, indent=2))
    print("\n%s: %d/%d checks passed" % ("PASS" if ok else "FAIL", sum(r["ok"] for r in RESULTS), len(RESULTS)))
    return 0 if ok else 1


def discovery(root, port, idle, stale, no_state):
    check("discovery: current state copy, no server started")(discovery_check)("current", root, port, idle)
    check("discovery: stale state copy, no server started")(discovery_check)("stale", root, port, idle, mutate=stale)
    check("discovery: no state copy (seed), no server started")(discovery_check)("nostate", root, port, idle, mutate=no_state)

    def failed_refresh_state(w):  # the renderer produced no state copy; the shipped seed is what remains
        require(not w.state.exists(), "state copy exists after a failed refresh")
        require("refresh of furi failed" in w.apply_log, "failure not logged by name")
        w.seed.mkdir(parents=True)
        shutil.copy2(Path(tempfile.gettempdir()) / "pml-seed-for-failed.json", w.seed / "furi.json")
    # produce a seed once from a successful refresh, then use it in the failed-refresh world
    tmp_world = World(root, "seedmaker", idle, [Fake(Path(root), "furi")])
    try:
        shutil.copy2(tmp_world.state / "furi.json", Path(tempfile.gettempdir()) / "pml-seed-for-failed.json")
    finally:
        tmp_world.cleanup()
    check("discovery: refresh failed at apply time (seed), no server started")(discovery_check)(
        "failedrefresh", root, port, idle, mutate=failed_refresh_state, fail_refresh=True)



def lifecycle(root, port, idle):
    f = Fake(Path(root), "furi", "--grandchild")
    w = World(root, "lifecycle", idle, [f])
    holder = {}
    try:
        w.write_models(port)
        base = f.starts()  # starts made by the apply step's refresh, before the session
        rpc = w.open()
        holder["rpc"] = rpc
        pi_pid = rpc.p.pid

        @check("first use: real server starts, real result, timing measured")
        def first_use():
            rpc.prompt("noop")
            t0 = time.monotonic()
            rpc.prompt("noop")
            turn = time.monotonic() - t0
            holder["rss_pre"] = mcp_side_rss_kb(pi_pid)
            holder["owned_pre"] = holder["rss_pre"] + pi_rss_kb(pi_pid)
            require(f.procs() == [], "server running before first use")
            t0 = time.monotonic()
            out = rpc.prompt("echo-furi")
            took = time.monotonic() - t0
            require("RESULT:echo:hi" in out, out[:300])
            time.sleep(0.5)  # let the fork/exec of the server's helper settle before counting processes
            now, started = f.procs(), f.starts() - base
            require(started == 1 and len(now) == 2,
                    "expected one session start and server+grandchild; session starts=%d, processes=%d: %r" % (started, len(now), [p[-90:] for p in now]))
            holder["rss_up"] = mcp_side_rss_kb(pi_pid)
            holder["pid1"] = (f.dir / "server.pid").read_text()
            return {"call_to_result_s": round(took, 2), "baseline_turn_s": round(turn, 2), "extra_s": round(took - turn, 2)}
        first_use()

        @check("idle stop: server, wrappers and grandchild gone; memory back within 10%")
        def idle_stop():
            require(wait_until(lambda: f.procs() == [], idle + 30), "server still running: %r" % f.procs())
            time.sleep(1)
            post = mcp_side_rss_kb(pi_pid)
            pre = holder["rss_pre"]
            # AC-5 is about the whole owned set. The stand-in itself keeps a little (modules loaded on first use) and is reported.
            owned_pre, owned_post = holder["owned_pre"], post + pi_rss_kb(pi_pid)
            require(owned_post <= 1.10 * owned_pre, "owned-set RSS pre %d kB post %d kB" % (owned_pre, owned_post))
            return {"owned_set_rss_kb": {"before_use": owned_pre, "after_idle": owned_post},
                    "stand_in_only_rss_kb": {"before_use": pre, "server_up": holder["rss_up"], "after_idle": post}}
        idle_stop()

        @check("restart: a later call starts the server again and succeeds")
        def restart():
            out = rpc.prompt("echo-furi")
            require("RESULT:echo:hi" in out, out[:300])
            require(f.starts() == base + 2 and (f.dir / "server.pid").read_text() != holder["pid1"], "server was not restarted")
            require(wait_until(lambda: f.procs() == [], idle + 30), "second idle stop failed")
            return {"session_starts": f.starts() - base}
        restart()

        @check("long call: never stopped mid-call, stops after it ends")
        def long_call():
            t0 = time.monotonic()
            rpc.start_prompt("slow-furi")
            time.sleep(idle + 4)
            require(len(f.procs()) == 2, "server stopped during the call: %r" % f.procs())
            out = rpc.settle(60)
            require("RESULT:slow-done" in out, out[:300])
            require(time.monotonic() - t0 >= 13, "call finished too early")
            require(f.starts() == base + 3, "the call was restarted: starts=%d" % (f.starts() - base))
            require(wait_until(lambda: f.procs() == [], idle + 30), "server not stopped after the call")
            return {"call_s": round(time.monotonic() - t0, 1), "idle_s": idle}
        long_call()

        @check("exit cleanup: closing Pi leaves no server or stand-in")
        def exit_cleanup():
            rpc.p.stdin.close()
            rpc.call = None
            rpc.p.wait(timeout=30)
            require(wait_until(lambda: f.procs() == [] and not [r for r in ps_rows() if "executable_pi-mcp-lazy" in r[3] and str(w.home) in r[3]], 15),
                    "processes left after Pi exit")
        exit_cleanup()
        holder["rpc"] = None
    finally:
        if holder.get("rpc"):
            try:
                holder["rpc"].close()
            except Exception:
                pass
        w.cleanup()


def failure_and_retry(root, port, idle):
    crash = Path(root) / "crash-flag"
    f = Fake(Path(root), "furi", "--crash-file", str(crash))
    w = World(root, "failure", idle, [f])
    try:
        w.write_models(port)
        base = f.starts()
        rpc = w.open()
        try:
            @check("start failure: named error with stderr tail, session responsive, later call retries")
            def failure():
                crash.write_text("x")
                out = rpc.prompt("try-echo-furi")
                require("ERR:MCP server 'furi' failed to start" in out and "boom: cannot start" in out, out[:400])
                require("noop" in rpc.prompt("noop"), "session unresponsive after a failed start")
                crash.unlink()
                out2 = rpc.prompt("try-echo-furi")
                require("OK:echo:x" in out2, out2[:300])
                require(f.starts() == base + 1, "starts=%d" % (f.starts() - base))
            failure()
        finally:
            rpc.close()
        require(wait_until(lambda: f.procs() == [], 10), "processes left")
    finally:
        w.cleanup()


def six_servers(root, port, remote_port, idle):
    fakes = [Fake(Path(root), n) for n in ("furi", "playwright", "rea")]
    url = "http://127.0.0.1:%d/mcp" % remote_port
    w = World(root, "six", idle, fakes, remotes=[("hindsight", url), ("context7", url), ("ticktick", url)])
    try:
        w.write_models(port)
        cfg = w.servers_config()

        @check("rendering: three servers wrapped, three remote entries unchanged")
        def rendering():
            for n in ("furi", "playwright", "rea"):
                require(cfg[n]["command"] == STANDIN and cfg[n]["args"][:3] == [n, str(idle), "--"], cfg[n])
            for n in ("hindsight", "context7", "ticktick"):
                require(cfg[n] == {"type": "http", "url": url}, cfg[n])
        rendering()

        pi = w.pi()[0]

        @check("pi mcp list: all six servers connected, no real server started")
        def cli_list():
            r = subprocess.run([pi, "mcp", "list", "--json"], env=w.env, cwd=w.project, capture_output=True, text=True, timeout=180)
            require(r.returncode == 0, (r.stdout + r.stderr)[-600:])
            data = json.loads(r.stdout)
            rows = data if isinstance(data, list) else data.get("servers", data)
            names = {x.get("name") for x in rows} if isinstance(rows, list) else set(rows)
            require(names >= {"furi", "playwright", "rea", "hindsight", "context7", "ticktick"}, names)
            require('"connected"' in r.stdout and r.stdout.count('"connected"') >= 6, r.stdout[:600])
            for f in fakes:
                require(f.procs() == [], "pi mcp list started %s" % f.name)
            return {"servers": len(names)}
        cli_list()

        rpc = w.open()
        try:
            @check("/mcp in a session lists every server connected; remote server call works")
            def session_mcp():
                require(rpc.command("prompt", message="/mcp").get("disposition") == "handled", "/mcp not handled")
                blob = json.dumps(rpc.events)
                for n in ("furi", "playwright", "rea", "hindsight", "context7", "ticktick"):
                    require("%s: connected" % n in blob, "%s not listed as connected" % n)
                out = rpc.prompt("remote")
                require("RESULT:remote-echo:remote" in out, out[:300])
                for f in fakes:
                    require(f.procs() == [], "a lazy server started without a call: %s" % f.name)
            session_mcp()
        finally:
            rpc.close()
    finally:
        w.cleanup()


REAL_CODES = {
    "real-furi": "const r = await tools.list_mcp_resources({server:'furi'}); const j = JSON.stringify(r); text('RESULT:' + JSON.stringify({isError: !!(r && r.isError), bytes: j.length, head: (r && r.isError) ? String((r.content && r.content[0] && r.content[0].text) || '').slice(0, 200) : ''}));",
    "real-playwright": "const r = await tools.mcp__playwright__browser_navigate({url:'about:blank'}); const j = JSON.stringify(r); text('RESULT:' + JSON.stringify({isError: !!(r && r.isError), bytes: j.length, head: (r && r.isError) ? String((r.content && r.content[0] && r.content[0].text) || '').slice(0, 200) : ''}));",
    "real-rea": "const r = await tools.mcp__rea__binary_session({}); const j = JSON.stringify(r); text('RESULT:' + JSON.stringify({isError: !!(r && r.isError), bytes: j.length, head: (r && r.isError) ? String((r.content && r.content[0] && r.content[0].text) || '').slice(0, 200) : ''}));",
}
REAL_PROCESS = {"furi": "furi", "playwright": "node playwright-mcp", "rea": "node rea"}
REAL_IDLE = 10


def real_calls(root, port):
    """One harmless call to each real server through a real Pi session in a throwaway home. The three entries come
    from the real rendering step and state copies built by the real refresh. The throwaway home is the measurement
    tool's: offline npx from clones of the owner's npx cache, stubbed credential helpers, no credentials."""
    import types
    sys.path.insert(0, str(ROOT / "tests" / "pi-idle-rss"))
    import pi_idle_rss as tool

    CODES.update(REAL_CODES)
    marker = "pmlreal" + uuid.uuid4().hex[:10]
    holder = {}

    @check("real servers: environment prepared (rendering, state copies, throwaway home)")
    def prepare():
        store_root = Path(tempfile.mkdtemp(prefix="pmlreal-store-", dir=root))
        for name, src in (("npx", tool.REAL_HOME / ".npm" / "_npx"), ("cacache", tool.REAL_HOME / ".npm" / "_cacache")):
            if src.exists():
                tool.clone(src, store_root / name)  # APFS clones: the owner's caches are never written
        store = types.SimpleNamespace(root=store_root, lazy={})
        node_dir = tool.release_paths()[1]
        rendered = tool.lazy_render(store, "state", node_dir)
        home = Path(tempfile.mkdtemp(prefix="pmlreal-home-", dir=root))
        agent = home / ".pi" / "agent"
        agent.mkdir(parents=True)
        mcp = json.loads(json.dumps(rendered["mcp"]))
        for n in ("furi", "playwright", "rea"):
            mcp["mcpServers"][n]["args"][1] = str(REAL_IDLE)  # shortened idle period, in the proof's own copy only
        (agent / "mcp.json").write_text(json.dumps(mcp))
        (home / ".local" / "state").mkdir(parents=True)
        shutil.copytree(rendered["state"], home / ".local" / "state" / "pi-mcp-lazy")
        seed = home / ".local" / "share" / "pi-mcp-lazy" / "seed"
        seed.parent.mkdir(parents=True)
        shutil.copytree(tool.LAZY_SEED, seed)
        (home / ".npm").mkdir()
        for name, link in (("npx", "_npx"), ("cacache", "_cacache")):
            if (store_root / name).exists():
                (home / ".npm" / link).symlink_to(store_root / name)
        tools_dir = home / ".tools"
        tools_dir.mkdir()
        for c in ("python3", "node", "npx", "npm", "furi", "git"):
            real = shutil.which(c)
            if real:
                (tools_dir / c).symlink_to(real)
        (agent / "settings.json").write_text(json.dumps({
            "defaultProvider": "scripted", "defaultModel": "proof-model", "enabledModels": [], "packages": [],
            "defaultThinkingLevel": "off", "defaultTools": ["+codemode"], "codemode": {"mode": "only"}, "theme": "dark"}))
        (agent / "models.json").write_text(json.dumps({"providers": {"scripted": {
            "baseUrl": "http://127.0.0.1:%d/v1" % port, "api": "openai-completions", "apiKey": "proof-only",
            "models": [{"id": "proof-model", "reasoning": False, "input": ["text"], "contextWindow": 100000, "maxTokens": 4096,
                        "compat": {"supportsStrictMode": False}}]}}}))
        project = home / "project"
        project.mkdir()
        holder["env"] = {"PATH": ":".join([str(node_dir), str(tools_dir), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]), "HOME": str(home),
                         "PI_CODING_AGENT_DIR": str(agent), "PI_OFFLINE": "1", "npm_config_offline": "true", "PI_SKIP_VERSION_CHECK": "1",
                         "PI_TELEMETRY": "0", tool.MARKER: marker, "PLAYWRIGHT_MCP_HEADLESS": "true"}
        holder["project"] = project
        servers = rendered["mcp"]["mcpServers"]
        for n in ("furi", "playwright", "rea"):
            require(servers[n]["command"].endswith("pi-mcp-lazy"), "%s not wrapped" % n)
        require(all((home / ".local" / "state" / "pi-mcp-lazy" / (n + ".json")).exists() for n in ("furi", "playwright", "rea")), "state copies missing")

    prepare()
    if "env" not in holder:
        return
    pi = shutil.which(os.environ.get("PI_BIN", "pi"))
    rpc = Rpc([pi, "--no-session", "--offline", "--no-context-files"], holder["env"], holder["project"])
    try:
        def owned_names():
            rows = tool.owned_set(tool.ps_table(), marker, rpc.p.pid)
            return sorted(tool.cmd_name(r["line"]) for r in rows)

        @check("real servers: none running before the first call")
        def none_before():
            rpc.prompt("noop")
            holder["rss_pre"] = mcp_side_rss_kb(rpc.p.pid)
            holder["owned_pre"] = holder["rss_pre"] + pi_rss_kb(rpc.p.pid)
            names = owned_names()
            require(not [n for n in names if n in tool.MCP_REAL_NAMES], "real server processes before any call: %r" % names)
            return {"owned_process_names": names}
        none_before()

        for name in ("furi", "playwright", "rea"):
            @check("real server %s: first harmless call starts it and returns a real result" % name)
            def one(name=name):
                t0 = time.monotonic()
                out = rpc.prompt("real-" + name, timeout=180)
                took = time.monotonic() - t0
                require("RESULT:" in out, out[:400])
                outcome = "success"
                if '"isError":true' in out:
                    # Only playwright can answer this way here: no browser build matching this playwright-mcp is installed on
                    # this machine, so the live server gives the same error. It is the real server's own answer, relayed
                    # through the stand-in; a stand-in start error ("failed to start", "exited") never qualifies.
                    require(name == "playwright" and ("is not installed" in out or "is not found" in out)
                            and "failed to start" not in out and "exited" not in out, out[:400])
                    outcome = "real server's own answer: browser not installed (no matching browser build on this machine)"
                names = owned_names()
                require(REAL_PROCESS[name] in names, "%s did not start: %r" % (name, names))
                return {"call_to_result_s": round(took, 2), "outcome": outcome, "owned_process_names": names,
                        "tool": REAL_CODES["real-" + name].split("tools.")[1].split("(")[0]}
            one()

        @check("real servers: idle stop reclaims every server and npm wrapper, memory back within 10%, restart works")
        def idle_real():
            up = mcp_side_rss_kb(rpc.p.pid)
            gone = wait_until(lambda: not [n for n in owned_names() if n in tool.MCP_REAL_NAMES], REAL_IDLE + 90)
            require(gone, "real MCP processes remain after the idle period: %r" % owned_names())
            time.sleep(1)
            after = mcp_side_rss_kb(rpc.p.pid)
            pre = holder["rss_pre"]
            # AC-5 is about the whole owned set (Pi plus everything it started); the stand-ins alone are reported too
            owned_pre, owned_after = holder["owned_pre"], after + pi_rss_kb(rpc.p.pid)
            require(owned_after <= 1.10 * owned_pre, "owned-set RSS before %d kB, after idle %d kB" % (owned_pre, owned_after))
            names = owned_names()
            require(len([n for n in names if "pi-mcp-lazy" in n]) == 3, "stand-ins should stay: %r" % names)
            out = rpc.prompt("real-rea", timeout=180)
            require('"isError":false' in out, out[:300])
            require("node rea" in owned_names(), "rea was not started again")
            return {"owned_set_rss_kb": {"before_use": owned_pre, "after_idle": owned_after},
                    "stand_ins_only_rss_kb": {"before_use": pre, "servers_up": up, "after_idle": after}, "owned_after_idle": names}
        idle_real()
    finally:
        try:
            rpc.close()
        except Exception:
            pass
        tool.kill_owned(marker, None)

    @check("real servers: nothing left running after Pi exits")
    def gone():
        require(wait_until(lambda: not tool.owned_set(tool.ps_table(), marker, None), 15), "marker-owned processes remain")
    gone()


if __name__ == "__main__":
    sys.exit(main())
