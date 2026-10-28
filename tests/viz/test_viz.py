#!/usr/bin/env python3
"""Black-box tests for dot_local/bin/executable_viz.

Needs node, chromium (or VIZ_CHROMIUM), mmdc and Playwright's
chrome-headless-shell. Every test uses its own temporary VIZ_STATE_DIR.
Run: python3 tests/viz/test_viz.py
"""
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VIZ = os.path.join(ROOT, "dot_local", "bin", "executable_viz")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
# CI has node but no chromium or mmdc: there these tests skip and only the core and
# boundary tests run. On a machine with the tools they always run.
RENDER_DEPS = bool(shutil.which("node") and shutil.which("mmdc")
                   and (os.environ.get("VIZ_CHROMIUM") or shutil.which("chromium")))


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", head[16:24])


def png_pixel(path, x, y):
    """RGB of one pixel of an 8-bit, non-interlaced RGB or RGBA PNG (what Chromium writes)."""
    with open(path, "rb") as f:
        data = f.read()
    pos, idat = 8, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, _, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
    assert depth == 8 and color in (2, 6) and interlace == 0, (depth, color, interlace)
    bpp = 3 if color == 2 else 4
    raw, stride = zlib.decompress(idat), width * bpp
    prev = bytearray(stride)
    for row in range(y + 1):
        start = row * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
    return tuple(prev[x * bpp:x * bpp + 3])


@unittest.skipUnless(RENDER_DEPS, "needs node, mmdc and chromium (or VIZ_CHROMIUM) on PATH")
class VizTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory(prefix="viz-test-state-")
        self.addCleanup(self.state.cleanup)

    def viz(self, *args, stdin=None, env=None, code=0):
        e = dict(os.environ, VIZ_STATE_DIR=self.state.name)
        e.pop("VIZ_CHROMIUM", None)
        e.update(env or {})
        r = subprocess.run([VIZ, *args], input=stdin, capture_output=True, text=True, env=e, timeout=120)
        out = json.loads(r.stdout)  # exactly one JSON document
        self.assertIsInstance(out, dict)
        self.assertEqual(r.returncode, code, (out, r.stderr[-500:]))
        return out

    def assert_render(self, out, ext):
        self.assertTrue(out["ok"], out)
        folder = os.path.join(os.path.realpath(self.state.name), out["id"])
        self.assertEqual(os.path.realpath(os.path.dirname(out["png"])), folder)
        for name in ("image.png", "page.html", "source." + ext, "meta.json"):
            self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)
        with open(os.path.join(folder, "meta.json")) as f:
            self.assertEqual(json.load(f)["id"], out["id"])
        self.assertEqual(png_size(out["png"]), (out["width"], out["height"]))
        self.assertEqual(out["bytes"], os.path.getsize(out["png"]))

    def test_render_each_format(self):
        self.assert_render(self.viz("render", os.path.join(FIXTURES, "flow.mmd")), "mmd")
        self.assert_render(self.viz("render", os.path.join(FIXTURES, "chart.svg")), "svg")
        with open(os.path.join(FIXTURES, "flow.mmd")) as f:
            self.assert_render(self.viz("render", "-", "--as", "mermaid", stdin=f.read()), "mmd")

    def test_png_is_sized_to_content(self):
        out = self.viz("render", os.path.join(FIXTURES, "box-800x300.html"), "--width", "800", "--scale", "2")
        self.assert_render(out, "html")
        self.assertEqual((out["width"], out["height"]), (1600, 600))

    def test_bad_mermaid_reports_parser_message(self):
        out = self.viz("render", os.path.join(FIXTURES, "bad.mmd"), code=3)
        self.assertEqual(out["code"], "render_failed")
        self.assertIn("Parse error", out["message"])

    def test_bad_input(self):
        flow = os.path.join(FIXTURES, "flow.mmd")
        for args in (("render",), ("render", "-"), ("render", os.path.join(FIXTURES, "missing.mmd")),
                     ("render", flow, "--as", "png"),
                     ("render", flow, "--width", "wide"), ("render", flow, "--width", "0"),
                     ("render", flow, "--width", "1.5"), ("render", flow, "--scale", "0"),
                     ("render", flow, "--scale", "-1"), ("render", flow, "--scale", "Infinity"),
                     ("list", "--limit", "x"), ("frobnicate",), ()):
            out = self.viz(*args, stdin="", code=2)
            self.assertEqual(out["code"], "bad_input", args)

    def test_as_rejects_inherited_property_names(self):
        for name in ("constructor", "toString", "__proto__"):
            out = self.viz("render", "-", "--as", name, stdin="<p>Hello</p>\n", code=2)
            self.assertEqual(out["code"], "bad_input", name)
            out = self.viz("render", os.path.join(FIXTURES, "chart.svg"), "--as", name, code=2)
            self.assertEqual(out["code"], "bad_input", name)

    def test_width_and_scale_have_no_policy_bounds(self):
        out = self.viz("render", os.path.join(FIXTURES, "chart.svg"), "--width", "80", "--scale", "5")
        self.assert_render(out, "svg")

    def assert_color(self, got, want):
        self.assertTrue(all(abs(g - w) <= 8 for g, w in zip(got, want)), (got, want))

    def render_page(self, page_dir, html, *args):
        page = os.path.join(page_dir, "page.html")
        with open(page, "w") as f:
            f.write(html)
        out = self.viz("render", page, *args)
        self.assert_render(out, "html")
        with open(out["html"], "rb") as f, open(page, "rb") as g:
            self.assertEqual(f.read(), g.read(), "page.html must be a byte-exact copy of the source")
        return out

    def test_script_text_is_not_rewritten(self):
        # A "<head>" string inside a script must reach the browser untouched.
        html = ('<!doctype html><body><canvas id="c" width="800" height="300"></canvas><script>'
                'const label="<head>";document.getElementById("c").getContext("2d").fillRect(0,0,800,300)'
                '</script>')
        with tempfile.TemporaryDirectory(prefix="viz-test-page-") as page_dir:
            out = self.render_page(page_dir, html, "--width", "800", "--scale", "1")
        # Body margin 8px: the black rect covers (8,8)-(808,308); a blank page is white there.
        self.assert_color(png_pixel(out["png"], 408, 158), (0, 0, 0))

    def test_relative_base_resolves_against_the_source_directory(self):
        html = '<head><base href="./"></head><body><img src="chart.svg"></body>'
        with tempfile.TemporaryDirectory(prefix="viz-test-page-") as page_dir:
            with open(os.path.join(FIXTURES, "chart.svg")) as f, open(os.path.join(page_dir, "chart.svg"), "w") as g:
                g.write(f.read())
            out = self.render_page(page_dir, html, "--width", "600", "--scale", "1")
        # The 400x200 #3a6 image sits at (8,8); a broken image leaves the page about 20px tall.
        self.assertGreaterEqual(out["height"], 200)
        self.assert_color(png_pixel(out["png"], 208, 58), (0x33, 0xaa, 0x66))

    def test_every_call_appends_one_action_record(self):
        log = os.path.join(self.state.name, "actions.jsonl")
        out = self.viz("render", os.path.join(FIXTURES, "bad.mmd"), code=3)
        self.viz("list")
        self.viz("doctor", env={"VIZ_CHROMIUM": "/nonexistent"}, code=4)
        self.viz("frobnicate", code=2)
        with open(log) as f:
            records = [json.loads(line) for line in f]
        self.assertEqual([r["command"] for r in records], ["render", "list", "doctor", "frobnicate"])
        bad = records[0]
        for key in ("id", "ts", "duration_ms", "args", "steps", "outcome"):
            self.assertIn(key, bad)
        self.assertTrue(bad["ts"].endswith("Z"))
        self.assertEqual(bad["args"], [os.path.join(FIXTURES, "bad.mmd")])
        self.assertEqual(bad["outcome"], out)
        mmdc = [s for s in bad["steps"] if s["step"] == "mmdc"]
        self.assertEqual(len(mmdc), 1)
        self.assertFalse(mmdc[0]["ok"])
        self.assertIn("Parse error", mmdc[0]["message"])
        self.assertEqual(records[2]["outcome"]["code"], "missing_dependency")

    def test_render_record_id_is_the_render_id(self):
        out = self.viz("render", os.path.join(FIXTURES, "chart.svg"))
        with open(os.path.join(self.state.name, "actions.jsonl")) as f:
            record = json.loads(f.readlines()[-1])
        self.assertEqual(record["id"], out["id"])
        self.assertEqual(record["outcome"], out)
        shot = [s for s in record["steps"] if s["step"] == "screenshot"]
        self.assertEqual((shot[0]["width"], shot[0]["height"]), (out["width"], out["height"]))

    def test_missing_chromium(self):
        env = {"VIZ_CHROMIUM": "/nonexistent"}
        self.assertEqual(self.viz("doctor", env=env, code=4)["code"], "missing_dependency")
        out = self.viz("render", os.path.join(FIXTURES, "chart.svg"), env=env, code=4)
        self.assertEqual(out["code"], "missing_dependency")

    def test_list_newest_first(self):
        self.assertEqual(self.viz("list")["renders"], [])
        a = self.viz("render", os.path.join(FIXTURES, "chart.svg"))
        b = self.viz("render", os.path.join(FIXTURES, "chart.svg"))
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual([r["id"] for r in self.viz("list")["renders"]], [b["id"], a["id"]])
        self.assertEqual([r["id"] for r in self.viz("list", "--limit", "1")["renders"]], [b["id"]])


if __name__ == "__main__":
    unittest.main()
