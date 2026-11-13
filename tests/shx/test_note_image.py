#!/usr/bin/env python3
"""Black-box tests for dot_local/bin/executable_shx-note-image.

A small stdlib HTTP server plays shartifacts: a /view/<id> page with a frame like the real one (the frame address is
set after a fetch, as web/view.js does), the page versions behind it, the comments, and a sink for the match report.
The command runs against it with real Chromium. Needs node and chromium (or SHX_CHROMIUM); without them the render
tests skip. Run: python3 -I tests/shx/test_note_image.py
"""
import json
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import unittest
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CMD = os.path.join(ROOT, "dot_local", "bin", "executable_shx-note-image")
CHROMIUM = os.environ.get("SHX_CHROMIUM") or shutil.which("chromium")
RENDER_DEPS = bool(shutil.which("node") and CHROMIUM)

ARTIFACT = "art1"
MAGENTA, GREEN, BLUE, YELLOW = (255, 0, 255), (0, 204, 68), (10, 132, 255), (255, 238, 0)
PAGE_HEIGHT = 1600  # CSS px, taller than any crop


def page(version):
    """The artifact's page. Version 2 moves the chart down, rewords the intro and drops the legend."""
    top = 400 if version == 1 else 700
    intro = "Revenue grew in every quarter." if version == 1 else "Sales rose each quarter."
    legend = '<p id="legend">Legend</p>' if version == 1 else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body {{ margin: 0; position: relative; min-height: {PAGE_HEIGHT}px; font: 16px sans-serif; background: #fff; color: #111; }}
#chart {{ position: absolute; left: 24px; top: {top}px; width: 342px; height: 210px; background: #eeeeff; }}
@media (max-width: 400px) {{ #chart {{ background: #ffee00; }} }}
#bar {{ position: absolute; left: 30px; top: 30px; width: 60px; height: 150px; background: #0a84ff; }}
</style></head><body>
<h1>Report</h1><p id="intro">{intro}</p>{legend}<p id="emoji">{"😀" * 130}</p>
<div id="chart"><div id="bar"></div></div>
</body></html>"""


def view_page():
    """What /view does: ask which version to show, then set the frame's address (so it is not there at load time)."""
    return """<!doctype html><html><head><meta charset="utf-8"><title>fixture</title>
<style>body { margin: 0; display: flex; flex-direction: column; height: 100vh; }
header { min-height: 44px; border-bottom: 1px solid #ccc; } #preview { flex: 1; width: 100%; border: 0; }</style></head><body>
<header>bar</header>
<iframe id="preview" sandbox="allow-scripts allow-forms allow-modals" title="Artifact"></iframe>
<script>
const id = location.pathname.split('/')[2];
const pinned = Number(new URL(location.href).searchParams.get('version')) || 0;
fetch('/api/artifacts/' + id).then((r) => r.json()).then((a) => {
  const latest = a.revisions.length;
  const version = pinned >= 1 && pinned <= latest ? pinned : latest;
  document.getElementById('preview').src = '/preview/' + id + '?version=' + version;
});
</script></body></html>"""


def ellipse(rx=181, ry=116, cx=171, cy=105):
    """A closed loop around the chart, as [dx, dy, pressure] offsets from the chart's top-left corner."""
    import math
    return [[round(cx + rx * math.cos(t / 20 * 2 * math.pi), 1), round(cy + ry * math.sin(t / 20 * 2 * math.pi), 1), 0.5] for t in range(22)]


def stroke(color, anchor="#chart", box=None):
    return {"v": 1, "version": 1, "viewport": {"w": 390, "h": 844, "scroll_x": 0, "scroll_y": 312}, "anchor": anchor,
            "box": box or {"x": 24, "y": 400, "w": 342, "h": 210}, "points": ellipse(), "color": color, "width": 8, "elements": []}


COMMENTS = [
    {"id": "s1", "author": "person", "body": "look", "anchor": "#chart", "version": 1, "stroke": stroke("#ff00ff")},
    {"id": "s2", "author": "person", "body": "look", "anchor": "#chart", "version": 1, "stroke": stroke("#00cc44")},
    {"id": "s3", "author": "person", "body": "look", "anchor": "#removed", "version": 1,
     "stroke": stroke("#ff00ff", "#removed", {"x": 24, "y": 1000, "w": 100, "h": 50})},
    {"id": "p1", "author": "person", "body": "pin", "anchor": "#legend", "version": 1},
    {"id": "q1", "author": "person", "body": "words", "anchor": "#intro", "quote": "Sales  rose\n each quarter.", "version": 2},
    {"id": "q2", "author": "person", "body": "old words", "anchor": "#intro", "quote": "Revenue grew in every quarter.", "version": 1},
    {"id": "t1", "author": "person", "body": "done", "anchor": "#chart", "version": 1, "resolved": True},
    {"id": "r1", "author": "agent", "body": "reply", "parent": "s1", "version": 1},
    {"id": "g1", "author": "person", "body": "whole page", "version": 1},
]


class Fixture(ThreadingHTTPServer):
    def __init__(self, latest=2, comments=COMMENTS):
        super().__init__(("127.0.0.1", 0), Handler)
        self.latest, self.comments, self.requests, self.matches = latest, comments, [], []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def base(self):
        return "http://127.0.0.1:%d" % self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, body, kind):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(200)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        parts = url.path.strip("/").split("/")
        self.server.requests.append(self.path)
        if parts[0] == "view" and len(parts) == 2:
            return self.send(view_page(), "text/html")
        if parts[0] == "preview" and len(parts) == 2:
            version = int(parse_qs(url.query).get("version", [self.server.latest])[0])
            return self.send(page(version), "text/html")
        if parts[:2] == ["api", "artifacts"] and parts[2:3] == [ARTIFACT]:
            if len(parts) == 3:
                return self.send(json.dumps({"revisions": [{}] * self.server.latest}), "application/json")
            if parts[3:] == ["comments"]:
                return self.send(json.dumps(self.server.comments), "application/json")
        self.send_error(404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path == "/api/artifacts/%s/comments/matches" % ARTIFACT:
            self.server.matches.append(json.loads(body))
            return self.send("{}", "application/json")
        self.send_error(404)


def read_png(path):
    """(width, height, rows of RGB tuples) of an 8-bit, non-interlaced RGB or RGBA PNG, which is what Chromium writes."""
    with open(path, "rb") as f:
        data = f.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    pos, idat = 8, b""
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
    assert depth == 8 and color in (2, 6) and interlace == 0, (depth, color, interlace)
    bpp = 3 if color == 2 else 4
    raw, stride = zlib.decompress(idat), width * bpp
    rows, prev = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if kind == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif kind == 3:
            for i in range(stride):
                line[i] = (line[i] + (((line[i - bpp] if i >= bpp else 0) + prev[i]) >> 1)) & 255
        elif kind == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, rows, bpp


def count_colors(path, *colors, tolerance=6):
    """For each rgb, how many pixels are within `tolerance` of it on every channel (the file is decoded once)."""
    _, _, rows, bpp = read_png(path)
    counts = [0] * len(colors)
    for row in rows:
        for i in range(0, len(row), bpp):
            r, g, b = row[i], row[i + 1], row[i + 2]
            for k, (cr, cg, cb) in enumerate(colors):
                if abs(r - cr) <= tolerance and abs(g - cg) <= tolerance and abs(b - cb) <= tolerance:
                    counts[k] += 1
    return counts


class ShxTestCase(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory(prefix="shx-test-state-")
        self.out = tempfile.TemporaryDirectory(prefix="shx-test-out-")
        self.addCleanup(self.state.cleanup)
        self.addCleanup(self.out.cleanup)

    def serve(self, **kwargs):
        server = Fixture(**kwargs)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def shx(self, *args, env=None, code=0):
        e = dict(os.environ, XDG_STATE_HOME=self.state.name)
        e.pop("SHARTIFACTS_URL", None)
        e.update(env or {})
        r = subprocess.run([CMD, *args], capture_output=True, text=True, env=e, timeout=120)
        out = json.loads(r.stdout)  # exactly one JSON document
        self.assertIsInstance(out, dict)
        self.assertEqual(r.returncode, code, (out, r.stderr[-500:]))
        return out

    def log_lines(self):
        path = os.path.join(self.state.name, "shx", "note-image.log")
        with open(path) as f:
            return [json.loads(line) for line in f.read().splitlines()]


@unittest.skipUnless(RENDER_DEPS, "needs node and chromium (or SHX_CHROMIUM) on PATH")
class NoteImageTest(ShxTestCase):
    def test_picture_of_a_drawn_comment(self):
        server = self.serve()
        png = os.path.join(self.out.name, "s1.png")
        out = self.shx(server.base, ARTIFACT, "s1", "--out", png)

        self.assertEqual(set(out), {"ok", "path", "width", "height", "anchor_found", "version"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["path"], png)
        self.assertEqual(out["version"], 1)  # the stroke's own version: the latest is 2
        self.assertTrue(out["anchor_found"])
        width, height, _, _ = read_png(png)
        self.assertEqual((out["width"], out["height"]), (width, height))
        # The crop is the stroke and its chart plus 24 px, at pixel ratio 2: about 390 x 280 CSS px, not the 1600 px page.
        self.assertTrue(600 <= width <= 780 and 400 <= height <= 700, (width, height))
        self.assertLess(height, PAGE_HEIGHT * 2 * 0.4)

        magenta, blue, yellow = count_colors(png, MAGENTA, BLUE, YELLOW)
        self.assertGreater(magenta, 300, "the stroke colour is in the crop")
        self.assertGreater(blue, 300, "the chart is in the crop")
        self.assertGreater(yellow, 300, "the page was laid out at the stroke's 390 px width")
        # Opened through /view with the stroke's version, then the frame's own address.
        self.assertIn("/view/%s?version=1" % ARTIFACT, server.requests)
        self.assertIn("/preview/%s?version=1" % ARTIFACT, server.requests)

        line = self.log_lines()[-1]
        self.assertEqual(self.log_lines(), [line])
        self.assertEqual((line["command"], line["artifact"], line["comment"], line["version"]), ("note", ARTIFACT, "s1", 1))
        self.assertEqual((line["viewport"], line["out"], line["pad"]), ({"w": 390, "h": 844}, png, 24))
        self.assertEqual(line["base"], server.base)
        self.assertIsNone(line["error"])
        self.assertIsInstance(line["duration_ms"], int)
        self.assertRegex(line["ts"], r"^\d{4}-\d\d-\d\dT[\d:.]+Z$")

    def test_stroke_colour_comes_from_the_stroke(self):
        server = self.serve()
        magenta = os.path.join(self.out.name, "magenta.png")
        green = os.path.join(self.out.name, "green.png")
        self.shx(server.base, ARTIFACT, "s1", "--out", magenta)
        self.shx(server.base, ARTIFACT, "s2", "--out", green)
        # Same page, same crop, other colour: the first colour is not part of the page.
        in_green, green_in_green = count_colors(green, MAGENTA, GREEN)
        self.assertEqual(in_green, 0)
        self.assertGreater(green_in_green, 300)
        self.assertEqual(count_colors(magenta, GREEN), [0])

    def test_stroke_follows_its_element_to_a_newer_version(self):
        server = self.serve()
        png = os.path.join(self.out.name, "v2.png")
        out = self.shx(server.base, ARTIFACT, "s1", "--version", "2", "--out", png)
        self.assertEqual(out["version"], 2)
        self.assertTrue(out["anchor_found"])
        # Version 2 puts the chart 300 px lower. A stroke left where it was drawn would show the empty page there.
        blue, magenta = count_colors(png, BLUE, MAGENTA)
        self.assertGreater(blue, 300)
        self.assertGreater(magenta, 300)
        self.assertIn("/preview/%s?version=2" % ARTIFACT, server.requests)

    def test_missing_anchor_still_draws_where_it_was_drawn(self):
        server = self.serve()
        png = os.path.join(self.out.name, "s3.png")
        out = self.shx(server.base, ARTIFACT, "s3", "--out", png, "--pad", "10")
        self.assertFalse(out["anchor_found"])
        self.assertGreater(count_colors(png, MAGENTA)[0], 300)

    def test_default_base_and_default_file(self):
        server = self.serve()
        out = self.shx(ARTIFACT, "s1", env={"SHARTIFACTS_URL": server.base + "/"})
        self.assertTrue(out["path"].startswith(os.path.realpath(self.state.name) + os.sep + "shx"), out["path"])
        self.assertTrue(os.path.isfile(out["path"]))

    def test_errors_are_json_exit_codes_and_logged(self):
        server = self.serve()
        for args, code, text in (
            ((server.base, ARTIFACT, "nope"), 2, "no comment nope"),
            ((server.base, ARTIFACT, "t1"), 2, "no stroke"),
            ((server.base, ARTIFACT, "r1"), 2, "is a reply"),
            ((server.base, ARTIFACT, "s1", "--pad", "wide"), 2, "--pad"),
            ((ARTIFACT, "s1"), 2, "no base URL"),
            ((server.base, "missing", "s1"), 5, "404"),
        ):
            with self.subTest(args=args):
                out = self.shx(*args, code=code)
                self.assertFalse(out["ok"])
                self.assertIn(text, out["message"])
        out = self.shx(server.base, ARTIFACT, "s1", env={"SHX_CHROMIUM": "/nonexistent/chromium"}, code=4)
        self.assertEqual(out["code"], "missing_dependency")
        last = self.log_lines()[-1]
        self.assertEqual(last["error"]["code"], "missing_dependency")
        self.assertEqual(last["artifact"], ARTIFACT)
        self.assertEqual(len(self.log_lines()), 7, "one line per run, failures included")


@unittest.skipUnless(RENDER_DEPS, "needs node and chromium (or SHX_CHROMIUM) on PATH")
class CheckTest(ShxTestCase):
    def test_reports_found_for_a_present_anchor_and_not_found_for_a_removed_one(self):
        server = self.serve()
        out = self.shx("check", server.base, ARTIFACT)
        expected = [{"id": "s1", "found": True}, {"id": "s2", "found": True}, {"id": "s3", "found": False},
                    {"id": "p1", "found": False}, {"id": "q1", "found": True}, {"id": "q2", "found": False}]
        # Open root comments only: the resolved one, the reply and the one that points at nothing are left out.
        self.assertEqual(out, {"ok": True, "version": 2, "results": expected})
        self.assertEqual(server.matches, [{"version": 2, "results": expected}])
        self.assertIn("/preview/%s?version=2" % ARTIFACT, server.requests)
        line = self.log_lines()[-1]
        self.assertEqual((line["command"], line["artifact"], line["version"], line["error"]), ("check", ARTIFACT, 2, None))

    def test_a_drawing_is_found_only_on_the_element_it_was_drawn_on(self):
        # The anchor path still finds an element in every case; only "same", "older" (no record to compare) and "emoji-same" are the one drawn on; "bar" has no text and is left out.
        def drawn(id, tag, text):
            st = stroke("#ff00ff", "#intro", {"x": 8, "y": 60, "w": 300, "h": 20})
            st.update({"anchor_tag": tag, "anchor_text": text})
            return {"id": id, "author": "person", "body": "look", "anchor": "#intro", "version": 1, "stroke": st}
        older = stroke("#ff00ff", "#intro", {"x": 8, "y": 60, "w": 300, "h": 20})
        clipped = "😀" * 120  # the frame cuts at 120 whole characters, never inside an emoji
        def drawn_on(id, anchor, tag, text):
            return {**drawn(id, tag, text), "anchor": anchor, "stroke": {**drawn(id, tag, text)["stroke"], "anchor": anchor}}
        comments = [
            drawn("same", "p", "Sales rose each quarter."),
            drawn("reworded", "p", "Revenue grew in every quarter."),
            drawn("retagged", "h2", "Sales rose each quarter."),
            {"id": "older", "author": "person", "body": "look", "anchor": "#intro", "version": 1, "stroke": older},
            drawn_on("emoji-same", "#emoji", "p", clipped),
            # A drawing on an element with no text (#bar has none) is not checked at all: it is not in the results.
            drawn_on("bar", "#bar", "div", ""),
        ]
        server = self.serve(comments=comments)
        out = self.shx("check", server.base, ARTIFACT)
        self.assertEqual(out["results"], [{"id": "same", "found": True}, {"id": "reworded", "found": False},
                                          {"id": "retagged", "found": False}, {"id": "older", "found": True},
                                          {"id": "emoji-same", "found": True}])

    def test_nothing_to_check_posts_nothing(self):
        server = self.serve(comments=[COMMENTS[-1]])
        self.assertEqual(self.shx("check", server.base, ARTIFACT), {"ok": True, "version": 2, "results": []})
        self.assertEqual(server.matches, [])
        self.assertFalse([r for r in server.requests if r.startswith("/view/")], "no browser was needed")


class UsageTest(ShxTestCase):
    def test_no_arguments_is_a_usage_error(self):
        out = self.shx(code=2)
        self.assertEqual(out["code"], "bad_input")
        self.assertIn("usage:", out["message"])

    def test_unknown_option(self):
        out = self.shx("http://127.0.0.1:9", ARTIFACT, "s1", "--colour", "red", code=2)
        self.assertIn("unknown option --colour", out["message"])


if __name__ == "__main__":
    unittest.main()
