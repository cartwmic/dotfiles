"""Shared helpers: drive the stand-in over real pipes, inspect the process table."""
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STANDIN = str(ROOT / "dot_local" / "bin" / "executable_pi-mcp-lazy")
FAKE = str(Path(__file__).resolve().parent / "fake_server.py")


def procs(marker):
    """Command lines of processes carrying the marker, excluding stand-ins and the ps itself."""
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines():
        if marker not in line or "ps -axo" in line:
            continue
        tokens = line.split()[1:]
        script = os.path.basename(tokens[1]) if len(tokens) > 1 and "python" in os.path.basename(tokens[0]).lower() else os.path.basename(tokens[0])
        if script.startswith("pi-mcp-lazy") or script.startswith("executable_pi-mcp-lazy"):
            continue  # the stand-in itself (also under a wrapper name), whose arguments carry the marker
        res.append(line.strip())
    return res


def wait_until(fn, timeout=15, step=0.1):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(step)
    return fn()


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class Env:
    """A temporary world: state dir, seed dir, fake-server dir, unique marker."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pml-test-"))
        self.state, self.seed, self.fdir = self.tmp / "state", self.tmp / "seed", self.tmp / "fake"
        self.marker = "pmltest" + uuid.uuid4().hex[:10]

    def env(self, **extra):
        e = dict(os.environ, PI_MCP_LAZY_STATE_DIR=str(self.state), PI_MCP_LAZY_SEED_DIR=str(self.seed),
                 PI_MCP_LAZY_GRACE="1", PI_MCP_LAZY_START_TIMEOUT="20")
        e.update(extra)
        return {k: v for k, v in e.items() if v is not None}  # a value of None removes the variable (e.g. the production default grace)

    def fake_cmd(self, *more):
        return [sys.executable, FAKE, "--dir", str(self.fdir), "--marker", self.marker] + list(more)

    def key(self, *more):
        return json.dumps(self.fake_cmd(*more))

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def server_pid(self):
        p = self.fdir / "server.pid"
        return int(p.read_text()) if p.exists() else None

    def starts(self):
        p = self.fdir / "events.log"
        return p.read_text().count("start ") if p.exists() else 0


def write_copy(directory, name, key, tools=("echo", "slow", "roots"), version="2025-11-25", sha=None):
    """Write a saved copy in the stand-in's format: one JSON header line, then the tool list as raw JSON."""
    directory.mkdir(parents=True, exist_ok=True)
    head = {"server": name, "key": key, "tools_sha": sha,
            "initialize": {"protocolVersion": version, "capabilities": {"tools": {"listChanged": True}},
                           "serverInfo": {"name": "fake", "version": "1.0"}, "instructions": "fake server"}}
    tool_defs = [{"name": n, "description": "fake %s" % n, "inputSchema": {"type": "object", "properties": {}}} for n in tools]
    (directory / (name + ".json")).write_text(json.dumps(head) + "\n" + json.dumps(tool_defs) + "\n")


def read_saved(path):
    """Parse a saved copy for assertions: header fields plus a parsed 'tools' list."""
    head, _, rest = Path(path).read_text().partition("\n")
    d = json.loads(head)
    d["tools"] = json.loads(rest)
    return d


class Session:
    """Pi's side of a stand-in: sends requests, reads messages, answers server requests."""

    def __init__(self, env, name, idle, *fake_args, extra_env=None, roots=None):
        self.env, self.n = env, 0
        self.q = queue.Queue()
        self.notes, self.stderr = [], bytearray()
        self.roots = roots or [{"uri": "file:///tmp/x", "name": "x"}]
        cmd = [sys.executable, STANDIN, name, str(idle), "--"] + env.fake_cmd(*fake_args)
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  env=env.env(**(extra_env or {})))
        threading.Thread(target=self._rd, daemon=True).start()
        threading.Thread(target=self._er, daemon=True).start()

    def _rd(self):
        for line in iter(self.p.stdout.readline, b""):
            msg = json.loads(line)
            if "method" in msg and "id" in msg:
                if msg["method"] == "roots/list":
                    self.send({"jsonrpc": "2.0", "id": msg["id"], "result": {"roots": self.roots}})
                elif msg["method"] == "ping":
                    self.send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
            elif "method" in msg:
                self.notes.append(msg["method"])
            else:
                self.q.put(msg)

    def _er(self):
        for line in iter(self.p.stderr.readline, b""):
            self.stderr += line

    def send(self, obj):
        self.p.stdin.write((json.dumps(obj) + "\n").encode())
        self.p.stdin.flush()

    def request(self, method, params=None, timeout=30):
        self.n += 1
        rid = self.n
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        end = time.time() + timeout
        while True:
            try:
                msg = self.q.get(timeout=max(0.05, end - time.time()))
            except queue.Empty:
                raise AssertionError("no response to %s within %ss" % (method, timeout))
            if msg.get("id") == rid:
                return msg

    def initialize(self):
        r = self.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {"roots": {}},
                                        "clientInfo": {"name": "pi-test", "version": "0"}})
        if "result" in r:
            self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return r

    def call(self, tool, args=None, timeout=30):
        return self.request("tools/call", {"name": tool, "arguments": args or {}}, timeout)

    def stderr_text(self):
        return bytes(self.stderr).decode("utf-8", "replace")

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()
            self.p.wait()
        for pipe in (self.p.stdout, self.p.stderr):
            try:
                pipe.close()
            except Exception:
                pass


def text_of(resp):
    return resp["result"]["content"][0]["text"]
