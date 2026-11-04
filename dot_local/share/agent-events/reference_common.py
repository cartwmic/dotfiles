"""Helpers shared by parity_dump.py and rollback_drill.py (source-only, not deployed).

A loopback receiver that gunzips what the collector posts, the scratch-directory guard, and the one JSON style
the dump uses. Nothing here touches the live agent-events directories.
"""
import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from shadow_py_run import live_dirs  # noqa: F401  (one definition, in the deployed file; the guard lives there)


def dumps(obj):
    """Canonical JSON: sorted keys, no spaces, floats as the shortest round-trip repr, UTF-8 as is."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def refuse_live(path, what):
    """Exit-worthy error if `path` is, is inside, or contains a live agent-events directory."""
    p = Path(path).resolve()
    for live in live_dirs():
        if p == live or live in p.parents or p in live.parents:
            raise SystemExit(f"refusing: {what} {p} is, is inside or contains the live directory {live}")


def empty_dir(path, what):
    """Create `path` if missing; refuse if it holds anything or is live."""
    refuse_live(path, what)
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    if any(p.iterdir()):
        raise SystemExit(f"refusing: {what} {p} is not empty")
    return p


class Receiver:
    """A scripted OTLP receiver on 127.0.0.1. Each POST is gunzipped and kept in `.bodies`.
    `.script` is a list of HTTP status codes to answer with, in order; once it is empty the answer is 200."""

    def __init__(self, script=()):
        self.bodies, self.script, self.headers = [], list(script), []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.headers.append(dict(self.headers))
                code = outer.script.pop(0) if outer.script else 200
                if code == 200:
                    body = raw
                    if self.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(raw)
                    outer.bodies.append(json.loads(body))
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/v1/metrics" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def names(self):
        """Every metric name received, in order of arrival, de-duplicated."""
        out = []
        for body in self.bodies:
            for rm in body["resourceMetrics"]:
                for sm in rm["scopeMetrics"]:
                    for m in sm["metrics"]:
                        if m["name"] not in out:
                            out.append(m["name"])
        return out
