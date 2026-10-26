#!/usr/bin/env python3
"""Real-Pi journey for the anthropic-stall-retry extension.

Drives the installed Pi CLI (read-only; nothing is patched or copied) against a local scripted
Anthropic SSE backend whose first reply sends pings but no content. Loads pi-response-visibility
from RESPONSE_VISIBILITY_ROOT (default ~/git/pi-response-visibility) plus this extension. Private
HOME and PI_CODING_AGENT_DIR; dummy key; no live provider.
"""
from __future__ import annotations

import http.server
import json
import os
import pty
import re
import select
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "dot_pi/private_agent/extensions/anthropic-stall-retry/index.ts"
VISIBILITY = Path(os.environ.get("RESPONSE_VISIBILITY_ROOT", Path.home() / "git/pi-response-visibility")) / "index.ts"
PI = Path.home() / ".pi/agent/install/releases/1.4.0/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"
MARKER = "STALL-RETRY-OK"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class Backend(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.plan: list[str] = []  # per request: "stall" or "ok"
        self.requests: list[dict] = []
        self.release = threading.Event()
        super().__init__(("127.0.0.1", 0), self.handler())

    def handler(self):
        backend = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                pass

            def event(self, name: str, value: dict) -> None:
                self.wfile.write(f"event: {name}\ndata: {json.dumps(value)}\n\n".encode())
                self.wfile.flush()

            def do_POST(self) -> None:
                index = len(backend.requests)
                backend.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                mode = backend.plan[index] if index < len(backend.plan) else "ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.event("message_start", {"type": "message_start", "message": {
                        "id": f"fixture-{index}", "type": "message", "role": "assistant", "model": "claude-stall-probe",
                        "content": [], "stop_reason": None, "stop_sequence": None,
                        "usage": {"input_tokens": 1, "output_tokens": 0}}})
                    if mode == "stall":
                        # Keep-alive pings with no content: the failure the owner sees.
                        while not backend.release.wait(0.3):
                            self.event("ping", {"type": "ping"})
                        return
                    self.event("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
                    self.event("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": MARKER}})
                    self.event("content_block_stop", {"type": "content_block_stop", "index": 0})
                    self.event("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}})
                    self.event("message_stop", {"type": "message_stop"})
                except (BrokenPipeError, ConnectionResetError):
                    pass

        return Handler


def user_texts(request: dict) -> list[str]:
    texts = []
    for message in request["messages"]:
        content = message["content"]
        parts = [content] if isinstance(content, str) else [p.get("text", "") for p in content if p.get("type") == "text"]
        texts.append(f"{message['role']}:{' '.join(parts)}")
    return texts


def run(backend: Backend, root: Path, plan: list[str], env_extra: dict, release_after: float | None = None, visibility: bool = True) -> tuple[list[dict], str]:
    backend.plan = plan
    backend.requests.clear()
    backend.release.clear()
    env = os.environ.copy()
    env.update({"HOME": str(root), "PI_CODING_AGENT_DIR": str(root / "agent"), "PI_OFFLINE": "1"})
    for key in ("PI_ANTHROPIC_STALL_RETRY_MS", "PI_ANTHROPIC_STALL_RETRY_MAX"):
        env.pop(key, None)
    env.update(env_extra)
    if release_after is not None:
        threading.Timer(release_after, backend.release.set).start()
    started = time.monotonic()
    result = subprocess.run(["node", str(PI), "--mode", "json", "--no-session", "--no-extensions", "--no-skills",
        "--no-prompt-templates", "--no-context-files", "--no-approve",
        *(["--extension", str(VISIBILITY)] if visibility else []), "--extension", str(EXTENSION), "Return the marker."], cwd=root, env=env, capture_output=True, text=True, timeout=40)
    backend.release.set()
    records = [json.loads(line) for line in result.stdout.splitlines() if line.strip().startswith("{")]
    return records, f"rc={result.returncode} {time.monotonic() - started:.1f}s stderr={result.stderr[-800:]}"


def tui(backend: Backend, root: Path, env_extra: dict) -> str:
    """Interactive TUI in a PTY: the retry notice must be visible on screen and the answer must arrive."""
    backend.plan = ["stall", "ok"]
    backend.requests.clear()
    backend.release.clear()
    env = os.environ.copy()
    env.update({"HOME": str(root), "PI_CODING_AGENT_DIR": str(root / "agent"), "PI_OFFLINE": "1", "TERM": "xterm-256color",
                "COLUMNS": "200", "LINES": "50", **env_extra})
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(root)
        os.execvpe("node", ["node", str(PI), "--no-session", "--no-extensions", "--no-skills", "--no-prompt-templates",
            "--no-context-files", "--no-approve", "--extension", str(VISIBILITY), "--extension", str(EXTENSION),
            "Return the marker."], env)
    screen = b""
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                try:
                    screen += os.read(fd, 65536)
                except OSError:
                    break
            plain = re.sub(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07", b"", screen)
            if b"Aborting and sending" in plain and plain.count(MARKER.encode()) >= 1 and len(backend.requests) == 2:
                return plain.decode(errors="replace")
        raise RuntimeError(f"TUI: notice/answer not seen; requests={len(backend.requests)}; tail={screen[-1500:]!r}")
    finally:
        backend.release.set()
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)


def main() -> None:
    require(PI.exists() and VISIBILITY.exists(), f"missing {PI} or {VISIBILITY}")
    backend = Backend()
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="pi-stall-retry-") as temporary:
            root = Path(temporary)
            (root / "agent").mkdir()
            (root / "agent/settings.json").write_text(json.dumps({"defaultProvider": "anthropic", "defaultModel": "claude-stall-probe",
                "retry": {"enabled": False}, "compaction": {"enabled": False}, "cacheWarming": "off"}))
            (root / "agent/models.json").write_text(json.dumps({"providers": {"anthropic": {
                "api": "anthropic-messages", "baseUrl": f"http://127.0.0.1:{backend.server_port}", "apiKey": "test-only-dummy",
                "models": [{"id": "claude-stall-probe", "reasoning": False, "input": ["text"], "contextWindow": 32768, "maxTokens": 128,
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}]}}}))
            state = root / ".local/state/pi-response-visibility"
            state.mkdir(parents=True)
            (state / "settings.json").write_text(json.dumps({"quietMs": 500, "capture": "off"}))
            fast = {"PI_ANTHROPIC_STALL_RETRY_MS": "2000"}

            # 1. Stall, then recover on retry: one abort, one "continue", completed answer, prompt not duplicated.
            records, info = run(backend, root, ["stall", "ok"], fast)
            require(len(backend.requests) == 2, f"stall+ok: expected 2 provider requests, got {len(backend.requests)}; {info}")
            second = user_texts(backend.requests[1])
            require(second == ["user:Return the marker.", "user:continue"], f"retry request context: {second}")
            ends = [r["message"] for r in records if r.get("type") == "message_end"]
            stops = [m.get("stopReason") for m in ends if m.get("role") == "assistant"]
            require(stops == ["aborted", "stop"], f"assistant outcomes {stops}; {info}")
            require(any(p.get("text") == MARKER for p in ends[-1].get("content", [])), f"final answer missing marker; {info}")
            print(f"PASS: stall -> abort -> continue -> completed answer; retry context {second}; {info.split(' stderr')[0]}")

            # 2. Healthy reply: no abort, one request.
            records, info = run(backend, root, ["ok"], fast)
            require(len(backend.requests) == 1, f"healthy: {len(backend.requests)} requests; {info}")
            print("PASS: healthy reply is untouched (1 request)")

            # 3. Never recovers: cap 1 means original + 1 retry, then it stops retrying.
            records, info = run(backend, root, ["stall", "stall", "stall"], {**fast, "PI_ANTHROPIC_STALL_RETRY_MAX": "1"}, release_after=9)
            require(len(backend.requests) == 2, f"cap: expected 2 requests, got {len(backend.requests)}; {info}")
            print("PASS: persistent stall stops at the retry cap (2 requests with MAX=1)")

            # 4. Disabled: stall is left alone.
            records, info = run(backend, root, ["stall"], {"PI_ANTHROPIC_STALL_RETRY_MS": "0"}, release_after=5)
            require(len(backend.requests) == 1, f"disabled: {len(backend.requests)} requests; {info}")
            print("PASS: PI_ANTHROPIC_STALL_RETRY_MS=0 disables retries")

            # 5. Without pi-response-visibility the extension stays inactive.
            records, info = run(backend, root, ["stall"], fast, release_after=5, visibility=False)
            require(len(backend.requests) == 1, f"no handle: {len(backend.requests)} requests; {info}")
            print("PASS: no observer handle -> no retries")

            # 6. Interactive TUI: the notice is visible and the retried answer renders.
            plain = tui(backend, root, fast)
            notice = re.search(r"Anthropic: no content progress for \d+s\. Aborting and sending \"continue\" \(retry 1/2\)\.", plain)
            require(notice is not None, "TUI notice text differs")
            print(f"PASS: TUI shows '{notice.group(0)}' and renders {MARKER}")
    finally:
        backend.release.set()
        backend.shutdown()
        backend.server_close()


if __name__ == "__main__":
    main()
