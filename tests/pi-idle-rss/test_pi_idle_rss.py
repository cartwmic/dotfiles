import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
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


class Acceptance(unittest.TestCase):
    def test_dependency_classification(self):
        deps = {"web-search": ["auth_json", "keychain", "cred_helper"], "recap": ["home", "recap_cli"]}
        ok = m.classify_dependencies(deps, {"security": "stub", "op": "stub", "gh": "absent"}, [], True)
        self.assertEqual(ok, {})
        bad = m.classify_dependencies(deps, {"security": "real", "op": "stub"}, ["x/auth.json"], False)
        self.assertEqual(sorted(bad), ["recap", "web-search"])
        self.assertTrue(any("real binary" in x for x in bad["web-search"]))
        self.assertTrue(any("credential-looking" in x for x in bad["web-search"]))

    def test_expected_commands_scan_respects_variant_packages(self):
        with tempfile.TemporaryDirectory() as d:
            agent = Path(d)
            (agent / "extensions/a").mkdir(parents=True)
            (agent / "extensions/a/index.ts").write_text("pi.registerCommand('alpha', {}); pi.registerCommand(dynamicName, {})")
            (agent / "extensions/a/index.test.ts").write_text("pi.registerCommand('ignored', {})")
            (agent / "extensions/a/bridge.ts").write_text("pi.registerCommand('hidden', { description: 'Internal dispatch', handler })")
            pkg = agent / "git/github.com/o/pk"
            (pkg / "src").mkdir(parents=True)
            (pkg / "package.json").write_text(json.dumps({"pi": {"extensions": ["./src/index.ts"]}}))
            (pkg / "src/index.ts").write_text('pi.registerCommand("beta", {})')
            (agent / "settings.json").write_text(json.dumps({"packages": ["https://github.com/o/pk", "https://github.com/o/gone"]}))
            exp = m.expected_commands(agent, m.parse_variant("full"))
            self.assertEqual(exp, {"ext:a": ["alpha"], "pkg:pk": ["beta"]})

    def test_menu_match_is_not_fooled_by_typed_echo(self):
        self.assertTrue(m.menu_has("/goal → goal [u] Set a goal", "goal"))
        self.assertFalse(m.menu_has("/goal  no matching commands", "goal"))
        self.assertTrue(m.menu_has("→ subagents-refresh-provider-mod [u:git:github.com/o/p] Refresh", "subagents-refresh-provider-models"))
        self.assertTrue(m.menu_has("x btw [u] side thread btw:ask [u] ask", "btw:ask"))
        self.assertFalse(m.menu_has("/goal → goals-list [u]", "goal"))

    def test_aged_tags_keep_reload_only_separate(self):
        self.assertEqual(m.aged_tag("large", "turn,compact,reload"), "aged-large")
        self.assertEqual(m.aged_tag("large", "reload"), "aged-large[reload]")

    def test_package_dir_mapping(self):
        a = Path("/a")
        self.assertEqual(m.package_dir(a, "https://github.com/o/r"), a / "git/github.com/o/r")
        self.assertEqual(m.package_dir(a, {"source": "git:github.com/o/r@abc"}), a / "git/github.com/o/r")
        self.assertEqual(m.package_dir(a, "npm:@s/p"), a / "npm/node_modules/@s/p")


class LoadedInventory(unittest.TestCase):
    HEAD = "x [Extensions] @s/pi-stamp:dist, auto-compact, catalog-overlay-nudge, herdr-agent-state.ts, pi-cursor/src, sub-bar, sub-core, pi-subagents Warning: something"

    def fixture(self, d):
        agent = Path(d)
        (agent / "extensions/auto-compact").mkdir(parents=True)
        (agent / "extensions/auto-compact/index.ts").write_text("x")
        (agent / "extensions/catalog-overlay-nudge").mkdir()
        (agent / "extensions/catalog-overlay-nudge/index.ts").write_text("x")
        (agent / "extensions/herdr-agent-state.ts").write_text("x")
        (agent / "extensions/README.md").write_text("x")
        pk = agent / "git/github.com/o/pi-sub"
        pk.mkdir(parents=True)
        (pk / "package.json").write_text(json.dumps({"pi": {"extensions": ["./packages/sub-bar/index.ts", "./packages/sub-core/index.ts"]}}))
        cu = agent / "git/github.com/o/pi-cursor"
        cu.mkdir(parents=True)
        (cu / "package.json").write_text(json.dumps({"pi": {"extensions": ["./src/index.ts"]}}))
        (agent / "settings.json").write_text(json.dumps({"packages": ["https://github.com/o/pi-sub", "https://github.com/o/pi-cursor", "npm:@s/pi-stamp"]}))
        return agent

    def test_header_parse(self):
        self.assertEqual(m.header_extensions(self.HEAD)[:3], ["@s/pi-stamp:dist", "auto-compact", "catalog-overlay-nudge"])
        self.assertEqual(m.header_extensions("no header"), [])

    def test_all_owners_found_including_commandless(self):
        with tempfile.TemporaryDirectory() as d:
            owners = m.expected_loaded(self.fixture(d))
            self.assertNotIn("ext:README.md", owners)
            self.assertEqual(m.missing_loaded(m.header_extensions(self.HEAD), owners), [])

    def test_missing_commandless_owner_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            owners = m.expected_loaded(self.fixture(d))
            tokens = [x for x in m.header_extensions(self.HEAD) if x != "catalog-overlay-nudge"]
            self.assertEqual(m.missing_loaded(tokens, owners), ["ext:catalog-overlay-nudge"])

    def test_overlapping_name_does_not_satisfy_a_missing_owner(self):
        with tempfile.TemporaryDirectory() as d:
            owners = m.expected_loaded(self.fixture(d))
            tokens = [x for x in m.header_extensions(self.HEAD) if x not in ("sub-bar", "sub-core")]  # only pi-subagents left
            self.assertEqual(m.missing_loaded(tokens, owners), ["pkg:pi-sub"])
            self.assertEqual(sorted(m.missing_loaded([x for x in tokens if x != "pi-cursor/src"], owners)), ["pkg:pi-cursor", "pkg:pi-sub"])

    def test_directories_without_an_entry_and_packages_with_no_extensions_are_not_owners(self):
        with tempfile.TemporaryDirectory() as d:
            agent = self.fixture(d)
            (agent / "extensions/config-only").mkdir()
            (agent / "extensions/config-only/config.json").write_text("{}")
            pk = agent / "git/github.com/o/lib"
            pk.mkdir(parents=True)
            (pk / "package.json").write_text(json.dumps({"pi": {"extensions": ["./src/index.ts"]}}))
            st = json.loads((agent / "settings.json").read_text())
            st["packages"].append({"source": "https://github.com/o/lib", "extensions": []})
            (agent / "settings.json").write_text(json.dumps(st))
            owners = m.expected_loaded(agent)
            self.assertNotIn("ext:config-only", owners)
            self.assertEqual(owners["pkg:lib"], [])
            self.assertEqual(m.missing_loaded(m.header_extensions(self.HEAD), owners), [])

    def test_nested_entry_directory_name(self):
        with tempfile.TemporaryDirectory() as d:
            agent = Path(d)
            pk = agent / "git/github.com/o/tools"
            pk.mkdir(parents=True)
            (pk / "package.json").write_text(json.dumps({"pi": {"extensions": ["./packages/pi-thing/src/index.js"]}}))
            (agent / "settings.json").write_text(json.dumps({"packages": ["https://github.com/o/tools"]}))
            owners = m.expected_loaded(agent)
            self.assertEqual(m.missing_loaded(["pi-thing/src"], owners), [])
            self.assertEqual(m.missing_loaded(["tools-x"], owners), ["pkg:tools"])

    def test_one_of_several_package_entries_missing_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            owners = m.expected_loaded(self.fixture(d))
            tokens = [x for x in m.header_extensions(self.HEAD) if x != "sub-core"]
            self.assertEqual(m.missing_loaded(tokens, owners), ["pkg:pi-sub"])

    def test_startup_errors_survive_a_screen_buffer_clear(self):
        n = len(m.ERROR_RE.findall(b"...Failed to load extension x..."))
        self.assertEqual(n, 1)
        s = m.Session.__new__(m.Session)
        s.err_count = 2
        s.buf = b""
        self.assertEqual(m.Session.load_errors(s), 2)


class _AgedFake:
    def __init__(self):
        self.sent = []
        self.session_file = None
        self.backend_requests = lambda: 0

    def send(self, text):
        self.sent.append(text)

    def pump(self, seconds, abort=None):
        return not (abort is not None and abort.is_set())

    def child_pids(self):
        return set()


class FinalAcceptance(unittest.TestCase):
    FULL = m.parse_variant("full")
    DROP = m.parse_variant("full-pkg:x")

    def test_clean_sample_is_accepted(self):
        self.assertEqual(m.accept_sample(True, None, False, 0, {"missing": []}, {"missing": []}, self.FULL), (True, None, None))

    def test_error_arriving_after_the_readings_rejects(self):
        # the cumulative count is read after every pump, so a late error is caught
        self.assertEqual(m.accept_sample(True, None, False, 1, {"missing": []}, {"missing": []}, self.FULL)[:2], (False, "load errors seen (1)"))

    def test_pressure_rising_during_final_readings_rejects(self):
        self.assertEqual(m.accept_sample(True, None, True, 0, None, None, self.FULL)[:2], (False, "pressure"))

    def test_missing_owner_rejects_everywhere_missing_command_only_for_full(self):
        self.assertFalse(m.accept_sample(True, None, False, 0, {"missing": ["ext:a"]}, {"missing": []}, self.DROP)[0])
        self.assertFalse(m.accept_sample(True, None, False, 0, {"missing": []}, {"missing": ["ext:a:cmd"]}, self.FULL)[0])
        self.assertEqual(m.accept_sample(True, None, False, 0, {"missing": []}, {"missing": ["pkg:p:cmd"]}, self.DROP), (True, None, ["pkg:p:cmd"]))

    def test_absent_inventory_is_not_a_pass(self):
        ok, reason, _ = m.accept_sample(True, None, False, 0, None, {"missing": []}, self.FULL)
        self.assertFalse(ok)
        self.assertIn("inventory missing", reason)
        self.assertTrue(m.accept_sample(True, None, False, 0, None, None, m.parse_variant("core"))[0])

    def test_absent_smoke_rejects_when_required_but_not_for_plain_fresh_samples(self):
        self.assertFalse(m.accept_sample(True, None, False, 0, {"missing": []}, None, self.FULL, smoke_required=True)[0])
        self.assertTrue(m.accept_sample(True, None, False, 0, {"missing": []}, None, self.FULL, smoke_required=False)[0])

    def test_aged_driver_runs_inventory_and_smoke_after_the_loaded_reading(self):
        class FakeSession(_AgedFake):
            def loaded_check(self):
                return {"missing": ["ext:x"], "load_error_markers": 0}
            def smoke_commands(self, everything=False, abort=None):
                return {"checked": 3, "missing": []}
        w = type("W", (), {})()
        w.rose = threading.Event()
        with mock.patch.object(m, "wait_settled", return_value={"settled": True, "extra_wait_s": 0}), \
             mock.patch.object(m, "median_reading", return_value={"rss_pi_kb": 1, "pi_readings_kb": [1, 1, 1]}), \
             mock.patch.object(m, "pressure_ok", return_value=True):
            out = m.aged_driver(FakeSession(), w, lambda *_: None, order=("turn",))
        self.assertEqual(out["loaded"]["loaded"]["missing"], ["ext:x"])
        self.assertEqual(out["loaded"]["smoke"]["checked"], 3)
        # and final acceptance rejects the missing owner on the aged path
        self.assertFalse(m.accept_sample(True, None, False, 0, out["loaded"]["loaded"], out["loaded"]["smoke"], m.parse_variant("full"), smoke_required=True)[0])

    def test_earlier_failure_reason_is_kept(self):
        self.assertEqual(m.accept_sample(False, "unsettled", False, 0, None, None, self.FULL), (False, "unsettled", None))

    def test_readings_and_smoke_stop_when_pressure_is_raised(self):
        class FakeSession:
            def measure(self):
                return {"rss_pi_kb": 1, "owned": []}
            def pump(self, seconds, abort=None):
                return not (abort is not None and abort.is_set())
        ev = threading.Event()
        self.assertIsNotNone(m.median_reading(FakeSession(), n=1, gap=0, abort=ev))
        ev.set()
        self.assertIsNone(m.median_reading(FakeSession(), n=1, gap=0, abort=ev))


class AgedPressure(unittest.TestCase):
    class Fake:
        def __init__(self):
            self.sent = []
            self.session_file = None
            self.backend_requests = lambda: 0
        def send(self, text):
            self.sent.append(text)
        def pump(self, seconds, abort=None):
            return not (abort is not None and abort.is_set())
        def child_pids(self):
            return set()

        def loaded_check(self):
            return {"missing": [], "load_error_markers": 0}

        def smoke_commands(self, everything=False, abort=None):
            return None if (abort is not None and abort.is_set()) else {"checked": 1, "missing": []}

    def run_driver(self, rose=False, ok=True):
        s = self.Fake()
        w = type("W", (), {})()
        w.rose = threading.Event()
        if rose:
            w.rose.set()
        with mock.patch.object(m, "wait_settled", return_value={"settled": True, "extra_wait_s": 0}), \
             mock.patch.object(m, "median_reading", side_effect=lambda sess, abort=None: None if (abort is not None and abort.is_set()) else {"rss_pi_kb": 1, "pi_readings_kb": [1, 1, 1]}), \
             mock.patch.object(m, "pressure_ok", return_value=ok):
            out = m.aged_driver(s, w, lambda *_: None, order=("turn",))
        return out, s.sent

    def test_aged_driver_aborts_on_raised_watcher_and_sends_nothing(self):
        out, sent = self.run_driver(rose=True)
        self.assertIsNone(out)
        self.assertEqual(sent, [])

    def test_aged_driver_does_not_wait_for_pressure_with_the_session_alive(self):
        out, sent = self.run_driver(ok=False)
        self.assertIsNone(out)
        self.assertEqual(sent, [])  # no command is sent, and it returned immediately instead of waiting up to 15 minutes

    def reload_driver(self, before, after):
        calls = iter([before, after])
        class S(self.Fake):
            def child_pids(inner):
                return next(calls, after)
        s = S()
        w = type("W", (), {})()
        w.rose = threading.Event()
        with mock.patch.object(m, "wait_settled", return_value={"settled": True, "extra_wait_s": 0}), \
             mock.patch.object(m, "median_reading", return_value={"rss_pi_kb": 1, "pi_readings_kb": [1, 1, 1]}), \
             mock.patch.object(m, "pressure_ok", return_value=True):
            return m.aged_driver(s, w, lambda *_: None, order=("reload",))

    def test_reload_with_no_child_before_is_rejected_not_nulled(self):
        with self.assertRaises(m.SampleRejected):
            self.reload_driver(set(), set())

    def test_reload_that_replaces_no_child_is_rejected(self):
        with self.assertRaises(m.SampleRejected):
            self.reload_driver({1, 2}, {1, 2})

    def test_reload_where_a_child_only_disappears_is_rejected(self):
        with self.assertRaises(m.SampleRejected):
            self.reload_driver({1, 2}, {1})
        with self.assertRaises(m.SampleRejected):
            self.reload_driver({1}, set())

    def test_reload_where_only_new_children_appear_is_rejected(self):
        with self.assertRaises(m.SampleRejected):
            self.reload_driver({1, 2}, {1, 2, 3})

    def test_reload_that_replaces_a_child_is_verified(self):
        out = self.reload_driver({1, 2}, {1, 3})
        self.assertIs(out["after_reload"]["reload_verified"], True)
        self.assertEqual(out["after_reload"]["child_pids_replaced"], 1)

    def test_aged_driver_proceeds_at_normal_pressure(self):
        out, sent = self.run_driver()
        self.assertEqual(sent, ["continue"])
        self.assertIn("after_turn", out)


class Gate(unittest.TestCase):
    def test_gate_returns_at_normal_pressure(self):
        with mock.patch.object(m, "pressure_level", return_value=1), mock.patch.object(m, "free_percent", return_value=60):
            self.assertEqual(m.gate("t")["level"], 1)

    def test_gate_times_out_fail_closed(self):
        with mock.patch.object(m, "pressure_level", return_value=2), mock.patch.object(m, "free_percent", return_value=60):
            with self.assertRaises(m.Fatal):
                m.gate("t", wait_max=0, poll=0, log=lambda *_: None)


class RemainderTests(unittest.TestCase):
    def test_numeric_remainder_and_noise_floor(self):
        mm = {("core", "fresh"): {"fp_pi_kb": 90 * 1024}, ("full", "fresh"): {"fp_pi_kb": 210 * 1024},
              ("full-pkg:big", "fresh"): {"fp_pi_kb": 150 * 1024}, ("full-pkg:noise", "fresh"): {"fp_pi_kb": 205 * 1024},
              ("full-nomcp", "fresh"): {"fp_pi_kb": 100 * 1024}, ("full-mcp:a+b", "fresh"): {"fp_pi_kb": 100 * 1024}}
        r = m.remainder(mm, {"fp_pi_kb": 40 * 1024}, "fp_pi_kb")
        self.assertEqual(list(r["supported"]), ["full-pkg:big"])  # aggregates and in-noise parts excluded
        self.assertAlmostEqual(r["unexplained_mb"], 120 - 60)
        self.assertAlmostEqual(r["noise_mb"], 20)


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


class WarmupIsolationTests(unittest.TestCase):
    def run_main(self, pf_ok):
        pf = {"ok": pf_ok, "checks": [{"name": "no-credential-looking-files-placed", "ok": pf_ok}]}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(m, "release_paths", return_value=(Path(td), Path(td))), \
             mock.patch.object(m, "Store"), mock.patch.object(m, "Backend"), \
             mock.patch.object(m, "preflight", return_value=pf) as pre, \
             mock.patch.object(m, "run_sample") as run:
            rc = m.main(["measure", "--variants", "full", "--samples", "1", "--warmup", "--out", td + "/out"])
        return rc, pre, run

    def test_failed_isolation_launches_nothing_not_even_the_warmup(self):
        rc, pre, run = self.run_main(False)
        self.assertEqual(rc, 2)
        run.assert_not_called()

    def test_passing_isolation_runs_warmup_then_samples(self):
        rc, pre, run = self.run_main(True)
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_count, 2)


class ReadingStabilityTests(unittest.TestCase):
    def test_a_compaction_still_finishing_is_not_stable(self):
        self.assertFalse(m.readings_stable([3128656, 663744, 667568]))
        self.assertFalse(m.readings_stable([2928416, 478176, 478224]))

    def test_agreeing_readings_are_stable(self):
        self.assertTrue(m.readings_stable([510208, 510208, 510208]))
        self.assertTrue(m.readings_stable([3053648, 2938224, 2990048]))
        self.assertFalse(m.readings_stable([]))


class ExtensionGroupTests(unittest.TestCase):
    def test_groups_never_split_an_import(self):
        exts = ["a", "b", "c", "d", "e", "f"]
        imports = {"b": {"e"}, "f": {"a"}}
        g1, g2 = m.split_extension_groups(exts, imports)
        self.assertEqual(sorted(g1 + g2), exts)
        for owner, deps in imports.items():
            for d in deps:
                self.assertEqual(owner in g1, d in g1)
        self.assertTrue(g1 and g2)

    def test_extension_imports_reads_sibling_imports_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "x").mkdir(); (root / "y").mkdir()
            (root / "x" / "index.ts").write_text('import { h } from "../y/helpers.ts";\nimport z from "./local.ts";\n')
            (root / "y" / "helpers.ts").write_text("export const h = 1;\n")
            self.assertEqual(m.extension_imports(root), {"x": {"y"}})



class LazyVariantTests(unittest.TestCase):
    def test_lazy_variants_parse(self):
        self.assertEqual(m.parse_variant("full-lazy")["lazy"], "state")
        self.assertEqual(m.parse_variant("full-lazy-nostate")["lazy"], "nostate")
        self.assertEqual(m.parse_variant("full-lazy-failedrefresh")["lazy"], "failed")
        self.assertIsNone(m.parse_variant("full")["lazy"])
        with self.assertRaises(ValueError):
            m.parse_variant("full-lazy-bogus")

    def test_mcp_process_counts_separate_stand_ins_from_real_servers(self):
        owned = [{"name": "pi", "rss_kb": 1}, {"name": "python3 pi-mcp-lazy", "rss_kb": 1}, {"name": "python3 pi-mcp-lazy", "rss_kb": 1},
                 {"name": "node rea", "rss_kb": 1}, {"name": "npm exec", "rss_kb": 1}, {"name": "furi", "rss_kb": 1}, {"name": "node other", "rss_kb": 1}]
        self.assertEqual(m.mcp_process_counts(owned), (2, 3))

    def test_report_lists_mcp_process_counts_per_sample(self):
        with tempfile.TemporaryDirectory() as t:
            rows = [{"variant": "full-lazy", "tag": "fresh", "rss_pi_kb": 200000, "rss_owned_kb": 260000, "fp_pi_kb": 150000, "fp_owned_kb": 200000,
                     "owned": [{"name": "pi", "rss_kb": 1}, {"name": "python3 pi-mcp-lazy", "rss_kb": 1}]} for _ in range(3)]
            (Path(t) / "samples.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
            text = m.report(Path(t))
        self.assertIn("MCP server processes at the settled point", text)
        self.assertIn("| full-lazy | fresh | 1/1/1 | 0/0/0 |", text)


if __name__ == "__main__":
    unittest.main()
