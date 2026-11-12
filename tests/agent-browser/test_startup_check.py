"""The launcher's startup check (server.py): it patches private names of browser-use and browser-harness, so it verifies the pins and
every one of those names before it starts, and exits 1 at once naming what is missing.

Each case runs the real launcher file in a real process, in the pinned environment, after hiding one thing: a wrapper deletes one patched
name (or reports another version) and then runs server.py as __main__. No Chrome needed. The control runs the same wrapper, hides nothing,
and gets a server that answers `initialize`.
"""
import json
import shutil
import subprocess
import unittest

from support import FROM, LAUNCHER

WRAPPER = """
import importlib, importlib.metadata, runpy, sys
hide, version = sys.argv[1], sys.argv[2]
if hide:
    module_name, _, dotted = hide.partition(":")
    owner = importlib.import_module(module_name)
    *path, last = dotted.split(".")
    for part in path:
        owner = getattr(owner, part)
    delattr(owner, last)
if version:
    package, _, shown = version.partition("=")
    real = importlib.metadata.version
    importlib.metadata.version = lambda name: shown if name == package else real(name)
runpy.run_path(%r, run_name="__main__")
""" % str(LAUNCHER)

NAMES = ("browser_use.mcp.cli_mcp:CLIMCPServer._attach", "browser_use.mcp.cli_mcp:CLIMCPServer._ensure_namespace",
         "browser_harness.helpers:cdp", "browser_harness.helpers:new_tab", "browser_harness.helpers:switch_tab",
         "browser_harness.helpers:close_tab", "browser_harness.helpers:current_tab", "browser_harness.helpers:ensure_real_tab",
         "browser_harness.helpers:_send",
         "browser_harness._ipc:identify")


def launch(hide="", version="", stdin=""):
    return subprocess.run(FROM + ["python", "-I", "-c", WRAPPER, hide, version], input=stdin, capture_output=True, text=True, timeout=60, cwd="/tmp")


@unittest.skipUnless(shutil.which("uvx"), "needs uvx")
class StartupCheck(unittest.TestCase):
    def test_control_nothing_hidden_the_server_starts_and_answers(self):
        init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "check", "version": "0"}}}) + "\n"
        r = launch(stdin=init)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout.splitlines()[0])["result"]["serverInfo"]["name"], "browser-use")

    def test_each_patched_name_missing_fails_loudly_and_names_it(self):
        for hidden in NAMES:
            with self.subTest(hidden=hidden):
                module_name, _, dotted = hidden.partition(":")
                r = launch(hide=hidden)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertEqual(r.stdout, "")   # nothing on the protocol stream
                self.assertIn("%s.%s is missing" % (module_name, dotted), r.stderr)
                self.assertIn("nothing started", r.stderr)

    def test_a_version_other_than_the_pin_fails_loudly_and_names_it(self):
        for package, shown, pin in (("browser-use", "1.0.3", "1.0.2"), ("browser-harness", "0.1.14", "0.1.13")):
            with self.subTest(package=package):
                r = launch(version="%s=%s" % (package, shown))
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("%s==%s is required, installed: %s" % (package, pin, shown), r.stderr)


if __name__ == "__main__":
    unittest.main()
