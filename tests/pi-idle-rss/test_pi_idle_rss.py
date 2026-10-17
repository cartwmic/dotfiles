import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load(real_home=None):
    if real_home is not None:
        os.environ["PI_IDLE_RSS_REAL_HOME"] = str(real_home)
    else:
        os.environ.pop("PI_IDLE_RSS_REAL_HOME", None)
    import pi_idle_rss
    return importlib.reload(pi_idle_rss)


m = load()


class Parsing(unittest.TestCase):
    def test_ps_skips_zombies_and_parses_fields(self):
        rows = m.parse_ps("  10 1 S 2048 node a b FOO=1\n  11 10 Z 0 defunct\n  x y z\n")
        self.assertEqual([r["pid"] for r in rows], [10])
        self.assertEqual(rows[0]["rss_kb"], 2048)

    def test_owned_set_uses_marker_and_tree(self):
        rows = m.parse_ps("100 1 S 10 pi PI_IDLE_RSS_SAMPLE=abc\n101 100 S 20 child\n"
                          "102 1 S 30 detached PI_IDLE_RSS_SAMPLE=abc\n103 1 S 40 other PI_IDLE_RSS_SAMPLE=zzz\n104 1 S 50 plain\n")
        owned = {r["pid"] for r in m.owned_set(rows, "abc", 100)}
        self.assertEqual(owned, {100, 101, 102})

    def test_cmd_name_never_returns_environment(self):
        self.assertEqual(m.cmd_name("/x/node /y/playwright-mcp --a TERM=xterm HOME=/h"), "node playwright-mcp")
        self.assertEqual(m.cmd_name("pi TOKEN=secret"), "pi")

    def test_footprint_units(self):
        self.assertEqual(m.parse_footprint("phys_footprint: 84 MB"), 84 * 1024)
        self.assertEqual(m.parse_footprint("phys_footprint: 1.5 GB"), int(1.5 * 1024 * 1024))
        self.assertIsNone(m.parse_footprint("nothing"))


class Variants(unittest.TestCase):
    SETTINGS = {"deviceId": "x", "defaultProvider": "a", "defaultModel": "b", "enabledModels": ["a/b"],
                "packages": ["https://github.com/o/pi-one", {"source": "npm:@s/pi-two", "extensions": []}, "https://github.com/o/pi-three"]}

    def test_variant_grammar(self):
        v = m.parse_variant("full-pkg:pi-one+pi-two/full-nomcp")
        self.assertEqual(v["drop_pkgs"], ["pi-one", "pi-two"])
        self.assertTrue(v["no_mcp"])
        with self.assertRaises(ValueError):
            m.parse_variant("bogus")

    def test_settings_filter(self):
        s = m.filter_settings(self.SETTINGS, m.parse_variant("full-pkg:pi-two"), "http://x")
        self.assertNotIn("deviceId", s)
        self.assertEqual((s["defaultProvider"], s["defaultModel"]), ("dummy", "dummy-1"))
        self.assertEqual(len(s["packages"]), 2)
        self.assertEqual(m.filter_settings(self.SETTINGS, m.parse_variant("core"), "http://x")["packages"], [])

    def test_package_drop_is_exact_not_substring(self):
        settings = {"packages": ["https://github.com/o/pi-sub", "https://github.com/o/pi-subagents", "git:github.com/o/x@abc123"]}
        s = m.filter_settings(settings, m.parse_variant("full-pkg:pi-sub"), "http://x")
        self.assertEqual(s["packages"], ["https://github.com/o/pi-subagents", "git:github.com/o/x@abc123"])
        self.assertEqual(m.package_key("git:github.com/o/x@abc123"), "x")
        self.assertEqual(m.package_key("npm:@narumitw/pi-stamp"), "pi-stamp")

    def test_patch_variant_parses_and_unknown_patch_is_refused(self):
        self.assertEqual(m.parse_variant("full-patch:pi-sub-no-nested-sdk")["patches"], ["pi-sub-no-nested-sdk"])
        with self.assertRaises(ValueError):
            m.parse_variant("full-patch:nope")

    def test_mcp_credentials_are_replaced(self):
        mcp = {"mcpServers": {"a": {"url": "u", "headers": {"K": "real-secret"}}, "b": {"command": "c"}}}
        out = m.filter_mcp(mcp, m.parse_variant("full-mcp:b"))
        self.assertNotIn("real-secret", json.dumps(out))
        self.assertEqual(list(out["mcpServers"]), ["a"])


class Isolation(unittest.TestCase):
    def test_credential_file_and_env_detection(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "h"
            (home / ".pi/agent/extensions/x").mkdir(parents=True)
            (home / ".pi/agent/extensions/x/auth.json").write_text("{}")
            real = Path(d) / "store"
            real.mkdir()
            (real / "id_rsa").write_text("k")
            (home / "linked").symlink_to(real)
            found = m.placed_credential_files(home)
            self.assertEqual(found, [".pi/agent/extensions/x/auth.json"])  # symlinked stores are not walked
        self.assertEqual(m.credential_env({"HOME": "h", "GITHUB_TOKEN": "x", "OP_SERVICE_ACCOUNT_TOKEN": "y", "PI_IDLE_RSS_SAMPLE": "z"}), ["GITHUB_TOKEN", "OP_SERVICE_ACCOUNT_TOKEN"])

    def test_preflight_fails_closed_when_credential_file_would_be_placed(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "home"
            agent = fake / ".pi/agent"
            (agent / "extensions/leaky").mkdir(parents=True)
            (agent / "extensions/leaky/auth.json").write_text("{}")
            (agent / "settings.json").write_text(json.dumps({"packages": []}))
            mod = load(fake)
            try:
                store = mod.Store(Path(d) / "store")
                res = mod.preflight(mod.parse_variant("full"), Path(d) / "pf", store, Path(node).parent, Path(d) / "work")
            finally:
                load()
            self.assertFalse(res["ok"])
            self.assertFalse(next(c for c in res["checks"] if c["name"] == "no-credential-looking-files-placed")["ok"])
            self.assertTrue(next(c for c in res["checks"] if c["name"] == "keychain-lookup-fails")["ok"])
            self.assertTrue(next(c for c in res["checks"] if c["name"] == "home-resolves-to-throwaway")["ok"])


class Gate(unittest.TestCase):
    def test_gate_returns_at_normal_pressure(self):
        with mock.patch.object(m, "pressure_level", return_value=1), mock.patch.object(m, "free_percent", return_value=60):
            self.assertEqual(m.gate("t")["level"], 1)

    def test_gate_times_out_fail_closed(self):
        with mock.patch.object(m, "pressure_level", return_value=2), mock.patch.object(m, "free_percent", return_value=60):
            with self.assertRaises(m.Fatal):
                m.gate("t", wait_max=0, poll=0, log=lambda *_: None)


class Aged(unittest.TestCase):
    def test_synthetic_session_matches_requested_shape_and_is_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            info = m.build_aged_session(p, Path(d), total_bytes=200_000, messages=100)
            lines = [json.loads(x) for x in p.read_text().splitlines()]
            self.assertEqual(lines[0]["type"], "session")
            self.assertEqual(sum(1 for x in lines if x["type"] == "message"), 100)
            self.assertAlmostEqual(info["bytes"], 200_000, delta=40_000)
            ids = [x["id"] for x in lines[1:]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(lines[2]["parentId"], lines[1]["id"])


class Reporting(unittest.TestCase):
    def test_report_and_scan(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "samples.jsonl"
            rows = [{"variant": v, "tag": "fresh", "rss_pi_kb": kb, "rss_owned_kb": kb + 100, "fp_pi_kb": kb - 10, "fp_owned_kb": kb}
                    for v, kbs in (("core", (130000, 132000, 131000)), ("full", (340000, 350000, 345000)), ("full-pkg:x", (300000, 305000, 302000))) for kb in kbs]
            f.write_text("\n".join(json.dumps(r) for r in rows))
            text = m.report(Path(d))
            self.assertIn("full-pkg:x", text)
            self.assertIn("Core-only vs full", text)
            self.assertIn("footprint Pi", text)
            self.assertEqual(m.scan_post(text), [])
        self.assertTrue(m.scan_post("token sk-" + "a" * 30))
        self.assertTrue(m.scan_post("see /Users/x/.pi/agent/sessions/abc.jsonl"))


if __name__ == "__main__":
    unittest.main()
