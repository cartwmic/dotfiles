"""scripts/ci-install-tool.sh: a pinned, retried, checksum-checked download of one tool from a release (a local server stands in for GitHub)."""
import hashlib
import http.server
import io
import os
import platform
import subprocess
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci-install-tool.sh"
REAL_PINS = ROOT / "scripts" / "ci-tool-pins.txt"
FILE = "faketool_1.0_any.tar.gz"
PATH_IN_URL = f"/example/faketool/releases/download/v1.0/{FILE}"


def archive():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        data = b"#!/bin/sh\necho faketool 1.0\n"
        info = tarfile.TarInfo("bin/faketool")
        info.size = len(data)
        info.mode = 0o755
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def host_platform():
    os_name = {"Linux": "linux", "Darwin": "darwin"}[platform.system()]
    cpu = {"x86_64": "amd64", "AMD64": "amd64", "arm64": "arm64", "aarch64": "arm64"}[platform.machine()]
    return f"{os_name}-{cpu}"


class Server:
    """Answers `failures` times with HTTP 503, then serves the archive. `hits` counts the requests."""

    def __init__(self, body, failures):
        self.hits = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits += 1
                if outer.hits <= failures or self.path != PATH_IN_URL:
                    self.send_response(503)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class CiInstallToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        self.body = archive()
        self.sha = hashlib.sha256(self.body).hexdigest()
        self.bin = self.tmp / "bin"

    def pins(self, sha=None):
        path = self.tmp / "pins.txt"
        path.write_text(f"faketool v1.0 {host_platform()} example/faketool {FILE} {sha or self.sha} bin/faketool\n")
        return path

    def run_script(self, base_url, pins, tool="faketool"):
        env = dict(os.environ, CI_TOOL_BASE_URL=base_url, CI_TOOL_PINS=str(pins), CI_TOOL_RETRY_DELAY="1", TMPDIR=str(self.tmp))
        return subprocess.run(["sh", str(SCRIPT), tool, str(self.bin)], env=env, capture_output=True, text=True, timeout=120)

    def test_installs_the_checked_file(self):
        server = Server(self.body, failures=0)
        self.addCleanup(server.close)
        r = self.run_script(server.url, self.pins())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(subprocess.run([str(self.bin / "faketool")], capture_output=True, text=True).stdout, "faketool 1.0\n")

    def test_one_error_answer_is_retried_and_the_install_passes(self):
        server = Server(self.body, failures=1)
        self.addCleanup(server.close)
        r = self.run_script(server.url, self.pins())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(server.hits, 2)

    def test_an_error_every_time_fails_with_a_message_that_names_the_download(self):
        server = Server(self.body, failures=1000)
        self.addCleanup(server.close)
        r = self.run_script(server.url, self.pins())
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"ci-install-tool: download failed: {FILE} from {server.url}{PATH_IN_URL}", r.stderr)
        self.assertFalse((self.bin / "faketool").exists())

    def test_a_wrong_checksum_is_refused_and_nothing_is_installed(self):
        server = Server(self.body, failures=0)
        self.addCleanup(server.close)
        r = self.run_script(server.url, self.pins(sha="0" * 64))
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"checksum mismatch for {FILE}", r.stderr)
        self.assertFalse((self.bin / "faketool").exists())

    def test_a_tool_with_no_pin_for_this_platform_fails_plainly(self):
        r = self.run_script("http://127.0.0.1:9", self.pins(), tool="othertool")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no pin for othertool", r.stderr)

    def test_every_pin_in_the_real_file_is_one_line_of_seven_fields_with_a_sha256(self):
        rows = [l.split() for l in REAL_PINS.read_text().splitlines() if l.strip() and not l.startswith("#")]
        self.assertGreaterEqual(len(rows), 4)
        for row in rows:
            with self.subTest(row=row):
                self.assertEqual(len(row), 7)
                self.assertRegex(row[5], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
