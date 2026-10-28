#!/usr/bin/env python3
"""Runs viz's core use cases with fake ports: no Chromium, mmdc or filesystem.

Needs only node. Run: python3 tests/viz/test_core.py
"""
import json
import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(ROOT, "dot_local", "share", "viz", "core")

SCRIPT = r"""
import { pathToFileURL } from 'node:url';
const core = process.env.VIZ_CORE;
const { runAction } = await import(pathToFileURL(core + '/use_cases.mjs').href);
const { VizError } = await import(pathToFileURL(core + '/domain.mjs').href);

function png(width, height) {
  const b = new Uint8Array(24);
  b.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const v = new DataView(b.buffer);
  v.setUint32(16, width);
  v.setUint32(20, height);
  return b;
}

const renders = new Map();
const actions = [];
const store = {
  root: '/fake-state',
  isTaken: (id) => renders.has(id),
  stage: (files) => ({ files: { ...files }, path: (name) => '/fake-state/.staging/' + name }),
  add: (staging, name, data) => { staging.files[name] = data; },
  finalPaths: (id, names) => Object.fromEntries(names.map((n) => [n, `/fake-state/${id}/${n}`])),
  commit: (staging, id) => { renders.set(id, staging.files); },
  discard: () => {},
  readRenders: () => [...renders.values()].map((files) => JSON.parse(files['meta.json'])),
  appendAction: (record) => { actions.push(record); },
};
const sources = new Map([
  ['/in/a.svg', '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'],
  ['-', 'flowchart LR\n  A-->B\n'],
  ['/in/bad.mmd', 'flowchart LR\n  A[unclosed --> B\n'],
  ['/in/page.html', '<!doctype html><script>const s = "<head>";</script><img src="chart.svg">'],
]);
const input = {
  read(file) {
    if (!sources.has(file)) throw new VizError('bad_input', 'no such file: ' + file);
    const text = sources.get(file);
    return { bytes: new TextEncoder().encode(text), text, path: file, baseHref: file === '-' ? null : 'file:///in/' };
  },
};
const shots = [];
const browser = {
  locate: () => '/fake/chromium',
  screenshot(req) {
    shots.push({ width: req.width, scale: req.scale, clipTo: req.clipTo, page: req.pagePath });
    return { png: png(req.width * req.scale, 40 * req.scale), pageErrors: [] };
  },
};
const mermaid = {
  locate: () => ({ mmdc: '/fake/mmdc', browser: '/fake/headless-shell' }),
  toSvg(source) {
    if (source.includes('unclosed')) throw new VizError('render_failed', 'Parse error on line 2: fake parser');
    return '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="20"/>';
  },
  version: () => '11.16.0',
};
let now = Date.UTC(2026, 9, 28, 12, 0, 0);
let counter = 0;
const ports = {
  store, input, browser, mermaid,
  clock: { now: () => (now += 7) },
  random: { hex: () => (counter++).toString(16).padStart(6, '0') },
  runtime: { node: '/fake/node', nodeVersion: 'v24.0.0' },
  warn: () => {},
};
const noChromium = { ...ports, browser: { locate() { throw new VizError('missing_dependency', 'no chromium'); } } };

const results = [];
for (const [argv, p] of [
  [['render', '/in/a.svg', '--width', '300', '--scale', '2'], ports],
  [['render', '-', '--as', 'mermaid'], ports],
  [['render', '/in/bad.mmd'], ports],
  [['render', '-', '--as', 'constructor'], ports],
  [['list', '--limit', '1'], ports],
  [['list'], ports],
  [['doctor'], ports],
  [['doctor'], noChromium],
  [['render', '/in/page.html'], ports],
]) results.push({ argv, ...(await runAction(argv, p)) });
const htmlId = results.at(-1).output.id;
const htmlPage = new TextDecoder().decode(renders.get(htmlId)['page.html']);
console.log(JSON.stringify({ results, actions, shots, htmlPage }));
"""


class CoreUseCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "--input-type=module", "-e", SCRIPT], capture_output=True, text=True,
                           env=dict(os.environ, VIZ_CORE=CORE), timeout=60)
        if r.returncode != 0:
            raise AssertionError("fake-port script failed: %s" % r.stderr)
        cls.run_ = json.loads(r.stdout)
        cls.results = cls.run_["results"]

    def test_render_with_fake_ports(self):
        svg, mmd = self.results[0], self.results[1]
        self.assertEqual(svg["exitCode"], 0, svg)
        self.assertEqual((svg["output"]["width"], svg["output"]["height"]), (600, 80))
        self.assertEqual(svg["output"]["png"], "/fake-state/%s/image.png" % svg["output"]["id"])
        self.assertEqual(svg["output"]["source"], "/fake-state/%s/source.svg" % svg["output"]["id"])
        self.assertEqual(mmd["output"]["source"], "/fake-state/%s/source.mmd" % mmd["output"]["id"])
        self.assertNotEqual(svg["output"]["id"], mmd["output"]["id"])
        self.assertEqual([s["clipTo"] for s in self.run_["shots"]], ["#viz-root svg", "#viz-root > svg", None])

    def test_html_file_is_copied_verbatim_and_rendered_from_its_own_path(self):
        html = self.results[-1]
        self.assertEqual(html["exitCode"], 0, html)
        self.assertEqual(self.run_["htmlPage"], '<!doctype html><script>const s = "<head>";</script><img src="chart.svg">')
        self.assertEqual(self.run_["shots"][-1]["page"], "/in/page.html")
        self.assertTrue(self.run_["shots"][0]["page"].endswith("/page.html"))

    def test_failures_map_to_contract_codes(self):
        bad, inherited = self.results[2], self.results[3]
        self.assertEqual((bad["exitCode"], bad["output"]["code"]), (3, "render_failed"))
        self.assertIn("Parse error", bad["output"]["message"])
        self.assertEqual((inherited["exitCode"], inherited["output"]["code"]), (2, "bad_input"))
        self.assertEqual(len(self.run_["shots"]), 3, "failed renders must not reach the browser")

    def test_list_newest_first(self):
        newest = self.results[1]["output"]["id"]
        oldest = self.results[0]["output"]["id"]
        self.assertEqual([r["id"] for r in self.results[4]["output"]["renders"]], [newest])
        self.assertEqual([r["id"] for r in self.results[5]["output"]["renders"]], [newest, oldest])

    def test_doctor(self):
        ok, missing = self.results[6], self.results[7]
        self.assertEqual(ok["exitCode"], 0)
        self.assertEqual((ok["output"]["chromium"], ok["output"]["mmdc"]), ("/fake/chromium", "/fake/mmdc"))
        self.assertEqual((missing["exitCode"], missing["output"]["code"]), (4, "missing_dependency"))

    def test_one_action_record_per_call(self):
        actions = self.run_["actions"]
        self.assertEqual(len(actions), len(self.results))
        self.assertEqual(actions[0]["id"], self.results[0]["output"]["id"])
        self.assertTrue(all(a["ts"].endswith("Z") and a["duration_ms"] >= 0 for a in actions))
        bad = actions[2]
        self.assertEqual(bad["outcome"], self.results[2]["output"])
        self.assertIn({"step": "mmdc", "ok": False, "mmdc": "/fake/mmdc",
                       "message": "Parse error on line 2: fake parser"}, bad["steps"])


if __name__ == "__main__":
    unittest.main()
