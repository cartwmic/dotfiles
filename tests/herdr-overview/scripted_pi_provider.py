#!/usr/bin/env python3
"""Loopback-only scripted Pi provider retained across proof scenarios."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

FIRST_REPLY = "\n".join(
    [f"Scripted Pi proof reply, review line {index:02d}: deterministic response content."
     for index in range(1, 38)]
    + ["Present state: the scripted response is complete; no external model was called."]
)
FOLLOWUP_REPLY = "Scripted Pi response after native pane move: present state remains unchanged."


class ProviderState:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.count = 0
        self.lock = threading.Lock()


class ProviderHandler(BaseHTTPRequestHandler):
    state: ProviderState

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        state = type(self).state
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", "replace")
        with state.lock:
            state.count += 1
            count = state.count
            capture = {
                "request_number": count,
                "path": self.path,
                "body": body,
                "received_at": time.time(),
            }
            with (state.root / "scripted-provider-requests.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(capture, ensure_ascii=False) + "\n")

        if count == 1:
            release = state.root / "scripted-provider-release-first"
            deadline = time.monotonic() + 75
            while not release.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not release.exists():
                self.send_error(504, "proof did not release the first scripted response")
                return
        text = FIRST_REPLY if count == 1 else FOLLOWUP_REPLY
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        common: dict[str, Any] = {
            "id": f"t8-scripted-{count}",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "scripted-model",
        }
        chunks = [
            {**common, "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
            {**common, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60}},
        ]
        try:
            for chunk in chunks:
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit("proof root does not exist")
    state = ProviderState(root)
    handler = type("BoundProviderHandler", (ProviderHandler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    ready = {
        "pid": os.getpid(),
        "root": str(root),
        "host": "127.0.0.1",
        "port": server.server_address[1],
    }
    ready_path = root / "scripted-provider-ready.json"
    temporary = ready_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(ready) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, ready_path)
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
