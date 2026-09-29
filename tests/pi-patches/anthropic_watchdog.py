#!/usr/bin/env python3
"""Exercise the watchdog through a private real Pi CLI and local Anthropic SSE."""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "dot_local/share/pi-patches/anthropic-idle-watchdog/patch.mjs"
TARGET = "node_modules/@earendil-works/pi-ai/dist/api/anthropic-messages.js"
MARKER = "chezmoi-pi-patch:anthropic-idle-watchdog v2"
SIBLING = "chezmoi-pi-patch:empty-turn-retry v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


class Backend(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.mode = "healthy"
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
                backend.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    self.event("message_start", {"type": "message_start", "message": {
                        "id": "watchdog-fixture", "type": "message", "role": "assistant",
                        "model": "watchdog-probe", "content": [], "stop_reason": None,
                        "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 0},
                    }})
                    self.event("ping", {"type": "ping"})
                    if backend.mode == "stall":
                        backend.release.wait(10)
                        return
                    if backend.mode == "disabled":
                        # Intentional simulated provider silence, not a readiness wait.
                        time.sleep(0.25)
                    self.event("content_block_start", {"type": "content_block_start", "index": 0,
                                                        "content_block": {"type": "text", "text": ""}})
                    self.event("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                        "delta": {"type": "text_delta", "text": "WATCHDOG-COMPLETE"}})
                    self.event("content_block_stop", {"type": "content_block_stop", "index": 0})
                    self.event("message_delta", {"type": "message_delta", "delta": {
                        "stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}})
                    self.event("message_stop", {"type": "message_stop"})
                except (BrokenPipeError, ConnectionResetError):
                    pass

        return Handler


def main() -> None:
    source = Path(subprocess.check_output(["npm", "root", "-g"], text=True).strip()) / "@earendil-works/pi-coding-agent"
    require(json.loads((source / "package.json").read_text())["version"] == "0.99.1", "proof is prepared for Pi 0.99.1")
    bundles = list((source / "dist/bundle/chunks").glob("anthropic-messages-*.js"))
    require(len(bundles) == 1, "expected one installed Anthropic bundle")
    source_hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in [source / TARGET, bundles[0]]}
    backend = Backend()
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="pi-watchdog-proof-") as temporary:
            root = Path(temporary)
            package = root / "pi-coding-agent"
            shutil.copytree(source, package, symlinks=True)
            target = package / TARGET
            # Retain a sibling edit even when running against an otherwise clean install.
            if SIBLING not in target.read_text():
                with target.open("a") as stream:
                    stream.write(f"\n// {SIBLING} — composition fixture\n")
            env = os.environ.copy()
            env["PI_ANTHROPIC_IDLE_WATCHDOG_PACKAGE"] = str(package)

            def patch(*args: str, success: bool = True) -> None:
                result = subprocess.run(["node", str(PATCH), *args], env=env, capture_output=True, text=True)
                require((result.returncode == 0) == success, f"unexpected patch outcome: {result.stdout}{result.stderr}")

            patch()
            patched = target.read_bytes()
            patch()
            patch("--check")
            require(target.read_bytes() == patched and SIBLING in target.read_text(), "reapply changed the file or sibling")
            target.write_bytes(patched.replace(MARKER.encode(), MARKER.replace("v2", "v1").encode()))
            stale = target.read_bytes()
            patch(success=False)
            require(target.read_bytes() == stale, "stale revision restored a shared-file backup")
            target.write_bytes(patched.replace(b'    "ping", // ' + MARKER.encode(), b'    "ping", // incomplete'))
            partial = target.read_bytes()
            patch("--check", success=False)
            require(target.read_bytes() == partial, "partial check changed its target")
            target.write_bytes(patched)

            agent = root / "agent"
            agent.mkdir()
            (agent / "settings.json").write_text(json.dumps({
                "defaultProvider": "watchdog-fixture", "defaultModel": "watchdog-probe",
                "retry": {"enabled": False}, "compaction": {"enabled": False}, "cacheWarming": "off",
            }))
            (agent / "models.json").write_text(json.dumps({"providers": {"watchdog-fixture": {
                "api": "anthropic-messages", "baseUrl": f"http://127.0.0.1:{backend.server_port}",
                "apiKey": "test-only-dummy", "models": [{"id": "watchdog-probe", "reasoning": False,
                    "input": ["text"], "contextWindow": 32768, "maxTokens": 128,
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}],
            }}}))
            observer = root / "observer.ts"
            observer.write_text('''import { appendFileSync } from "node:fs";
export default function(pi) {
  pi.on("provider_stream_event", event => {
    appendFileSync(process.env.WATCHDOG_TRACE, JSON.stringify({ type: event.data.type }) + "\\n");
  });
}
''')
            trace = root / "events.jsonl"
            env.update({"PI_CODING_AGENT_DIR": str(agent), "PI_OFFLINE": "1", "WATCHDOG_TRACE": str(trace)})
            cli = package / "dist/bundle/cli.js"
            for mode, idle_ms in [("healthy", "1000"), ("stall", "100"), ("disabled", "0")]:
                backend.mode = mode
                trace.write_text("")
                env["PI_STREAM_IDLE_TIMEOUT_MS"] = idle_ms
                before = len(backend.requests)
                result = subprocess.run([str(cli), "--mode", "json", "--no-session", "--no-extensions",
                    "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve",
                    "--extension", str(observer), "Return the completion marker."], cwd=root, env=env,
                    capture_output=True, text=True, timeout=15)
                require(len(backend.requests) == before + 1, f"{mode}: expected exactly one local provider request: {result.stderr}")
                records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
                answers = [record["message"] for record in records if record.get("type") == "message_end"
                           and record.get("message", {}).get("role") == "assistant"]
                require(answers, f"{mode}: CLI produced no completed assistant message: {result.stderr}")
                answer = answers[-1]
                if mode == "stall":
                    require(answer.get("stopReason") == "error" and "Anthropic SSE idle for 100ms" in answer.get("errorMessage", ""),
                            f"stalled body did not terminate through the watchdog: {answer}")
                    backend.release.set()
                else:
                    require(result.returncode == 0 and answer.get("stopReason") == "stop"
                            and any(part.get("text") == "WATCHDOG-COMPLETE" for part in answer.get("content", [])),
                            f"{mode}: no successful completed answer: {answer}; {result.stderr}")
                observed = [json.loads(line)["type"] for line in trace.read_text().splitlines()]
                require("ping" in observed, f"{mode}: provider observers did not receive ping")
                print(f"PASS: {mode} real-Pi request completed; provider callback received ping")
    finally:
        backend.release.set()
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=2)
    require(all(hashlib.sha256(path.read_bytes()).digest() == digest for path, digest in source_hashes.items()),
            "installed provider or CLI bundle changed during isolated proof")
    print("PASS: patch reapply, stale/partial refusal, sibling preservation, and unchanged installed SDK/CLI")


if __name__ == "__main__":
    main()
