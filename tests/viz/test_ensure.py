#!/usr/bin/env python3
"""A Mermaid render after a Playwright cache prune: viz asks the managed chromium wrapper to restore the cache.

Black-box through dot_local/bin/executable_viz with a fake mmdc, a fake chromium and an empty scratch
PLAYWRIGHT_BROWSERS_PATH. Needs only node. No real browser runs and no real cache is touched.
RED control: a chromium without the wrapper's marker is never asked, and the render stops at missing_dependency.
Run: python3 tests/viz/test_ensure.py
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VIZ = os.path.join(ROOT, "dot_local", "bin", "executable_viz")
FLOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "flow.mmd")

FAKE_MMDC = """#!/bin/sh
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift ;; esac; shift; done
printf '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>' > "$out"
"""

# --ensure puts a headless shell in the scratch cache (as the wrapper's install would); anything else is a browser start.
FAKE_CHROMIUM = """#!/bin/sh
# %s
if [ "${1-}" = "--ensure" ]; then
	echo ensure >> "$FAKE_LOG"
	[ -z "${FAKE_ENSURE_FAILS-}" ] || exit 1
	d="$PLAYWRIGHT_BROWSERS_PATH/chromium_headless_shell-1248/chrome-headless-shell-mac-arm64"
	mkdir -p "$d" && printf '#!/bin/sh\\n' > "$d/.tmp" && chmod 755 "$d/.tmp" && mv "$d/.tmp" "$d/chrome-headless-shell"
	exit 0
fi
echo run >> "$FAKE_LOG"
exit 1
"""
MARKER = "chromium-wrapper: --ensure"


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o755)
    os.rename(tmp, path)


@unittest.skipUnless(shutil.which("node"), "needs node")
class EnsureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="viz-ensure-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.bin = os.path.join(self.root, "bin")
        os.mkdir(self.bin)
        self.cache = os.path.join(self.root, "cache")
        os.mkdir(self.cache)
        self.log = os.path.join(self.root, "calls.log")
        write_atomic(os.path.join(self.bin, "mmdc"), FAKE_MMDC)

    def chromium(self, marker):
        write_atomic(os.path.join(self.bin, "chromium"), FAKE_CHROMIUM % (MARKER if marker else "no marker"))

    def render(self, **extra):
        env = {"PATH": "%s:%s:/usr/bin:/bin" % (self.bin, os.path.dirname(shutil.which("node"))), "HOME": self.root,
               "VIZ_STATE_DIR": os.path.join(self.root, "state"), "PLAYWRIGHT_BROWSERS_PATH": self.cache,
               "FAKE_LOG": self.log}
        env.update(extra)
        r = subprocess.run(["/bin/sh", VIZ, "render", FLOW], env=env, capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout), r

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().split()

    def test_empty_cache_triggers_one_ensure_then_the_render_goes_ahead(self):
        self.chromium(marker=True)
        out, r = self.render()
        self.assertNotEqual(out.get("code"), "missing_dependency", out)
        self.assertEqual(self.calls(), ["ensure", "run"])  # one ensure, then the browser start (the fake exits 1)
        self.assertEqual(out["code"], "render_failed")
        self.assertIn("Chromium exited early", out["message"])

    def test_the_record_says_the_cache_was_restored(self):
        self.chromium(marker=True)
        self.render()
        state = os.path.join(self.root, "state")
        with open(os.path.join(state, "actions.jsonl")) as f:
            records = [json.loads(l) for l in f]
        steps = [s for rec in records for s in rec.get("steps", []) if s.get("step") == "mmdc"]
        self.assertTrue(any(s.get("ok") and s.get("ensured") for s in steps), records)

    def test_a_cache_that_is_already_whole_is_not_ensured(self):
        self.chromium(marker=True)
        self.render()  # first render restores the shell
        os.unlink(self.log)
        out, _ = self.render()
        self.assertEqual(self.calls(), ["run"])
        self.assertEqual(out["code"], "render_failed")

    def test_a_failed_ensure_reports_the_missing_dependency(self):
        self.chromium(marker=True)
        out, r = self.render(FAKE_ENSURE_FAILS="1")
        self.assertEqual((r.returncode, out["code"]), (4, "missing_dependency"))
        self.assertEqual(self.calls(), ["ensure"])

    def test_red_control_without_the_ensure_call_it_is_missing_dependency(self):
        self.chromium(marker=False)  # not the managed wrapper: viz must never pass it --ensure
        out, r = self.render()
        self.assertEqual((r.returncode, out["code"]), (4, "missing_dependency"))
        self.assertIn("chrome-headless-shell", out["message"])
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
