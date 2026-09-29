#!/usr/bin/env python3
"""Black-box standing-reminder journey through real Pi.

All provider traffic is served by a local scripted OpenAI-compatible backend.
The configured editor is a gate-controlled subprocess. Runs use a temporary
Pi agent directory, project, and saved-session directory; no user session or
provider credential is read or modified.
"""
from __future__ import annotations

import fcntl
import http.server
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import tempfile
import threading
import time
import termios
from collections import Counter
from pathlib import Path
from typing import Any, Callable

TIMEOUT = 35
ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "dot_pi/private_agent/extensions/standing-reminder/index.ts"
REMINDER_OLD = "Keep this exact wording.\n  Preserve indent\tand the second line.\n"
REMINDER_EDITED = "Edited during streaming.\n  Keep this tab\tand line break.\n"
REMINDER_DRAFT = "Temporary editor draft; it must not become current before close."
REMINDER_FORK_OLD = "Reminder at the earlier fork point."
REMINDER_PARENT = "Parent's current reminder after the fork point.\nSecond line stays."
REMINDER_PARENT_NAVIGATED = "Edited after /tree navigation.\nCurrent value wins over the selected branch."
REMINDER_FOR_EMPTY_CLEAR = "Re-set before proving an empty editor save clears it."
REMINDER_CHILD = "Fork-only reminder."
REMINDER_CLONE = "Clone-only reminder."
STREAM = "PROOF-STREAM-OPERATOR-REQUEST"
FOLLOWUP_STREAM = "PROOF-EXTENSION-FOLLOWUP-STREAM"
COMPACTION_WORK = "PROOF-COMPACTION-WITHIN-OPERATOR-WORK"
COMPACTION_NEXT = "PROOF-AFTER-WITHIN-WORK-COMPACTION"
BATCH_STREAM = "PROOF-ALL-MODE-BATCH-STREAM"
BATCH_OPERATOR_ONE = "PROOF-BATCH-OPERATOR-ONE"
BATCH_OPERATOR_TWO = "PROOF-BATCH-OPERATOR-TWO"
BATCH_EXTENSION = "PROOF-BATCH-EXTENSION-STEERING-INPUT"
STEER = "PROOF-QUEUED-STEERING-REQUEST"
# The processed extension message deliberately collides with the operator text.
GENERATED = STEER
TEMPLATE_INPUT = "/expanded PROOF-TEMPLATE-ARGUMENT"
TEMPLATE_MESSAGE = "PROOF-EXPANDED-OPERATOR-MESSAGE\nPROOF-TEMPLATE-ARGUMENT"
TOOL_PROMPT = "PROOF-TOOL-ONLY-CONTINUATION"
TREE_POINT = "PROOF-FORK-POINT-OLDER-USER-MESSAGE"
TREE_SEARCH = "fork-point"
PATCH_MARKER = "chezmoi-pi-patch:standing-reminder-origin v2"
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


class ProofFailure(RuntimeError):
    pass


class ProofBlocked(RuntimeError):
    pass


def require_isolated_patched_pi(pi_bin: str) -> None:
    package_value = os.environ.get("PI_STANDING_REMINDER_ORIGIN_PACKAGE")
    if not package_value:
        raise ProofBlocked("run this proof through tests/standing-reminder/isolated_pi.py")
    package = Path(package_value).resolve()
    executable = Path(pi_bin).resolve()
    try:
        executable.relative_to(package)
    except ValueError as exc:
        raise ProofBlocked(f"PI_BIN is outside the isolated Pi package: {executable}") from exc
    try:
        metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
        runtime = (package / "dist/core/agent-session.js").read_text(encoding="utf-8")
        declarations = (package / "dist/core/extensions/types.d.ts").read_text(encoding="utf-8")
        bundles = [path for path in (package / "dist/bundle/chunks").glob("*.js")
                   if PATCH_MARKER in path.read_text(encoding="utf-8")]
    except (OSError, json.JSONDecodeError) as exc:
        raise ProofBlocked("the isolated Pi package or standing-reminder patch is incomplete") from exc
    if metadata.get("name") != "@earendil-works/pi-coding-agent" or metadata.get("version") != "0.99.1":
        raise ProofBlocked("the proof requires isolated @earendil-works/pi-coding-agent 0.99.1")
    if (PATCH_MARKER not in runtime or PATCH_MARKER not in declarations or len(bundles) != 1
            or os.environ.get("PI_CHEZMOI_PROFILE") not in {"personal", "axon-work-computer"}):
        raise ProofBlocked("the desktop-gated standing-reminder origin patch is missing from isolated Pi")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofFailure(message)


def wait_for(predicate: Callable[[], Any], description: str, timeout: float = TIMEOUT) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise ProofFailure(f"timed out waiting for {description}")


def as_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def request_text(body: dict[str, Any]) -> str:
    return "\n".join(as_text(message.get("content")) for message in body.get("messages", []))


def latest_user_text(body: dict[str, Any]) -> str:
    users = [as_text(message.get("content")) for message in body.get("messages", [])
             if message.get("role") == "user"]
    return next((text for text in reversed(users) if not text.startswith("<standing-reminder>")), "")


def request_for(provider: "ScriptedProvider", marker: str, occurrence: int = 1) -> dict[str, Any]:
    found = [body for body in provider.snapshot() if marker in request_text(body)]
    require(len(found) >= occurrence, f"provider did not receive {marker!r} (occurrence {occurrence})")
    return found[occurrence - 1]


def is_compaction_request(body: dict[str, Any]) -> bool:
    return any(message.get("role") == "system"
               and "You are a context summarization assistant." in as_text(message.get("content"))
               for message in body.get("messages", []))


def latest_request_for(provider: "ScriptedProvider", prompt: str) -> dict[str, Any]:
    found = [body for body in provider.snapshot() if latest_user_text(body) == prompt]
    require(bool(found), f"provider did not receive {prompt!r} as the latest user message")
    return found[-1]


def assert_user_message(body: dict[str, Any], prompt: str) -> None:
    found = [m for m in body.get("messages", []) if m.get("role") == "user" and as_text(m.get("content")) == prompt]
    require(bool(found), f"provider request changed or omitted operator message {prompt!r}; "
            f"latest user text: {latest_user_text(body)[:500]!r}")


def assert_reminder(body: dict[str, Any], prompt: str, reminder: str) -> None:
    assert_user_message(body, prompt)
    exact = f"<standing-reminder>\n{reminder}\n</standing-reminder>"
    projected = [m for m in body.get("messages", []) if exact == as_text(m.get("content"))]
    require(len(projected) == 1, f"{prompt!r} must receive one exact current reminder projection")
    require(request_text(body).count("<standing-reminder>") == 1,
            f"{prompt!r} has duplicate or stale reminder projections")


def assert_no_reminder(body: dict[str, Any], prompt: str) -> None:
    assert_user_message(body, prompt)
    require("<standing-reminder>" not in request_text(body),
            f"{prompt!r} unexpectedly received a reminder")


def assert_operator_batch(body: dict[str, Any], prompts: tuple[str, ...], reminder: str) -> None:
    messages = body.get("messages", [])
    for prompt in prompts:
        assert_user_message(body, prompt)
    exact = f"<standing-reminder>\n{reminder}\n</standing-reminder>"
    projected = [message for message in messages
                 if message.get("role") == "user" and as_text(message.get("content")) == exact]
    require(len(projected) == len(prompts),
            f"all-mode batch must contain one exact reminder projection per operator message; found {len(projected)}")
    require(request_text(body).count("<standing-reminder>") == len(prompts),
            "all-mode batch contains a missing, duplicate, or stale reminder projection")


def write_exec(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o700)


OBSERVER_SOURCE = r'''import { appendFileSync } from "node:fs";
let cancelNextSameTextExtension = false;
function record(value) {
  appendFileSync(process.env.STANDING_PROOF_TRACE, JSON.stringify({ at: Date.now(), ...value }) + "\n");
}
export default function (pi) {
  pi.on("session_start", (event, ctx) => record({
    kind: "session_start", reason: event.reason,
    sessionId: ctx.sessionManager.getSessionId(),
    sessionFile: ctx.sessionManager.getSessionFile() ?? null,
  }));
  pi.on("input", (event) => {
    record({ kind: "input", text: event.text, source: event.source,
      streamingBehavior: event.streamingBehavior ?? null });
    if (event.source === "extension" && event.text === "PROOF-QUEUED-STEERING-REQUEST"
      && cancelNextSameTextExtension) {
      cancelNextSameTextExtension = false;
      record({ kind: "input_cancelled", text: event.text, source: event.source,
        streamingBehavior: event.streamingBehavior ?? null });
      return { action: "handled" };
    }
  });
  pi.on("session_tree", (event, ctx) => record({ kind: "session_tree",
    oldLeafId: event.oldLeafId, newLeafId: event.newLeafId,
    sessionId: ctx.sessionManager.getSessionId() }));
  pi.on("session_compact", (event) => record({ kind: "session_compact", reason: event.reason,
    summary: event.compactionEntry?.summary ?? null, willRetry: event.willRetry ?? null }));
  pi.on("agent_settled", (_event, ctx) => record({ kind: "agent_settled",
    sessionId: ctx.sessionManager.getSessionId() }));
  pi.on("message_start", (event, ctx) => {
    if (event.message.role === "user") record({ kind: "processed_user", sessionId: ctx.sessionManager.getSessionId(),
      source: (event as typeof event & { source?: unknown }).source ?? "unavailable",
      text: typeof event.message.content === "string" ? event.message.content :
        (event.message.content ?? []).filter((part) => part?.type === "text").map((part) => part.text).join("\n") });
  });
  pi.registerCommand("proof-cancelled-neighbor", {
    description: "Cancel an extension message with the next operator message's exact text",
    handler: async () => {
      cancelNextSameTextExtension = true;
      pi.sendUserMessage("PROOF-QUEUED-STEERING-REQUEST", { deliverAs: "followUp" });
    },
  });
  pi.registerCommand("proof-followup", {
    description: "Queue an extension-origin follow-up with the operator's exact text",
    handler: async () => {
      pi.sendUserMessage("PROOF-QUEUED-STEERING-REQUEST", { deliverAs: "followUp" });
    },
  });
  pi.registerCommand("proof-batch-extension-steering", {
    description: "Queue a distinct extension-origin steering message for the all-mode batch",
    handler: async () => {
      pi.sendUserMessage("PROOF-BATCH-EXTENSION-STEERING-INPUT", { deliverAs: "steer" });
    },
  });
}
'''


EDITOR_SOURCE = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
trace = Path(os.environ["STANDING_PROOF_EDITOR_TRACE"])
release = Path(os.environ["STANDING_PROOF_EDITOR_RELEASE"])
counter = Path(os.environ["STANDING_PROOF_EDITOR_COUNTER"])
try:
    number = int(counter.read_text(encoding="utf-8")) + 1
except FileNotFoundError:
    number = 1
counter.write_text(str(number), encoding="utf-8")
plan = json.loads(Path(os.environ["STANDING_PROOF_EDITOR_PLAN"]).read_text(encoding="utf-8"))
if number > len(plan):
    raise SystemExit(90)
item = plan[number - 1]
def log(kind, **fields):
    with trace.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"kind": kind, "invocation": number, **fields}) + "\n")
log("editor_started", path=sys.argv[-1])
if "draft" in item:
    Path(sys.argv[-1]).write_text(item["draft"], encoding="utf-8")
    log("editor_draft_saved", chars=len(item["draft"]))
while not (release / str(number)).exists():
    time.sleep(0.02)
if item.get("write", True):
    Path(sys.argv[-1]).write_text(item.get("text", ""), encoding="utf-8")
log("editor_closed", code=item.get("code", 0), wrote=item.get("write", True))
raise SystemExit(item.get("code", 0))
'''


FOLLOWUP_AND_TOOL_SCRIPT = "printf PROOF-TOOL-EXECUTED"


def sse(handler: http.server.BaseHTTPRequestHandler, delta: dict[str, Any], finish: str | None = None) -> None:
    payload = {"id": "chatcmpl-standing-proof", "object": "chat.completion.chunk", "created": 1,
               "model": "standing-proof", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    handler.wfile.write(f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode())
    handler.wfile.flush()


def sse_start(handler: http.server.BaseHTTPRequestHandler) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()
    sse(handler, {"role": "assistant"})


def sse_text(handler: http.server.BaseHTTPRequestHandler, text: str) -> None:
    sse(handler, {"content": text})


def sse_finish(handler: http.server.BaseHTTPRequestHandler, reason: str = "stop") -> None:
    sse(handler, {}, reason)
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()


class ScriptedProvider(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.errors: list[str] = []
        self.first_stream_open = threading.Event()
        self.allow_stream_while_editor_open = threading.Event()
        self.stream_while_editor_sent = threading.Event()
        self.finish_first_stream = threading.Event()
        self.steer_request_open = threading.Event()
        self.finish_steer = threading.Event()
        self.batch_stream_open = threading.Event()
        self.finish_batch_stream = threading.Event()
        self.followup_stream_open = threading.Event()
        self.finish_followup_stream = threading.Event()
        self.expect_compaction = False
        self.compaction_work_active = False
        self.compaction_tool_sent = False
        self.compaction_summary_requests = 0
        self.compaction_continuation_requests = 0
        self.compaction_continuation_seen = threading.Event()
        self.tool_call_sent = False
        super().__init__(("127.0.0.1", 0), self.make_handler())

    def make_handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, _format: str, *_args: Any) -> None:
                pass

            def do_POST(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length))
                    with server.lock:
                        server.requests.append(body)
                        index = len(server.requests)
                        compact = server.expect_compaction
                        if compact:
                            server.expect_compaction = False
                    text = request_text(body)
                    latest = latest_user_text(body)

                    if compact:
                        sse_start(self)
                        sse_text(self, "PROOF-MANUAL-COMPACTION-SUMMARY: the saved reminder remains session-current.")
                        sse_finish(self)
                    elif server.compaction_work_active and COMPACTION_WORK in latest and not server.compaction_tool_sent:
                        server.compaction_tool_sent = True
                        sse_start(self)
                        args = json.dumps({"command": "python3 -c 'print(\"COMPACTION-PADDING-\" + \"x\" * 45000)'"})
                        sse(self, {"tool_calls": [{"index": 0, "id": "call-standing-compaction-proof", "type": "function",
                            "function": {"name": "bash", "arguments": args}}]})
                        sse_finish(self, "tool_calls")
                    elif server.compaction_work_active and "You are a context summarization assistant." in text:
                        server.compaction_summary_requests += 1
                        sse_start(self)
                        sse_text(self, "PROOF-MID-WORK-COMPACTION-SUMMARY: continue the operator's existing work.")
                        sse_finish(self)
                    elif server.compaction_work_active and server.compaction_summary_requests:
                        server.compaction_continuation_requests += 1
                        server.compaction_continuation_seen.set()
                        sse_start(self)
                        sse_text(self, "PROOF-COMPACTION-WORK-ANSWER")
                        sse_finish(self)
                    elif FOLLOWUP_STREAM in latest:
                        server.followup_stream_open.set()
                        sse_start(self)
                        sse_text(self, "PROOF-FOLLOWUP-STREAM-HEAD ")
                        server._wait(server.finish_followup_stream, "extension-follow-up stream release")
                        sse_text(self, "PROOF-FOLLOWUP-STREAM-TAIL")
                        sse_finish(self)
                    elif STREAM in latest:
                        server.first_stream_open.set()
                        sse_start(self)
                        sse_text(self, "PROOF-STREAM-HEAD ")
                        server._wait(server.allow_stream_while_editor_open, "stream while editor is open")
                        sse_text(self, "PROOF-STREAM-DURING-EDITOR ")
                        server.stream_while_editor_sent.set()
                        server._wait(server.finish_first_stream, "first response release")
                        sse_text(self, "PROOF-STREAM-TAIL")
                        sse_finish(self)
                    elif BATCH_STREAM in latest:
                        server.batch_stream_open.set()
                        sse_start(self)
                        sse_text(self, "PROOF-BATCH-STREAM-HEAD ")
                        server._wait(server.finish_batch_stream, "all-mode batch stream release")
                        sse_text(self, "PROOF-BATCH-STREAM-TAIL")
                        sse_finish(self)
                    elif latest == BATCH_OPERATOR_TWO and BATCH_OPERATOR_ONE in text and BATCH_OPERATOR_TWO in text:
                        sse_start(self)
                        sse_text(self, "PROOF-BATCH-OPERATOR-ANSWER")
                        sse_finish(self)
                    elif STEER in latest:
                        if "<standing-reminder>" not in text:
                            sse_start(self)
                            sse_text(self, "PROOF-GENERATED-FOLLOWUP-ANSWER")
                            sse_finish(self)
                        else:
                            server.steer_request_open.set()
                            sse_start(self)
                            sse_text(self, "PROOF-STEER-HEAD ")
                            server._wait(server.finish_steer, "steering response release")
                            sse_text(self, "PROOF-STEER-TAIL")
                            sse_finish(self)
                    elif TOOL_PROMPT in latest and not server.tool_call_sent:
                        server.tool_call_sent = True
                        sse_start(self)
                        args = json.dumps({"command": FOLLOWUP_AND_TOOL_SCRIPT})
                        sse(self, {"tool_calls": [{"index": 0, "id": "call-standing-proof", "type": "function",
                            "function": {"name": "bash", "arguments": args}}]})
                        sse_finish(self, "tool_calls")
                    else:
                        sse_start(self)
                        if TOOL_PROMPT in latest:
                            reply = "PROOF-TOOL-CONTINUATION-ANSWER"
                        else:
                            reply = f"PROOF-SCRIPTED-ANSWER-{index}"
                        sse_text(self, reply)
                        sse_finish(self)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:
                    with server.lock:
                        server.errors.append(f"request handler: {type(exc).__name__}: {exc}")
                    try:
                        self.send_error(500, str(exc))
                    except OSError:
                        pass

        return Handler

    @staticmethod
    def _wait(event: threading.Event, description: str) -> None:
        if not event.wait(TIMEOUT):
            raise TimeoutError(f"provider gate timed out: {description}")

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.requests)

    def wait_count(self, count: int) -> None:
        wait_for(lambda: len(self.snapshot()) >= count, f"provider request #{count}")

    def assert_healthy(self) -> None:
        with self.lock:
            errors = list(self.errors)
        require(not errors, "; ".join(errors))


class PiPTY:
    def __init__(self, argv: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 42, 150, 0, 0))
        self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave,
                                         start_new_session=True, close_fds=True)
        os.close(slave)
        os.set_blocking(self.master, False)
        self.output = bytearray()
        self.lock = threading.Lock()
        self.reader_done = threading.Event()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        try:
            while not self.reader_done.is_set():
                ready, _, _ = select.select([self.master], [], [], 0.1)
                if not ready:
                    if self.process.poll() is not None:
                        return
                    continue
                try:
                    chunk = os.read(self.master, 65536)
                except (BlockingIOError, OSError):
                    if self.process.poll() is not None:
                        return
                    continue
                if not chunk:
                    return
                with self.lock:
                    self.output.extend(chunk)
        finally:
            self.reader_done.set()

    def write_all(self, data: bytes) -> None:
        view = memoryview(data)
        deadline = time.monotonic() + TIMEOUT
        while view:
            try:
                written = os.write(self.master, view)
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [self.master], [], min(0.1, remaining))[1]:
                    raise ProofFailure("timed out writing input to the isolated Pi PTY")
                continue
            if written <= 0:
                raise ProofFailure("isolated Pi PTY accepted no input bytes")
            view = view[written:]

    def send(self, text: str) -> None:
        self.write_all(text.encode("utf-8") + b"\r")

    def type_text(self, text: str) -> None:
        for character in text:
            self.write_all(character.encode("utf-8"))
            time.sleep(0.015)

    def key(self, raw: bytes) -> None:
        self.write_all(raw)

    def plain(self) -> str:
        with self.lock:
            raw = bytes(self.output).decode("utf-8", errors="replace")
        return ANSI.sub("", raw)

    def plain_since(self, offset: int) -> str:
        with self.lock:
            raw = bytes(self.output[offset:]).decode("utf-8", errors="replace")
        return ANSI.sub("", raw)

    def output_length(self) -> int:
        with self.lock:
            return len(self.output)

    def wait_output(self, marker: str, timeout: float = TIMEOUT) -> None:
        wait_for(lambda: marker in self.plain(), f"TUI output {marker!r}", timeout)

    def wait_output_since(self, offset: int, marker: str, timeout: float = TIMEOUT) -> None:
        recent = lambda: self.plain_since(offset)
        wait_for(lambda: marker in recent(), f"new TUI output {marker!r} (recent: {recent()[-1200:]!r})", timeout)

    def stop(self) -> None:
        self.reader_done.set()
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=3)
        try:
            os.close(self.master)
        except OSError:
            pass


class Trace:
    def __init__(self, path: Path, editor_path: Path) -> None:
        self.path = path
        self.editor_path = editor_path

    def records(self, *, editor: bool = False) -> list[dict[str, Any]]:
        path = self.editor_path if editor else self.path
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    records.append(value)
            except json.JSONDecodeError:
                continue
        return records

    def wait(self, predicate: Callable[[dict[str, Any]], bool], description: str,
             *, editor: bool = False, timeout: float = TIMEOUT) -> dict[str, Any]:
        match: dict[str, Any] | None = None
        def found() -> bool:
            nonlocal match
            match = next((record for record in self.records(editor=editor) if predicate(record)), None)
            return match is not None
        wait_for(found, description, timeout)
        assert match is not None
        return match

    def wait_count(self, predicate: Callable[[dict[str, Any]], bool], count: int, description: str,
                   *, timeout: float = TIMEOUT) -> None:
        wait_for(lambda: sum(bool(predicate(item)) for item in self.records()) >= count, description, timeout)


class ProofRun:
    def __init__(self, root: Path, provider: ScriptedProvider, provider_thread: threading.Thread,
                 extension: Path, context_window: int = 32768) -> None:
        self.root = root
        self.extension = extension
        self.context_window = context_window
        self.provider = provider
        self.provider_thread = provider_thread
        self.agent = root / "agent"
        self.project = root / "project"
        self.sessions = root / "sessions"
        self.trace_file = root / "extension-trace.jsonl"
        self.editor_trace = root / "editor-trace.jsonl"
        self.editor_release = root / "editor-release"
        self.editor_counter = root / "editor-counter"
        self.editor_plan = root / "editor-plan.json"
        self.tui: PiPTY | None = None
        self.trace = Trace(self.trace_file, self.editor_trace)
        self.editor_invocation = 0

    def setup(self) -> None:
        self.agent.mkdir(parents=True)
        (self.project / ".pi").mkdir(parents=True)
        self.sessions.mkdir(parents=True)
        self.editor_release.mkdir()
        editor = self.root / "fake-editor"
        write_exec(editor, EDITOR_SOURCE)
        plan = [
            {"text": REMINDER_OLD},
            {"draft": REMINDER_DRAFT, "text": REMINDER_EDITED},
            {"write": False},
            {"text": "SHOULD-NOT-COMMIT-FAILED-EDITOR", "code": 23},
            {"text": REMINDER_FOR_EMPTY_CLEAR},
            {"text": ""},
            {"text": REMINDER_FORK_OLD},
            {"text": REMINDER_PARENT},
            {"text": REMINDER_PARENT_NAVIGATED},
            {"text": REMINDER_CHILD},
            {"text": REMINDER_CLONE},
        ]
        self.editor_plan.write_text(json.dumps(plan), encoding="utf-8")
        settings = {
            "externalEditor": str(editor),
            "steeringMode": "all",
            "treeFilterMode": "user-only",
            "branchSummary": {"skipPrompt": True},
            "compaction": {"reserveTokens": 128, "keepRecentTokens": 1},
        }
        prompts = self.agent / "prompts"
        prompts.mkdir()
        (prompts / "expanded.md").write_text(
            "---\ndescription: standing-reminder origin expansion fixture\n---\n"
            "PROOF-EXPANDED-OPERATOR-MESSAGE\n$ARGUMENTS",
            encoding="utf-8",
        )
        (self.project / ".pi" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        host, port = self.provider.server_address
        (self.agent / "models.json").write_text(json.dumps({"providers": {"standing-proof": {
            "baseUrl": f"http://{host}:{port}/v1",
            "api": "openai-completions",
            "apiKey": "scripted-provider-only",
            "models": [{"id": "standing-reminder-proof", "name": "Standing reminder proof",
                "api": "openai-completions", "reasoning": False, "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": self.context_window, "maxTokens": 256}],
        }}}), encoding="utf-8")

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update({
            "PI_CODING_AGENT_DIR": str(self.agent),
            "PI_CODING_AGENT_SESSION_DIR": str(self.sessions),
            "PI_OFFLINE": "1",
            "PI_TELEMETRY": "0",
            "TERM": "xterm-256color",
            "STANDING_PROOF_TRACE": str(self.trace_file),
            "STANDING_PROOF_EDITOR_TRACE": str(self.editor_trace),
            "STANDING_PROOF_EDITOR_RELEASE": str(self.editor_release),
            "STANDING_PROOF_EDITOR_COUNTER": str(self.editor_counter),
            "STANDING_PROOF_EDITOR_PLAN": str(self.editor_plan),
        })
        return env

    def argv(self, *, session: Path | None = None, session_id: str | None = None, tui: bool = False,
             extensions: bool = True) -> list[str]:
        pi = os.environ.get("PI_BIN") or shutil.which("pi")
        require(bool(pi), "`pi` is not on PATH (or set PI_BIN)")
        args = [str(pi), "--no-context-files", "--no-skills", "--no-themes",
                "--offline", "--approve", "--provider", "standing-proof",
                "--model", "standing-proof/standing-reminder-proof", "--tools", "bash",
                "--session-dir", str(self.sessions)]
        if session:
            args.extend(["--session", str(session)])
        elif session_id:
            args.extend(["--session-id", session_id])
        if not extensions:
            args.append("--no-extensions")
        else:
            args.extend(["--no-extensions", "--extension", str(self.extension),
                         "--extension", str(self.root / "observer.ts")])
        return args

    def launch_tui(self, *, session: Path | None = None, session_id: str | None = None,
                   extensions: bool = True) -> PiPTY:
        self.tui = PiPTY(self.argv(session=session, session_id=session_id, tui=True, extensions=extensions),
                         self.project, self.env())
        self.tui.wait_output("standing-reminder-proof")
        return self.tui

    def start_editor(self, tui: PiPTY) -> tuple[int, int]:
        output_start = tui.output_length()
        self.editor_invocation += 1
        invocation = self.editor_invocation
        tui.send("/reminder")
        try:
            self.trace.wait(lambda record: record.get("kind") == "editor_started" and record.get("invocation") == invocation,
                            f"configured editor invocation {invocation}", editor=True)
        except ProofFailure as exc:
            raise ProofFailure(f"{exc}; pi_exit={tui.process.poll()}; TUI tail={tui.plain()[-1200:]!r}") from exc
        return invocation, output_start

    def close_editor(self, tui: PiPTY, invocation: int, output_start: int,
                     *, expect_warning: str | None = None) -> None:
        Path(self.editor_release / str(invocation)).touch()
        self.trace.wait(lambda record: record.get("kind") == "editor_closed" and record.get("invocation") == invocation,
                        f"editor invocation {invocation} close", editor=True)
        if expect_warning:
            tui.wait_output_since(output_start, expect_warning)

    def next_editor(self, tui: PiPTY, *, expect_warning: str | None = None) -> int:
        invocation, output_start = self.start_editor(tui)
        self.close_editor(tui, invocation, output_start, expect_warning=expect_warning)
        return output_start

    def session_file(self, session_id: str) -> Path:
        matches = []
        for path in self.sessions.rglob("*.jsonl"):
            try:
                first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            except (OSError, ValueError, IndexError):
                continue
            if first.get("type") == "session" and first.get("id") == session_id:
                matches.append(path)
        require(len(matches) == 1, f"expected one saved session for {session_id}, got {matches}")
        return matches[0]

    def session_id_for(self, tui: PiPTY) -> str:
        records = self.trace.records()
        starts = [item for item in records if item.get("kind") == "session_start"]
        require(bool(starts), "Pi did not emit a session_start event")
        # The latest start belongs to the currently bound session, including fork/clone.
        return str(starts[-1]["sessionId"])

    def state_path(self, session_id: str) -> Path:
        return self.sessions / "standing-reminder" / f"{session_id}.json"

    def saved_state(self, session_id: str) -> dict[str, Any]:
        path = self.state_path(session_id)
        require(path.is_file(), f"missing session reminder sidecar {path}")
        state = json.loads(path.read_text(encoding="utf-8"))
        require(state.get("version") == 1, "unexpected reminder state version")
        return state

    def assert_no_delivery_transcript(self, session_id: str) -> None:
        session_file = self.session_file(session_id)
        for line in session_file.read_text(encoding="utf-8").splitlines():
            require("<standing-reminder>" not in line,
                    f"hidden reminder projection was persisted as a chat/session entry in {session_file}")
            require(PATCH_MARKER not in line,
                    f"runtime provenance marker was persisted in {session_file}")
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProofFailure(f"saved session contains invalid JSON in {session_file}") from exc
            message = entry.get("message")
            if isinstance(message, dict) and message.get("role") == "user":
                require("source" not in message,
                        f"input provenance was serialized into a user message in {session_file}")
                require(PATCH_MARKER not in as_text(message.get("content")),
                        f"input provenance changed saved user text in {session_file}")
        session_user_texts = []
        for line in session_file.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            message = entry.get("message")
            if isinstance(message, dict) and message.get("role") == "user":
                session_user_texts.append(as_text(message.get("content")))
        trace_records = self.trace.records()
        for item in trace_records:
            if item.get("kind") in {"input", "processed_user"}:
                require(PATCH_MARKER not in str(item.get("text", "")),
                        f"input provenance marker changed original user text in {session_file}")
        observed_user_texts = Counter(item.get("text", "") for item in trace_records
                                      if item.get("kind") == "processed_user" and item.get("sessionId") == session_id)
        saved_user_counts = Counter(session_user_texts)
        require(not (observed_user_texts - saved_user_counts),
                f"processed user text was changed or omitted from the saved session {session_file}")

    def prompt_and_wait(self, tui: PiPTY, prompt: str, *, provider_prompt: str | None = None,
                        expected_output: str = "PROOF-SCRIPTED-ANSWER",
                        min_settled: int | None = None, timeout: float = TIMEOUT) -> dict[str, Any]:
        output_start = tui.output_length()
        previous = sum(item.get("kind") == "agent_settled" for item in self.trace.records())
        request_count = len(self.provider.snapshot())
        tui.send(prompt)
        self.provider.wait_count(request_count + 1)
        target = previous + 1 if min_settled is None else min_settled
        self.trace.wait_count(lambda item: item.get("kind") == "agent_settled", target,
                              f"agent_settled after {prompt}", timeout=timeout)
        try:
            tui.wait_output_since(output_start, expected_output, timeout=timeout)
        except ProofFailure as exc:
            raise ProofFailure(f"operator-visible answer incomplete after {prompt!r}; pi_exit={tui.process.poll()}; {exc}") from exc
        return (latest_request_for(self.provider, provider_prompt) if provider_prompt is not None
                else request_for(self.provider, prompt))

    def cleanup(self) -> None:
        if self.tui:
            self.tui.stop()
        self.provider.shutdown()
        self.provider.server_close()
        self.provider_thread.join(timeout=2)


def configure_run(root: Path, extension: Path, context_window: int = 32768) -> ProofRun:
    provider = ScriptedProvider()
    thread = provider.start()
    run = ProofRun(root, provider, thread, extension, context_window)
    run.setup()
    write_exec(root / "observer.ts", OBSERVER_SOURCE)
    return run


def scripted_noninteractive(run: ProofRun, mode: str, session_file: Path, prompt: str) -> tuple[list[dict[str, Any]], str, str]:
    args = run.argv(session=session_file)
    env = run.env()
    if mode == "print":
        args.extend(["--print", prompt])
    elif mode == "json":
        args.extend(["--mode", "json", prompt])
    else:
        raise ValueError(mode)
    try:
        completed = subprocess.run(args, cwd=run.project, env=env, text=True, capture_output=True,
                                   timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProofBlocked(f"Pi {mode} invocation could not complete: {exc}") from exc
    require(completed.returncode == 0,
            f"Pi {mode} exited {completed.returncode}: {completed.stderr[-2000:]}")
    if mode == "print":
        require("PROOF-SCRIPTED-ANSWER" in completed.stdout, "print-mode operator request did not finish")
        records: list[dict[str, Any]] = []
    else:
        records = parse_json_lines(completed.stdout, f"Pi JSON {prompt}")
        require(any(item.get("type") == "agent_settled" for item in records),
                "JSON mode did not report a completed operator request")
        require(any(item.get("type") == "message_end" and item.get("message", {}).get("role") == "user"
                    and as_text(item["message"].get("content")) == prompt for item in records),
                "JSON mode did not preserve the submitted operator request")
        require(any(item.get("type") == "message_end" and item.get("message", {}).get("role") == "assistant"
                    and as_text(item["message"].get("content")).strip() for item in records),
                "JSON mode settled without a completed assistant answer")
    return records, completed.stdout, completed.stderr


def parse_json_lines(text: str, description: str) -> list[dict[str, Any]]:
    records = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProofFailure(f"{description} wrote non-JSON stdout on line {number}: {line[:300]!r}") from exc
        require(isinstance(value, dict), f"{description} emitted a non-object JSON record")
        records.append(value)
    require(bool(records), f"{description} emitted no JSON records")
    return records


class RpcProcess:
    def __init__(self, run: ProofRun, session_file: Path) -> None:
        self.run = run
        self.process = subprocess.Popen(run.argv(session=session_file) + ["--mode", "rpc"], cwd=run.project,
            env=run.env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1)
        self.records: list[dict[str, Any]] = []
        self.stderr = ""
        self.lock = threading.Lock()
        self.reader_done = threading.Event()
        self.reader = threading.Thread(target=self._read_stdout, daemon=True)
        self.stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self.reader.start()
        self.stderr_reader.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout
        try:
            for line in self.process.stdout:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    with self.lock:
                        self.records.append({"__invalid__": line.rstrip(), "error": str(exc)})
                    continue
                with self.lock:
                    self.records.append(item)
        finally:
            self.reader_done.set()

    def _read_stderr(self) -> None:
        assert self.process.stderr
        self.stderr = self.process.stderr.read()

    def send(self, record: dict[str, Any]) -> None:
        assert self.process.stdin
        self.process.stdin.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.records)

    def wait_record(self, predicate: Callable[[dict[str, Any]], bool], description: str) -> dict[str, Any]:
        result: dict[str, Any] | None = None
        def found() -> bool:
            nonlocal result
            result = next((item for item in self.snapshot() if predicate(item)), None)
            return result is not None
        wait_for(found, description)
        assert result is not None
        return result

    def finish(self) -> tuple[list[dict[str, Any]], str]:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            code = self.process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            self.process.kill()
            raise ProofFailure("RPC Pi did not exit after stdin closed") from exc
        self.reader.join(timeout=2)
        self.stderr_reader.join(timeout=2)
        require(code == 0, f"RPC Pi exited {code}: {self.stderr[-1500:]}")
        records = self.snapshot()
        invalid = [item for item in records if "__invalid__" in item]
        require(not invalid, f"RPC stdout contained non-JSON data: {invalid[:1]}")
        return records, self.stderr


def rpc_prompt(run: ProofRun, session_file: Path, prompt: str) -> tuple[list[dict[str, Any]], str]:
    rpc = RpcProcess(run, session_file)
    try:
        rpc.send({"id": "standing-proof-prompt", "type": "prompt", "message": prompt})
        rpc.wait_record(lambda item: item.get("id") == "standing-proof-prompt" and item.get("type") == "response"
                        and item.get("success") is True, "RPC prompt acceptance")
        before = len(rpc.snapshot())
        rpc.wait_record(lambda item: item.get("type") == "agent_settled", "RPC agent_settled")
        # The record payload is checked below; this call makes sure asynchronous
        # events continue to be consumed through the completed outcome.
        _ = before
        return rpc.finish()
    finally:
        if rpc.process.poll() is None:
            try:
                if rpc.process.stdin:
                    rpc.process.stdin.close()
                rpc.process.wait(timeout=3)
            except Exception:
                rpc.process.kill()


def assert_rpc_request(records: list[dict[str, Any]], prompt: str) -> None:
    require(any(item.get("type") == "message_start" and item.get("message", {}).get("role") == "user"
                and as_text(item["message"].get("content")) == prompt for item in records),
            f"RPC did not preserve user request {prompt!r}")
    require(any(item.get("type") == "agent_settled" for item in records), "RPC request did not settle")
    require(any(item.get("type") == "message_end" and item.get("message", {}).get("role") == "assistant"
                and as_text(item["message"].get("content")).strip() for item in records),
            "RPC settled without a completed assistant answer")


def run_interactive_journey(run: ProofRun) -> tuple[str, str, str]:
    pi = run.launch_tui(session_id="standing-proof-parent")
    run.trace.wait(lambda item: item.get("kind") == "session_start" and item.get("reason") in {"new", "startup"},
                   "new saved Pi session")
    pi.wait_output("No session reminder")
    parent_id = run.session_id_for(pi)

    # Materialize a real saved session before reminder state is written.
    initialized = run.prompt_and_wait(pi, "PROOF-SAVED-SESSION-INITIALIZER")
    assert_no_reminder(initialized, "PROOF-SAVED-SESSION-INITIALIZER")
    run.session_file(parent_id)

    # Save the first exact multiline value, then prove a user request receives it.
    editor_output = run.next_editor(pi)
    pi.wait_output_since(editor_output, "Reminder saved")
    pi.wait_output_since(editor_output, "applies to next request")
    pi.wait_output_since(editor_output, "Reminder saved · applies to next request:")
    state = run.saved_state(parent_id)
    require(state.get("reminder") == REMINDER_OLD and state.get("pending") is True,
            "initial editor result or pending status was not persisted")
    first_message = run.trace.wait(lambda item: item.get("kind") == "editor_closed" and item.get("invocation") == 1,
                                   "first editor close", editor=True)
    require(first_message.get("code") == 0, "initial editor did not close successfully")

    # Commit a successful edit while the first response remains active and
    # before its already-queued steering message is processed. The in-flight
    # request keeps its old snapshot; the next processed message gets the edit.
    settled_before = sum(item.get("kind") == "agent_settled" for item in run.trace.records())
    pi.send(STREAM)
    require(run.provider.first_stream_open.wait(TIMEOUT), "streaming request never reached the scripted provider")
    first_stream_body = request_for(run.provider, STREAM)
    assert_reminder(first_stream_body, STREAM, REMINDER_OLD)
    require(REMINDER_EDITED not in request_text(first_stream_body),
            "an already-started request did not retain its original reminder snapshot")
    pi.send("/proof-cancelled-neighbor")
    cancelled_neighbor = run.trace.wait(
        lambda item: item.get("kind") == "input_cancelled" and item.get("text") == STEER,
        "canceled extension-origin neighbor with the operator's exact text",
    )
    require(cancelled_neighbor.get("source") == "extension"
            and cancelled_neighbor.get("streamingBehavior") == "followUp",
            "the same-text canceled queue neighbor was not extension-origin")
    pi.send(STEER)
    run.trace.wait(lambda item: item.get("kind") == "input" and item.get("text") == STEER
                   and item.get("source") == "interactive" and item.get("streamingBehavior") == "steer",
                   "interactive queued steering input after canceled same-text neighbor")
    editor_invocation, _editor_output = run.start_editor(pi)
    require(editor_invocation == 2, "streaming editor was not the planned intermediate-draft invocation")
    draft_saved = run.trace.wait(
        lambda item: item.get("kind") == "editor_draft_saved" and item.get("invocation") == editor_invocation,
        "temporary editor draft while editor remains open", editor=True,
    )
    editor_start = run.trace.wait(
        lambda item: item.get("kind") == "editor_started" and item.get("invocation") == editor_invocation,
        "streaming editor temp-file path", editor=True,
    )
    require(draft_saved.get("chars") == len(REMINDER_DRAFT)
            and Path(editor_start["path"]).read_text(encoding="utf-8") == REMINDER_DRAFT,
            "scripted editor did not write the planned intermediate draft")
    require(run.saved_state(parent_id).get("reminder") == REMINDER_OLD
            and run.saved_state(parent_id).get("pending") is False,
            "an intermediate editor save changed the living reminder before close")
    redraw_start = pi.output_length()

    run.provider.allow_stream_while_editor_open.set()
    require(run.provider.stream_while_editor_sent.wait(TIMEOUT), "provider did not continue while editor owned the terminal")
    while_editor_output = pi.plain_since(redraw_start)
    require(not any(marker in while_editor_output for marker in (
        "PROOF-STREAM-DURING-EDITOR", "PROOF-STREAM-TAIL", "PROOF-STEER-HEAD", "PROOF-STEER-TAIL",
    )), "Pi rendered accumulated response bytes before the editor returned the terminal")
    require(not any(latest_user_text(body) == STEER for body in run.provider.snapshot()),
            "queued operator steering was processed before the successful editor save")
    require(sum(item.get("kind") == "agent_settled" for item in run.trace.records()) == settled_before,
            "the active response settled before its streaming editor transaction completed")

    run.close_editor(pi, editor_invocation, _editor_output)
    pi.wait_output_since(_editor_output, "Reminder saved · applies to next request:")
    require(run.saved_state(parent_id).get("reminder") == REMINDER_EDITED
            and run.saved_state(parent_id).get("pending") is True,
            "successful editor close did not commit the new reminder and next-request cue")
    require(sum(item.get("kind") == "agent_settled" for item in run.trace.records()) == settled_before
            and run.provider.first_stream_open.is_set(),
            "the response was no longer active when the saved-edit cue appeared")
    require(not any(latest_user_text(body) == STEER for body in run.provider.snapshot()),
            "queued operator steering reached the model before the saved-edit cue")
    assert_reminder(first_stream_body, STREAM, REMINDER_OLD)
    require(REMINDER_EDITED not in request_text(first_stream_body),
            "editing the living reminder retroactively changed an already-started model request")
    pi.wait_output_since(redraw_start, "PROOF-STREAM-DURING-EDITOR")

    run.provider.finish_first_stream.set()
    require(run.provider.steer_request_open.wait(TIMEOUT), "queued operator message did not reach its own provider turn")
    queued_body = request_for(run.provider, STEER)
    assert_reminder(queued_body, STEER, REMINDER_EDITED)
    require(latest_user_text(queued_body) == STEER,
            "queued operator reminder was not paired with the latest processed message")
    require(REMINDER_OLD not in request_text(queued_body) and REMINDER_DRAFT not in request_text(queued_body),
            "superseded or uncommitted editor text reached the queued operator request")
    require(run.saved_state(parent_id).get("pending") is False,
            "processing the queued operator message did not clear the saved next-request cue")
    run.provider.finish_steer.set()
    run.trace.wait_count(lambda item: item.get("kind") == "agent_settled", settled_before + 1,
                         "stream and queued operator response to settle")
    pi.wait_output_since(redraw_start, "PROOF-STREAM-TAIL")
    pi.wait_output_since(redraw_start, "PROOF-STEER-HEAD")
    pi.wait_output_since(redraw_start, "PROOF-STEER-TAIL")
    redrawn = pi.plain_since(redraw_start)
    redraw_positions = [redrawn.find(marker) for marker in (
        "PROOF-STREAM-DURING-EDITOR", "PROOF-STREAM-TAIL", "PROOF-STEER-HEAD", "PROOF-STEER-TAIL",
    )]
    require(all(position >= 0 for position in redraw_positions)
            and redraw_positions == sorted(redraw_positions),
            "Pi did not redraw every streamed response chunk in order after editor close")

    committed_body = run.prompt_and_wait(pi, "PROOF-AFTER-STREAMING-EDITOR-COMMIT")
    assert_reminder(committed_body, "PROOF-AFTER-STREAMING-EDITOR-COMMIT", REMINDER_EDITED)

    # An extension follow-up with the same text as an operator message remains
    # extension-origin and receives no fresh reminder.
    settled_before_followup = sum(item.get("kind") == "agent_settled" for item in run.trace.records())
    requests_before_generated = len(run.provider.snapshot())
    pi.send(FOLLOWUP_STREAM)
    require(run.provider.followup_stream_open.wait(TIMEOUT), "extension follow-up contrast never streamed")
    assert_reminder(request_for(run.provider, FOLLOWUP_STREAM), FOLLOWUP_STREAM, REMINDER_EDITED)
    pi.send("/proof-followup")
    run.trace.wait(lambda item: item.get("kind") == "input" and item.get("text") == GENERATED
                   and item.get("source") == "extension" and item.get("streamingBehavior") == "followUp",
                   "extension-generated follow-up input")
    run.provider.finish_followup_stream.set()
    run.provider.wait_count(requests_before_generated + 2)
    run.trace.wait_count(lambda item: item.get("kind") == "agent_settled", settled_before_followup + 1,
                         "extension follow-up contrast to settle")
    same_text_turns = [body for body in run.provider.snapshot() if latest_user_text(body) == STEER]
    require(len(same_text_turns) == 2,
            f"identical operator/extension text must produce exactly two distinct model turns; got {len(same_text_turns)}")
    extension_duplicate = same_text_turns[-1]
    assert_no_reminder(extension_duplicate, GENERATED)
    require(latest_user_text(extension_duplicate) == STEER,
            "same-text extension follow-up was not the latest processed model input")
    require(sum(latest_user_text(body) == STEER for body in run.provider.snapshot()) == 2,
            "a canceled same-text queue neighbor unexpectedly reached the model")
    pi.wait_output("PROOF-FOLLOWUP-STREAM-TAIL")
    pi.wait_output("PROOF-GENERATED-FOLLOWUP-ANSWER")
    same_text_processed = [item.get("source") for item in run.trace.records()
                           if item.get("kind") == "processed_user" and item.get("text") == STEER]
    require(same_text_processed == ["interactive", "extension"],
            f"identical processed text lost per-message origin or a canceled neighbor was processed: {same_text_processed}")

    # Operator tool call and tool-only continuation share one existing projection.
    settled_before = sum(item.get("kind") == "agent_settled" for item in run.trace.records())
    requests_before_tool = len(run.provider.snapshot())
    pi.send(TOOL_PROMPT)
    run.provider.wait_count(requests_before_tool + 1)
    run.provider.wait_count(requests_before_tool + 2)
    run.trace.wait_count(lambda item: item.get("kind") == "agent_settled", settled_before + 1,
                         "tool continuation to settle")
    first_tool = request_for(run.provider, TOOL_PROMPT)
    continuation = request_for(run.provider, TOOL_PROMPT, occurrence=2)
    assert_reminder(first_tool, TOOL_PROMPT, REMINDER_EDITED)
    require(request_text(continuation).count("<standing-reminder>") == 1,
            "tool-only provider continuation did not carry exactly one existing reminder")
    require("PROOF-TOOL-EXECUTED" in request_text(continuation),
            "tool-only continuation did not contain the completed tool result")
    pi.wait_output("PROOF-TOOL-CONTINUATION-ANSWER")

    # Prompt-template expansion changes the processed text but must retain the
    # operator origin and exact reminder pairing without leaking the raw command.
    # The input trace is produced by the next send, so prove it together with
    # the actual expanded provider request.
    expanded = run.prompt_and_wait(pi, TEMPLATE_INPUT, provider_prompt=TEMPLATE_MESSAGE)
    template_input = run.trace.wait(
        lambda item: item.get("kind") == "input" and item.get("text") == TEMPLATE_INPUT,
        "operator prompt-template input before expansion",
    )
    require(template_input.get("source") == "interactive",
            "prompt-template command did not retain operator provenance")
    processed_expanded = run.trace.wait(
        lambda item: item.get("kind") == "processed_user" and item.get("text") == TEMPLATE_MESSAGE,
        "expanded message_start with its actual origin",
    )
    require(processed_expanded.get("source") == "interactive",
            "expanded operator message lost input provenance")
    assert_reminder(expanded, TEMPLATE_MESSAGE, REMINDER_EDITED)
    require(TEMPLATE_INPUT not in request_text(expanded),
            "raw prompt-template command replaced or leaked into the model request")

    run_all_mode_batch(run, pi, REMINDER_EDITED)

    # Reload and manual compaction are explicit saved-session operations. Each
    # is followed by a real operator message whose provider payload is checked.
    run_reload_and_compaction(run, pi, parent_id)

    # Keep advisory text separate from the operator's contradictory request.
    contradictory = "For this request only, do the opposite of the standing reminder."
    body = run.prompt_and_wait(pi, contradictory)
    assert_reminder(body, contradictory, REMINDER_EDITED)
    require(run.saved_state(parent_id).get("reminder") == REMINDER_EDITED,
            "a contradictory request changed the living reminder")

    # An unchanged editor is view-only; a failed editor draft never commits.
    prior = run.saved_state(parent_id)
    editor_output = run.next_editor(pi)
    pi.wait_output_since(editor_output, "Reminder unchanged")
    require(run.saved_state(parent_id) == prior, "closing the editor unchanged rewrote reminder state")
    run.next_editor(pi, expect_warning="Reminder edit canceled")
    require(run.saved_state(parent_id) == prior, "nonzero editor exit committed its temporary draft")
    require("SHOULD-NOT-COMMIT-FAILED-EDITOR" not in request_text(request_for(run.provider, contradictory)),
            "failed editor draft leaked into the current provider request")
    require(prior.get("reminder") == REMINDER_EDITED,
            "failed-editor contrast did not start with the expected old reminder")
    after_failed_editor = run.prompt_and_wait(pi, "PROOF-AFTER-FAILED-EDITOR")
    assert_reminder(after_failed_editor, "PROOF-AFTER-FAILED-EDITOR", REMINDER_EDITED)
    require("SHOULD-NOT-COMMIT-FAILED-EDITOR" not in request_text(after_failed_editor)
            and run.saved_state(parent_id).get("reminder") == REMINDER_EDITED,
            "the failed draft replaced the old reminder for the next model request")

    # The explicit clear command is local, shows its next-request cue, and
    # stops delivery without changing the operator's next message.
    clear_output = pi.output_length()
    pi.send("/reminder-clear")
    pi.wait_output_since(clear_output, "Reminder cleared")
    pi.wait_output_since(clear_output, "applies to next request")
    pi.wait_output_since(clear_output, "Reminder cleared · applies to next request")
    require(run.saved_state(parent_id).get("reminder") is None and run.saved_state(parent_id).get("pending") is True,
            "clear command did not persist its pending cleared state")
    no_reminder = run.prompt_and_wait(pi, "PROOF-CLEARED-REMINDER-REQUEST")
    assert_no_reminder(no_reminder, "PROOF-CLEARED-REMINDER-REQUEST")

    # Refill, then save an empty external-editor file. The empty commit clears
    # the reminder and the next model request proves it was not just widget state.
    editor_output = run.next_editor(pi)
    pi.wait_output_since(editor_output, "Reminder saved")
    editor_output = run.next_editor(pi)
    pi.wait_output_since(editor_output, "Reminder cleared · applies to next request")
    require(run.saved_state(parent_id).get("reminder") is None and run.saved_state(parent_id).get("pending") is True,
            "an empty successful editor save did not clear the living reminder")
    empty_editor_clear = run.prompt_and_wait(pi, "PROOF-EMPTY-EDITOR-CLEAR")
    assert_no_reminder(empty_editor_clear, "PROOF-EMPTY-EDITOR-CLEAR")

    # Save an earlier branch point, continue later, then edit the living value.
    editor_output = run.next_editor(pi)
    pi.wait_output_since(editor_output, "Reminder saved")
    old_point = run.prompt_and_wait(pi, TREE_POINT)
    assert_reminder(old_point, TREE_POINT, REMINDER_FORK_OLD)
    later = run.prompt_and_wait(pi, "PROOF-LATER-PARENT-WORK")
    assert_reminder(later, "PROOF-LATER-PARENT-WORK", REMINDER_FORK_OLD)
    editor_output = run.next_editor(pi)
    pi.wait_output_since(editor_output, "Reminder saved")
    require(run.saved_state(parent_id).get("reminder") == REMINDER_PARENT,
            "parent reminder was not updated after the earlier fork point")

    # Real /tree navigates to the earlier message while the session-current value remains.
    tree_events_before = sum(item.get("kind") == "session_tree" for item in run.trace.records())
    tree_output = pi.output_length()
    pi.send("/tree")
    pi.wait_output_since(tree_output, "Session Tree")
    pi.type_text(TREE_SEARCH)
    pi.wait_output_since(tree_output, f"Type to search: {TREE_SEARCH}")
    pi.wait_output_since(tree_output, TREE_POINT)
    pi.key(b"\r")
    run.trace.wait_count(lambda item: item.get("kind") == "session_tree", tree_events_before + 1,
                         "actual /tree navigation")
    pi.wait_output("Navigated to selected point")
    pi.key(b"\x15")  # /tree preloads the selected user text into the editor.
    require(run.saved_state(parent_id).get("reminder") == REMINDER_PARENT,
            "/tree restored an earlier reminder instead of the current session value")
    editor_output = run.next_editor(pi)
    pi.wait_output_since(editor_output, "Reminder saved")
    require(run.saved_state(parent_id).get("reminder") == REMINDER_PARENT_NAVIGATED,
            "editing after /tree did not replace the one session-current value")
    after_tree = run.prompt_and_wait(pi, "PROOF-AFTER-TREE-NAVIGATION")
    assert_reminder(after_tree, "PROOF-AFTER-TREE-NAVIGATION", REMINDER_PARENT_NAVIGATED)

    # Fork from the old point after the parent's later edit. Pi's /fork UI is
    # navigated to the older user message; the new session must copy today's value.
    starts_before_fork = len([item for item in run.trace.records() if item.get("kind") == "session_start"])
    fork_output = pi.output_length()
    pi.send("/fork")
    pi.wait_output_since(fork_output, "Fork from Message")
    pi.wait_output_since(fork_output, "PROOF-AFTER-TREE-NAVIGATION")
    pi.key(b"\x1b[A")  # The previous operator input is the selected older tree point.
    pi.key(b"\r")
    fork_start = run.trace.wait(lambda item: item.get("kind") == "session_start"
                                and item.get("reason") == "fork" and item.get("sessionId") != parent_id,
                                "new session from the /fork UI")
    fork_id = str(fork_start["sessionId"])
    require(len([item for item in run.trace.records() if item.get("kind") == "session_start"]) > starts_before_fork,
            "Pi did not switch to the fork session")
    require(run.saved_state(fork_id).get("reminder") == REMINDER_PARENT_NAVIGATED,
            "older-point /fork did not copy the parent's current reminder")
    require(run.saved_state(parent_id).get("reminder") == REMINDER_PARENT_NAVIGATED,
            "fork creation changed the parent reminder")
    pi.key(b"\x15")  # /fork preloads the selected user message into the editor.
    fork_prompt = run.prompt_and_wait(pi, "PROOF-FORK-CURRENT-VALUE")
    assert_reminder(fork_prompt, "PROOF-FORK-CURRENT-VALUE", REMINDER_PARENT_NAVIGATED)

    # The fork edits independently; /clone copies that value and then diverges too.
    editor_output = run.next_editor(pi)
    pi.wait_output_since(editor_output, "Reminder saved")
    child_prompt = run.prompt_and_wait(pi, "PROOF-FORK-INDEPENDENT-EDIT")
    assert_reminder(child_prompt, "PROOF-FORK-INDEPENDENT-EDIT", REMINDER_CHILD)
    require(run.saved_state(parent_id).get("reminder") == REMINDER_PARENT_NAVIGATED,
            "fork edit changed parent state")

    clone_events_before = len([item for item in run.trace.records() if item.get("kind") == "session_start"])
    pi.send("/clone")
    clone_start = run.trace.wait(lambda item: item.get("kind") == "session_start"
                                 and item.get("reason") == "fork" and item.get("sessionId") not in {parent_id, fork_id},
                                 "/clone session_start")
    clone_id = str(clone_start["sessionId"])
    require(len([item for item in run.trace.records() if item.get("kind") == "session_start"]) > clone_events_before,
            "Pi did not switch into the /clone session")
    require(run.saved_state(clone_id).get("reminder") == REMINDER_CHILD,
            "/clone did not copy the current reminder at clone time")
    clone_prompt = run.prompt_and_wait(pi, "PROOF-CLONE-CURRENT-VALUE")
    assert_reminder(clone_prompt, "PROOF-CLONE-CURRENT-VALUE", REMINDER_CHILD)
    editor_output = run.next_editor(pi)
    pi.wait_output_since(editor_output, "Reminder saved")
    clone_changed = run.prompt_and_wait(pi, "PROOF-CLONE-INDEPENDENT-EDIT")
    assert_reminder(clone_changed, "PROOF-CLONE-INDEPENDENT-EDIT", REMINDER_CLONE)
    require(run.saved_state(fork_id).get("reminder") == REMINDER_CHILD,
            "clone edit changed the source fork reminder")
    require(run.saved_state(parent_id).get("reminder") == REMINDER_PARENT_NAVIGATED,
            "fork or clone edit changed the original parent reminder")

    for session_id in (parent_id, fork_id, clone_id):
        run.assert_no_delivery_transcript(session_id)
    require("<standing-reminder>" not in pi.plain(), "hidden reminder projection appeared as a TUI chat bubble")
    run.provider.assert_healthy()
    print("PASS: active-response edit/status before queued processing; old in-flight snapshot, exact new queued reminder, and full editor catch-up")
    print("PASS: identical cross-origin text, expanded input, canceled neighbor, and mixed-origin batch")
    print("PASS: extension follow-up exclusion, tool-only carry, contradiction, clear, view-only, and failed-editor rollback")
    print("PASS: /reload, manual /compact, /tree, older-point /fork, /clone, and independent session-current state")
    return parent_id, fork_id, clone_id


def run_all_mode_batch(run: ProofRun, pi: PiPTY, reminder: str) -> None:
    settled_before = sum(item.get("kind") == "agent_settled" for item in run.trace.records())
    requests_before = len(run.provider.snapshot())
    pi.send(BATCH_STREAM)
    require(run.provider.batch_stream_open.wait(TIMEOUT), "all-mode streaming request never reached the scripted provider")
    assert_reminder(request_for(run.provider, BATCH_STREAM), BATCH_STREAM, reminder)

    pi.send("/proof-batch-extension-steering")
    extension_input = run.trace.wait(
        lambda item: item.get("kind") == "input" and item.get("text") == BATCH_EXTENSION,
        "queued extension-origin message mixed into the all-mode steering batch",
    )
    require(extension_input.get("source") == "extension" and extension_input.get("streamingBehavior") == "steer",
            "mixed all-mode neighbor was not captured as extension-origin steering input")

    for prompt in (BATCH_OPERATOR_ONE, BATCH_OPERATOR_TWO):
        pi.send(prompt)
        input_event = run.trace.wait(
            lambda item, prompt=prompt: item.get("kind") == "input" and item.get("text") == prompt,
            f"queued all-mode operator input {prompt}",
        )
        require(input_event.get("source") == "interactive" and input_event.get("streamingBehavior") == "steer",
                f"{prompt!r} was not captured as interactive steering input")

    run.provider.finish_batch_stream.set()
    run.provider.wait_count(requests_before + 2)
    run.trace.wait_count(lambda item: item.get("kind") == "agent_settled", settled_before + 1,
                         "all-mode batch operator work to settle")
    pi.wait_output("PROOF-BATCH-STREAM-TAIL")
    pi.wait_output("PROOF-BATCH-OPERATOR-ANSWER")

    requests = run.provider.snapshot()[requests_before + 1:]
    batch_requests = [body for body in requests if latest_user_text(body) in {BATCH_OPERATOR_ONE, BATCH_OPERATOR_TWO}]
    require(len(batch_requests) == 1,
            f"steeringMode=all must deliver both queued operators in one provider request; got {len(batch_requests)}")
    body = batch_requests[0]
    require(latest_user_text(body) == BATCH_OPERATOR_TWO,
            "all-mode batch did not preserve the final queued operator message")
    assert_user_message(body, BATCH_EXTENSION)
    assert_operator_batch(body, (BATCH_OPERATOR_ONE, BATCH_OPERATOR_TWO), reminder)

    session_id = run.session_id_for(pi)
    processed = [item for item in run.trace.records()
                 if item.get("kind") == "processed_user" and item.get("sessionId") == session_id
                 and item.get("text") in {BATCH_EXTENSION, BATCH_OPERATOR_ONE, BATCH_OPERATOR_TWO}]
    require([(item.get("text"), item.get("source")) for item in processed] == [
        (BATCH_EXTENSION, "extension"),
        (BATCH_OPERATOR_ONE, "interactive"),
        (BATCH_OPERATOR_TWO, "interactive")],
        "mixed all-mode batch lost per-message provenance or processed an unexpected neighbor")
    require(run.saved_state(session_id).get("pending") is False,
            "all-mode delivery did not clear the reminder's next-request cue")
    print("PASS: mixed-origin steeringMode=all batch delivered one reminder per operator and none for the extension")


def run_reload_and_compaction(run: ProofRun, pi: PiPTY, parent_id: str) -> None:
    # The state must be re-read by the actual /reload action, then delivered on
    # the next operator input, not merely left in the old extension closure.
    starts = len([item for item in run.trace.records() if item.get("kind") == "session_start"])
    reload_output_start = len(pi.plain())
    pi.send("/reload")
    pi.wait_output_since(reload_output_start, "Reloaded keybindings, extensions")
    # The observer is reloaded with the implementation extension. Requiring a
    # new start proves the command completed through Pi's reload lifecycle.
    run.trace.wait_count(lambda item: item.get("kind") == "session_start", starts + 1,
                         "extension session_start after /reload")
    post_reload = run.prompt_and_wait(pi, "PROOF-AFTER-RELOAD")
    assert_reminder(post_reload, "PROOF-AFTER-RELOAD", REMINDER_EDITED)

    run.provider.expect_compaction = True
    compact_before = len([item for item in run.trace.records() if item.get("kind") == "session_compact"])
    request_before = len(run.provider.snapshot())
    compact_output = pi.output_length()
    pi.send("/compact")
    run.provider.wait_count(request_before + 1)
    run.trace.wait_count(lambda item: item.get("kind") == "session_compact", compact_before + 1,
                         "manual /compact completion")
    pi.wait_output_since(compact_output, "Compacted from")
    after_compact = run.prompt_and_wait(pi, "PROOF-AFTER-MANUAL-COMPACT")
    assert_reminder(after_compact, "PROOF-AFTER-MANUAL-COMPACT", REMINDER_EDITED)
    require(run.saved_state(parent_id).get("reminder") == REMINDER_EDITED,
            "manual compaction lost saved reminder state")


def run_mid_work_compaction(root: Path, extension: Path) -> None:
    run = configure_run(root, extension, context_window=8192)
    try:
        pi = run.launch_tui(session_id="standing-proof-mid-work-compaction")
        run.trace.wait(lambda item: item.get("kind") == "session_start"
                       and item.get("reason") in {"new", "startup"}, "mid-work compaction session")
        session_id = run.session_id_for(pi)
        initialized = run.prompt_and_wait(pi, "PROOF-COMPACTION-SESSION-INITIALIZER")
        assert_no_reminder(initialized, "PROOF-COMPACTION-SESSION-INITIALIZER")
        run.session_file(session_id)

        editor_output = run.next_editor(pi)
        pi.wait_output_since(editor_output, "Reminder saved · applies to next request:")
        require(run.saved_state(session_id).get("reminder") == REMINDER_OLD,
                "compaction fixture reminder was not saved before operator work")

        requests_before = len(run.provider.snapshot())
        settled_before = sum(item.get("kind") == "agent_settled" for item in run.trace.records())
        compact_before = sum(item.get("kind") == "session_compact" for item in run.trace.records())
        run.provider.compaction_work_active = True
        output_start = pi.output_length()
        pi.send(COMPACTION_WORK)
        run.provider.wait_count(requests_before + 1)
        initial = request_for(run.provider, COMPACTION_WORK)
        assert_reminder(initial, COMPACTION_WORK, REMINDER_OLD)
        require(run.provider.compaction_tool_sent, "scripted provider did not start the compaction-triggering tool")

        compact_event = run.trace.wait(
            lambda item: item.get("kind") == "session_compact" and item.get("reason") == "threshold",
            "real Pi threshold compaction inside the operator's ongoing tool work",
        )
        require(compact_event.get("summary") and "PROOF-MID-WORK-COMPACTION-SUMMARY" in compact_event["summary"],
                "real Pi compaction did not persist the scripted in-work summary")
        run.trace.wait_count(lambda item: item.get("kind") == "agent_settled", settled_before + 1,
                             "operator work to finish after its within-work compaction")
        requests = run.provider.snapshot()
        # This snapshot ends at this work's agent_settled, before COMPACTION_NEXT
        # is submitted; compaction may rewrite the prompt tail, so use the real
        # Pi lifecycle boundary rather than requiring original text to survive.
        work_requests = requests[requests_before:]
        summaries = [body for body in work_requests if is_compaction_request(body)]
        require(summaries, "real in-work compaction did not make a summary request")
        require(all("<standing-reminder>" not in request_text(body) for body in summaries),
                "an in-work compaction summary received a fresh reminder projection")
        first_summary = next(index for index, body in enumerate(work_requests) if is_compaction_request(body))
        continuations = [body for body in work_requests[first_summary + 1:]
                         if not is_compaction_request(body)]
        require(continuations,
                "Pi settled the operator work without an ordinary model request after compaction")
        require(run.provider.compaction_continuation_requests >= len(continuations)
                and run.provider.compaction_continuation_seen.is_set(),
                "the scripted provider did not complete each ordinary same-work continuation")
        require(all("<standing-reminder>" not in request_text(body) for body in continuations),
                "an ordinary same-work continuation received a fresh reminder projection")
        require(all("<standing-reminder>" not in request_text(body) for body in work_requests[1:]),
                "within-work compaction caused a fresh reminder on a later model request")
        require(len(work_requests) >= 3,
                "Pi did not complete the initial, summary, and post-compaction model requests")
        pi.wait_output_since(output_start, "PROOF-COMPACTION-WORK-ANSWER")

        session_text = run.session_file(session_id).read_text(encoding="utf-8")
        require("COMPACTION-PADDING-" in session_text,
                "Pi did not persist the large tool result that drove the within-work compaction")
        saved_entries = [json.loads(line) for line in session_text.splitlines()]
        saved_compactions = [entry for entry in saved_entries if entry.get("type") == "compaction"]
        compaction_events = [item for item in run.trace.records()
                             if item.get("kind") == "session_compact" and item.get("reason") == "threshold"]
        require(len(saved_compactions) == compact_before + len(compaction_events)
                and len(compaction_events) >= 1
                and any("PROOF-MID-WORK-COMPACTION-SUMMARY" in entry.get("summary", "")
                        for entry in saved_compactions),
                f"Pi did not persist its actual within-work compaction entries: events={len(compaction_events)}, "
                f"saved={len(saved_compactions)}")
        processed_work = [item for item in run.trace.records()
                          if item.get("kind") == "processed_user" and item.get("text") == COMPACTION_WORK]
        require(len(processed_work) == 1 and processed_work[0].get("source") == "interactive",
                "the work was not one actual interactive processed operator message")

        run.provider.compaction_work_active = False
        next_body = run.prompt_and_wait(pi, COMPACTION_NEXT)
        assert_reminder(next_body, COMPACTION_NEXT, REMINDER_OLD)
        run.assert_no_delivery_transcript(session_id)
        run.provider.assert_healthy()
        print("PASS: repeated within-work compactions add no reminders to same-work continuations; the next operator gets the living value")
    finally:
        run.cleanup()


def run_noninteractive_reuse(run: ProofRun, parent_id: str) -> Path:
    parent_file = run.session_file(parent_id)
    print_body = "PROOF-PRINT-REUSE"
    before = len(run.provider.snapshot())
    _, stdout, stderr = scripted_noninteractive(run, "print", parent_file, print_body)
    require("[standing-reminder]" not in stdout, "print mode wrote extension diagnostics to stdout")
    require("Could not restore" not in stderr, "valid saved state generated a restore warning in print mode")
    assert_reminder(request_for(run.provider, print_body), print_body, REMINDER_PARENT_NAVIGATED)
    require(len(run.provider.snapshot()) == before + 1, "print reuse produced an unexpected provider request count")

    json_body = "PROOF-JSON-REUSE"
    records, _json_stdout, json_stderr = scripted_noninteractive(run, "json", parent_file, json_body)
    require(not json_stderr.strip(), f"valid JSON-mode request wrote diagnostics: {json_stderr[-400:]}")
    require(all(item.get("type") for item in records), "JSON event records lacked event types")
    assert_reminder(request_for(run.provider, json_body), json_body, REMINDER_PARENT_NAVIGATED)

    # Reuse interactive steering text through RPC to prove identical content
    # still takes the origin of this exact processed message.
    rpc_body = STEER
    rpc_records, rpc_stderr = rpc_prompt(run, parent_file, rpc_body)
    require(not rpc_stderr.strip(), f"valid RPC request wrote diagnostics: {rpc_stderr[-400:]}")
    assert_rpc_request(rpc_records, rpc_body)
    assert_reminder(latest_request_for(run.provider, rpc_body), rpc_body, REMINDER_PARENT_NAVIGATED)
    rpc_processed = run.trace.wait(
        lambda item: item.get("kind") == "processed_user" and item.get("sessionId") == parent_id
        and item.get("text") == rpc_body and item.get("source") == "rpc",
        "RPC origin on the exact duplicate processed message",
    )
    require(rpc_processed.get("source") == "rpc", "duplicate RPC text inherited another message's origin")

    # An unrelated saved session begins empty; reminder state is not global.
    unrelated = "PROOF-UNRELATED-SESSION-STARTS-EMPTY"
    run_name = "standing-proof-unrelated"
    args = run.argv(session_id=run_name)
    args.extend(["--mode", "json", unrelated])
    completed = subprocess.run(args, cwd=run.project, env=run.env(), text=True, capture_output=True,
                               timeout=TIMEOUT, check=False)
    require(completed.returncode == 0, f"unrelated JSON session failed: {completed.stderr[-1000:]}")
    parse_json_lines(completed.stdout, "unrelated-session JSON")
    assert_no_reminder(request_for(run.provider, unrelated), unrelated)
    print("PASS: saved session reminder is reused through print, JSON, and RPC; unrelated session starts empty")
    return parent_file


def run_resume(run: ProofRun, parent_file: Path) -> str:
    pi = run.launch_tui(session=parent_file)
    run.trace.wait(lambda item: item.get("kind") == "session_start" and item.get("reason") in {"resume", "switch", "startup"},
                   "saved-session resume")
    pi.wait_output("Edited after /tree navigation.")
    body = run.prompt_and_wait(pi, "PROOF-AFTER-SAVED-SESSION-RESUME")
    assert_reminder(body, "PROOF-AFTER-SAVED-SESSION-RESUME", REMINDER_PARENT_NAVIGATED)
    session_id = run.session_id_for(pi)
    pi.stop()
    run.tui = None
    print("PASS: restarting Pi on the saved session restored and delivered the current reminder")
    return session_id


def run_corrupt_state_proofs(run: ProofRun, parent_file: Path, session_id: str) -> None:
    path = run.state_path(session_id)
    require(path.is_file(), "cannot corrupt missing saved reminder state")
    path.write_text("{corrupted reminder state", encoding="utf-8")
    corrupted_prompt = "PROOF-CORRUPT-STATE-TUI-CONTINUES"

    # TUI warning must be visible while the operator's request still completes.
    tui = run.launch_tui(session=parent_file)
    tui.wait_output("Could not restore this session's reminder")
    body = run.prompt_and_wait(tui, corrupted_prompt)
    assert_no_reminder(body, corrupted_prompt)
    tui.stop()
    run.tui = None

    # Print and JSON keep stdout reserved for their user-facing output/protocol.
    for mode, prompt in (("print", "PROOF-CORRUPT-STATE-PRINT-CONTINUES"),
                         ("json", "PROOF-CORRUPT-STATE-JSON-CONTINUES")):
        records, stdout, stderr = scripted_noninteractive(run, mode, parent_file, prompt)
        require("Could not restore this session's reminder" in stderr,
                f"{mode} mode did not warn on stderr after state corruption")
        require("Could not restore this session's reminder" not in stdout,
                f"{mode} warning polluted stdout")
        if mode == "json":
            require(all(item.get("type") for item in records), "corrupt-state JSON stdout was not valid event JSONL")
        assert_no_reminder(request_for(run.provider, prompt), prompt)

    rpc_prompt_text = "PROOF-CORRUPT-STATE-RPC-CONTINUES"
    records, stderr = rpc_prompt(run, parent_file, rpc_prompt_text)
    require(any(item.get("type") == "extension_ui_request" and item.get("method") == "notify"
                and "Could not restore this session's reminder" in item.get("message", "")
                and item.get("notifyType") == "warning" for item in records),
            "RPC mode did not emit a warning through the extension UI protocol after state corruption")
    require("Could not restore this session's reminder" not in stderr,
            "RPC warning unexpectedly bypassed the JSONL UI protocol")
    require(any(item.get("type") == "response" and item.get("command") == "prompt"
                and item.get("success") is True for item in records),
            "corrupt-state RPC request was rejected")
    assert_rpc_request(records, rpc_prompt_text)
    assert_no_reminder(request_for(run.provider, rpc_prompt_text), rpc_prompt_text)
    print("PASS: corrupted sidecar warned in TUI, print, JSON, and RPC; every request completed without stale delivery")


def run_missing_state_proof(run: ProofRun, parent_file: Path, session_id: str) -> None:
    path = run.state_path(session_id)
    require(path.is_file(), "missing-sidecar proof needs a previously saved reminder")
    session_entries = [json.loads(line) for line in parent_file.read_text(encoding="utf-8").splitlines()]
    require(any(entry.get("type") == "custom" and entry.get("customType") == "standing-reminder-state"
                for entry in session_entries),
            "missing-sidecar proof session has no persistent reminder marker")
    path.unlink()
    require(not path.exists(), "could not remove the marked session's reminder sidecar")

    tui_prompt = "PROOF-MISSING-SIDECAR-TUI-CONTINUES"
    tui = run.launch_tui(session=parent_file)
    try:
        tui.wait_output("Could not restore this session's reminder")
        body = run.prompt_and_wait(tui, tui_prompt)
        assert_no_reminder(body, tui_prompt)
        require("PROOF-SCRIPTED-ANSWER" in tui.plain(),
                "TUI did not finish the request after the marked reminder sidecar was removed")
    finally:
        tui.stop()
        run.tui = None
    require(not path.exists(), "TUI request recreated unavailable reminder state without an edit")

    for mode, prompt in (("print", "PROOF-MISSING-SIDECAR-PRINT-CONTINUES"),
                         ("json", "PROOF-MISSING-SIDECAR-JSON-CONTINUES")):
        records, stdout, stderr = scripted_noninteractive(run, mode, parent_file, prompt)
        require("Could not restore this session's reminder" in stderr,
                f"{mode} mode did not warn when the marked reminder sidecar was missing")
        require("Could not restore this session's reminder" not in stdout,
                f"{mode} warning polluted stdout")
        if mode == "json":
            require(all(item.get("type") for item in records), "missing-state JSON stdout was not valid event JSONL")
        assert_no_reminder(request_for(run.provider, prompt), prompt)

    rpc_text = "PROOF-MISSING-SIDECAR-RPC-CONTINUES"
    records, stderr = rpc_prompt(run, parent_file, rpc_text)
    require(any(item.get("type") == "extension_ui_request" and item.get("method") == "notify"
                and "Could not restore this session's reminder" in item.get("message", "")
                and item.get("notifyType") == "warning" for item in records),
            "RPC mode did not warn through the UI protocol when the marked sidecar was missing")
    require("Could not restore this session's reminder" not in stderr,
            "missing-state RPC warning bypassed the JSONL UI protocol")
    assert_rpc_request(records, rpc_text)
    assert_no_reminder(request_for(run.provider, rpc_text), rpc_text)
    require(not path.exists(), "noninteractive requests recreated unavailable reminder state without an edit")
    print("PASS: a missing sidecar on a marked saved session warns and completes without stale delivery in TUI, print, JSON, and RPC")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension", type=Path, default=EXTENSION,
                        help="extension source to test (default: this worktree's implementation)")
    args = parser.parse_args()
    extension = args.extension.resolve()
    if not extension.is_file():
        print(f"BLOCKED: extension source not found: {extension}")
        return 2
    pi_bin = os.environ.get("PI_BIN") or shutil.which("pi")
    if not pi_bin:
        print("BLOCKED: `pi` is not on PATH (or set PI_BIN)")
        return 2
    try:
        require_isolated_patched_pi(pi_bin)
        version = subprocess.run([pi_bin, "--version"], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        if version != "0.99.1":
            raise ProofBlocked(f"Pi 0.99.1 is the prepared interactive boundary; found {version}")
        print(f"Using Pi {version}; local scripted provider and gate-controlled editor")
        with tempfile.TemporaryDirectory(prefix="pi-standing-reminder-proof-") as temporary:
            run = configure_run(Path(temporary), extension)
            try:
                parent_id, _fork_id, _clone_id = run_interactive_journey(run)
                if run.tui:
                    run.tui.stop()
                    run.tui = None
                parent_file = run.session_file(parent_id)
                run_resume(run, parent_file)
                run_noninteractive_reuse(run, parent_id)
                run_corrupt_state_proofs(run, parent_file, parent_id)
                run_missing_state_proof(run, parent_file, parent_id)
                for session_id in (parent_id, _fork_id, _clone_id):
                    run.assert_no_delivery_transcript(session_id)
                run.provider.assert_healthy()
            finally:
                run.cleanup()
            run_mid_work_compaction(Path(temporary) / "mid-work-compaction", extension)
    except ProofBlocked as exc:
        print(f"BLOCKED: {exc}")
        return 2
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
