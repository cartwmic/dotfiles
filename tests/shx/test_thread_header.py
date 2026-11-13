#!/usr/bin/env python3
"""The shartifacts connection sends X-Origin (the profile's machine) and X-Thread (the T3 thread id of the session).

Generated: the real chezmoi renders the canonical MCP file for both desktop profiles and the real apply_harness_config.sh
installs it into a scratch home for Claude Code, Codex and Pi; each harness's entry is read back. T3CODE_THREAD_ID is
set during one apply and unset during the other: the entry is installed either way and never holds the apply-time value.
LiveClaude: a real Claude Code session started with T3CODE_THREAD_ID, using the entry the apply installed, pointed at a
scripted local MCP server that logs the request headers. It skips only when no claude binary is found, and says so.
Needs chezmoi (Generated).
Run: python3 tests/shx/test_thread_header.py [Generated|LiveClaude]
"""
import http.server
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import tomllib
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_agent_access as access  # the chezmoi helper and the profiles used there

ROOT = access.ROOT
APPLY = ROOT / "dot_local/user_scripts/executable_apply_harness_config.sh"
MACHINE = {"personal": "personal", "axon-work-computer": "work"}
THREAD = "thread-under-test"
APPLY_THREAD = "thread-set-only-during-apply"
RUN_TIME_VALUE = "${T3CODE_THREAD_ID:-}"


def claude_binary():
    """The real Claude Code binary, or None. Resolves mise's shim, which needs the real home."""
    if shutil.which("mise"):
        r = subprocess.run(["mise", "which", "claude"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return shutil.which("claude")


def scratch_apply(tmp, profile, harnesses, apply_thread, url=None, only_shartifacts=False, fake_claude=None, env_extra=None):
    """Render the canonical MCP file for `profile`, apply it into tmp/home, return (home, generated root, apply output)."""
    home, canon = tmp / "home", tmp / "canonical"
    (canon / "skills").mkdir(parents=True)
    (canon / "mcp").mkdir()
    home.mkdir(exist_ok=True)
    rendered = json.loads(access.chezmoi(profile, "execute-template", stdin=access.TMPL.read_text()))
    if only_shartifacts:
        rendered["mcpServers"] = {"shartifacts": rendered["mcpServers"]["shartifacts"]}
    if url:
        rendered["mcpServers"]["shartifacts"]["url"] = url
    (canon / "mcp" / "servers.json").write_text(json.dumps(rendered, indent=2))
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "AGENT_HARNESS_CANONICAL_ROOT": str(canon),
           "AGENT_HARNESS_GENERATED_ROOT": str(tmp / "generated"), "AGENT_HARNESS_ADAPTERS_ROOT": str(tmp / "adapters"),
           "AGENT_HARNESS_EXTERNAL_ROOT": str(tmp / "external"), "PI_MCP_LAZY_LIST": str(tmp / "no-servers.list"),
           "CLAUDE_CONFIG_DIR": str(tmp / "claude-config"), **(env_extra or {})}
    if fake_claude:
        env["CLAUDE_BIN"] = str(fake_claude)
        env["AGENT_HARNESS_APPLY_CLAUDE_MCP"] = "1"
    else:
        env["AGENT_HARNESS_APPLY_CLAUDE_MCP"] = "0"
    if apply_thread:
        env["T3CODE_THREAD_ID"] = apply_thread
    r = subprocess.run(["sh", str(APPLY), *harnesses], capture_output=True, text=True, env=env, timeout=240)
    if r.returncode:
        raise AssertionError("apply failed: %s%s" % (r.stdout[-800:], r.stderr[-800:]))
    return home, tmp / "generated", r.stdout + r.stderr


@unittest.skipUnless(shutil.which("chezmoi"), "needs chezmoi on PATH")
class Generated(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shx-thread-header-"))
        self.addCleanup(shutil.rmtree, self.tmp)

    def fake_claude(self):
        """A claude that logs each `mcp add` as one block: CALL, then one argument per line."""
        log = self.tmp_case / "claude-calls"
        script = self.tmp_case / "fake-claude"
        script.write_text('#!/bin/sh\n{ echo CALL; for a in "$@"; do printf "%s\\n" "$a"; done; } >> ' + str(log) + "\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script, log

    def calls(self, log):
        blocks = [b.splitlines() for b in log.read_text().split("CALL\n") if b.strip()]
        return [b for b in blocks if b[:2] == ["mcp", "add"]]

    def test_each_harness_gets_origin_and_a_run_time_thread_on_both_profiles(self):
        for profile, machine in MACHINE.items():
            for apply_thread in (APPLY_THREAD, None):
                with self.subTest(profile=profile, thread_set_during_apply=bool(apply_thread)):
                    self.tmp_case = self.tmp / ("%s-%s" % (profile, bool(apply_thread)))
                    self.tmp_case.mkdir()
                    fake, log = self.fake_claude()
                    home, generated, out = scratch_apply(self.tmp_case, profile, ["claude", "codex", "pi"], apply_thread, only_shartifacts=True, fake_claude=fake)
                    self.check_claude(log, machine)
                    self.check_codex(home, machine)
                    self.check_pi(home, machine)
                    for path in [*home.rglob("*"), *generated.rglob("*")]:
                        if path.is_file():
                            self.assertNotIn(APPLY_THREAD, path.read_text(errors="replace"), "the apply-time thread id leaked into %s" % path)
                    self.assertNotIn(APPLY_THREAD, log.read_text())

    def check_claude(self, log, machine):
        shartifacts = [c for c in self.calls(log) if "shartifacts" in c]
        self.assertEqual(len(shartifacts), 1, "the shartifacts entry is registered")
        argv = shartifacts[0]
        headers = [argv[i + 1] for i, a in enumerate(argv) if a == "--header"]
        # Claude Code expands ${VAR:-} itself when a session starts (LiveClaude proves it): the stored header keeps the placeholder.
        self.assertEqual(sorted(headers), sorted(["X-Origin: " + machine, "X-Thread: " + RUN_TIME_VALUE]))

    def check_codex(self, home, machine):
        entry = tomllib.loads((home / ".codex/config.toml").read_text())["mcp_servers"]["shartifacts"]
        self.assertEqual(entry["url"], access.ENTRY["url"])
        self.assertEqual(entry["http_headers"], {"X-Origin": machine})
        self.assertEqual(entry["env_http_headers"], {"X-Thread": "T3CODE_THREAD_ID"})

    def check_pi(self, home, machine):
        entry = json.loads((home / ".pi/agent/mcp.json").read_text())["mcpServers"]["shartifacts"]
        self.assertEqual(entry["url"], access.ENTRY["url"])
        self.assertEqual(entry["headers"]["X-Origin"], machine)
        # Pi runs a "!" value when the session connects, with the session's environment; an unset thread gives "none".
        self.assertEqual(entry["headers"]["X-Thread"], '!printf %s "${T3CODE_THREAD_ID:-none}"')

    def test_pi_resolves_the_header_from_the_session_environment(self):
        # The same value, run through Pi's own resolver (when a Pi install is present): set gives the id, unset gives "none".
        resolver = next(iter(sorted(Path.home().glob(".pi/agent/install/releases/*/node_modules/@earendil-works/pi-coding-agent/dist/core/resolve-config-value.js"))), None)
        if not resolver or not shutil.which("node"):
            self.skipTest("no Pi install or node: the Pi header form is checked only as generated text")
        script = ("import(process.argv[1]).then(m => console.log(JSON.stringify(m.resolveHeadersOrThrow({'X-Thread': process.argv[2]}, 'x'))))")
        value = '!printf %s "${T3CODE_THREAD_ID:-none}"'
        for env_thread, want in ((THREAD, THREAD), (None, "none")):
            env = {k: v for k, v in os.environ.items() if k != "T3CODE_THREAD_ID"}
            if env_thread:
                env["T3CODE_THREAD_ID"] = env_thread
            r = subprocess.run(["node", "-e", script, str(resolver), value], capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(json.loads(r.stdout), {"X-Thread": want}, r.stderr)


class Logger(http.server.BaseHTTPRequestHandler):
    """A scripted MCP server: answers the handshake and logs the headers of every request."""
    log = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.log.append({k.lower(): v for k, v in self.headers.items()})
        try:
            message = json.loads(body)
        except ValueError:
            message = {}
        if "id" not in message:
            self.send_response(202)
            self.end_headers()
            return
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "scripted", "version": "1"}} \
            if message.get("method") == "initialize" else {}
        out = json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        self.send_response(405)
        self.end_headers()

    def log_message(self, *args):
        pass


class LiveClaude(unittest.TestCase):
    def test_a_real_claude_session_sends_the_thread_it_runs_in(self):
        claude = claude_binary()
        if not claude:
            self.skipTest("SKIPPED: no claude binary on this machine, so the live Claude Code header check did not run")
        if not shutil.which("chezmoi"):
            self.skipTest("SKIPPED: needs chezmoi to render the installed entry")
        seen = {}
        servers = []
        for label in ("with_thread", "without_thread"):
            handler = type("H_" + label, (Logger,), {"log": []})
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            servers.append((label, server, handler))

        def run(label, server, handler):
            tmp = Path(tempfile.mkdtemp(prefix="shx-live-claude-"))
            self.addCleanup(shutil.rmtree, tmp, True)
            url = "http://127.0.0.1:%d/mcp" % server.server_address[1]
            # The apply installs the entry into a scratch Claude config with the real claude CLI; the thread is unset then.
            home, _, _ = scratch_apply(tmp, "personal", ["claude"], None, url=url, only_shartifacts=True,
                                       fake_claude=claude)
            env = {k: v for k, v in os.environ.items() if k != "T3CODE_THREAD_ID"}
            env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(tmp / "claude-config")})
            if label == "with_thread":
                env["T3CODE_THREAD_ID"] = THREAD
            # The session connects its MCP servers before it needs the API, so no sign-in is needed to see the headers.
            subprocess.run([claude, "-p", "say ok"], capture_output=True, text=True, env=env, timeout=180, stdin=subprocess.DEVNULL, cwd=tmp)
            seen[label] = list(handler.log)

        with ThreadPoolExecutor(max_workers=2) as pool:
            for future in [pool.submit(run, *s) for s in servers]:
                future.result()
        self.assertTrue(seen["with_thread"], "the session never reached the scripted server")
        for request in seen["with_thread"]:
            self.assertEqual(request.get("x-thread"), THREAD)
            self.assertEqual(request.get("x-origin"), "personal")
        # Installed with no thread at apply time and started with none: the header is empty, and the server is still reached.
        self.assertTrue(seen["without_thread"])
        for request in seen["without_thread"]:
            self.assertEqual(request.get("x-thread"), "")


if __name__ == "__main__":
    unittest.main()
