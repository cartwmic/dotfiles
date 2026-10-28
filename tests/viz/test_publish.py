#!/usr/bin/env python3
"""Black-box tests for `viz publish` against a scripted local site.

The site is a small HTTP server in this process that accepts PUTs with basic
auth (user viz), like the nginx site in cartwmic-homelab-v2 k8s/viz. Publishing
a saved render needs only node; publishing a file also renders it, so that test
needs Chromium and mmdc. Run: python3 tests/viz/test_publish.py
"""
import base64
import http.server
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VIZ = os.path.join(ROOT, "dot_local", "bin", "executable_viz")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
NODE = shutil.which("node")
RENDER_DEPS = bool(NODE and shutil.which("mmdc") and (os.environ.get("VIZ_CHROMIUM") or shutil.which("chromium")))
PASSWORD = "test-password-not-a-secret"
RENDER_ID = "20261028-120000-000-abc123"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16 + b"rest of a png"
PAGE = b"<!doctype html><p>chart</p>\n"


class Site(http.server.BaseHTTPRequestHandler):
    files = {}

    def do_PUT(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        want = "Basic " + base64.b64encode(("viz:" + PASSWORD).encode()).decode()
        if self.headers.get("Authorization") != want:
            self.send_response(401)
            self.end_headers()
            return
        self.files[self.path] = (body, self.headers.get("Content-Type"))
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PublishTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Site.files = {}
        self.state = tempfile.TemporaryDirectory(prefix="viz-test-state-")
        self.addCleanup(self.state.cleanup)
        folder = os.path.join(self.state.name, RENDER_ID)
        os.mkdir(folder)
        meta = {"id": RENDER_ID, "created": "2026-10-28T12:00:00.000Z", "as": "html", "input": "/in/chart.html",
                "png": os.path.join(folder, "image.png"), "html": os.path.join(folder, "page.html"),
                "source": os.path.join(folder, "source.html"), "width": 0, "height": 0, "bytes": len(PNG)}
        for name, data in (("image.png", PNG), ("page.html", PAGE), ("source.html", PAGE),
                           ("meta.json", json.dumps(meta).encode())):
            with open(os.path.join(folder, name), "wb") as f:
                f.write(data)
        # PATH without 1Password's op, so the shim never reaches a real vault.
        self.bin = tempfile.mkdtemp(prefix="viz-test-bin-")
        self.addCleanup(shutil.rmtree, self.bin)
        os.symlink(NODE, os.path.join(self.bin, "node"))
        self.env = {"PATH": self.bin + ":/usr/bin:/bin", "HOME": self.state.name, "VIZ_STATE_DIR": self.state.name,
                    "VIZ_PUBLISH_URL": self.base + "/", "VIZ_PUBLISH_PASSWORD": PASSWORD}

    def viz(self, *args, env=None, code=0):
        e = dict(self.env)
        for k, v in (env or {}).items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
        r = subprocess.run([VIZ, *args], capture_output=True, text=True, env=e, timeout=120)
        out = json.loads(r.stdout)  # exactly one JSON document
        self.assertIsInstance(out, dict)
        self.assertEqual(r.returncode, code, (out, r.stderr[-500:]))
        return out

    def last_record(self):
        with open(os.path.join(self.state.name, "actions.jsonl")) as f:
            return json.loads(f.readlines()[-1])

    def test_publish_saved_render(self):
        out = self.viz("publish", RENDER_ID)
        self.assertTrue(out["ok"])
        self.assertEqual(out["id"], RENDER_ID)
        self.assertEqual(out["url"], "%s/%s/" % (self.base, RENDER_ID))
        self.assertEqual(out["png_url"], "%s/%s/image.png" % (self.base, RENDER_ID))
        self.assertEqual(out["png"], os.path.join(self.state.name, RENDER_ID, "image.png"))
        self.assertEqual(Site.files, {
            "/%s/image.png" % RENDER_ID: (PNG, "image/png"),
            "/%s/index.html" % RENDER_ID: (PAGE, "text/html; charset=utf-8"),
        })
        record = self.last_record()
        self.assertEqual(record["command"], "publish")
        self.assertEqual(record["outcome"], out)
        self.assertEqual([s["status"] for s in record["steps"] if s["step"] == "upload"], [201, 201])
        with open(os.path.join(self.state.name, "actions.jsonl")) as f:
            self.assertNotIn(PASSWORD, f.read())

    def test_wrong_password(self):
        out = self.viz("publish", RENDER_ID, env={"VIZ_PUBLISH_PASSWORD": "wrong"}, code=5)
        self.assertEqual(out["code"], "publish_failed")
        self.assertIn("401", out["message"])
        self.assertIn("viz publish " + RENDER_ID, out["message"])
        self.assertEqual(Site.files, {})

    def test_site_down(self):
        out = self.viz("publish", RENDER_ID, env={"VIZ_PUBLISH_URL": "http://127.0.0.1:%d" % free_port()}, code=5)
        self.assertEqual(out["code"], "publish_failed")
        self.assertIn("ECONNREFUSED", out["message"])

    def test_no_password_and_no_op(self):
        out = self.viz("publish", RENDER_ID, env={"VIZ_PUBLISH_PASSWORD": None}, code=4)
        self.assertEqual(out["code"], "missing_dependency")
        self.assertIn("VIZ_PUBLISH_PASSWORD", out["message"])

    def test_shim_reads_the_password_from_op_only_for_publish(self):
        calls = os.path.join(self.bin, "op-calls")
        with open(os.path.join(self.bin, "op"), "w") as f:
            f.write("#!/bin/sh\necho \"$*\" >> %s\nprintf '%%s\\n' '%s'\n" % (calls, PASSWORD))
        os.chmod(os.path.join(self.bin, "op"), 0o755)
        self.viz("list", env={"VIZ_PUBLISH_PASSWORD": None})
        self.assertFalse(os.path.exists(calls), "op must not run for other commands")
        self.viz("publish", RENDER_ID, env={"VIZ_PUBLISH_PASSWORD": None})
        with open(calls) as f:
            self.assertEqual(f.read(), "read op://developer/viz-publish/password\n")
        self.assertEqual(len(Site.files), 2)

    def test_bad_input(self):
        for args in (("publish",), ("publish", "20990101-000000-000-abcdef"),
                     ("publish", RENDER_ID, "--width", "300"), ("publish", os.path.join(FIXTURES, "missing.mmd"))):
            self.assertEqual(self.viz(*args, code=2)["code"], "bad_input", args)
        out = self.viz("publish", RENDER_ID, env={"VIZ_PUBLISH_URL": "ftp://example"}, code=2)
        self.assertEqual(out["code"], "bad_input")

    @unittest.skipUnless(RENDER_DEPS, "needs mmdc and chromium (or VIZ_CHROMIUM) on PATH")
    def test_publish_file_renders_then_uploads(self):
        # The real PATH and HOME find Chromium and mmdc's headless shell; the password is set, so op never runs.
        env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
        out = self.viz("publish", os.path.join(FIXTURES, "flow.mmd"), env=env)
        self.assertNotEqual(out["id"], RENDER_ID)
        with open(out["png"], "rb") as f:
            self.assertEqual(Site.files["/%s/image.png" % out["id"]][0], f.read())
        with open(out["html"], "rb") as f:
            self.assertEqual(Site.files["/%s/index.html" % out["id"]][0], f.read())
        self.assertEqual(out["url"], "%s/%s/" % (self.base, out["id"]))


if __name__ == "__main__":
    unittest.main()
