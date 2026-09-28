#!/usr/bin/env python3
"""Drive isolated, real Pi TUI scenarios for the Learnings monitor.

All model and Hindsight traffic terminates at loopback scripted servers. Each
run gets a private HOME, Pi agent directory, persistent session directory, and
XDG data root. Temporary artifacts are removed unless --keep is supplied.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pty
import re
import selectors
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "dot_pi/private_agent/extensions/learnings-monitor/index.ts"
MODEL_ID = "dummy-model"
MODEL = f"openai/{MODEL_ID}"
WARNING = "Learnings monitor has a persistent failure. Run /learnings status for details."
ANSI = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])"
)
BATCH_MARKER = "Serialized activity batch (untrusted data):\n"
ACTIVE_UI_LOG: Path | None = None
ACTIVE_SESSION_DIRS: tuple[Path, ...] = ()
ACTIVE_ARTIFACT_ROOT: Path | None = None


class ProofFailure(AssertionError):
    def __init__(self, message: str, owner: str, integration_failures: list[dict[str, str]] | None = None, scenario: str | None = None):
        super().__init__(message)
        self.owner = owner
        self.integration_failures = integration_failures or []
        self.scenario = scenario


def require(condition: bool, message: str, owner: str) -> None:
    if not condition:
        raise ProofFailure(message, owner)


def json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(item.get("text", "")) for item in value
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


def extract_batch(messages: list[dict[str, Any]]) -> tuple[dict[str, Any], int]:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") != "user":
            continue
        text = content_text(message.get("content"))
        marker_at = text.find(BATCH_MARKER)
        if marker_at < 0:
            continue
        decoder = json.JSONDecoder()
        payload, _ = decoder.raw_decode(text[marker_at + len(BATCH_MARKER):])
        return payload, index
    raise ValueError("observer request did not contain a serialized activity batch")


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, _request: Any, _client_address: Any) -> None:
        return


class ScriptedBackends:
    """OpenAI-compatible SSE model and local Hindsight HTTP backend."""

    def __init__(self, work_file: Path, log_path: Path | None = None):
        self.work_file = work_file
        self.log_path = log_path
        self.events: list[dict[str, Any]] = []
        self.condition = threading.Condition()
        self.model_requests: list[dict[str, Any]] = []
        self.observer_batches: dict[str, dict[str, Any]] = {}
        self.observer_calls: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.primary_tool_calls: list[dict[str, Any]] = []
        self.recall_calls: list[dict[str, Any]] = []
        self.retain_calls: list[dict[str, Any]] = []
        self.fail_recalls = True
        self.delay_next_recall = 0.0
        self.hold_next_observer = False
        self.cosmetic_sources: set[str] = set()
        self.observer_held = threading.Event()
        self.release_observer = threading.Event()
        self.release_observer.set()
        self.hold_next_primary = False
        self.primary_held = threading.Event()
        self.release_primary = threading.Event()
        self.release_primary.set()

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def handle_error(self, _request: Any, _client_address: Any) -> None:
                owner.log_event({"event": "client-disconnected"})

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length) or b"{}")
                except Exception:
                    self.send_error(400)
                    return

                owner.log_event({"event": "http-request", "path": self.path})
                if self.path.endswith("/memories/recall"):
                    with owner.condition:
                        delay = owner.delay_next_recall
                        owner.delay_next_recall = 0.0
                        fail = owner.fail_recalls
                        owner.recall_calls.append({"body": payload, "started": time.monotonic(), "finished": None})
                        call_index = len(owner.recall_calls) - 1
                        owner.condition.notify_all()
                    if delay:
                        threading.Event().wait(delay)
                    status = 503 if fail else 200
                    response = {"error": "scripted Hindsight failure"} if fail else {"results": []}
                    owner._json_response(self, status, response)
                    with owner.condition:
                        owner.recall_calls[call_index]["finished"] = time.monotonic()
                        owner.condition.notify_all()
                    return

                if self.path.endswith("/memories"):
                    with owner.condition:
                        owner.retain_calls.append(payload)
                        owner.condition.notify_all()
                    owner._json_response(self, 202, {"accepted": True})
                    return

                if self.path.endswith("/chat/completions"):
                    self.proof_response_id = f"chatcmpl-{uuid.uuid4().hex}"
                    owner._handle_model(self, payload)
                    return

                self.send_error(404)

        owner = self
        self.model_server = QuietThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.memory_server = QuietThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.model_server.daemon_threads = True
        self.memory_server.daemon_threads = True
        # Keep model and memory URLs distinct even though they share one handler class.
        self.model_url = f"http://127.0.0.1:{self.model_server.server_port}/v1"
        self.memory_url = f"http://127.0.0.1:{self.memory_server.server_port}"
        self.threads = [
            threading.Thread(target=self.model_server.serve_forever, daemon=True),
            threading.Thread(target=self.memory_server.serve_forever, daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    @staticmethod
    def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Connection", "close")
        handler.end_headers()
        try:
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_model(self, handler: BaseHTTPRequestHandler, request: dict[str, Any]) -> None:
        messages = request.get("messages", [])
        last_user = next((
            message for message in reversed(messages)
            if isinstance(message, dict) and message.get("role") == "user"
        ), {})
        observer = any(
            "read-only workflow observer" in content_text(message.get("content"))
            for message in messages if isinstance(message, dict) and message.get("role") == "system"
        )
        record = {"observer": observer, "request": request, "at": time.monotonic()}
        with self.condition:
            self.model_requests.append(record)
            self.condition.notify_all()

        if not observer:
            text = content_text(last_user.get("content"))
            match = re.search(r"PI_CASE:([A-Za-z0-9_-]+)", text)
            tag = match.group(1) if match else "UNMARKED"
            last_user_index = next((index for index in range(len(messages) - 1, -1, -1) if messages[index] is last_user), -1)
            tool_returned = any(
                isinstance(message, dict) and message.get("role") == "tool"
                for message in messages[last_user_index + 1:]
            )
            if tag == "D02_FAILED_TOOL" and not tool_returned:
                arguments = {"path": str(self.work_file.parent / "missing-proof-read-target.txt")}
                with self.condition:
                    self.primary_tool_calls.append({"name": "read", "arguments": arguments})
                    self.condition.notify_all()
                self.log_event({"event": "primary-failed-tool-call", "name": "read", "tag": tag})
                self._stream_tool_call(handler, "read", arguments)
                return
            if tag == "D03_ABORTED" and not tool_returned:
                with self.condition:
                    hold = self.hold_next_primary
                    if hold:
                        self.hold_next_primary = False
                        self.primary_held.set()
                        self.release_primary.clear()
                    self.condition.notify_all()
                if hold:
                    self.release_primary.wait(30)
            self._stream_text(handler, f"PRIMARY_RESPONSE__{tag}")
            return

        try:
            batch, user_index = extract_batch(messages)
            batch_id = str(batch.get("batchId") or f"request-{len(self.observer_calls)}")
        except Exception as error:
            self._stream_text(handler, json.dumps({"proposals": []}))
            with self.condition:
                self.observer_calls.append({"error": str(error), "request": request})
                self.condition.notify_all()
            return

        with self.condition:
            if batch_id not in self.observer_batches:
                self.observer_batches[batch_id] = batch
            tool_returned = any(
                isinstance(message, dict) and message.get("role") == "tool"
                for message in messages[user_index + 1:]
            )
            hold = self.hold_next_observer
            if hold:
                self.hold_next_observer = False
                self.observer_held.set()
                self.release_observer.clear()
            self.observer_calls.append({
                "batchId": batch_id,
                "evidence": batch.get("evidence", []),
                "request": request,
                "toolReturned": tool_returned,
                "held": hold,
            })
            self.condition.notify_all()
        self.log_event({
            "event": "observer-model-request",
            "batchId": batch_id,
            "evidenceIds": [item.get("id") for item in batch.get("evidence", []) if isinstance(item, dict)],
            "toolReturned": tool_returned,
            "toolNames": [tool.get("function", {}).get("name") for tool in request.get("tools", []) if isinstance(tool, dict)],
            "hold": hold,
        })

        if hold:
            self.release_observer.wait(30)

        source_id = str(batch.get("source", {}).get("id", ""))
        if not tool_returned and not any(call.get("sourceId") == source_id for call in self.tool_calls):
            tool_name = "read"
            for tool in request.get("tools", []):
                function = tool.get("function", {}) if isinstance(tool, dict) else {}
                if function.get("name") in {"read", "grep", "find", "ls"}:
                    tool_name = function["name"]
                    break
            if tool_name == "read":
                arguments = {"path": str(self.work_file)}
            elif tool_name == "grep":
                arguments = {"pattern": "TOOL_OUTPUT_PRIVATE_SENTINEL", "path": str(self.work_file)}
            elif tool_name == "find":
                arguments = {"path": str(self.work_file.parent), "pattern": self.work_file.name}
            else:
                arguments = {"path": str(self.work_file.parent)}
            tool_call = {"batchId": batch_id, "sourceId": source_id, "name": tool_name, "arguments": arguments}
            with self.condition:
                self.tool_calls.append(tool_call)
                self.condition.notify_all()
            self.log_event({"event": "tool-call-response", "batchId": batch_id, "name": tool_name})
            self._stream_tool_call(handler, tool_name, arguments)
            return

        evidence_ids = [
            str(item["id"]) for item in batch.get("evidence", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        evidence_text = "\n".join(
            str(item.get("summary", "")) for item in batch.get("evidence", [])
            if isinstance(item, dict)
        )
        if "BRANCH-FRICTION" in evidence_text:
            proposal = {
                "type": "improvement",
                "observation": "A prior workflow branch was revisited before choosing a different approach.",
                "recommendation": "Consider a reusable branch-comparison checklist.",
                "evidenceIds": evidence_ids,
            }
            answer = {"proposals": [proposal]}
        elif "WORKFLOW-FRICTION" in evidence_text or "manual" in evidence_text.lower():
            proposal = {
                "type": "improvement",
                "observation": "The verification checklist was repeated manually.",
                "recommendation": "Consider a reusable verification script.",
                "evidenceIds": evidence_ids,
            }
            answer = {"proposals": [proposal]}
        else:
            answer = {"proposals": []}
        with self.condition:
            cosmetic = source_id in self.cosmetic_sources and bool(answer["proposals"])
            if cosmetic:
                self.cosmetic_sources.remove(source_id)
        if cosmetic:
            proposal = answer["proposals"][0]
            proposal["observation"] = proposal["observation"].removesuffix(".") + "!"
            proposal["recommendation"] = proposal["recommendation"].removesuffix(".") + "!"
        self.log_event({"event": "proposal-response", "batchId": batch_id, "proposalCount": len(answer["proposals"]), "cosmetic": cosmetic})
        self._stream_text(handler, json.dumps(answer))

    def log_event(self, value: dict[str, Any]) -> None:
        with self.condition:
            self.events.append({"at": time.monotonic(), "unixTime": time.time(), **value})
            self.condition.notify_all()

    def _start_sse(self, handler: BaseHTTPRequestHandler) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()

    def _sse_chunk(self, handler: BaseHTTPRequestHandler, delta: dict[str, Any], finish: str | None = None) -> None:
        value = {
            "id": getattr(handler, "proof_response_id", "chatcmpl-learnings-proof"),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        line = ("data: " + json.dumps(value) + "\n\n").encode("utf-8")
        handler.wfile.write(f"{len(line):X}\r\n".encode() + line + b"\r\n")
        handler.wfile.flush()

    def _sse_end(self, handler: BaseHTTPRequestHandler) -> None:
        usage = {
            "id": getattr(handler, "proof_response_id", "chatcmpl-learnings-proof"),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": MODEL_ID,
            "choices": [],
            "usage": {"prompt_tokens": 240, "completion_tokens": 32, "total_tokens": 272},
        }
        line = ("data: " + json.dumps(usage) + "\n\n").encode("utf-8")
        try:
            handler.wfile.write(f"{len(line):X}\r\n".encode() + line + b"\r\n")
            done = b"data: [DONE]\n\n"
            handler.wfile.write(f"{len(done):X}\r\n".encode() + done + b"\r\n0\r\n\r\n")
            handler.wfile.flush()
            self.log_event({"event": "stream-end-sent"})
        except (BrokenPipeError, ConnectionResetError, OSError) as error:
            self.log_event({"event": "stream-end-error", "error": repr(error)})

    def _stream_text(self, handler: BaseHTTPRequestHandler, text: str) -> None:
        try:
            self._start_sse(handler)
            self._sse_chunk(handler, {"role": "assistant"})
            self._sse_chunk(handler, {"content": text})
            self._sse_chunk(handler, {}, "stop")
        except (BrokenPipeError, ConnectionResetError, OSError) as error:
            self.log_event({"event": "stream-text-error", "error": repr(error)})
            return
        self.log_event({"event": "stream-text-sent"})
        self._sse_end(handler)

    def _stream_tool_call(self, handler: BaseHTTPRequestHandler, name: str, arguments: dict[str, Any]) -> None:
        try:
            self._start_sse(handler)
            self._sse_chunk(handler, {"role": "assistant"})
            self._sse_chunk(handler, {
                "tool_calls": [{
                    "index": 0,
                    "id": f"call-{hashlib.sha256((json.dumps(arguments) + str(time.monotonic_ns())).encode()).hexdigest()[:12]}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }],
            })
            self._sse_chunk(handler, {}, "tool_calls")
        except (BrokenPipeError, ConnectionResetError, OSError) as error:
            self.log_event({"event": "stream-tool-error", "error": repr(error)})
            return
        self.log_event({"event": "stream-tool-sent"})
        self._sse_end(handler)

    def wait_for(self, collection: str, count: int, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        with self.condition:
            values = getattr(self, collection)
            while len(values) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"waiting for {collection} count {count}, saw {len(values)}")
                self.condition.wait(remaining)

    def start_hold(self) -> None:
        with self.condition:
            self.hold_next_observer = True
            self.observer_held.clear()
            self.release_observer.clear()

    def release_hold(self) -> None:
        self.release_observer.set()
        with self.condition:
            self.condition.notify_all()

    def start_primary_hold(self) -> None:
        with self.condition:
            self.hold_next_primary = True
            self.primary_held.clear()
            self.release_primary.clear()

    def release_primary_hold(self) -> None:
        self.release_primary.set()
        with self.condition:
            self.condition.notify_all()

    def close(self) -> None:
        self.release_hold()
        self.release_primary_hold()
        for server in (self.model_server, self.memory_server):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=1)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.log_path.write_text(chr(10).join(json.dumps(row) for row in self.events) + chr(10), encoding="utf-8")
            self.log_path.chmod(0o600)


class ForkedProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        try:
            waited, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.returncode = -1
            return self.returncode
        if waited:
            self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            result = self.poll()
            if result is not None:
                return result
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("pi", timeout)
            interval = 0.05 if deadline is None else min(0.05, max(0.0, deadline - time.monotonic()))
            threading.Event().wait(interval)


class PiTui:
    def __init__(self, command: list[str], env: dict[str, str], cwd: Path, label: str):
        self.label = label
        pid, self.master = pty.fork()
        if pid == 0:
            try:
                os.chdir(cwd)
                os.environ.clear()
                os.environ.update(env)
                os.execvpe(command[0], command, env)
            except BaseException as error:
                os.write(2, f"Pi proof child failed to exec: {error}\\n".encode())
                os._exit(127)
        fcntl.ioctl(self.master, termios_tiocswinsz(), struct.pack("HHHH", 48, 180, 0, 0))
        self.proc = ForkedProcess(pid)
        os.set_blocking(self.master, False)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.master, selectors.EVENT_READ)
        self.output = bytearray()
        self.closed = False
        self.exit_forced = False
        self._output_condition = threading.Condition()
        self._stop_reader = threading.Event()
        self._reader = threading.Thread(target=self._drain_output, daemon=True)
        self._reader.start()

    def _drain_output(self) -> None:
        while not self._stop_reader.is_set():
            try:
                ready = self.selector.select(0.1)
            except (OSError, ValueError):
                return
            for key, _ in ready:
                try:
                    chunk = os.read(key.fd, 65536)
                except OSError:
                    chunk = b""
                with self._output_condition:
                    if chunk:
                        self.output.extend(chunk)
                    else:
                        self.closed = True
                    self._output_condition.notify_all()
                if not chunk:
                    return

    def text(self) -> str:
        with self._output_condition:
            raw = bytes(self.output)
        return ANSI.sub("", raw.decode("utf-8", errors="replace").replace("\r", "\n"))

    def pump(self, timeout: float = 0.2) -> None:
        with self._output_condition:
            if not self.closed:
                self._output_condition.wait(max(0.0, timeout))

    def send(self, value: str | bytes) -> None:
        data = value.encode("utf-8") if isinstance(value, str) else value
        try:
            os.write(self.master, data)
        except OSError as error:
            raise ProofFailure(f"could not write to Pi TUI {self.label}: {error}", "T6") from error

    def sendline(self, value: str) -> None:
        self.send(value + "\r")

    def wait_text(self, needle: str, timeout: float = 12.0, start: int = 0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            visible = self.text()
            if needle in visible[start:]:
                return visible
            if self.proc.poll() is not None:
                break
            self.pump(min(0.2, max(0.0, deadline - time.monotonic())))
        tail = self.text()[-8000:]
        raise ProofFailure(
            f"Pi TUI {self.label} did not emit completion signal {needle!r}; exit={self.proc.poll()}\n{tail}",
            "T6",
        )

    def wait_start(self, timeout: float = 20.0) -> None:
        before = len(json_lines(ACTIVE_UI_LOG)) if ACTIVE_UI_LOG else 0
        self.wait_text(MODEL_ID, timeout=timeout)
        if ACTIVE_UI_LOG:
            self.wait_ui(
                ACTIVE_UI_LOG,
                lambda row: row.get("kind") == "instrumented" and row.get("installed") is True,
                timeout=timeout,
                after=before,
            )

    def wait_ui(self, log_path: Path, predicate: Callable[[dict[str, Any]], bool], timeout: float = 12.0, after: int = 0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for row in json_lines(log_path)[after:]:
                if predicate(row):
                    return row
            if self.proc.poll() is not None:
                break
            self.pump(min(0.1, max(0.0, deadline - time.monotonic())))
        tail = json_lines(log_path)[-10:]
        raise ProofFailure(f"Pi UI event signal not observed in {self.label}: {tail}", "T6")

    def exit(self, timeout: float = 5.0) -> None:
        if self.proc.poll() is None:
            self.sendline("/quit")
            deadline = time.monotonic() + timeout
            while self.proc.poll() is None and time.monotonic() < deadline:
                self.pump(min(0.1, max(0.0, deadline - time.monotonic())))
            if self.proc.poll() is None:
                # Keep later scenarios isolated, but report that orderly Pi exit failed.
                self.exit_forced = True
                with contextlib.suppress(ProcessLookupError):
                    os.kill(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=2)
        self.pump(0)
        self.close()

    def close(self) -> None:
        if self.proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=3)
        self._stop_reader.set()
        self._reader.join(timeout=1)
        with contextlib.suppress(Exception):
            self.selector.unregister(self.master)
        self.selector.close()
        with contextlib.suppress(OSError):
            os.close(self.master)
        with self._output_condition:
            self.closed = True
            self._output_condition.notify_all()


def termios_tiocswinsz() -> int:
    # TIOCSWINSZ is stable on Unix, but its integer differs by OS.
    import termios
    return termios.TIOCSWINSZ


def write_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def make_environment(root: Path, backend: ScriptedBackends, ui_log: Path) -> tuple[dict[str, str], Path, Path, Path, Path]:
    home = root / "home"
    agent = home / ".pi" / "agent"
    sessions = root / "sessions"
    xdg = root / "xdg"
    project = root / "project"
    for directory in (home, agent, sessions, xdg, project):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)

    models = {
        "providers": {
            "openai": {
                "baseUrl": backend.model_url,
                "api": "openai-completions",
                "apiKey": "local-proof-key-not-a-secret",
                "models": [{
                    "id": MODEL_ID,
                    "name": "Scripted local proof model",
                    "contextWindow": 32768,
                    "maxTokens": 2048,
                    "input": ["text"],
                    "reasoning": False,
                    "cost": {"input": 10, "output": 20, "cacheRead": 0, "cacheWrite": 0},
                }],
            },
        },
    }
    write_private(agent / "models.json", json.dumps(models, indent=2) + "\n")
    write_private(agent / "settings.json", json.dumps({
        "quietStartup": True,
        "enableInstallTelemetry": False,
        "cacheWarming": "off",
        "retry": {"enabled": False},
        "branchSummary": {"skipPrompt": True},
        "defaultTools": ["read", "grep", "find", "ls"],
    }, indent=2) + "\n")
    write_private(agent / "extensions" / "hindsight" / "config.json", json.dumps({
        "apiUrl": backend.memory_url,
        "bankId": "cartwmic",
        "apiToken": "",
        "autoRecall": False,
        "autoRetain": False,
        "requestTimeoutMs": 2500,
        "recallBudget": "low",
        "recallMaxTokens": 128,
    }, indent=2) + "\n")
    probe = agent / "learnings-proof-ui-tap.mjs"
    probe_source = r'''import fs from "node:fs";
const logPath = process.env.LEARNINGS_PROOF_UI_LOG;
function log(row) {
  if (logPath) fs.appendFileSync(logPath, `${JSON.stringify({ timestamp: new Date().toISOString(), ...row })}\n`, { mode: 0o600 });
}
function wrap(ui, method, kind) {
  const original = ui?.[method];
  if (typeof original !== "function" || original.__learningsProofTap) return false;
  const wrapped = function (...args) {
    log(kind === "notify"
      ? { kind, type: args[1] ?? "info", message: String(args[0] ?? "") }
      : { kind, title: String(args[0] ?? ""), message: String(args[1] ?? "") });
    return original.apply(this, args);
  };
  Object.defineProperty(wrapped, "__learningsProofTap", { value: true });
  try {
    Object.defineProperty(ui, method, { configurable: true, writable: true, value: wrapped });
  } catch (error) {
    log({ kind: "instrumentation-error", method, error: String(error) });
    return false;
  }
  const installed = ui[method] === wrapped;
  log({ kind: "instrumented", method, installed });
  return installed;
}
export default function (pi) {
  pi.on("session_start", (_event, ctx) => {
    wrap(ctx.ui, "notify", "notify");
    wrap(ctx.ui, "confirm", "confirm");
  });
  pi.on("agent_settled", (_event, ctx) => {
    log({ kind: "agent-settled", sessionId: ctx.sessionManager?.getSessionId?.() ?? null });
  });
  pi.on("session_tree", (event) => {
    log({ kind: "session-tree", oldLeafId: event?.oldLeafId ?? null, newLeafId: event?.newLeafId ?? null });
  });
}
'''
    write_private(probe, probe_source)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "TMPDIR": str(root / "tmp"),
        "XDG_DATA_HOME": str(xdg),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "PI_CODING_AGENT_DIR": str(agent),
        "PI_CODING_AGENT_SESSION_DIR": str(sessions),
        "PI_OFFLINE": "1",
        "PI_TELEMETRY": "0",
        "LEARNINGS_PROOF_UI_LOG": str(ui_log),
        "HINDSIGHT_API_URL": backend.memory_url,
        "HINDSIGHT_API_TOKEN": "",
        "HINDSIGHT_BANK_ID": "cartwmic",
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "NO_COLOR": "1",
    }
    Path(env["TMPDIR"]).mkdir(mode=0o700)
    Path(env["XDG_CONFIG_HOME"]).mkdir(mode=0o700)
    Path(env["XDG_CACHE_HOME"]).mkdir(mode=0o700)
    write_private(project / "tool-evidence.txt", "Relevant local checklist reference. TOOL_OUTPUT_PRIVATE_SENTINEL must stay out of opportunity Markdown.\n")
    return env, agent, sessions, xdg, project


def pi_command(env: dict[str, str], agent: Path, sessions: Path, *, session: Path | None = None, fork: Path | None = None) -> list[str]:
    pi = shutil.which("pi", path=env["PATH"])
    if not pi:
        raise ProofFailure("Pi executable not found; install Pi before running the black-box proof", "T4")
    command = [
        pi,
        "--model", MODEL,
        "--tools", "read,grep,find,ls",
        "--session-dir", str(sessions),
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--approve",
        "--offline",
        "--extension", str(EXTENSION),
        "--extension", str(agent / "learnings-proof-ui-tap.mjs"),
    ]
    if session:
        command.extend(["--session", str(session)])
    if fork:
        command.extend(["--fork", str(fork)])
    return command


def source_id(session_id: str) -> str:
    return "pi-source-" + hashlib.sha256(session_id.encode()).hexdigest()[:48]


def session_files(sessions: Path) -> list[Path]:
    roots = dict.fromkeys((sessions, *ACTIVE_SESSION_DIRS))
    return sorted({path for root in roots if root.exists() for path in root.rglob("*.jsonl")})


def parse_session(path: Path) -> list[dict[str, Any]]:
    return json_lines(path)


def primary_session(sessions: Path, *, before: set[Path] | None = None) -> Path:
    old = before or set()
    candidates = [path for path in session_files(sessions) if path not in old and not is_observer_file(path)]
    if not candidates:
        # A resumed primary already existed before the process launched.
        candidates = [path for path in session_files(sessions) if not is_observer_file(path)]
    if not candidates:
        raise ProofFailure("Pi did not create a persistent primary session JSONL", "T3")
    return max(candidates, key=lambda item: item.stat().st_mtime_ns)


def is_observer_file(path: Path) -> bool:
    return any(
        row.get("customType") == "learnings-monitor-observer"
        for row in parse_session(path)
    )


def all_observer_files(sessions: Path) -> list[Path]:
    return [path for path in session_files(sessions) if is_observer_file(path)]


def observer_files_for_source(sessions: Path, sid: str) -> list[Path]:
    return [
        path for path in all_observer_files(sessions)
        if any(
            row.get("customType") == "learnings-monitor-observer"
            and row.get("data", {}).get("sourceId") == sid
            for row in parse_session(path)
        )
    ]


def operational_state(root: Path, sid: str) -> dict[str, Any] | None:
    expected_dir = hashlib.sha256(sid.encode()).hexdigest()
    path = root / "xdg" / "pi" / "learnings-monitor" / "sources" / expected_dir / "operational.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def markdown_status(text: str) -> str | None:
    match = re.search(r"^\*\*Status:\*\*\s*(open|kept|dismissed)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def all_records(root: Path) -> list[tuple[Path, dict[str, Any], str]]:
    records = []
    base = root / "xdg" / "pi" / "learnings-monitor" / "sources"
    if not base.exists():
        return records
    for path in base.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        marker = "<!-- learnings-monitor:metadata\n"
        start = text.find(marker)
        end = text.find("\n-->", start + len(marker)) if start >= 0 else -1
        if start < 0 or end < 0:
            continue
        try:
            metadata = json.loads(text[start + len(marker):end])
        except json.JSONDecodeError:
            continue
        records.append((path, metadata, text))
    return records


def wait_records(root: Path, count: int = 1, timeout: float = 15.0) -> list[tuple[Path, dict[str, Any], str]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        records = all_records(root)
        if len(records) >= count:
            return records
        threading.Event().wait(0.025)
    raise ProofFailure(f"expected {count} local Markdown record(s), found {len(all_records(root))}", "T2")


def event_count(log: Path, kind: str, *, event_type: str | None = None, message: str | None = None) -> int:
    return sum(
        1 for row in json_lines(log)
        if row.get("kind") == kind
        and (event_type is None or row.get("type") == event_type)
        and (message is None or row.get("message") == message)
    )


def wait_record(root: Path, predicate: Callable[[dict[str, Any], str], bool], timeout: float = 15.0) -> tuple[Path, dict[str, Any], str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for item in all_records(root):
            if predicate(item[1], item[2]):
                return item
        threading.Event().wait(0.025)
    raise ProofFailure("expected Markdown change was not written", "T2")


def turn(pi: PiTui, label: str, text: str, timeout: float = 12.0) -> None:
    marker = f"PRIMARY_RESPONSE__{label}"
    before = len(pi.text())
    audit_before = len(json_lines(ACTIVE_UI_LOG)) if ACTIVE_UI_LOG else 0
    pi.sendline(text)
    pi.wait_text(marker, timeout=timeout, start=before)
    if ACTIVE_UI_LOG:
        pi.wait_ui(
            ACTIVE_UI_LOG,
            lambda row: row.get("kind") == "agent-settled",
            timeout=timeout,
            after=audit_before,
        )


def assistant_for_case(session: Path, label: str) -> dict[str, Any] | None:
    rows = parse_session(session)
    for index, row in enumerate(rows):
        message = row.get("message", {})
        if row.get("type") != "message" or message.get("role") != "user":
            continue
        if f"PI_CASE:{label}" not in content_text(message.get("content")):
            continue
        for candidate in rows[index + 1:]:
            current = candidate.get("message", {})
            if candidate.get("type") == "message" and current.get("role") == "assistant":
                return current
    return None


def tree_navigate(pi: PiTui, log: Path, session: Path, assistant_marker: str) -> dict[str, Any]:
    targets = [
        row for row in parse_session(session)
        if row.get("type") == "message"
        and row.get("message", {}).get("role") == "assistant"
        and assistant_marker in content_text(row.get("message", {}).get("content"))
    ]
    require(len(targets) == 1, f"expected one /tree target for {assistant_marker}, found {len(targets)}", "T3")
    target_id = targets[0].get("id")
    before_text = len(pi.text())
    before_log = len(json_lines(log))
    pi.sendline("/tree")
    pi.wait_text("Session Tree", timeout=12, start=before_text)
    search_text = assistant_marker.lower()
    pi.send(search_text)
    pi.wait_text(search_text, timeout=12, start=before_text)
    pi.send(b"\r")
    event = pi.wait_ui(
        log,
        lambda row: row.get("kind") == "session-tree" and row.get("newLeafId") == target_id,
        timeout=12,
        after=before_log,
    )
    require(event.get("oldLeafId") != event.get("newLeafId"), "/tree reported no branch navigation", "T3")
    return event


def abort_primary_turn(pi: PiTui, backend: ScriptedBackends, log: Path, session: Path, label: str) -> None:
    before_log = len(json_lines(log))
    pi.sendline(f"PI_CASE:{label} WORKFLOW-FRICTION: I was interrupted before verifying this workflow attempt.")
    if not backend.primary_held.wait(10):
        raise ProofFailure(f"scripted primary response for {label} never entered its held in-flight state", "T6")
    pi.send(b"\x1b")
    pi.wait_ui(
        log,
        lambda row: row.get("kind") == "agent-settled",
        timeout=12,
        after=before_log,
    )
    backend.release_primary_hold()
    wait_condition(
        lambda: (assistant_for_case(session, label) or {}).get("stopReason") == "aborted",
        f"Pi to persist an aborted assistant turn for {label}",
        owner="T3",
    )


def command(pi: PiTui, log: Path, value: str, expected: str, *, timeout: float = 12.0) -> dict[str, Any]:
    before = len(json_lines(log))
    pi.sendline(value)
    return pi.wait_ui(
        log,
        lambda row: row.get("kind") == "notify" and expected in row.get("message", ""),
        timeout=timeout,
        after=before,
    )


def observer_call_count(backend: ScriptedBackends) -> int:
    with backend.condition:
        return sum(1 for row in backend.model_requests if row.get("observer"))


def observer_batch_count(backend: ScriptedBackends) -> int:
    with backend.condition:
        return len(backend.observer_batches)


def current_state(root: Path, session: Path) -> tuple[str, dict[str, Any]]:
    header = next((row for row in parse_session(session) if row.get("type") == "session"), {})
    sid = source_id(str(header.get("id", "")))
    state = operational_state(root, sid)
    if state is None:
        raise ProofFailure("monitor operational state is missing", "T2")
    return sid, state


def primary_user_messages(path: Path) -> list[str]:
    result = []
    for row in parse_session(path):
        if row.get("type") == "message" and row.get("message", {}).get("role") == "user":
            result.append(content_text(row["message"].get("content")))
    return result


def append_saved_unqueued_exchange(primary: Path, sessions: Path, env: dict[str, str]) -> None:
    """Simulate a crash after Pi saved an assistant but before agent_settled ran."""
    pi = shutil.which("pi", path=env["PATH"])
    node = shutil.which("node", path=env["PATH"])
    require(bool(pi and node), "Pi and Node are required to create a saved-unseen fixture", "T8")
    sdk = Path(pi).resolve().parents[2] / "dist/index.js"
    require(sdk.is_file(), f"Pi SDK is unavailable at {sdk}", "T8")
    script = r'''import { pathToFileURL } from "node:url";
const { SessionManager } = await import(pathToFileURL(process.argv[1]).href);
const manager = SessionManager.open(process.argv[2], process.argv[3]);
const branch = manager.getBranch();
const user = [...branch].reverse().find((entry) => entry.type === "message" && entry.message?.role === "user")?.message;
const assistant = [...branch].reverse().find((entry) => entry.type === "message" && entry.message?.role === "assistant")?.message;
if (!user || !assistant) throw new Error("no completed primary exchange to clone");
manager.appendMessage({ ...user, content: "PI_CASE:SAVED_UNQUEUED WORKFLOW-FRICTION: a completed exchange saved before its settled callback.", timestamp: Date.now() });
const id = manager.appendMessage({ ...assistant, content: [{ type: "text", text: "PRIMARY_RESPONSE__SAVED_UNQUEUED" }], stopReason: "stop", timestamp: Date.now() + 1 });
console.log(id);
'''
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, str(sdk), str(primary), str(sessions)],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=15, check=False,
    )
    require(result.returncode == 0, f"could not save the unqueued Pi exchange: {result.stderr.strip()}", "T8")
    require(any(row.get("id") == result.stdout.strip() for row in parse_session(primary)), "saved assistant entry was not persisted", "T8")


def queue_replayed_evidence(root: Path, sid: str, metadata: dict[str, Any]) -> str:
    """Set up a durable retry with the same source evidence while Pi is stopped."""
    state_path = root / "xdg" / "pi" / "learnings-monitor" / "sources" / hashlib.sha256(sid.encode()).hexdigest() / "operational.json"
    state = operational_state(root, sid) or {}
    require(state.get("enabled") is True and state.get("pending") == [], "replay fixture needs an enabled, drained source", "T8")
    item = metadata["evidence"][0]
    require(item["sourceId"] == sid, "replay evidence belongs to a different source", "T8")
    evidence = {key: item[key] for key in ("summary", "outcome", "provenance")}
    evidence["id"] = item["evidenceId"]
    if item.get("occurredAt"):
        evidence["occurredAt"] = item["occurredAt"]
    state["pending"] = [{
        "id": f"proof-replay-{uuid.uuid4().hex}",
        "payload": {"source": {"id": sid, "label": item.get("sourceLabel", sid)}, "evidence": [evidence]},
        "cursorAfter": state["cursor"],
    }]
    temporary = state_path.with_name(f"operational-{uuid.uuid4().hex}.tmp")
    write_private(temporary, json.dumps(state, indent=2) + "\n")
    os.replace(temporary, state_path)
    return evidence["id"]


def status_for(pi: PiTui, log: Path) -> dict[str, Any]:
    return command(pi, log, "/learnings status", "Learnings monitor:")


def wait_batch_processed(backend: ScriptedBackends, root: Path, sid: str, batch_count: int, recall_count: int, timeout: float = 60.0) -> dict[str, Any]:
    try:
        backend.wait_for("recall_calls", recall_count, timeout=timeout)
    except TimeoutError as error:
        with backend.condition:
            last_observer = backend.observer_calls[-1] if backend.observer_calls else None
            last_batch_id = last_observer.get("batchId") if last_observer else None
            response_sent = any(
                row.get("event") == "proposal-response" and row.get("batchId") == last_batch_id
                for row in backend.events
            )
        owner = "T6" if response_sent else "T4"
        boundary = "scripted proposal reached Pi but runtime did not perform the candidate-memory step" if response_sent else "native observer did not complete its model/tool round-trip"
        raise ProofFailure(
            f"{boundary} for expected recall {recall_count}; "
            f"last observer call={last_observer and {key: last_observer.get(key) for key in ('batchId', 'evidence', 'toolReturned', 'held')}}; "
            f"pending={operational_state(root, sid) and len(operational_state(root, sid).get('pending', []))}",
            owner,
        ) from error
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = operational_state(root, sid)
        with backend.condition:
            batches = len(backend.observer_batches)
        if state and not state.get("pending") and batches >= batch_count:
            return state
        with backend.condition:
            backend.condition.wait(0.025)
    raise ProofFailure(
        f"observer batch {batch_count} saved or proposed work but did not advance the durable capture checkpoint; "
        f"state={operational_state(root, sid)}; records={[len(item[1].get('evidence', [])) for item in all_records(root)]}; "
        f"observer requests={observer_call_count(backend)}; recalls={len(backend.recall_calls)}",
        "T3",
    )


def edit_observation(markdown_path: Path, replacement: str) -> None:
    text = markdown_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(<!-- learnings-monitor:begin:observation -->\n).*?(\n<!-- learnings-monitor:end:observation -->)",
        re.DOTALL,
    )
    updated, count = pattern.subn(lambda match: match.group(1) + replacement + match.group(2), text, count=1)
    if count != 1:
        raise ProofFailure(f"could not edit authoritative Observation section in {markdown_path}", "T2")
    markdown_path.write_text(updated, encoding="utf-8")


def parse_usage(session: Path) -> tuple[int, float, int, list[str]]:
    total_tokens = 0
    total_cost = 0.0
    tool_calls = []
    assistant_messages = 0
    for row in parse_session(session):
        if row.get("type") != "message":
            continue
        message = row.get("message", {})
        if message.get("role") == "assistant":
            assistant_messages += 1
            usage = message.get("usage", {})
            total_tokens += int(usage.get("totalTokens", usage.get("total_tokens", 0)) or 0)
            cost = usage.get("cost", {})
            total_cost += float(cost.get("total", 0) or 0) if isinstance(cost, dict) else 0.0
            for part in message.get("content", []) if isinstance(message.get("content"), list) else []:
                if part.get("type") == "toolCall":
                    tool_calls.append(str(part.get("name")))
    return total_tokens, total_cost, assistant_messages, tool_calls


def wait_condition(predicate: Callable[[], bool], description: str, timeout: float = 15.0, owner: str = "T2") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.025)
    raise ProofFailure(f"timed out waiting for {description}", owner)


def run_integrated(root: Path, backend: ScriptedBackends, env: dict[str, str], agent: Path, sessions: Path, xdg: Path, project: Path) -> dict[str, Any]:
    global ACTIVE_UI_LOG, ACTIVE_SESSION_DIRS
    log = root / "ui-events.jsonl"
    ACTIVE_UI_LOG = log
    ACTIVE_SESSION_DIRS = (sessions, agent / "sessions")
    pi = PiTui(pi_command(env, agent, sessions), env, project, "primary")
    child: PiTui | None = None
    replayed_child: PiTui | None = None
    resumed: PiTui | None = None
    resumed_off: PiTui | None = None
    report: dict[str, Any] = {"scenario": "isolated-primary-and-fork", "checks": []}

    def ensure_observer_started(target_count: int, label: str) -> None:
        try:
            backend.wait_for("observer_calls", target_count, timeout=60)
        except TimeoutError:
            state = operational_state(root, sid) or {}
            # The capture bridge creates and associates the native session only
            # after automatic threshold scheduling enters the observer runner.
            # A missing model request after that boundary belongs to the worker,
            # not to the scheduler; do not hide it by forcing an explicit flush.
            discovered_workers = observer_files_for_source(sessions, sid)
            if state.get("workerSession"):
                return
            failures = report.setdefault("integrationFailures", [])
            if not any(item.get("scenario") == "automatic threshold scheduling" for item in failures):
                failures.append({
                    "owner": "T3",
                    "scenario": "automatic threshold scheduling",
                    "detail": f"Three finalized primary exchanges ({label}) remained pending after 15s without an observer provider request; pending={len(state.get('pending', []))}, workerSessionAssociation={state.get('workerSession')!r}, discoveredObserverFiles={[str(item) for item in discovered_workers]}.",
                })
            command(pi, log, "/learnings flush", "Observer flush queued")
            try:
                backend.wait_for("observer_calls", target_count, timeout=60)
            except TimeoutError as error:
                state = operational_state(root, sid) or {}
                worker_path = Path(str(state.get("workerSession", ""))) if state.get("workerSession") else None
                raise ProofFailure(
                    f"observer did not reach the scripted model after explicit flush ({label}); "
                    f"pending={len(state.get('pending', []))}, worker={str(worker_path) if worker_path else None!r}, "
                    f"workerFileExists={bool(worker_path and worker_path.is_file())}, "
                    f"modelRequests={len(backend.model_requests)}, "
                    f"backendEvents={[row.get('event') for row in backend.events]}",
                    "T4",
                    report.get("integrationFailures", []),
                ) from error

    try:
        pi.wait_start()
        wait_condition(
            lambda: any(row.get("kind") == "instrumented" and row.get("installed") for row in json_lines(log)),
            "Pi test UI signal tap installation", owner="T6",
        )

        # Negative control: an off-by-default primary exchange cannot create a worker or note.
        turn(pi, "OPT_OUT_NEGATIVE", "PI_CASE:OPT_OUT_NEGATIVE ordinary unmonitored task", timeout=12)
        require(not all_records(root), "opt-in default was not OFF: an unmonitored turn wrote a proposal", "T3")
        require(not all_observer_files(sessions), "opt-in default was not OFF: an unmonitored turn created an observer", "T4")
        report["checks"].append("default-off-negative")

        command(pi, log, "/learnings on", "Learnings monitor ON")
        wait_condition(lambda: bool([p for p in session_files(sessions) if not is_observer_file(p)]), "primary persistent session", owner="T3")
        primary = primary_session(sessions)
        sid, state = current_state(root, primary)
        require(state.get("enabled") is True, "on command did not persist enabled state", "T6")

        # Trigger one bounded three-exchange batch against delayed failing memory.
        backend.fail_recalls = True
        backend.delay_next_recall = 1.8
        primary_turn_started = time.monotonic()
        for label in ("A01", "A02", "A03"):
            if label == "A03":
                primary_turn_started = time.monotonic()
            turn(pi, label, f"PI_CASE:{label} WORKFLOW-FRICTION: I manually repeat the same verification checklist across services.")
            if label == "A03":
                first_primary_elapsed = time.monotonic() - primary_turn_started
        ensure_observer_started(1, "initial fresh-state batch")
        try:
            backend.wait_for("recall_calls", 1, timeout=60)
        except TimeoutError as error:
            state = operational_state(root, sid) or {}
            discovered_workers = observer_files_for_source(sessions, sid)
            worker_path = Path(state["workerSession"]) if state.get("workerSession") else (discovered_workers[0] if discovered_workers else None)
            worker_entries = parse_session(worker_path) if worker_path and worker_path.is_file() else []
            tool_calls = [
                part.get("name")
                for row in worker_entries if row.get("type") == "message"
                for part in row.get("message", {}).get("content", [])
                if row.get("message", {}).get("role") == "assistant" and part.get("type") == "toolCall"
            ]
            tool_results = sum(
                row.get("type") == "message" and row.get("message", {}).get("role") == "toolResult"
                for row in worker_entries
            )
            proposals = sum(row.get("event") == "proposal-response" for row in backend.events)
            observer_requests = observer_call_count(backend)
            assistant_messages = [
                row.get("message", {}) for row in worker_entries
                if row.get("type") == "message" and row.get("message", {}).get("role") == "assistant"
            ]
            last_assistant_stop = assistant_messages[-1].get("stopReason") if assistant_messages else None
            final_response_saved = last_assistant_stop == "stop"
            owner = "T6" if final_response_saved and proposals else "T4"
            raise ProofFailure(
                f"scripted Hindsight was not called for the fresh-state batch; "
                f"observerRequests={observer_requests}, toolCalls={tool_calls}, toolResults={tool_results}, "
                f"proposalResponses={proposals}, lastAssistantStop={last_assistant_stop!r}, "
                f"pending={len(state.get('pending', []))}, "
                f"workerSessionAssociation={state.get('workerSession')!r}, "
                f"discoveredWorkerFiles={[str(path) for path in discovered_workers]}, "
                f"workerFileExists={bool(worker_path and worker_path.is_file())}, "
                f"modelRequests={len(backend.model_requests)}, "
                f"backendEvents={[row.get('event') for row in backend.events]}; "
                "the observer response did not reach the local memory lookup path",
                owner,
                report.get("integrationFailures", []),
                scenario="initial fresh-state observer/tool round-trip",
            ) from error
        first_recall = backend.recall_calls[0]
        require(
            first_recall.get("finished") is None and "PRIMARY_RESPONSE__A03" in pi.text(),
            "the primary turn did not complete while its delayed Hindsight lookup was still pending",
            "T5",
        )
        try:
            wait_batch_processed(backend, root, sid, 1, 1)
        except ProofFailure as error:
            debug_status = status_for(pi, log)
            raise ProofFailure(f"{error}; user-visible status after batch failure: {debug_status.get('message', '')}", error.owner) from error
        record_path, metadata, markdown = wait_records(root)[0]
        require(markdown_status(markdown) == "open", "fresh-state proposal is not open for review", "T1")
        require(metadata.get("type") == "improvement", "scripted proposal did not produce an improvement note", "T1")
        require(metadata.get("evidenceAssessment", {}).get("claim") == "recurring", "three distinct captured exchanges did not support a recurring claim", "T1")
        require(len(metadata.get("evidence", [])) == 3, "initial worker batch did not include exactly three incremental exchanges", "T3")
        require("verification checklist" in markdown and "Consider a reusable" in markdown, "grounded proposal was not written after Hindsight failure", "T2")
        require("TOOL_OUTPUT_PRIVATE_SENTINEL" not in markdown, "full read-tool output leaked into opportunity Markdown", "T2")
        require(event_count(log, "notify", event_type="warning", message=WARNING) == 0, "normal detached pass warned before status inspection", "T6")
        report["checks"].append("AC-5-fail-open-primary-completes")

        # A read-only tool call and native persisted transcript/cost are required.
        first_state = operational_state(root, sid) or {}
        worker_path = Path(str(first_state.get("workerSession", "")))
        require(worker_path.is_file(), "observer session locator is not a persisted Pi JSONL path", "T4")
        require(worker_path.resolve().is_relative_to(root.resolve()), "observer session escaped the private proof artifact root", "T4")
        worker_entries = parse_session(worker_path)
        require(any(row.get("customType") == "learnings-monitor-observer" for row in worker_entries), "observer transcript lacks its ownership marker", "T4")
        tokens, cost, assistant_count, tools_used = parse_usage(worker_path)
        require("read" in tools_used, "native observer transcript does not show a real read-tool call", "T4")
        require(any(row.get("type") == "message" and row.get("message", {}).get("role") == "toolResult" and "TOOL_OUTPUT_PRIVATE_SENTINEL" in content_text(row.get("message", {}).get("content")) for row in worker_entries), "observer Pi transcript does not contain the scripted read result", "T4")
        require(tokens > 0 and cost > 0 and assistant_count >= 2, f"native observer usage/cost missing: tokens={tokens} cost={cost} assistant={assistant_count}", "T4")

        # Status converts the failure into one warning; repeated inspection does not spam.
        first_status = status_for(pi, log)
        require("(failed)" in first_status.get("message", "") and any(kind in first_status.get("message", "") for kind in ("http-error", "timeout")), "Pi status did not expose the failed Hindsight lookup", "T6")
        require(str(worker_path) in first_status.get("message", ""), "Pi status omitted the native observer session path", "T6")
        require("Native usage:" in first_status.get("message", "") and "$0.0000" not in first_status.get("message", ""), "Pi status omitted nonzero native usage and cost", "T6")
        require(event_count(log, "notify", event_type="warning", message=WARNING) == 1, "first persistent memory failure did not produce exactly one warning", "T6")
        status_for(pi, log)
        require(event_count(log, "notify", event_type="warning", message=WARNING) == 1, "repeated status inspection emitted duplicate warnings", "T6")

        # A second failing pass is still one warning for the persistent failure period.
        # Hold its native model response and drive status through the real Pi command.
        backend.start_hold()
        next_observer_call = observer_call_count(backend) + 1
        for label in ("B01", "B02", "B03"):
            turn(pi, label, f"PI_CASE:{label} WORKFLOW-FRICTION: I manually repeat the same verification checklist across services.")
        ensure_observer_started(next_observer_call, "repeated-failure batch")
        require(backend.observer_held.wait(10), "repeated-failure observer did not enter its held response", "T4")
        try:
            status_started = time.monotonic()
            held_status = status_for(pi, log)
            require(time.monotonic() - status_started < 6, "status waited on the held observer response", "T6")
            require("Pending: 3 batch(es)" in held_status.get("message", ""), "held status omitted the durable pending work", "T6")
            require(str(worker_path) in held_status.get("message", ""), "held status omitted the native observer session", "T6")
            require(event_count(log, "notify", event_type="warning", message=WARNING) == 1, "held observer triggered an extra warning", "T6")
        finally:
            backend.release_hold()
        report["checks"].append("AC-2-AC-21-status-while-observer-held")
        try:
            wait_batch_processed(backend, root, sid, 2, 2)
        except ProofFailure as error:
            debug_status = status_for(pi, log)
            raise ProofFailure(
                f"{error}; user-visible status after retry: {debug_status.get('message', '')}; "
                f"earlier integration failures: {report.get('integrationFailures', [])}",
                error.owner,
            ) from error
        status_for(pi, log)
        require(event_count(log, "notify", event_type="warning", message=WARNING) == 1, "repeated observer/memory failure warned more than once", "T6")
        report["checks"].append("AC-22-one-warning-for-repeated-failures")

        # Recovery resets failure health. A successful pass must be silent.
        backend.fail_recalls = False
        before_warning = event_count(log, "notify", event_type="warning", message=WARNING)
        next_observer_call = observer_call_count(backend) + 1
        for label in ("C01", "C02", "C03"):
            turn(pi, label, f"PI_CASE:{label} WORKFLOW-FRICTION: I manually repeat the same verification checklist across services.")
        ensure_observer_started(next_observer_call, "successful recovery batch")
        wait_batch_processed(backend, root, sid, 3, 3)
        wait_condition(lambda: not (operational_state(root, sid) or {}).get("pending"), "successful observer pass", owner="T4")
        status_after_recovery = status_for(pi, log)
        require("(failed)" not in status_after_recovery.get("message", "") and "Failure:" not in status_after_recovery.get("message", ""), "successful Hindsight lookup did not clear failure health", "T6")
        require(event_count(log, "notify", event_type="warning", message=WARNING) == before_warning, "successful observer/memory pass emitted a warning", "T6")
        report["checks"].append("failure-recovery-is-silent")

        # Create a real alternate Pi /tree branch, record its evidence, then leave
        # it and verify the historical note stays distinct from the active branch.
        tree_navigate(pi, log, primary, "PRIMARY_RESPONSE__A02")
        turn(
            pi,
            "BRANCH01",
            "PI_CASE:BRANCH01 BRANCH-FRICTION: I revisited an earlier workflow point before choosing a different approach.",
        )
        wait_condition(lambda: len((operational_state(root, sid) or {}).get("pending", [])) == 1, "branch evidence to become pending", owner="T3")
        branch_pending = (operational_state(root, sid) or {}).get("pending", [])
        branch_evidence = branch_pending[0]["payload"]["evidence"][0]
        branch_context = branch_evidence.get("provenance", {}).get("context", "")
        require(re.fullmatch(r"branch:[a-f0-9]+", branch_context) is not None, f"real Pi branch evidence lacks branch provenance: {branch_context!r}", "T3")
        require(branch_evidence.get("outcome") == "completed", "branch evidence did not preserve the completed primary outcome", "T3")
        command(pi, log, "/learnings flush", "Observer flush queued")
        wait_batch_processed(backend, root, sid, 4, 4)
        _branch_record_path, branch_metadata, branch_markdown = wait_record(
            root,
            lambda meta, _text: any(
                item.get("provenance", {}).get("context") == branch_context
                for item in meta.get("evidence", [])
            ),
            timeout=15,
        )
        require("branch-comparison checklist" in branch_markdown, "branch-grounded proposal was not written to Markdown", "T2")
        main_tree_event = tree_navigate(pi, log, primary, "PRIMARY_RESPONSE__C03")
        require(main_tree_event.get("newLeafId") != main_tree_event.get("oldLeafId"), "Pi /tree did not leave the insight-producing branch", "T3")
        main_status = status_for(pi, log)
        active_branch_match = re.search(r"^Branch: (.+)$", main_status.get("message", ""), re.MULTILINE)
        require(active_branch_match is not None, "Pi status omitted the active branch after /tree navigation", "T6")
        active_branch = active_branch_match.group(1)
        require(active_branch != branch_context, "the abandoned branch insight was presented as the active branch", "T3")
        branch_review = command(pi, log, f"/learnings-review {sid}", "Learnings review")
        require(branch_metadata["id"] in branch_review.get("message", ""), "Pi review omitted the insight from the abandoned branch", "T7")
        require(branch_context in branch_review.get("message", ""), "Pi review omitted the branch provenance of the historical insight", "T7")
        report["checks"].append("AC-20-real-tree-branch-provenance")

        # User Markdown edit is authoritative; the next generated update must preserve it.
        edit_observation(record_path, "Operator-edited observation stays authoritative: EDITED_OBSERVATION_SENTINEL.")

        # Stop a real in-flight native worker while the primary is idle. The
        # batch also carries failed-tool and aborted-turn evidence for AC-29.
        backend.start_hold()
        next_observer_call = observer_call_count(backend) + 1
        turn(pi, "D01", "PI_CASE:D01 WORKFLOW-FRICTION: I manually repeat the same verification checklist across services.")
        turn(pi, "D02_FAILED_TOOL", "PI_CASE:D02_FAILED_TOOL WORKFLOW-FRICTION: A read attempt failed before the checklist could be verified.")
        require(bool(backend.primary_tool_calls), "scripted primary did not issue its deliberately failing read tool call", "T6")
        wait_condition(lambda: len((operational_state(root, sid) or {}).get("pending", [])) == 2, "two pre-cancellation evidence snapshots", owner="T3")
        backend.start_primary_hold()
        abort_primary_turn(pi, backend, log, primary, "D03_ABORTED")
        ensure_observer_started(next_observer_call, "cancellation batch")
        require(backend.observer_held.wait(10), "scripted observer request never entered the held in-flight state", "T4")
        _, pre_off_state = current_state(root, primary)
        pending_evidence = [
            evidence
            for batch in pre_off_state.get("pending", [])
            for evidence in batch.get("payload", {}).get("evidence", [])
        ]
        failed_evidence = next((item for item in pending_evidence if item.get("outcome") == "failed"), None)
        incomplete_evidence = next((item for item in pending_evidence if item.get("outcome") == "incomplete"), None)
        require(failed_evidence is not None and "Tool read — failed" in failed_evidence.get("summary", ""), "failed tool attempt was not labeled failed in captured evidence", "T3")
        require(incomplete_evidence is not None and "D03_ABORTED" in incomplete_evidence.get("summary", ""), "aborted primary turn was not labeled incomplete in captured evidence", "T3")
        require("success" not in failed_evidence.get("summary", "").lower(), "failed tool evidence claimed a successful outcome", "T3")
        command(pi, log, "/learnings off", "Learnings monitor OFF")
        _, off_state = current_state(root, primary)
        require(off_state.get("enabled") is False, "off command did not persist disabled state", "T6")
        require(len(off_state.get("pending", [])) == 3, f"off/cancellation lost pending activity: {len(off_state.get('pending', []))}", "T3")
        require(len(pending_evidence) == 3, f"failed/aborted evidence changed the expected three-item cancellation batch: {len(pending_evidence)}", "T3")
        report["checks"].append("AC-29-failed-tool-and-aborted-turn-provenance")
        backend.release_hold()
        before_off_batch_count = observer_batch_count(backend)
        turn(pi, "OFF_NEGATIVE", "PI_CASE:OFF_NEGATIVE this primary turn must not be captured while the monitor is OFF")
        _, off_state = current_state(root, primary)
        require(len(off_state.get("pending", [])) == 3, "off mode captured or discarded activity instead of retaining the existing pending batch", "T3")
        require(observer_batch_count(backend) == before_off_batch_count, "off mode scheduled automatic observer work", "T3")
        report["checks"].append("AC-10-off-cancels-only-observer-and-retains-pending")

        # Resume the pending batch and prove direct Markdown edits survive the update.
        command(pi, log, "/learnings on", "Learnings monitor ON")
        wait_batch_processed(backend, root, sid, 5, 5)
        edited_path, edited_meta, edited_markdown = wait_record(
            root,
            lambda meta, text: meta.get("id") == metadata.get("id") and "EDITED_OBSERVATION_SENTINEL" in text,
            timeout=15,
        )
        require("EDITED_OBSERVATION_SENTINEL" in edited_markdown, "observer update replaced the operator's authoritative Markdown edit", "T2")
        require(len(edited_meta.get("evidence", [])) == 12, f"resumed batch did not add exactly its three new evidence items: {len(edited_meta.get('evidence', []))}", "T2")
        report["checks"].append("AC-23-markdown-edit-preserved")

        # An explicit flush drains one below-threshold delta without a primary model call.
        before_batches = observer_batch_count(backend)
        before_models = len(backend.model_requests)
        turn(pi, "FLUSH_ONE", "PI_CASE:FLUSH_ONE WORKFLOW-FRICTION: I manually repeat the same verification checklist across services.")
        wait_condition(lambda: len((operational_state(root, sid) or {}).get("pending", [])) == 1, "below-threshold pending snapshot", owner="T3")
        _, pending_state = current_state(root, primary)
        require(len(pending_state.get("pending", [])) == 1, "single below-threshold exchange was not retained as pending", "T3")
        require(observer_batch_count(backend) == before_batches, "below-threshold activity triggered an automatic pass", "T3")
        command(pi, log, "/learnings flush", "Observer flush queued")
        wait_batch_processed(backend, root, sid, before_batches + 1, 5)
        require(len(backend.model_requests) > before_models, "explicit flush did not reach the observer model", "T4")
        require(not any("FLUSH_ONE" in text for text in primary_user_messages(primary) if text.startswith("/learnings")), "flush command mutated the primary conversation", "T6")
        report["checks"].append("AC-27-explicit-flush")

        # Shutdown with a sub-threshold batch returns immediately and resume processes it.
        before_resume_batches = observer_batch_count(backend)
        turn(pi, "PENDING_EXIT", "PI_CASE:PENDING_EXIT WORKFLOW-FRICTION: I manually repeat the same verification checklist across services.")
        wait_condition(lambda: len((operational_state(root, sid) or {}).get("pending", [])) == 1, "shutdown pending snapshot", owner="T3")
        _, pending_exit_state = current_state(root, primary)
        require(len(pending_exit_state.get("pending", [])) == 1, "shutdown setup did not leave one durable pending exchange", "T3")
        pending_status = status_for(pi, log)
        require("Pending: 1 batch(es), 1 evidence item(s)" in pending_status.get("message", ""), "Pi status did not expose the unprocessed shutdown batch", "T6")
        pi.exit()
        require(len((operational_state(root, sid) or {}).get("pending", [])) == 1, "Pi shutdown discarded the pending activity", "T2")
        require(observer_batch_count(backend) == before_resume_batches, "Pi waited for or started an observer pass while shutting down", "T3")
        if pi.exit_forced:
            report.setdefault("integrationFailures", []).append({
                "owner": "T3",
                "scenario": "idle primary shutdown with pending activity",
                "detail": "Pi did not exit after /quit with the private PTY drained; the harness force-killed it only to continue isolated resume checks.",
            })
        append_saved_unqueued_exchange(primary, sessions, env)
        require(len((operational_state(root, sid) or {}).get("pending", [])) == 1, "offline Pi save incorrectly queued the exchange without a settled hook", "T3")
        require(observer_batch_count(backend) == before_resume_batches, "offline Pi save started an observer", "T4")

        resumed = PiTui(pi_command(env, agent, sessions, session=primary), env, project, "resume")
        resumed.wait_start()
        try:
            wait_condition(lambda: (operational_state(root, sid) or {}).get("pending") == [], "resume to drain pending work", timeout=60, owner="T3")
        except ProofFailure as error:
            state = operational_state(root, sid) or {}
            raise ProofFailure(
                f"resumed primary left durable activity pending: pending={len(state.get('pending', []))}, "
                f"observer model calls={observer_call_count(backend)}, worker={state.get('workerSession')}; "
                f"previous shutdown forced={pi.exit_forced}",
                "T3",
            ) from error
        wait_condition(lambda: observer_batch_count(backend) >= before_resume_batches + 1, "resumed observer batch", owner="T4")
        resume_batch = list(backend.observer_batches.values())[-1]
        require(len(resume_batch.get("evidence", [])) == 2, "resume skipped the saved-unseen exchange or reread the full Pi session", "T3")
        resume_summaries = "\n".join(item.get("summary", "") for item in resume_batch["evidence"])
        require("PENDING_EXIT" in resume_summaries, "resume skipped the durable pending exchange", "T3")
        require("SAVED_UNQUEUED" in resume_summaries, "resume skipped the finalized exchange saved before agent_settled", "T3")
        resumed_state = operational_state(root, sid) or {}
        require(resumed_state.get("workerSession") == str(worker_path), "resuming the primary created a new observer instead of continuing its native worker", "T4")
        report["checks"].append("AC-14-saved-unseen-recovery-and-AC-15-pending-shutdown")

        # Review surface reads the edited Markdown; keep/dismiss changes that same file.
        current_record = next(item for item in all_records(root) if item[1].get("id") == metadata.get("id"))
        record_id = str(current_record[1]["id"])
        review = command(resumed, log, "/learnings-review", "Learnings review")
        require("EDITED_OBSERVATION_SENTINEL" in review.get("message", ""), "Pi review did not show the direct Markdown edit", "T7")
        command(resumed, log, f"/learnings-keep {record_id}", "Authoritative Markdown updated")
        kept = next(item for item in all_records(root) if item[1].get("id") == record_id)
        require(markdown_status(kept[2]) == "kept", "keep command did not update authoritative Markdown", "T7")
        keep_review = command(resumed, log, f"/learnings-review {sid}", "Learnings review")
        require("[KEPT]" in keep_review.get("message", ""), "Pi review status diverged from the kept Markdown record", "T7")

        # Cancel promotion through the actual Pi confirmation UI, then confirm exact text.
        before_confirm = len(json_lines(log))
        before_modal = len(resumed.text())
        resumed.sendline(f"/learnings-promote {record_id}")
        resumed.wait_ui(log, lambda row: row.get("kind") == "confirm" and row.get("title") == "Promote kept opportunity to Hindsight", timeout=12, after=before_confirm)
        resumed.wait_text("Send this exact text?", start=before_modal)
        # Pi's confirmation selector starts on Yes; Down then Enter is an actual cancellation.
        before_cancel = len(json_lines(log))
        resumed.send(b"\x1b[B\r")
        cancel_note = resumed.wait_ui(log, lambda row: row.get("kind") == "notify" and "Promotion cancelled" in row.get("message", ""), timeout=12, after=before_cancel)
        require(not backend.retain_calls, "cancelled promotion sent a Hindsight retain request", "T5")
        require("EDITED_OBSERVATION_SENTINEL" not in cancel_note.get("message", "") or "remains kept" in cancel_note.get("message", ""), "cancelled promotion did not preserve the kept local record", "T7")

        before_confirm = len(json_lines(log))
        before_modal = len(resumed.text())
        resumed.sendline(f"/learnings-promote {record_id}")
        preview = resumed.wait_ui(log, lambda row: row.get("kind") == "confirm" and row.get("title") == "Promote kept opportunity to Hindsight", timeout=12, after=before_confirm)
        resumed.wait_text("Send this exact text?", start=before_modal)
        require("EDITED_OBSERVATION_SENTINEL" in preview.get("message", ""), "promotion preview did not show exact edited Markdown text", "T5")
        require("TOOL_OUTPUT_PRIVATE_SENTINEL" not in preview.get("message", "") and "pi-session://" not in preview.get("message", ""), "promotion preview included raw evidence or source pointers", "T5")
        before_accept = len(json_lines(log))
        resumed.send(b"\r")
        resumed.wait_ui(log, lambda row: row.get("kind") == "notify" and "Hindsight accepted the asynchronous request" in row.get("message", ""), timeout=12, after=before_accept)
        backend.wait_for("retain_calls", 1, timeout=8)
        sent_text = backend.retain_calls[0].get("items", [{}])[0].get("content")
        expected_text = "\n\n".join(part for part in (
            "Operator-edited observation stays authoritative: EDITED_OBSERVATION_SENTINEL.",
            "Consider a reusable verification script.",
        ) if part)
        require(sent_text == expected_text, f"promotion did not send the exact user-visible text: {sent_text!r}", "T5")
        require(backend.retain_calls[0] == {"items": [{"content": expected_text}], "async": True}, "promotion payload contains extra fields or raw evidence", "T5")
        command(resumed, log, f"/learnings-dismiss {record_id}", "Authoritative Markdown updated")
        dismissed = next(item for item in all_records(root) if item[1].get("id") == record_id)
        require(markdown_status(dismissed[2]) == "dismissed", "dismiss command did not update authoritative Markdown", "T7")
        dismiss_review = command(resumed, log, f"/learnings-review {sid}", "Learnings review")
        require("[DISMISSED]" in dismiss_review.get("message", ""), "Pi review status diverged from dismissed Markdown", "T7")
        report["checks"].append("AC-17-review-AC-11-exact-promotion")

        # Off survives another real primary resume and keeps later turns unobserved.
        command(resumed, log, "/learnings off", "Learnings monitor OFF")
        _, disabled_state = current_state(root, primary)
        require(disabled_state.get("enabled") is False and not disabled_state.get("pending"), "monitor did not persist a clean OFF state", "T6")
        parent_header = next(row for row in parse_session(primary) if row.get("type") == "session")
        resumed.exit()
        if resumed.exit_forced:
            report.setdefault("integrationFailures", []).append({
                "owner": "T3",
                "scenario": "resumed primary shutdown",
                "detail": "Pi did not exit after /quit with the private PTY drained; the harness force-killed the isolated resumed process.",
            })
        resumed_off = PiTui(pi_command(env, agent, sessions, session=primary), env, project, "resume-off")
        resumed_off.wait_start()
        off_resume_status = status_for(resumed_off, log)
        require("Learnings monitor: OFF" in off_resume_status.get("message", ""), "resuming an OFF primary silently re-enabled monitoring", "T6")
        before_off_resume_batches = observer_batch_count(backend)
        before_off_resume_records = len(all_records(root))
        turn(resumed_off, "OFF_RESUME_NEGATIVE", "PI_CASE:OFF_RESUME_NEGATIVE this resumed primary turn must remain unobserved")
        _, disabled_after_turn = current_state(root, primary)
        require(disabled_after_turn.get("enabled") is False and not disabled_after_turn.get("pending"), "resumed OFF mode captured activity", "T3")
        require(observer_batch_count(backend) == before_off_resume_batches, "resumed OFF mode scheduled observer work", "T3")
        require(len(all_records(root)) == before_off_resume_records, "resumed OFF mode created an opportunity record", "T2")
        resumed_off.exit()
        if resumed_off.exit_forced:
            report.setdefault("integrationFailures", []).append({
                "owner": "T3",
                "scenario": "off primary shutdown after resume",
                "detail": "Pi did not exit after /quit with the private PTY drained; the harness force-killed the isolated resumed process.",
            })
        report["checks"].append("AC-10-off-persists-across-primary-resume")
        before_fork = set(session_files(sessions))
        child = PiTui(pi_command(env, agent, sessions, fork=primary), env, project, "fork")
        child.wait_start()
        wait_condition(lambda: len([p for p in session_files(sessions) if p not in before_fork and not is_observer_file(p)]) >= 1, "Pi --fork primary session", owner="T3")
        fork_primary = primary_session(sessions, before=before_fork)
        fork_header = next(row for row in parse_session(fork_primary) if row.get("type") == "session")
        require(fork_header.get("id") != parent_header.get("id"), "Pi --fork reused the parent session ID", "T3")
        require(fork_header.get("parentSession") == str(primary), "Pi --fork session did not record its parent-session provenance", "T3")
        command(child, log, "/learnings on", "Learnings monitor ON")
        fork_sid, fork_state = current_state(root, fork_primary)
        require(fork_sid != sid, "forked primary reused the parent's Learnings source locator", "T3")
        next_observer_call = observer_call_count(backend) + 1
        expected_fork_batches = observer_batch_count(backend) + 1
        expected_fork_recalls = len(backend.recall_calls) + 1
        for label in ("FORK01", "FORK02", "FORK03"):
            turn(child, label, f"PI_CASE:{label} WORKFLOW-FRICTION: I manually repeat the same verification checklist across services.")
        ensure_observer_started(next_observer_call, "forked primary batch")
        wait_batch_processed(backend, root, fork_sid, expected_fork_batches, expected_fork_recalls)
        fork_state = operational_state(root, fork_sid) or {}
        fork_worker = Path(str(fork_state.get("workerSession", "")))
        require(fork_worker.is_file() and fork_worker != worker_path, "forked primary did not receive a distinct native observer session locator", "T4")
        require(len(all_observer_files(sessions)) == 2, f"expected one observer per primary, found {len(all_observer_files(sessions))}", "T4")
        require(not operational_state(root, source_id(next(
            str(row.get("id")) for row in parse_session(fork_worker) if row.get("type") == "session"
        ))), "observer transcript recursively became a primary activity source", "T3")
        child_transcript = parse_session(fork_worker)
        require(any(row.get("type") == "message" and row.get("message", {}).get("role") == "toolResult" for row in child_transcript), "forked observer transcript lacks tool use", "T4")
        fork_marker = next(row for row in child_transcript if row.get("customType") == "learnings-monitor-observer")
        parent_marker = next(row for row in parse_session(worker_path) if row.get("customType") == "learnings-monitor-observer")
        require(fork_marker.get("data", {}).get("sourceId") == fork_sid and parent_marker.get("data", {}).get("sourceId") == sid, "observer session ownership markers do not match their primary sources", "T4")
        report["checks"].append("AC-8-real-fork-distinct-observer-and-AC-26-no-recursion")

        # Positive and negative controls for extension ownership, session count, and persistence.
        model_counts = [row for row in backend.model_requests if row.get("observer")]
        require(len(model_counts) >= observer_batch_count(backend) and len(backend.tool_calls) >= 1, "native worker transcript/model requests are incomplete", "T4")
        require(len(all_records(root)) == 3, "primary branch/fork record count differed from the expected three, or an off turn created an extra record", "T2")
        require(len(primary_user_messages(primary)) == 19, f"slash commands/flush altered primary transcript or an exchange was lost: {len(primary_user_messages(primary))} user messages", "T3")
        report["checks"].append("positive-negative-controls-and-primary-transcript")
        report["evidence"] = {
            "parentSource": sid,
            "parentSession": str(primary),
            "parentObserver": str(worker_path),
            "forkSource": fork_sid,
            "forkSession": str(fork_primary),
            "forkObserver": str(fork_worker),
            "observerBatches": observer_batch_count(backend),
            "hindsightRecalls": len(backend.recall_calls),
            "warningCount": event_count(log, "notify", event_type="warning", message=WARNING),
            "workerTokens": tokens,
            "workerCost": cost,
            "firstPrimaryElapsedSeconds": round(first_primary_elapsed, 3),
        }
        # Retry the fork's same evidence after its proposal is dismissed. The
        # scripted observer changes only terminal punctuation, not the action.
        fork_records = [item for item in all_records(root) if any(e.get("sourceId") == fork_sid for e in item[1].get("evidence", []))]
        require(len(fork_records) == 1, "fork did not have one distinct opportunity to dismiss", "T1")
        fork_record_id = str(fork_records[0][1]["id"])
        command(child, log, f"/learnings-dismiss {fork_record_id}", "Authoritative Markdown updated")
        child.exit()
        if child.exit_forced:
            report.setdefault("integrationFailures", []).append({
                "owner": "T3",
                "scenario": "forked primary shutdown",
                "detail": "Pi did not exit after /quit with the private PTY drained; the harness force-killed the isolated fork process.",
            })
        replayed_id = queue_replayed_evidence(root, fork_sid, fork_records[0][1])
        before_replay_batches = observer_batch_count(backend)
        before_replay_recalls = len(backend.recall_calls)
        with backend.condition:
            backend.cosmetic_sources.add(fork_sid)
        replayed_child = PiTui(pi_command(env, agent, sessions, session=fork_primary), env, project, "fork-replay")
        replayed_child.wait_start()
        wait_condition(
            lambda: observer_batch_count(backend) >= before_replay_batches + 1 and (operational_state(root, fork_sid) or {}).get("pending") == [],
            "cosmetic replay to finish through the real Pi observer", timeout=60, owner="T1",
        )
        replay_batch = list(backend.observer_batches.values())[-1]
        require([item.get("id") for item in replay_batch.get("evidence", [])] == [replayed_id], "replay used different source evidence", "T1")
        require(any(event.get("event") == "proposal-response" and event.get("batchId") == replay_batch.get("batchId") and event.get("proposalCount") == 1 and event.get("cosmetic") for event in backend.events), "scripted observer did not return the punctuation-only variant", "T1")
        replay_records = [item for item in all_records(root) if any(e.get("sourceId") == fork_sid for e in item[1].get("evidence", []))]
        require(len(replay_records) == 1 and replay_records[0][1]["id"] == fork_record_id, "cosmetic rewrite created a second fork opportunity", "T1")
        require(markdown_status(replay_records[0][2]) == "dismissed" and replay_records[0][1].get("reviewHistory", [])[-1].get("status") == "dismissed", "cosmetic retry reopened or erased the dismissal", "T1")
        require(len(backend.recall_calls) == before_replay_recalls, "suppressed replay triggered a new Hindsight lookup", "T5")
        replay_review = command(replayed_child, log, f"/learnings-review {fork_sid}", "Learnings review")
        require("[DISMISSED]" in replay_review.get("message", ""), "Pi review lost the dismissed state after cosmetic replay", "T7")
        report["checks"].append("AC-24-cosmetic-dismissal-suppression-on-real-Pi-retry")
        report["evidence"]["cosmeticReplayEvidence"] = replayed_id
        replayed_child.exit()
        if replayed_child.exit_forced:
            report.setdefault("integrationFailures", []).append({
                "owner": "T3",
                "scenario": "fork replay shutdown",
                "detail": "Pi did not exit after /quit with the private PTY drained; the harness force-killed the isolated replay process.",
            })
        return report
    except ProofFailure as error:
        error.integration_failures = report.get("integrationFailures", [])
        raise
    finally:
        backend.release_hold()
        for name, process in (("primary", pi), ("resume", resumed), ("resume-off", resumed_off), ("fork", child), ("fork-replay", replayed_child)):
            if process:
                with contextlib.suppress(OSError):
                    terminal_log = root / f"{name}-terminal.txt"
                    terminal_log.write_bytes(process.output)
                    terminal_log.chmod(0o600)
                process.close()


def core_proof() -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        raise ProofFailure("Node.js is required for the independent non-Pi core proof", "T1")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tempfile.gettempdir(), "NODE_NO_WARNINGS": "1"}
    result = subprocess.run(
        [node, str(ROOT / "tests/learnings-monitor/core-proof.mjs")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        raise ProofFailure(f"independent non-Pi core subprocess failed: {result.stderr.strip()}", "T1")
    value = json.loads(result.stdout)
    require(value.get("status") == "kept", "non-Pi core producer did not receive review state", "T1")
    require(value.get("firstClaim") == "prospective" and value.get("repeatedClaim") == "recurring", "non-Pi core did not distinguish one event from recurrence", "T1")
    require(value.get("emptyChanges") == 0, "non-Pi empty-output control was not a no-op", "T1")
    return value


def run_full(keep: bool, artifact_dir: Path | None) -> dict[str, Any]:
    if artifact_dir:
        root = artifact_dir.resolve()
        if root.exists() and any(root.iterdir()):
            raise ProofFailure(f"artifact directory must be empty: {root}", "T8")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        global ACTIVE_ARTIFACT_ROOT
        ACTIVE_ARTIFACT_ROOT = root
        cleanup = False
    else:
        temporary = tempfile.TemporaryDirectory(prefix="learnings-monitor-proof-")
        root = Path(temporary.name)
        root.chmod(0o700)
        cleanup = not keep

    backends: ScriptedBackends | None = None
    try:
        work_file = root / "project" / "tool-evidence.txt"
        work_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_private(work_file, "Relevant local checklist reference. TOOL_OUTPUT_PRIVATE_SENTINEL must stay out of opportunity Markdown.\n")
        backends = ScriptedBackends(work_file, root / "backend-events.jsonl")
        env, agent, sessions, xdg, project = make_environment(root, backends, root / "ui-events.jsonl")
        # Run core before Pi; the child process receives no Pi/Hindsight imports or config.
        portable = core_proof()
        integrated = run_integrated(root, backends, env, agent, sessions, xdg, project)
        report = {
            "status": "FAIL" if integrated.get("integrationFailures") else "PASS",
            "root": str(root),
            "nonPiCore": portable,
            "pi": integrated,
            "backend": {
                "modelRequests": len(backends.model_requests),
                "observerBatches": len(backends.observer_batches),
                "toolCalls": len(backends.tool_calls),
                "recalls": len(backends.recall_calls),
                "retains": len(backends.retain_calls),
            },
            "artifactsRetained": bool(keep or artifact_dir),
        }
        if cleanup:
            temporary.cleanup()
            report["root"] = "<temporary; removed>"
        elif not keep and not artifact_dir:
            temporary.cleanup()
        return report
    finally:
        if backends:
            backends.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="retain generated private artifacts in the temporary directory")
    parser.add_argument("--artifacts", type=Path, help="use this empty, private directory instead of a temporary directory")
    parser.add_argument("--core-only", action="store_true", help="run only the independent non-Pi proof")
    args = parser.parse_args()
    try:
        if args.core_only:
            report = {"status": "PASS", "nonPiCore": core_proof()}
        else:
            report = run_full(args.keep, args.artifacts)
        rendered = json.dumps(report, indent=2)
        if args.artifacts and ACTIVE_ARTIFACT_ROOT == args.artifacts.resolve():
            write_private(ACTIVE_ARTIFACT_ROOT / "T8-report.json", rendered + "\n")
        print(rendered)
        return 1 if report.get("status") == "FAIL" else 0
    except ProofFailure as error:
        failure = {
            "status": "FAIL",
            "owner": error.owner,
            "failure": str(error),
            **({"failedScenario": error.scenario} if error.scenario else {}),
            **({"integrationFailures": error.integration_failures} if error.integration_failures else {}),
        }
        if args.artifacts:
            failure["artifactRoot"] = str(args.artifacts.resolve())
        if ACTIVE_ARTIFACT_ROOT and ACTIVE_ARTIFACT_ROOT == (args.artifacts.resolve() if args.artifacts else None):
            write_private(ACTIVE_ARTIFACT_ROOT / "T8-report.json", json.dumps({
                **failure,
                "command": ["python3", *sys.argv],
                "recordedAtUnix": time.time(),
            }, indent=2) + "\n")
        print(json.dumps(failure, indent=2), file=sys.stderr)
        return 1
    except Exception as error:
        failure = {"status": "FAIL", "owner": "T8", "failure": f"{type(error).__name__}: {error}"}
        if ACTIVE_ARTIFACT_ROOT and ACTIVE_ARTIFACT_ROOT == (args.artifacts.resolve() if args.artifacts else None):
            write_private(ACTIVE_ARTIFACT_ROOT / "T8-report.json", json.dumps({
                **failure,
                "command": ["python3", *sys.argv],
                "recordedAtUnix": time.time(),
            }, indent=2) + "\n")
        print(json.dumps(failure, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
