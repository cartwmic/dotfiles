#!/usr/bin/env python3
"""Prove native MCP migration through real Pi CLI, RPC, and TUI.

All model/MCP traffic is scripted and local. User packages, credentials,
configuration, and sessions are not copied into the isolated runtime.
Run from the dotfiles root: python3 tests/native-mcp/proof.py
"""
from __future__ import annotations

import fcntl
import http.server
import json
import os
import pty
import queue
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 45
PRIVATE = "PRIVATE_NESTED_RESULT_SENTINEL"
TITLE = "Native Jira transport proof"
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n")


def mcp_backend(trace):
    def record(data):
        with trace.open("a") as out:
            out.write(json.dumps({"pid": os.getpid(), **data}) + "\n")

    record({"event": "start", "inheritedEnv": os.environ.get("MCP_PROOF_VALUE")})
    try:
        for line in sys.stdin:
            request = json.loads(line)
            if "id" not in request:
                continue
            method, params = request["method"], request.get("params", {})
            if method == "initialize":
                result = {"protocolVersion": request["params"]["protocolVersion"],
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "migration-proof", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": name, "description": "Scripted migration proof " + name,
                                     "inputSchema": {"type": "object", "properties": properties},
                                     "annotations": {"readOnlyHint": name in {"echo", "get_jira_issue", "get_jira_transitions"}}}
                                    for name, properties in [
                                        ("echo", {"marker": {"type": "string"}}),
                                        ("get_jira_issue", {"issue_key": {"type": "string"}}),
                                        ("add_jira_comment", {"issue_key": {"type": "string"}, "comment": {"type": "string"}}),
                                        ("get_jira_transitions", {"issue_key": {"type": "string"}}),
                                        ("transition_jira_issue", {"issue_key": {"type": "string"}, "transition_id": {"type": "string"}}),
                                    ]]}
            elif method == "tools/call":
                name, args = params["name"], params.get("arguments", {})
                record({"event": "call", "name": name, "args": args})
                if name == "echo":
                    value = {"marker": args["marker"], "private": PRIVATE}
                elif name == "get_jira_issue":
                    value = {"key": args["issue_key"],
                             "self": "https://jira.example.test/rest/api/2/issue/1",
                             "fields": {"summary": TITLE, "status": {"name": "Open"}}}
                elif name == "get_jira_transitions":
                    value = {"transitions": [{"id": "2", "name": "Done"}]}
                else:
                    value = {"ok": True}
                result = {"content": [{"type": "text", "text": json.dumps(value)}],
                          "structuredContent": value}
                if name == "add_jira_comment" and args.get("comment") == "reject-proof":
                    result = {"isError": True, "content": [{"type": "text", "text": "Scripted Jira rejection"}]}
            elif method == "ping":
                result = {}
            else:
                print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                                  "error": {"code": -32601, "message": "Method not found"}}), flush=True)
                continue
            print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
    finally:
        record({"event": "stop"})


BATCH_CODE = """const matches = await searchTools('echo', {namespace:'mcp__fixture'});
if (!matches.some(t => t.name === 'mcp__fixture__echo')) throw new Error('Discovery failed');
const declaration = await describeTool('mcp__fixture__echo');
if (!declaration) throw new Error('Description missing');
const results = await Promise.all(['echo-one','echo-two'].map(marker => tools.mcp__fixture__echo({marker})));
const markers = results.map(result => result.structuredContent.marker);
store('proof-markers', markers);
text(markers.join(','));"""

BUILTINS_CODE = """await tools.write({path:'codemode-only.txt', content:'ONLY-BEFORE'});
await tools.edit({path:'codemode-only.txt', oldText:'ONLY-BEFORE', newText:'ONLY-AFTER'});
const content = await tools.read({path:'codemode-only.txt'});
if (!content.includes('ONLY-AFTER') || content.includes('ONLY-BEFORE')) throw new Error('Read/edit failed');
const failure = await tools.bash({command:'printf ONLY-FAILURE; exit 7'});
if (failure.exit_code !== 7 || !failure.output.includes('ONLY-FAILURE')) throw new Error('Shell failure lost');
text('ONLY-TOOLS-PASS');"""


class ModelHandler(http.server.BaseHTTPRequestHandler):
    requests = []
    errors = []

    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append(body)
        try:
            messages = body["messages"]
            user_index = max(i for i, message in enumerate(messages) if message["role"] == "user")
            user = messages[user_index]["content"]
            if isinstance(user, list):
                user = "".join(part.get("text", "") for part in user)
            results = [message for message in messages[user_index + 1:] if message["role"] == "tool"]
            if not results:
                declared = {tool["function"]["name"] for tool in body.get("tools", [])}
                require("codemode" in declared, "Native codemode was not declared")
                require(not {"mcp", "mcpScript"} & declared, "Old adapter tools remain")
                require(not {"read", "bash", "edit", "write"} & declared, "Codemode-only leaked direct tools")
                code = {"batch-proof": BATCH_CODE, "builtins-proof": BUILTINS_CODE,
                        "stored-proof": "text(load('proof-markers').join(','));"}[user]
                delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "proof-call",
                         "type": "function", "function": {"name": "codemode", "arguments": json.dumps({"code": code})}}]}
                reason = "tool_calls"
            else:
                content = json.dumps(results)
                if user == "builtins-proof":
                    require("ONLY-TOOLS-PASS" in content and "Script failed" not in content,
                            "Codemode-only built-in operations did not complete")
                    answer = "ONLY-TOOLS-PASS"
                else:
                    require("echo-one,echo-two" in content, "Completed tool results did not reach the model")
                    answer = "NATIVE-MCP-PASS" if user == "batch-proof" else "STORED-RESULT-PASS"
                require(PRIVATE not in content, "Unprinted nested MCP results leaked into model context")
                delta = {"role": "assistant", "content": answer}
                reason = "stop"
        except Exception as error:
            self.errors.append(str(error))
            delta, reason = {"role": "assistant", "content": "PROOF-FAILED: " + str(error)}, "stop"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        common = {"id": "scripted-proof", "object": "chat.completion.chunk", "created": 1, "model": "proof-model"}
        for chunk in [
            {**common, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {**common, "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
             "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}},
        ]:
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class Rpc:
    def __init__(self, command, env, cwd):
        self.process = subprocess.Popen(command + ["--mode", "rpc"], env=env, cwd=cwd,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True)
        self.records, self.events, self.errors = queue.Queue(), [], bytearray()
        self.counter = 0
        def read_stdout():
            for line in self.process.stdout:
                try:
                    self.records.put(json.loads(line))
                except ValueError:
                    self.records.put({"invalid_output": line.decode(errors="replace")})
        def read_stderr():
            for line in self.process.stderr:
                self.errors.extend(line)
        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()

    def send(self, record):
        self.process.stdin.write(json.dumps(record).encode() + b"\n")
        self.process.stdin.flush()

    def until(self, predicate):
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            try:
                record = self.records.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                require(self.process.poll() is None, "Pi exited: " + self.errors.decode(errors="replace"))
                continue
            self.events.append(record)
            require("invalid_output" not in record, str(record))
            if record.get("type") == "extension_ui_request" and record.get("method") == "confirm":
                self.send({"type": "extension_ui_response", "id": record["id"], "confirmed": True})
            if predicate(record):
                return record
        raise AssertionError("Timed out waiting for real Pi RPC: " + self.errors.decode(errors="replace"))

    def command(self, kind, **fields):
        self.counter += 1
        request_id = str(self.counter)
        self.send({"id": request_id, "type": kind, **fields})
        reply = self.until(lambda record: record.get("type") == "response" and record.get("id") == request_id)
        require(reply.get("success"), str(reply))
        return reply.get("data", {})

    def prompt(self, message):
        reply = self.command("prompt", message=message)
        require(reply.get("disposition") == "started", "Prompt did not start a run")
        self.until(lambda record: record.get("type") == "agent_settled")
        return self.command("get_last_assistant_text")["text"]

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()
            raise AssertionError("Pi did not shut down cleanly")
        require(self.process.returncode == 0, self.errors.decode(errors="replace"))


def tui_proof(command, env, cwd, trace):
    starts_before = sum(json.loads(line).get("event") == "start" for line in trace.read_text().splitlines())
    closed = cwd.parent / "mcp-ui-closed"
    observer = cwd.parent / "ui-observer.ts"
    observer.write_text('import {writeFileSync} from "node:fs";\nexport default pi => {\n'
                        'pi.on("ui_prompt_end", () => writeFileSync(process.env.MCP_PROOF_UI_CLOSED, "closed"));\n};\n')
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 130, 0, 0))
    process = subprocess.Popen(command + ["-e", str(observer)],
                               env={**env, "TERM": "xterm-256color", "NO_COLOR": "1", "MCP_PROOF_UI_CLOSED": str(closed)}, cwd=cwd,
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    output = bytearray()
    def wait(marker, start=0, predicate=None):
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            ready = predicate() if predicate else marker in ANSI.sub("", output[start:].decode(errors="replace"))
            if ready:
                return
            require(process.poll() is None, "TUI exited before " + marker)
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
        raise AssertionError("TUI did not show " + marker + ": " + ANSI.sub("", output.decode(errors="replace"))[-3000:])
    try:
        wait("proof-model")
        # The footer renders before the startup submission guard is removed.
        # Native MCP starts from session_start, after normal handlers bind.
        wait("native MCP session_start", predicate=lambda: sum(
            json.loads(line).get("event") == "start" for line in trace.read_text().splitlines()
        ) > starts_before)
        os.write(master, b"/mcp\r")
        wait("MCP servers")
        wait("fixture")
        wait("jira")
        start = len(output)
        os.write(master, b"\x1b")
        # Keep Escape separate from subsequent bytes (otherwise it is an Alt
        # sequence). Diff-rendered/queued terminal output cannot prove closure;
        # wait for the real custom-dialog completion boundary instead.
        wait("native MCP manager closed", predicate=closed.exists)
        start = len(output)
        os.write(master, b"/issue bind jira PROOF-1\r")
        wait("Bound jira: PROOF-1", start)
        start = len(output)
        os.write(master, b"/issue show jira\r")
        wait(TITLE, start)
        require("Jira MCP connect failed" not in ANSI.sub("", output.decode(errors="replace")), "TUI Jira failed")
    finally:
        try:
            os.write(master, b"\x04")  # User-facing Ctrl+D exit from the empty editor.
            # Keep draining the PTY: waiting without reading can block Pi's
            # final terminal writes and manufacture a shutdown hang.
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        output.extend(os.read(master, 65536))
                    except OSError:
                        break  # Slave closed; wait for the exit status below.
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise AssertionError("TUI required forced shutdown")
        finally:
            os.close(master)
        require(process.returncode == 0, "TUI exited unsuccessfully")


def render_settings(profile, temp):
    # Work normally reads private provider metadata through op. Supply a dummy
    # payload for this proof rather than reading or printing that credential.
    fake_bin = temp / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    op = fake_bin / "op"
    op.write_text("#!/bin/sh\nprintf '%s\\n' '{\"models\": []}'\n")
    op.chmod(0o700)
    data = {"profile": profile, "privatePiGlmProviderRef": "op://proof/provider/credential"}
    result = subprocess.run(["chezmoi", "--source", str(ROOT), "--override-data", json.dumps(data),
                             "cat", str(Path.home() / ".pi/agent/settings.json")],
                            env={**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]},
                            text=True, capture_output=True, check=True, timeout=TIMEOUT)
    settings = json.loads(result.stdout)
    require("https://github.com/cartwmic/pi-mcp-adapter" not in settings["packages"], "Old MCP package remains")
    require("-builtin:mcp" not in settings.get("extensions", []), "Native MCP remains disabled")
    require("+codemode" in settings.get("defaultTools", []), "Codemode not enabled")
    require(settings.get("codemode", {}).get("mode") == "only", "Codemode-only not configured")
    require("https://github.com/cartwmic/system-one-tools" in settings["packages"], "Assessment-only System One was removed")
    return settings


def generator_proof(temp, env, agent):
    canonical = temp / "canonical"
    (canonical / "skills").mkdir(parents=True)
    manual = {"url": "http://127.0.0.1:9/mcp", "enabled": False, "exposure": "direct"}
    ticktick = {"type": "http", "url": "https://mcp.ticktick.com"}
    for profile in ("personal", "axon-work-computer"):
        rendered = subprocess.run(["chezmoi", "--source", str(ROOT), "--override-data", json.dumps({"profile": profile}),
                                   "execute-template"], input=(ROOT / "dot_local/share/agent-harness/canonical/mcp/servers.json.tmpl").read_text(),
                                  text=True, capture_output=True, check=True, timeout=TIMEOUT)
        servers = json.loads(rendered.stdout)["mcpServers"]
        require(servers.get("ticktick") == ticktick, f"{profile}: official TickTick OAuth configuration missing")
        write_json(canonical / "mcp/servers.json", {"mcpServers": servers})
        write_json(agent / "mcp.json", {"autoEnableCodemode": False, "mcpServers": {
            "manual": manual, "hindsight": {"url": "http://127.0.0.1:9/old", "lifecycle": "keep-alive"}}})
        subprocess.run(["sh", str(ROOT / "dot_local/user_scripts/executable_apply_harness_config.sh"), "all"],
                       env={**env, "AGENT_HARNESS_CANONICAL_ROOT": str(canonical),
                            "AGENT_HARNESS_GENERATED_ROOT": str(temp / "generated"),
                            "AGENT_HARNESS_ADAPTERS_ROOT": str(temp / "no-secret-adapters"),
                            "AGENT_HARNESS_EXTERNAL_ROOT": str(temp / "no-external-skills"),
                            "AGENT_HARNESS_INLINE_SECRETS": "0", "AGENT_HARNESS_APPLY_CLAUDE_MCP": "0"},
                       capture_output=True, text=True, check=True, timeout=TIMEOUT)
        merged = json.loads((agent / "mcp.json").read_text())
        require(merged["mcpServers"]["manual"] == manual and merged["autoEnableCodemode"] is False,
                "Pi generator lost manual server/configuration additions")
        require("lifecycle" not in merged["mcpServers"]["hindsight"], "Pi generator retained the retired lifecycle field")
        require(set(merged["mcpServers"]) == set(servers) | {"manual"}, "Pi generator lost canonical servers")
        require(merged["mcpServers"]["ticktick"] == ticktick, f"{profile}: Pi changed the TickTick configuration")
        claude = (temp / "generated/claude/setup-mcp.sh").read_text()
        require('mcp add -s user --transport http "ticktick" "https://mcp.ticktick.com" || true' in claude,
                f"{profile}: Claude TickTick registration missing")
        codex = (Path(env["HOME"]) / ".codex/config.toml").read_text()
        require('[mcp_servers.ticktick]\nurl = "https://mcp.ticktick.com"\n' in codex,
                f"{profile}: Codex TickTick configuration missing")


def main():
    pi = shutil.which(os.environ.get("PI_BIN", "pi"))
    require(pi is not None, "Pi CLI unavailable")
    with tempfile.TemporaryDirectory(prefix="native-mcp-proof-") as name:
        temp = Path(name)
        for profile in ("personal", "axon-work-computer"):
            render_settings(profile, temp)
        settings = render_settings("personal", temp)
        # Keep source tool selection, but replace external resources/provider
        # selection. Nothing from the user's credential or package stores loads.
        settings.update(packages=[], defaultProvider="scripted", defaultModel="proof-model",
                        enabledModels=[], defaultThinkingLevel="off", modelThinkingLevels={}, theme="dark")
        home, project = temp / "home", temp / "project"
        project.mkdir()
        agent = home / ".pi/agent"
        agent.mkdir(parents=True)
        write_json(agent / "settings.json", settings)
        trace = temp / "mcp-trace.jsonl"
        fixture = {"command": sys.executable, "args": [str(Path(__file__).resolve()), "--mcp-backend", str(trace)]}
        env = {key: value for key, value in os.environ.items()
               if not any(word in key for word in ("TOKEN", "API_KEY", "SECRET", "PASSWORD"))}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), PI_CODING_AGENT_DIR=str(agent),
                   PI_OFFLINE="1", MCP_PROOF_VALUE="native-env-proof")
        generator_proof(temp, env, agent)
        write_json(agent / "mcp.json", {"mcpServers": {"fixture": fixture, "jira": fixture}})
        handler = type("BoundModelHandler", (ModelHandler,), {"requests": [], "errors": []})
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        write_json(agent / "models.json", {"providers": {"scripted": {
            "baseUrl": f"http://127.0.0.1:{server.server_port}/v1", "api": "openai-completions", "apiKey": "proof-only",
            "models": [{"id": "proof-model", "reasoning": False, "input": ["text"], "contextWindow": 100000,
                        "maxTokens": 4096, "compat": {"supportsStrictMode": False}}]}}})
        issue = temp / "issue"
        shutil.copytree(ROOT / "dot_pi/private_agent/extensions/issue", issue)
        command = [pi, "--no-session", "--offline", "--no-context-files", "-e", str(issue)]
        try:
            listing = subprocess.run([pi, "mcp", "list", "--json"], env=env, cwd=project,
                                     capture_output=True, text=True, check=True, timeout=TIMEOUT)
            require('"connected"' in listing.stdout, "CLI did not connect to the dummy MCP servers")
            rpc = Rpc(command, env, project)
            try:
                commands = rpc.command("get_commands")["commands"]
                mcp = next(item for item in commands if item["name"] == "mcp")
                require(mcp.get("sourceInfo", {}).get("path") == "builtin:mcp", "Non-native /mcp command loaded")
                require(rpc.command("prompt", message="/mcp").get("disposition") == "handled", "/mcp not handled")
                require("fixture: connected" in json.dumps(rpc.events), "Native /mcp failed to report the connection")
                require(rpc.prompt("batch-proof") == "NATIVE-MCP-PASS", "Batch did not reach a completed model outcome")
                require(rpc.prompt("stored-proof") == "STORED-RESULT-PASS", "Stored results did not survive the next turn")
                require(rpc.prompt("builtins-proof") == "ONLY-TOOLS-PASS", "Codemode-only built-ins failed")
                require((project / "codemode-only.txt").read_text() == "ONLY-AFTER", "Edit did not reach disk")
                nested = [event for event in rpc.events if event.get("type") == "tool_execution_end" and event.get("parentToolCallId")]
                require(len(nested) == 6 and {event["toolName"] for event in nested}
                        == {"mcp__fixture__echo", "write", "edit", "read", "bash"},
                        "Calls bypassed native nested-tool events")
                for message in ("/issue bind jira PROOF-1", "/issue show jira", "/issue sync jira proof-comment",
                                "/issue transition jira Done", "/issue sync jira reject-proof"):
                    rpc.command("prompt", message=message)
                notifications = json.dumps(rpc.events)
                require(TITLE in notifications and "Synced to jira: PROOF-1" in notifications
                        and "Transitioned PROOF-1" in notifications, "Jira commands did not complete")
                require("Scripted Jira rejection" in notifications, "Jira isError was not surfaced")
                confirms = [event for event in rpc.events if event.get("method") == "confirm"]
                require(len(confirms) == 3, "Jira write confirmation gates were bypassed")
            finally:
                rpc.close()
            tui_proof(command, env, project, trace)
            calls = [json.loads(line) for line in trace.read_text().splitlines()]
            starts = [row for row in calls if row.get("event") == "start"]
            require(all(row.get("inheritedEnv") == "native-env-proof" for row in starts),
                    "A native MCP transport dropped the runtime environment")
            def alive(pid):
                try:
                    os.kill(pid, 0)
                    return True
                except ProcessLookupError:
                    return False
            pids = {row["pid"] for row in starts}
            deadline = time.monotonic() + 10
            while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
                time.sleep(0.05)
            remaining = {pid for pid in pids if alive(pid)}
            for pid in remaining:
                os.kill(pid, signal.SIGTERM)  # Only this proof's own backends.
            require(not remaining, f"Native MCP backend processes survived shutdown: {remaining}")
            require(sum(row.get("name") == "echo" for row in calls) == 2, "Stored probe re-called MCP unexpectedly")
            require(any(row.get("name") == "transition_jira_issue" and row["args"]["transition_id"] == "2"
                        for row in calls), "Native Jira client sent the wrong argument shape")
            require(not handler.errors, str(handler.errors))
            print("PASS: personal/work codemode-only settings; native CLI and /mcp; codemode discovery, parallel calls, filtering, nested events, stored-result coherence; script-only read/write/edit and shell failure; real /issue reads, writes, confirmations, errors; TUI manager and Jira show.")
            print("No live provider calls, user configuration changes, or persistent test resources.")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--mcp-backend":
        mcp_backend(Path(sys.argv[2]))
    else:
        main()
