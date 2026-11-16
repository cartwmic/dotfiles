"""config-show: parses each format the agents met and masks every value whole; a --show key prints; nothing from the file leaks into an error.

The file holds made-up values that all contain FAKE, so a leak is one substring check. The tests also run the parser paths used when PyYAML
or tomllib is missing. Nothing here writes inside the repo.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
READER = ROOT / "dot_local/share/agent-harness/bin/executable_config-show"

FILES = {
    "RustDesk.toml": "password = 'FAKEPW'\nsalt = 'FAKESALT'\nkey_pair = [1, 2]\n\n[options]\nview_style = 'adaptive'\nkeyboard_mode = 'FAKEMODE'\n",
    "rclone.conf": "[remote]\ntype = s3\naccess_key_id = FAKEAK\nsecret_access_key = FAKESK\n  wrapped = FAKEWRAP\n\n[b]\nuser = u\n",
    ".env": "# comment\nexport API_KEY=FAKEKEY\nDB_PASS='FAKE x y'\nEMPTY=\n",
    "c.json": '{"a": {"token": "FAKETOK", "list": [1, {"p": "FAKEQ"}]}, "e": {}}',
    "c.yml": "server:\n  host: FAKEHOST\n  password: FAKEPW\n  tags:\n    - FAKEA\nusers:\n  - name: FAKEB\n    token: FAKEC\nnote: |\n  FAKE body\n  password: FAKED\nlast: 1\n",
}


def run(*args, **kw):
    return subprocess.run([sys.executable, str(READER), *args], capture_output=True, text=True, timeout=30, **kw)


class ConfigShow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        for name, text in FILES.items():
            (Path(cls.tmp) / name).write_text(text)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def path(self, name):
        return str(Path(self.tmp) / name)

    def test_every_value_is_masked_in_every_format(self):
        expect = {
            "RustDesk.toml": ["password = <masked>", "salt = <masked>", "key_pair = <masked list>", "options.view_style = <masked>"],
            "rclone.conf": ["remote.type = <masked>", "remote.secret_access_key = <masked>", "b.user = <masked>"],
            ".env": ["API_KEY = <masked>", "DB_PASS = <masked>", "EMPTY = <masked>"],
            "c.json": ["a.token = <masked>", "a.list[1].p = <masked>", "a.list[0] = <masked>", "e = <masked>"],
            "c.yml": ["server.password = <masked>", "server.tags = <masked list>", "users[0].token = <masked>", "note = <masked>"],
        }
        for name, lines in expect.items():
            with self.subTest(file=name):
                out = run(self.path(name))
                self.assertEqual(out.returncode, 0, out.stderr)
                for line in lines:
                    self.assertIn(line, out.stdout.splitlines())
                self.assertNotIn("FAKE", out.stdout + out.stderr)
                self.assertNotIn("adaptive", out.stdout)

    def test_a_wrapped_ini_value_is_not_a_key(self):
        self.assertNotIn("wrapped", run(self.path("rclone.conf")).stdout)

    def test_show_prints_a_named_key_only(self):
        out = run(self.path("RustDesk.toml"), "--show", "options.view_style").stdout.splitlines()
        self.assertIn('options.view_style = "adaptive"', out)
        self.assertIn("options.keyboard_mode = <masked>", out)
        bare = run(self.path("RustDesk.toml"), "--show=view_style").stdout.splitlines()
        self.assertIn('options.view_style = "adaptive"', bare)
        table = run(self.path("RustDesk.toml"), "--show", "options").stdout
        self.assertIn('options.keyboard_mode = "FAKEMODE"', table)
        self.assertIn("password = <masked>", table)

    def test_the_format_flag_overrides_the_name(self):
        out = run(self.path("c.json"), "--format", "yaml")
        self.assertEqual(out.returncode, 0)
        self.assertIn("a.token = <masked>", out.stdout)

    def test_parse_errors_report_a_line_and_no_text(self):
        bad = Path(self.tmp) / "bad.toml"
        bad.write_text("token = 'FAKEBROKEN\n[x")
        badyml = Path(self.tmp) / "bad.yml"
        badyml.write_text("a: [FAKEUNCLOSED\n  b: 'FAKE")
        badjson = Path(self.tmp) / "bad.json"
        badjson.write_text('{"token": "FAKEJ"')
        for path in (bad, badyml, badjson):
            with self.subTest(file=path.name):
                out = run(str(path))
                self.assertEqual(out.returncode, 1)
                self.assertEqual(out.stdout, "")
                self.assertIn("the text is not printed", out.stderr)
                self.assertNotIn("FAKE", out.stderr)

    def test_a_missing_file_and_bad_arguments(self):
        self.assertEqual(run(self.path("none.toml")).returncode, 1)
        self.assertEqual(run().returncode, 2)
        self.assertEqual(run(self.path("c.json"), "--format", "xml").returncode, 2)
        self.assertEqual(run(self.path("c.json"), "extra").returncode, 2)

    def run_without(self, name, *modules):
        code = ("import sys, runpy\nfor m in %r:\n    sys.modules[m] = None\nsys.argv = ['config-show', %r]\n"
                "runpy.run_path(%r, run_name='__main__')" % (modules, self.path(name), str(READER)))
        return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=30)

    def test_without_pyyaml_the_yaml_reader_gives_the_same_keys(self):
        with_yaml = run(self.path("c.yml")).stdout.splitlines()[1:]
        without = self.run_without("c.yml", "yaml")
        self.assertEqual(without.stdout.splitlines()[1:], with_yaml)
        self.assertNotIn("FAKE", without.stdout)

    def test_without_tomllib_the_toml_reader_still_masks_every_value(self):
        out = self.run_without("RustDesk.toml", "tomllib")
        self.assertEqual(out.returncode, 0, out.stderr)
        for key in ("password", "salt", "key_pair", "options.view_style", "options.keyboard_mode"):
            self.assertIn("%s = <masked>" % key, out.stdout)
        self.assertNotIn("FAKE", out.stdout)


if __name__ == "__main__":
    unittest.main()
