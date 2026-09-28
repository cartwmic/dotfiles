#!/usr/bin/env python3
"""Black-box feasibility journey for standing-reminder hooks in real Pi.

Runs the privately staged Pi 0.87.x executable supplied by isolated_pi.py in
an isolated PTY against a local scripted OpenAI-compatible provider and a
gate-controlled external editor. No provider credentials or network access are
used. Requires Node, Pi, and Python 3.
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
from pathlib import Path
from typing import Any, Callable

TIMEOUT = 30
START = "START-STREAM-PI-FEASIBILITY"
STEER = "IDENTICAL-ORIGIN-PI-FEASIBILITY"
GENERATED = "EXTENSION-FOLLOWUP-PI-FEASIBILITY"
TEMPLATE_INPUT = "/expanded TEMPLATE-ARGUMENT-PI-FEASIBILITY"
TEMPLATE_MESSAGE = "EXPANDED-OPERATOR-PI-FEASIBILITY\nTEMPLATE-ARGUMENT-PI-FEASIBILITY"
TOOL_PROMPT = "TOOL-ONLY-PI-FEASIBILITY"
REMINDER_INITIAL = "REMINDER-INITIAL-PI-FEASIBILITY"
REMINDER_EDITED = "REMINDER-EDITED-PI-FEASIBILITY\nSecond line must stay exact."

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


class CheckFailure(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def wait_for(predicate: Callable[[], bool], description: str, timeout: float = TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise CheckFailure(f"timed out waiting for {description}")


def extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def all_request_text(body: dict[str, Any]) -> str:
    return "\n".join(extract_text(message.get("content")) for message in body.get("messages", []))


def require_isolated_pi(pi_bin: str) -> None:
    package = os.environ.get("PI_STANDING_REMINDER_ORIGIN_PACKAGE")
    require(bool(package), "run this proof through tests/standing-reminder/isolated_pi.py")
    executable = Path(pi_bin).resolve()
    try:
        executable.relative_to(Path(package).resolve())
    except ValueError as exc:
        raise CheckFailure(f"PI_BIN is outside the staged Pi package: {executable}") from exc


def user_message_texts(body: dict[str, Any]) -> list[str]:
    return [
        extract_text(message.get("content")) for message in body.get("messages", [])
        if message.get("role") == "user"
    ]


def sse_chunk(handler: http.server.BaseHTTPRequestHandler, delta: dict[str, Any], finish: str | None = None) -> None:
    payload = {
        "id": "chatcmpl-standing-feasibility",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "feasibility",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    handler.wfile.write(f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode())
    handler.wfile.flush()


def sse_text(handler: http.server.BaseHTTPRequestHandler, text: str) -> None:
    sse_chunk(handler, {"content": text})


def sse_start(handler: http.server.BaseHTTPRequestHandler) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()
    sse_chunk(handler, {"role": "assistant"})


def sse_finish(handler: http.server.BaseHTTPRequestHandler, reason: str = "stop") -> None:
    sse_chunk(handler, {}, reason)
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()


class ScriptedProvider(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.errors: list[str] = []
        self.initial_request_open = threading.Event()
        self.allow_initial_chunk = threading.Event()
        self.initial_chunk_sent = threading.Event()
        self.finish_initial = threading.Event()
        self.steer_request_open = threading.Event()
        self.finish_steer = threading.Event()
        self.generated_request_open = threading.Event()
        self.expanded_request_open = threading.Event()
        self.tool_request_open = threading.Event()
        self.tool_continuation_open = threading.Event()
        super().__init__(("127.0.0.1", 0), self.handler())

    def handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        provider = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, _format: str, *_args: Any) -> None:
                pass

            def do_POST(self) -> None:
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(size))
                    with provider.lock:
                        provider.requests.append(body)
                        index = len(provider.requests)
                    if index == 1:
                        provider.initial_request_open.set()
                        sse_start(self)
                        sse_text(self, "INITIAL-HEAD-PI-FEASIBILITY ")
                        provider._wait(provider.allow_initial_chunk, "editor-open initial chunk")
                        sse_text(self, "INITIAL-DURING-EDITOR-PI-FEASIBILITY ")
                        provider.initial_chunk_sent.set()
                        provider._wait(provider.finish_initial, "initial response release")
                        sse_text(self, "INITIAL-END-PI-FEASIBILITY")
                        sse_finish(self)
                    elif index == 2:
                        provider.steer_request_open.set()
                        sse_start(self)
                        sse_text(self, "STEER-OUTPUT-HEAD-PI-FEASIBILITY ")
                        provider._wait(provider.finish_steer, "steering response release")
                        sse_text(self, "STEER-OUTPUT-TAIL-PI-FEASIBILITY")
                        sse_finish(self)
                    elif index == 3:
                        provider.generated_request_open.set()
                        sse_start(self)
                        sse_text(self, "GENERATED-FOLLOWUP-ANSWER-PI-FEASIBILITY")
                        sse_finish(self)
                    elif index == 4:
                        provider.expanded_request_open.set()
                        sse_start(self)
                        sse_text(self, "EXPANDED-PROMPT-ANSWER-PI-FEASIBILITY")
                        sse_finish(self)
                    elif index == 5:
                        provider.tool_request_open.set()
                        sse_start(self)
                        arguments = json.dumps({"command": "printf TOOL-EXECUTED-PI-FEASIBILITY"})
                        sse_chunk(self, {"tool_calls": [{
                            "index": 0,
                            "id": "call-standing-feasibility",
                            "type": "function",
                            "function": {"name": "bash", "arguments": arguments},
                        }]})
                        sse_finish(self, "tool_calls")
                    elif index == 6:
                        provider.tool_continuation_open.set()
                        sse_start(self)
                        sse_text(self, "TOOL-CONTINUATION-ANSWER-PI-FEASIBILITY")
                        sse_finish(self)
                    else:
                        raise RuntimeError(f"unexpected provider request #{index}")
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:  # surfaced in the main test thread
                    with provider.lock:
                        provider.errors.append(f"request handler: {type(exc).__name__}: {exc}")
                    try:
                        self.send_error(500, str(exc))
                    except OSError:
                        pass

        return Handler

    @staticmethod
    def _wait(event: threading.Event, description: str) -> None:
        if not event.wait(TIMEOUT):
            raise TimeoutError(f"test gate timed out: {description}")

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.requests)

    def assert_healthy(self) -> None:
        with self.lock:
            errors = list(self.errors)
        require(not errors, "; ".join(errors))


EXTENSION_SOURCE = r'''import { appendFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";

const tracePath = process.env.FEASIBILITY_TRACE;
const initialReminder = "REMINDER-INITIAL-PI-FEASIBILITY";
const collisionText = "IDENTICAL-ORIGIN-PI-FEASIBILITY";
const state = { reminder: initialReminder, delivery: undefined, cancelNextCollision: false };
function trace(record) {
  appendFileSync(tracePath, JSON.stringify({ time: Date.now(), ...record }) + "\n");
}
function textOf(message) {
  if (typeof message?.content === "string") return message.content;
  return Array.isArray(message?.content)
    ? message.content.filter((part) => part?.type === "text").map((part) => part.text).join("\n")
    : "";
}
function addReminder(messages, reminder) {
  return [...messages, {
    role: "user",
    content: [{ type: "text", text: `<standing-reminder>\n${reminder}\n</standing-reminder>` }],
    timestamp: Date.now(),
  }];
}

export default function (pi) {
  pi.on("session_start", () => trace({ kind: "session_start" }));
  pi.on("input", (event) => {
    trace({ kind: "input", text: event.text, source: event.source ?? "unavailable", behavior: event.streamingBehavior ?? null });
    if (event.source === "extension" && event.text === collisionText && state.cancelNextCollision) {
      state.cancelNextCollision = false;
      trace({ kind: "input_cancelled", text: event.text, source: event.source, behavior: event.streamingBehavior ?? null });
      return { action: "handled" };
    }
    return { action: "continue" };
  });
  pi.on("message_start", (event) => {
    if (event.message.role !== "user") return;
    const text = textOf(event.message);
    const source = event.source ?? "unavailable";
    const accepted = source === "interactive" || source === "rpc";
    state.delivery = accepted
      ? { text, source, reminder: state.reminder, fresh: true }
      : undefined;
    trace({ kind: "processed", text, source, accepted });
  });
  pi.on("context", (event) => {
    const users = event.messages.filter((message) => message.role === "user");
    const latestText = users.length ? textOf(users[users.length - 1]) : "";
    if (!state.delivery || latestText !== state.delivery.text) {
      trace({ kind: "context_no_delivery", latestText });
      return;
    }
    const fresh = state.delivery.fresh;
    state.delivery.fresh = false;
    trace({ kind: fresh ? "reminder_delivered" : "reminder_carried", text: state.delivery.text, reminder: state.delivery.reminder });
    return { messages: addReminder(event.messages, state.delivery.reminder) };
  });
  pi.on("message_update", (event) => {
    if (event.message.role === "assistant") trace({ kind: "assistant_update", text: textOf(event.message) });
  });
  pi.on("agent_settled", () => trace({ kind: "agent_settled" }));

  pi.registerCommand("probe-edit-reminder", {
    description: "Feasibility probe: edit reminder in a same-terminal external editor",
    handler: async (_args, ctx) => {
      const settings = JSON.parse(readFileSync(join(ctx.cwd, ".pi", "settings.json"), "utf8"));
      const editor = settings.externalEditor;
      const directory = mkdtempSync(join(tmpdir(), "pi-standing-feasibility-"));
      const draft = join(directory, "reminder.txt");
      writeFileSync(draft, state.reminder, "utf8");
      await ctx.ui.custom((tui, _theme, _keybindings, done) => {
        tui.stop();
        process.stdout.write("\x1b[2J\x1b[H");
        trace({ kind: "editor_open", editor });
        const finish = (code) => {
          try {
            if (code === 0) {
              state.reminder = readFileSync(draft, "utf8");
              trace({ kind: "editor_committed", reminder: state.reminder });
            } else {
              trace({ kind: "editor_failed", code });
            }
          } finally {
            try { rmSync(directory, { recursive: true, force: true }); } catch {}
            tui.start();
            tui.requestRender(true);
            done(code);
          }
        };
        const child = spawn(editor, [draft], { stdio: "inherit", env: process.env });
        child.once("error", () => finish(null));
        child.once("close", (code) => finish(code));
        return { render: () => [] };
      });
    },
  });
  pi.registerCommand("probe-cancelled-neighbor", {
    description: "Feasibility probe: cancel an extension input before a same-text operator neighbor",
    handler: async () => {
      state.cancelNextCollision = true;
      pi.sendUserMessage(collisionText, { deliverAs: "followUp" });
    },
  });
  pi.registerCommand("probe-generated-followup", {
    description: "Feasibility probe: queue an extension-origin follow-up with the operator's exact text",
    handler: async () => {
      pi.sendUserMessage(collisionText, { deliverAs: "followUp" });
    },
  });
}
'''


EDITOR_SOURCE = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
control = Path(os.environ["FEASIBILITY_TRACE"])
release_dir = Path(os.environ["FEASIBILITY_EDITOR_RELEASE_DIR"])
counter = Path(os.environ["FEASIBILITY_EDITOR_COUNTER"])
try:
    invocation = int(counter.read_text(encoding="utf-8")) + 1
except FileNotFoundError:
    invocation = 1
counter.write_text(str(invocation), encoding="utf-8")
contents = json.loads(os.environ["FEASIBILITY_EDITOR_CONTENTS"])
def log(kind, **extra):
    with control.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"kind": kind, **extra}) + "\n")
log("fake_editor_started", path=sys.argv[1], invocation=invocation)
while not (release_dir / str(invocation)).exists():
    time.sleep(0.02)
Path(sys.argv[1]).write_text(contents[invocation - 1], encoding="utf-8")
log("fake_editor_saved", invocation=invocation)
'''


class PiPTY:
    def __init__(self, command: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
        self.process = subprocess.Popen(
            command, cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, close_fds=True,
        )
        os.close(slave)
        os.set_blocking(self.master, False)
        self.output = bytearray()
        self.output_lock = threading.Lock()
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
                    data = os.read(self.master, 65536)
                except (BlockingIOError, OSError):
                    if self.process.poll() is not None:
                        return
                    continue
                if not data:
                    return
                with self.output_lock:
                    self.output.extend(data)
        finally:
            self.reader_done.set()

    def send(self, text: str) -> None:
        os.write(self.master, text.encode() + b"\r")

    def plain_output(self) -> str:
        with self.output_lock:
            text = bytes(self.output).decode("utf-8", errors="replace")
        return ANSI.sub("", text)

    def wait_output(self, marker: str, timeout: float = TIMEOUT) -> None:
        wait_for(lambda: marker in self.plain_output(), f"Pi TUI output {marker!r}", timeout)

    def stop(self) -> None:
        self.reader_done.set()
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=2)
        try:
            os.close(self.master)
        except OSError:
            pass


class Journey:
    def __init__(self, trace_path: Path, pi: PiPTY, provider: ScriptedProvider) -> None:
        self.trace_path = trace_path
        self.pi = pi
        self.provider = provider

    def trace(self) -> list[dict[str, Any]]:
        try:
            lines = self.trace_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return records

    def wait_trace(self, predicate: Callable[[dict[str, Any]], bool], description: str) -> dict[str, Any]:
        result: dict[str, Any] | None = None

        def matched() -> bool:
            nonlocal result
            result = next((item for item in self.trace() if predicate(item)), None)
            return result is not None

        wait_for(matched, description)
        assert result is not None
        return result

    def wait_trace_count(self, predicate: Callable[[dict[str, Any]], bool], count: int, description: str) -> None:
        wait_for(lambda: sum(predicate(item) for item in self.trace()) >= count, description)

    def wait_request_count(self, count: int) -> None:
        wait_for(lambda: len(self.provider.snapshot()) >= count, f"provider request #{count}")


FOLLOWUP_EXTENSION_SOURCE = r'''import { appendFileSync } from "node:fs";
function trace(record) {
  appendFileSync(process.env.FEASIBILITY_TRACE, JSON.stringify(record) + "\n");
}
function textOf(message) {
  if (typeof message?.content === "string") return message.content;
  return Array.isArray(message?.content)
    ? message.content.filter((part) => part?.type === "text").map((part) => part.text).join("\n")
    : "";
}
export default function (pi) {
  pi.on("input", (event) => trace({ kind: "actual_input", text: event.text, source: event.source, behavior: event.streamingBehavior ?? null }));
  pi.on("message_start", (event) => {
    if (event.message.role === "user") {
      trace({ kind: "implementation_processed", text: textOf(event.message),
        source: (event as typeof event & { source?: unknown }).source ?? "unavailable" });
    }
  });
  pi.on("agent_settled", () => trace({ kind: "agent_settled" }));
  pi.registerCommand("probe-generated-followup", {
    description: "Queue an extension-origin follow-up for the standing-reminder journey",
    handler: async () => {
      pi.sendUserMessage("EXTENSION-FOLLOWUP-PI-FEASIBILITY", { deliverAs: "followUp" });
      trace({ kind: "followup_enqueued" });
    },
  });
}
'''


def write_test_files(root: Path, provider: ScriptedProvider, implemented_extension: Path | None = None) -> tuple[Path, Path, Path, Path]:
    agent_dir = root / "agent"
    project_dir = root / "project"
    trace_path = root / "trace.jsonl"
    release_path = root / "release-editor"
    agent_dir.mkdir()
    (agent_dir / "prompts").mkdir()
    (agent_dir / "prompts" / "expanded.md").write_text(
        "---\ndescription: origin provenance expansion fixture\n---\n"
        "EXPANDED-OPERATOR-PI-FEASIBILITY\n$ARGUMENTS",
        encoding="utf-8",
    )
    (project_dir / ".pi").mkdir(parents=True)
    release_path.mkdir()
    if implemented_extension is None:
        (root / "probe-extension.ts").write_text(EXTENSION_SOURCE, encoding="utf-8")
    else:
        (root / "followup-extension.ts").write_text(FOLLOWUP_EXTENSION_SOURCE, encoding="utf-8")
    editor_path = root / "fake-editor"
    editor_path.write_text(EDITOR_SOURCE, encoding="utf-8")
    editor_path.chmod(0o755)
    (project_dir / ".pi" / "settings.json").write_text(
        json.dumps({"externalEditor": str(editor_path)}), encoding="utf-8"
    )
    host, port = provider.server_address
    (agent_dir / "models.json").write_text(json.dumps({
        "providers": {
            "feasibility": {
                "baseUrl": f"http://{host}:{port}/v1",
                "api": "openai-completions",
                "apiKey": "scripted-provider-only",
                "models": [{
                    "id": "standing-reminder-test",
                    "name": "Standing reminder feasibility",
                    "api": "openai-completions",
                    "reasoning": False,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": 8192,
                    "maxTokens": 256,
                }],
            }
        }
    }), encoding="utf-8")
    return agent_dir, project_dir, trace_path, release_path


def run_journey() -> None:
    pi_bin = os.environ.get("PI_BIN") or shutil.which("pi")
    require(bool(pi_bin), "`pi` is not on PATH (or set PI_BIN)")
    require_isolated_pi(pi_bin)
    version = subprocess.run([pi_bin, "--version"], check=True, text=True, capture_output=True).stdout.strip()
    print(f"Using Pi {version}")

    with tempfile.TemporaryDirectory(prefix="pi-standing-feasibility-") as temporary:
        root = Path(temporary)
        provider = ScriptedProvider()
        provider_thread = provider.start()
        agent_dir, project_dir, trace_path, editor_release = write_test_files(root, provider)
        env = os.environ.copy()
        env.update({
            "PI_CODING_AGENT_DIR": str(agent_dir),
            "PI_CODING_AGENT_SESSION_DIR": str(root / "sessions"),
            "PI_OFFLINE": "1",
            "PI_TELEMETRY": "0",
            "TERM": "xterm-256color",
            "FEASIBILITY_TRACE": str(trace_path),
            "FEASIBILITY_EDITOR_RELEASE_DIR": str(editor_release),
            "FEASIBILITY_EDITOR_COUNTER": str(root / "editor-counter"),
            "FEASIBILITY_EDITOR_CONTENTS": json.dumps([REMINDER_EDITED]),
        })
        command = [
            pi_bin, "--no-session", "--no-extensions", "--no-context-files", "--approve",
            "--provider", "feasibility", "--model", "feasibility/standing-reminder-test",
            "--tools", "bash", "--extension", str(root / "probe-extension.ts"),
        ]
        pi = PiPTY(command, project_dir, env)
        journey = Journey(trace_path, pi, provider)
        try:
            journey.wait_trace(lambda event: event.get("kind") == "session_start", "Pi session_start hook")
            wait_for(lambda: pi.process.poll() is None and "standing-reminder-test" in pi.plain_output(), "real Pi TUI ready")

            pi.send(START)
            require(provider.initial_request_open.wait(TIMEOUT), "initial provider request never started")
            first_text = all_request_text(provider.snapshot()[0])
            require(START in first_text, "initial operator text changed before the provider request")
            first_processed = journey.wait_trace(
                lambda event: event.get("kind") == "processed" and event.get("text") == START,
                "initial processed-message origin",
            )
            require(first_processed.get("source") == "interactive", "initial message_start lost its interactive origin")

            pi.send("/probe-cancelled-neighbor")
            cancelled = journey.wait_trace(
                lambda event: event.get("kind") == "input_cancelled" and event.get("text") == STEER,
                "canceled extension input adjacent to same-text operator input",
            )
            require(cancelled.get("source") == "extension" and cancelled.get("behavior") == "followUp",
                    "the canceled queue neighbor was not an extension follow-up")
            pi.send(STEER)
            submitted_steer = journey.wait_trace(
                lambda event: event.get("kind") == "input" and event.get("text") == STEER
                and event.get("source") == "interactive" and event.get("behavior") == "steer",
                "interactive steering input event after canceled same-text neighbor",
            )
            require(submitted_steer.get("text") == STEER, "the original operator steering text changed at input")
            pi.send("/probe-edit-reminder")
            journey.wait_trace(lambda event: event.get("kind") == "editor_open", "same-terminal editor open")
            journey.wait_trace(lambda event: event.get("kind") == "fake_editor_started", "scripted editor process")

            provider.allow_initial_chunk.set()
            journey.wait_trace(
                lambda event: event.get("kind") == "assistant_update"
                and "INITIAL-DURING-EDITOR-PI-FEASIBILITY" in event.get("text", ""),
                "assistant output processed while editor owns terminal",
            )
            require(not any(event.get("kind") == "editor_committed" for event in journey.trace()),
                    "editor committed before the scripted close gate")

            (editor_release / "1").touch()
            committed = journey.wait_trace(lambda event: event.get("kind") == "editor_committed", "editor commit on close")
            require(committed.get("reminder") == REMINDER_EDITED, "editor did not preserve exact multiline reminder text")
            provider.finish_initial.set()
            require(provider.steer_request_open.wait(TIMEOUT), "queued operator steering did not reach the provider")

            requests = provider.snapshot()
            require(len(requests) >= 2, "steering request was not recorded")
            second_text = all_request_text(requests[1])
            require(STEER in second_text, "model request omitted the queued operator message")
            require(user_message_texts(requests[1]).count(STEER) == 1,
                    "queued operator message text was changed or duplicated in the model request")
            require(REMINDER_EDITED in second_text, "queued message did not use reminder state at processing time")
            require(REMINDER_INITIAL not in second_text, "queued message received stale pre-edit reminder")
            delivered_steer = journey.wait_trace(
                lambda event: event.get("kind") == "reminder_delivered" and event.get("text") == STEER,
                "reminder paired with processed steering message",
            )
            processed_steer = journey.wait_trace(
                lambda event: event.get("kind") == "processed" and event.get("text") == STEER
                and event.get("source") == "interactive",
                "processing-time steering provenance despite a canceled same-text extension neighbor",
            )
            require(processed_steer.get("accepted") is True,
                    "processed steering origin was not attributed to the operator")
            require(delivered_steer.get("reminder") == REMINDER_EDITED, "wrong reminder paired with steering")

            pi.send("/probe-generated-followup")
            journey.wait_trace(
                lambda event: event.get("kind") == "input" and event.get("text") == STEER
                and event.get("source") == "extension" and event.get("behavior") == "followUp",
                "extension-origin same-text follow-up input event",
            )
            provider.finish_steer.set()
            require(provider.generated_request_open.wait(TIMEOUT), "extension follow-up did not reach provider")
            requests = provider.snapshot()
            generated_text = all_request_text(requests[2])
            require(STEER in generated_text, "provider did not receive extension-generated same-text follow-up")
            require("<standing-reminder>" not in generated_text, "extension-generated follow-up received a new reminder")
            excluded = journey.wait_trace(
                lambda event: event.get("kind") == "processed" and event.get("text") == STEER
                and event.get("source") == "extension",
                "extension follow-up processing provenance",
            )
            require(excluded.get("source") == "extension" and not excluded.get("accepted"),
                    "extension-generated follow-up was not excluded")
            journey.wait_trace_count(lambda event: event.get("kind") == "agent_settled", 1, "first agent run to settle")
            same_text_origins = [
                event.get("source") for event in journey.trace()
                if event.get("kind") == "processed" and event.get("text") == STEER
            ]
            require(same_text_origins == ["interactive", "extension"],
                    f"identical processed text lost its per-message origins: {same_text_origins}")

            pi.send(TEMPLATE_INPUT)
            submitted_template = journey.wait_trace(
                lambda event: event.get("kind") == "input" and event.get("text") == TEMPLATE_INPUT,
                "operator prompt-template input before expansion",
            )
            require(submitted_template.get("source") == "interactive", "template input was not operator-origin")
            require(provider.expanded_request_open.wait(TIMEOUT), "expanded operator request did not reach provider")
            requests = provider.snapshot()
            expanded_text = all_request_text(requests[3])
            require(TEMPLATE_MESSAGE in expanded_text, "provider request omitted the expanded operator text")
            require(TEMPLATE_INPUT not in expanded_text, "raw template command replaced or leaked instead of expansion")
            require(REMINDER_EDITED in expanded_text and expanded_text.count("<standing-reminder>") == 1,
                    "expanded operator message did not receive exactly one current reminder")
            processed_template = journey.wait_trace(
                lambda event: event.get("kind") == "processed" and event.get("text") == TEMPLATE_MESSAGE,
                "expanded message_start provenance",
            )
            require(processed_template.get("source") == "interactive" and processed_template.get("accepted"),
                    "prompt expansion lost the source of the actual processed message")
            journey.wait_trace(
                lambda event: event.get("kind") == "reminder_delivered" and event.get("text") == TEMPLATE_MESSAGE
                and event.get("reminder") == REMINDER_EDITED,
                "current reminder paired with expanded operator message",
            )
            journey.wait_trace_count(lambda event: event.get("kind") == "agent_settled", 2,
                                     "expanded operator run to settle")

            pi.send(TOOL_PROMPT)
            require(provider.tool_request_open.wait(TIMEOUT), "operator tool-call request did not reach provider")
            require(provider.tool_continuation_open.wait(TIMEOUT), "tool-only continuation did not reach provider")
            requests = provider.snapshot()
            require(len(requests) == 6, f"expected six provider requests, got {len(requests)}")
            tool_first_text = all_request_text(requests[4])
            tool_followup_text = all_request_text(requests[5])
            require(TOOL_PROMPT in tool_first_text and REMINDER_EDITED in tool_first_text,
                    "operator tool request was not paired with the current reminder")
            require(TOOL_PROMPT in tool_followup_text, "tool continuation lost its operator request")
            require(tool_followup_text.count("<standing-reminder>") == 1,
                    "tool continuation did not carry exactly one existing reminder projection")
            tool_delivery = journey.wait_trace(
                lambda event: event.get("kind") == "reminder_delivered" and event.get("text") == TOOL_PROMPT,
                "one reminder delivery for tool-triggering operator message",
            )
            require(tool_delivery.get("reminder") == REMINDER_EDITED, "tool-triggering request used stale reminder")
            journey.wait_trace(
                lambda event: event.get("kind") == "reminder_carried" and event.get("text") == TOOL_PROMPT,
                "existing reminder carried through tool-only continuation",
            )
            journey.wait_trace_count(lambda event: event.get("kind") == "agent_settled", 3, "tool continuation to settle")

            pi.wait_output("INITIAL-DURING-EDITOR-PI-FEASIBILITY")
            pi.wait_output("INITIAL-END-PI-FEASIBILITY")
            pi.wait_output("STEER-OUTPUT-TAIL-PI-FEASIBILITY")
            pi.wait_output("GENERATED-FOLLOWUP-ANSWER-PI-FEASIBILITY")
            pi.wait_output("EXPANDED-PROMPT-ANSWER-PI-FEASIBILITY")
            pi.wait_output("TOOL-CONTINUATION-ANSWER-PI-FEASIBILITY")
            require(pi.process.poll() is None, "Pi exited after editor return instead of continuing")
            provider.assert_healthy()
            print("PASS: identical operator/extension text retained per-message origin; canceled extension neighbor did not steal it")
            print("PASS: expanded prompt-template input retained operator origin and exact processed text")
            print("PASS: queued operator steering used the reminder saved while its response streamed")
            print("PASS: editor overlapped streaming; Pi redrew all accumulated and subsequent output after close")
            print("PASS: extension follow-up got no reminder; tool-only continuation carried one existing projection")
            print("Boundary exercised: input + message_start + context; ctx.ui.custom + TUI stop/start/requestRender")
        finally:
            pi.stop()
            provider.shutdown()
            provider.server_close()
            provider_thread.join(timeout=1)


def run_implemented_journey(extension_path: Path) -> None:
    pi_bin = os.environ.get("PI_BIN") or shutil.which("pi")
    require(bool(pi_bin), "`pi` is not on PATH (or set PI_BIN)")
    require_isolated_pi(pi_bin)
    require(extension_path.is_file(), f"extension source does not exist: {extension_path}")
    version = subprocess.run([pi_bin, "--version"], check=True, text=True, capture_output=True).stdout.strip()
    print(f"Using Pi {version} with {extension_path}")

    with tempfile.TemporaryDirectory(prefix="pi-standing-implemented-") as temporary:
        root = Path(temporary)
        provider = ScriptedProvider()
        provider_thread = provider.start()
        agent_dir, project_dir, trace_path, editor_release = write_test_files(root, provider, extension_path)
        env = os.environ.copy()
        env.update({
            "PI_CODING_AGENT_DIR": str(agent_dir),
            "PI_CODING_AGENT_SESSION_DIR": str(root / "sessions"),
            "PI_OFFLINE": "1",
            "PI_TELEMETRY": "0",
            "TERM": "xterm-256color",
            "FEASIBILITY_TRACE": str(trace_path),
            "FEASIBILITY_EDITOR_RELEASE_DIR": str(editor_release),
            "FEASIBILITY_EDITOR_COUNTER": str(root / "editor-counter"),
            "FEASIBILITY_EDITOR_CONTENTS": json.dumps([REMINDER_INITIAL, REMINDER_EDITED]),
        })
        command = [
            pi_bin, "--no-session", "--no-extensions", "--no-context-files", "--approve",
            "--provider", "feasibility", "--model", "feasibility/standing-reminder-test",
            "--tools", "bash", "--extension", str(extension_path),
            "--extension", str(root / "followup-extension.ts"),
        ]
        pi = PiPTY(command, project_dir, env)
        journey = Journey(trace_path, pi, provider)
        try:
            wait_for(lambda: pi.process.poll() is None and "standing-reminder-test" in pi.plain_output(), "real Pi TUI ready")
            pi.wait_output("No session reminder")

            pi.send("/reminder")
            journey.wait_trace(lambda event: event.get("kind") == "fake_editor_started" and event.get("invocation") == 1,
                               "initial configured editor")
            (editor_release / "1").touch()
            journey.wait_trace(lambda event: event.get("kind") == "fake_editor_saved" and event.get("invocation") == 1,
                               "initial editor close")
            pi.wait_output("REMINDER-INITIAL-PI-FEASIBILITY")

            pi.send(START)
            require(provider.initial_request_open.wait(TIMEOUT), "initial provider request never started")
            requests = provider.snapshot()
            first_text = all_request_text(requests[0])
            require(START in first_text and REMINDER_INITIAL in first_text,
                    "the implementation's initial operator request did not receive the saved reminder")
            require(first_text.count("<standing-reminder>") == 1,
                    "the initial operator request did not receive exactly one reminder projection")

            pi.send(STEER)
            pi.wait_output(STEER)
            journey.wait_trace(
                lambda event: event.get("kind") == "actual_input" and event.get("text") == STEER
                and event.get("source") == "interactive" and event.get("behavior") == "steer",
                "operator steering submission",
            )
            pi.send("/reminder")
            journey.wait_trace(lambda event: event.get("kind") == "fake_editor_started" and event.get("invocation") == 2,
                               "streaming edit through the implementation command")

            provider.allow_initial_chunk.set()
            require(provider.initial_chunk_sent.wait(TIMEOUT), "provider did not stream while the external editor was open")
            require(not any(event.get("kind") == "fake_editor_saved" and event.get("invocation") == 2
                            for event in journey.trace()), "streaming editor committed before close")
            (editor_release / "2").touch()
            journey.wait_trace(lambda event: event.get("kind") == "fake_editor_saved" and event.get("invocation") == 2,
                               "streaming editor close")
            pi.wait_output("REMINDER-EDITED-PI-FEASIBILITY")

            provider.finish_initial.set()
            require(provider.steer_request_open.wait(TIMEOUT), "queued operator steering did not reach the provider")
            requests = provider.snapshot()
            second_text = all_request_text(requests[1])
            require(STEER in second_text, "the implementation changed or lost the queued operator message")
            processed_steer = journey.wait_trace(
                lambda event: event.get("kind") == "implementation_processed" and event.get("text") == STEER,
                "processed-message provenance for queued steering",
            )
            require(processed_steer.get("source") == "interactive",
                    "queued steering did not carry its exact operator source to message_start")
            require(REMINDER_EDITED in second_text and REMINDER_INITIAL not in second_text,
                    "queued operator message did not use the edited value at processing time")
            require(second_text.count("<standing-reminder>") == 1,
                    "queued operator message did not receive exactly one current reminder")

            pi.send("/probe-generated-followup")
            journey.wait_trace(lambda event: event.get("kind") == "followup_enqueued", "extension follow-up enqueue")
            journey.wait_trace(
                lambda event: event.get("kind") == "actual_input" and event.get("text") == GENERATED
                and event.get("source") == "extension" and event.get("behavior") == "followUp",
                "extension-origin follow-up input",
            )
            provider.finish_steer.set()
            require(provider.generated_request_open.wait(TIMEOUT), "extension follow-up did not reach provider")
            generated_text = all_request_text(provider.snapshot()[2])
            require(GENERATED in generated_text, "provider did not receive extension-generated follow-up")
            require("<standing-reminder>" not in generated_text,
                    "extension-generated follow-up received a reminder intended for the operator")
            processed_generated = journey.wait_trace(
                lambda event: event.get("kind") == "implementation_processed" and event.get("text") == GENERATED,
                "processed-message provenance for extension follow-up",
            )
            require(processed_generated.get("source") == "extension",
                    "extension follow-up did not retain its exact extension source")
            journey.wait_trace_count(lambda event: event.get("kind") == "agent_settled", 1,
                                     "first agent run to settle")

            pi.send(TEMPLATE_INPUT)
            require(provider.expanded_request_open.wait(TIMEOUT), "expanded operator prompt did not reach the provider")
            expanded_text = all_request_text(provider.snapshot()[3])
            require(TEMPLATE_MESSAGE in expanded_text and TEMPLATE_INPUT not in expanded_text,
                    "the processed prompt-template text was changed or replaced")
            require(REMINDER_EDITED in expanded_text and expanded_text.count("<standing-reminder>") == 1,
                    "the expanded operator message did not receive exactly one current reminder")
            processed_template = journey.wait_trace(
                lambda event: event.get("kind") == "implementation_processed" and event.get("text") == TEMPLATE_MESSAGE,
                "expanded message_start provenance in the implementation",
            )
            require(processed_template.get("source") == "interactive",
                    f"prompt expansion lost the actual operator message origin: {processed_template!r}")
            journey.wait_trace_count(lambda event: event.get("kind") == "agent_settled", 2,
                                     "expanded operator run to settle")

            pi.send(TOOL_PROMPT)
            require(provider.tool_request_open.wait(TIMEOUT), "operator tool-call request did not reach the provider")
            require(provider.tool_continuation_open.wait(TIMEOUT), "tool-only continuation did not reach the provider")
            requests = provider.snapshot()
            require(len(requests) == 6, f"expected six provider requests, got {len(requests)}")
            tool_first_text = all_request_text(requests[4])
            tool_followup_text = all_request_text(requests[5])
            require(TOOL_PROMPT in tool_first_text and REMINDER_EDITED in tool_first_text,
                    "tool-triggering operator request did not receive the current reminder")
            require(tool_first_text.count("<standing-reminder>") == 1,
                    "tool-triggering operator request did not receive exactly one projection")
            require(TOOL_PROMPT in tool_followup_text and tool_followup_text.count("<standing-reminder>") == 1,
                    "ordinary tool-only continuation duplicated or lost its existing projection")
            journey.wait_trace_count(lambda event: event.get("kind") == "agent_settled", 3,
                                     "tool continuation to settle")

            pi.wait_output("INITIAL-DURING-EDITOR-PI-FEASIBILITY")
            pi.wait_output("INITIAL-END-PI-FEASIBILITY")
            pi.wait_output("STEER-OUTPUT-TAIL-PI-FEASIBILITY")
            pi.wait_output("GENERATED-FOLLOWUP-ANSWER-PI-FEASIBILITY")
            pi.wait_output("EXPANDED-PROMPT-ANSWER-PI-FEASIBILITY")
            pi.wait_output("TOOL-CONTINUATION-ANSWER-PI-FEASIBILITY")
            require(pi.process.poll() is None, "Pi exited after the editor returned instead of continuing")
            provider.assert_healthy()
            print("PASS: real extension delivered the exact initial reminder and the edited queued-steer value")
            print("PASS: edited text reached the next operator message; prompt-template expansion retained provenance")
            print("PASS: editor overlapped streaming; extension follow-up was excluded; tool continuation carried one projection")
            print("Boundary exercised: implemented extension in Pi 0.87.1, configured external editor, input/message_start/context")
        finally:
            pi.stop()
            provider.shutdown()
            provider.server_close()
            provider_thread.join(timeout=1)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension", type=Path, help="also run the black-box journey against this implementation")
    args = parser.parse_args()
    try:
        if args.extension:
            run_implemented_journey(args.extension.resolve())
        else:
            run_journey()
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
