"""check_record.py: accepts a good saved run and rejects a bad one, one defect at a time (criteria c12, c13, c14).

No device is touched. Each test builds a small fake source tree in a temp folder (no git, like the old-tree copy verify
uses), copies the real proof_sources.py, check_record.py and live_run.py into it, builds a record with live_run's own
writer (so the record format cannot drift from what the driver writes), and runs the real command line:
    python3 tests/agent-desktop/check_record.py --device D --record FILE
A rejection must exit 1 with the reason on stderr and nothing on stdout; each test changes exactly one thing and asserts
the reason names it.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 24
ROWS = ["J0", "J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8", "N1", "N2", "N3", "N4", "N5"]
OMARCHY_NOT_OFFERED = ["N1", "N2", "N3", "N4", "N5"]
SOURCES = {
    "dot_local/bin/executable_agent-desktop": "#!/bin/sh\necho linux script\n",
    ".chezmoitemplates/agent-desktop-macos.sh": "#!/bin/sh\necho macos body\n",
    "run_onchange_after_66_agent_desktop_macos.sh.tmpl": "#!/bin/sh\necho install step\n",
    ".chezmoiignore": "windows\n",
    "windows/install.ps1": "Write-Output install\n",
    "windows/agent-desktop.ps1": "Write-Output script\n",
    "windows/agent-desktop.cmd": "@echo off\n",
    # outside every device's selection
    "tests/agent-desktop/test_something.py": "pass\n",
    "docs/agent-desktop.md": "# doc\n",
    "dot_config/other/file": "unrelated\n",
}


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="live-record-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.make_root("a")

    def make_root(self, name, sources=None):
        root = self.tmp / name
        for rel, text in (SOURCES if sources is None else sources).items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        td = root / "tests/agent-desktop"
        td.mkdir(parents=True, exist_ok=True)
        for f in ("proof_sources.py", "check_record.py", "live_run.py"):
            shutil.copy(HERE / f, td / f)
        return root

    # ---- fixture records, built with the driver's own writer ----
    def make_record(self, device="mac-mini", root=None, outname=None):
        """Write a complete good record plus every file it names. Returns the record folder."""
        root = root or self.root
        out = self.tmp / (outname or "proof-" + device)
        out.mkdir(parents=True, exist_ok=True)
        lr = load_from(root)

        def cmd(label, exit_code=0):
            f = "%s.txt" % label
            (out / f).write_text("output of %s\n" % label)
            return {"command": "agent-desktop " + label, "exit": exit_code, "output_file": f}

        def shot(label):
            f = "%s.png" % label
            (out / f).write_bytes(PNG)
            return f

        rows = []
        for rid in ROWS:
            if device == "omarchy" and rid in OMARCHY_NOT_OFFERED:
                rows.append(lr.row(rid, "not_offered", note="no labelled controls on this desktop"))
            else:
                rows.append(lr.row(rid, "pass", commands=[cmd(rid)], screenshots=[shot(rid)] if rid == "J1" else []))
        install = {"fresh": dict(cmd("install-fresh"))}
        settings = None
        checks = None
        if device == "g14":
            install["second"] = dict(cmd("install-second"), changed=False)
            settings = {"before": g14_settings(), "after": g14_settings()}
            checks = {
                "locked_screen": dict(cmd("locked", 1), status="pass"),
                "ui_via_task": dict(cmd("ui-task"), status="pass"),
            }
        rec = lr.build_record(device, root, rows, install, settings=settings, checks=checks)
        lr.write_record(out, rec)
        return out

    def run_check(self, device, out, root=None):
        root = root or self.root
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run(
            [sys.executable, "-I", str(root / "tests/agent-desktop/check_record.py"), "--device", device, "--record", str(out / "record.json")],
            capture_output=True, text=True, env=env, timeout=60,
        )

    def edit(self, out, fn):
        p = out / "record.json"
        rec = json.loads(p.read_text())
        fn(rec)
        p.write_text(json.dumps(rec, indent=1))

    def row_of(self, rec, rid):
        return next(r for r in rec["rows"] if r["id"] == rid)

    def assert_rejected(self, r, *needles):
        self.assertEqual(r.returncode, 1, "stdout=%r stderr=%r" % (r.stdout, r.stderr))
        self.assertEqual(r.stdout, "")
        for n in needles:
            self.assertIn(n, r.stderr)

    def assert_accepted(self, r):
        self.assertEqual(r.returncode, 0, "stdout=%r stderr=%r" % (r.stdout, r.stderr))
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        return r.stdout.strip()


def load_from(root):
    """Import live_run.py from a fake root, the way the driver sees its own tree."""
    path = root / "tests/agent-desktop/live_run.py"
    spec = importlib.util.spec_from_file_location("live_run_" + root.name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def g14_settings():
    return {
        "registry": {"ScreenSaveTimeOut": "59940", "ScreenSaverIsSecure": "0", "InactivityTimeoutSecs": None},
        "powercfg": [
            "8ec4b3a5 (Console lock display off timeout) AC=0x0000001e",
            "8ec4b3a5 (Console lock display off timeout) DC=0x0000001e",
            "0e796bdb (Require a password on wakeup) AC=0x00000001",
            "29f6c1db (Sleep after) DC=0x000004b0",
        ],
    }


class Accepts(Case):
    def test_mac_mini_good_record(self):
        out = self.make_record("mac-mini")
        line = self.assert_accepted(self.run_check("mac-mini", out))
        self.assertEqual(line, "device=mac-mini score=14/14 pass=%s fail=-" % ",".join(ROWS))

    def test_work_mac_good_record_is_judged_like_a_mac(self):
        out = self.make_record("work-mac")
        line = self.assert_accepted(self.run_check("work-mac", out))
        self.assertEqual(line, "device=work-mac score=14/14 pass=%s fail=-" % ",".join(ROWS))

    def test_g14_good_record(self):
        out = self.make_record("g14")
        line = self.assert_accepted(self.run_check("g14", out))
        self.assertEqual(line, "device=g14 score=14/14 pass=%s fail=-" % ",".join(ROWS))

    def test_omarchy_good_record_scores_the_nine_it_offers(self):
        out = self.make_record("omarchy")
        line = self.assert_accepted(self.run_check("omarchy", out))
        self.assertEqual(line, "device=omarchy score=9/14 pass=%s fail=- not_offered=%s" % (",".join(ROWS[:9]), ",".join(OMARCHY_NOT_OFFERED)))

    def test_failing_optional_row_is_named_with_its_error_and_still_accepted(self):
        out = self.make_record("mac-mini")

        def f(rec):
            r = self.row_of(rec, "N3")
            r["status"] = "fail"
            r["error"] = "run 2 of 3:\n  display read 40"

        self.edit(out, f)
        line = self.assert_accepted(self.run_check("mac-mini", out))
        self.assertEqual(line, "device=mac-mini score=13/14 pass=%s fail=N3:run 2 of 3: display read 40" % ",".join(r for r in ROWS if r != "N3"))

    def test_omarchy_line_is_the_same_in_an_old_tree_with_the_same_script(self):
        # c14 'old: same': the old tree has the same Linux script and none of the other files.
        old = self.make_root("old", {"dot_local/bin/executable_agent-desktop": SOURCES["dot_local/bin/executable_agent-desktop"]})
        out = self.make_record("omarchy")
        new_line = self.assert_accepted(self.run_check("omarchy", out))
        old_line = self.assert_accepted(self.run_check("omarchy", out, root=old))
        self.assertEqual(new_line, old_line)

    def test_line_is_stable_across_runs(self):
        out = self.make_record("mac-mini")
        a = self.run_check("mac-mini", out)
        b = self.run_check("mac-mini", out)
        self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr))


class Rejects(Case):
    # --- the six rejections the lane names ---
    def test_wrong_digest(self):
        out = self.make_record("mac-mini")
        (self.root / "run_onchange_after_66_agent_desktop_macos.sh.tmpl").write_text("#!/bin/sh\necho changed after the run\n")
        self.assert_rejected(self.run_check("mac-mini", out), "source digest")

    def test_missing_row(self):
        out = self.make_record("mac-mini")
        self.edit(out, lambda rec: rec["rows"].remove(self.row_of(rec, "N4")))
        self.assert_rejected(self.run_check("mac-mini", out), "missing row N4")

    def test_failing_required_row(self):
        out = self.make_record("mac-mini")

        def f(rec):
            r = self.row_of(rec, "J5")
            r["status"] = "fail"
            r["error"] = "click did not register"

        self.edit(out, f)
        self.assert_rejected(self.run_check("mac-mini", out), "required row J5", "click did not register")

    def test_fail_without_error_text(self):
        out = self.make_record("mac-mini")

        def f(rec):
            r = self.row_of(rec, "N5")
            r["status"] = "fail"
            r["error"] = "  "

        self.edit(out, f)
        self.assert_rejected(self.run_check("mac-mini", out), "N5", "error text")

    def test_missing_screenshot(self):
        out = self.make_record("mac-mini")
        (out / "J1.png").unlink()
        self.assert_rejected(self.run_check("mac-mini", out), "J1.png")

    def test_changed_g14_settings(self):
        out = self.make_record("g14")

        def f(rec):
            rec["settings"]["after"]["powercfg"][0] = "8ec4b3a5 (Console lock display off timeout) AC=0x00000258"

        self.edit(out, f)
        self.assert_rejected(self.run_check("g14", out), "settings", "changed")

    # --- further defects ---
    def test_screenshot_that_is_not_a_png(self):
        out = self.make_record("mac-mini")
        (out / "J1.png").write_bytes(b"GIF89a" + b"\0" * 20)
        self.assert_rejected(self.run_check("mac-mini", out), "J1.png", "PNG")

    def test_missing_command_output_file(self):
        out = self.make_record("mac-mini")
        (out / "J3.txt").unlink()
        self.assert_rejected(self.run_check("mac-mini", out), "J3.txt")

    def test_pass_row_with_no_command(self):
        out = self.make_record("mac-mini")
        self.edit(out, lambda rec: self.row_of(rec, "J6").update(commands=[]))
        self.assert_rejected(self.run_check("mac-mini", out), "J6", "no command")

    def test_wrong_schema(self):
        out = self.make_record("mac-mini")
        self.edit(out, lambda rec: rec.update(schema=2))
        self.assert_rejected(self.run_check("mac-mini", out), "schema")

    def test_record_for_another_device(self):
        out = self.make_record("mac-mini")
        self.assert_rejected(self.run_check("g14", out), "device")

    def test_unreadable_record(self):
        out = self.make_record("mac-mini")
        (out / "record.json").write_text("{not json")
        self.assert_rejected(self.run_check("mac-mini", out), "record")

    def test_missing_fresh_install(self):
        out = self.make_record("mac-mini")
        self.edit(out, lambda rec: rec["install"].pop("fresh"))
        self.assert_rejected(self.run_check("mac-mini", out), "install", "fresh")

    def test_failed_fresh_install(self):
        out = self.make_record("mac-mini")
        self.edit(out, lambda rec: rec["install"]["fresh"].update(exit=1))
        self.assert_rejected(self.run_check("mac-mini", out), "install", "fresh")

    def test_g14_second_install_that_changed_something(self):
        out = self.make_record("g14")
        self.edit(out, lambda rec: rec["install"]["second"].update(changed=True))
        self.assert_rejected(self.run_check("g14", out), "second", "changed")

    def test_g14_without_second_install(self):
        out = self.make_record("g14")
        self.edit(out, lambda rec: rec["install"].pop("second"))
        self.assert_rejected(self.run_check("g14", out), "second")

    def test_g14_settings_that_do_not_hold_the_lock_timeout(self):
        # equal before and after is not enough if the lock timeout was never read
        out = self.make_record("g14")

        def f(rec):
            for k in ("before", "after"):
                rec["settings"][k]["powercfg"] = ["29f6c1db (Sleep after) DC=0x000004b0"]

        self.edit(out, f)
        self.assert_rejected(self.run_check("g14", out), "lock")

    def test_g14_without_the_locked_screen_check(self):
        out = self.make_record("g14")
        self.edit(out, lambda rec: rec["checks"].pop("locked_screen"))
        self.assert_rejected(self.run_check("g14", out), "locked_screen")

    def test_g14_locked_screen_check_that_did_not_exit_1(self):
        out = self.make_record("g14")
        self.edit(out, lambda rec: rec["checks"]["locked_screen"].update(exit=0))
        self.assert_rejected(self.run_check("g14", out), "locked_screen")

    def test_g14_ui_through_the_task_not_proven(self):
        out = self.make_record("g14")
        self.edit(out, lambda rec: rec["checks"]["ui_via_task"].update(status="fail"))
        self.assert_rejected(self.run_check("g14", out), "ui_via_task")

    def test_omarchy_row_that_should_be_not_offered(self):
        out = self.make_record("omarchy")

        def f(rec):
            r = self.row_of(rec, "N1")
            r["status"] = "pass"
            r["commands"] = [{"command": "x", "exit": 0, "output_file": "J0.txt"}]

        self.edit(out, f)
        self.assert_rejected(self.run_check("omarchy", out), "N1", "not_offered")

    def test_mac_row_marked_not_offered(self):
        out = self.make_record("mac-mini")
        self.edit(out, lambda rec: self.row_of(rec, "N2").update(status="not_offered"))
        self.assert_rejected(self.run_check("mac-mini", out), "required row N2")

    def test_work_mac_row_marked_not_offered(self):
        out = self.make_record("work-mac")
        self.edit(out, lambda rec: self.row_of(rec, "N2").update(status="not_offered"))
        self.assert_rejected(self.run_check("work-mac", out), "required row N2")

    def test_work_mac_failing_required_row(self):
        out = self.make_record("work-mac")

        def f(rec):
            self.row_of(rec, "J5").update(status="fail", error="a 7 on the calculator display")
        self.edit(out, f)
        self.assert_rejected(self.run_check("work-mac", out), "required row J5", "a 7 on the calculator display")

    def test_a_mac_mini_record_is_not_a_work_mac_record(self):
        out = self.make_record("mac-mini")
        self.assert_rejected(self.run_check("work-mac", out), "mac-mini")

    def test_old_tree_without_windows_files_rejects_a_g14_record(self):
        # c13 'old: fails': the old tree has no windows/ folder.
        out = self.make_record("g14")
        old = self.make_root("old", {k: v for k, v in SOURCES.items() if not k.startswith("windows/")})
        self.assert_rejected(self.run_check("g14", out, root=old), "windows")

    def test_old_tree_rejects_a_mac_record(self):
        out = self.make_record("mac-mini")
        old = self.make_root("old", {"dot_local/bin/executable_agent-desktop": SOURCES["dot_local/bin/executable_agent-desktop"]})
        self.assert_rejected(self.run_check("mac-mini", out, root=old), "source digest")


class Sources(Case):
    """Which files bind each device's record (proof_sources.py)."""

    def digest(self, device, root=None):
        r = subprocess.run([sys.executable, "-I", str((root or self.root) / "tests/agent-desktop/proof_sources.py"), device],
                           capture_output=True, text=True, timeout=30, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_omarchy_is_the_one_linux_script(self):
        d = self.digest("omarchy")
        self.assertEqual(d["files"], ["dot_local/bin/executable_agent-desktop"])

    def test_mac_mini_files(self):
        d = self.digest("mac-mini")
        self.assertEqual(
            d["files"],
            sorted([
                ".chezmoiignore",
                ".chezmoitemplates/agent-desktop-macos.sh",
                "dot_local/bin/executable_agent-desktop",
                "run_onchange_after_66_agent_desktop_macos.sh.tmpl",
            ]),
        )

    def test_work_mac_is_bound_to_the_same_files_as_the_mac_mini(self):
        self.assertEqual(self.digest("work-mac"), dict(self.digest("mac-mini"), device="work-mac"))

    def test_g14_files(self):
        d = self.digest("g14")
        self.assertEqual(d["files"], ["windows/agent-desktop.cmd", "windows/agent-desktop.ps1", "windows/install.ps1"])

    def test_tests_docs_and_windows_do_not_move_the_mac_digest(self):
        before = self.digest("mac-mini")["digest"]
        (self.root / "tests/agent-desktop/test_something.py").write_text("changed\n")
        (self.root / "docs/agent-desktop.md").write_text("changed\n")
        (self.root / "windows/install.ps1").write_text("changed\n")
        self.assertEqual(self.digest("mac-mini")["digest"], before)

    def test_mac_digest_follows_chezmoiignore(self):
        before = self.digest("mac-mini")["digest"]
        (self.root / ".chezmoiignore").write_text("changed\n")
        self.assertNotEqual(self.digest("mac-mini")["digest"], before)

    def test_g14_digest_follows_windows_files_only(self):
        before = self.digest("g14")["digest"]
        (self.root / "dot_local/bin/executable_agent-desktop").write_text("changed\n")
        self.assertEqual(self.digest("g14")["digest"], before)
        (self.root / "windows/agent-desktop.cmd").write_text("changed\n")
        self.assertNotEqual(self.digest("g14")["digest"], before)

    def test_selection_ignores_the_checkout_location(self):
        # a root whose own path contains 'agent-desktop' must not select every file under it
        sub = self.tmp / "read-agent-desktop" / "wt"
        shutil.copytree(self.root, sub)
        self.assertEqual(self.digest("omarchy", sub)["files"], ["dot_local/bin/executable_agent-desktop"])

    def test_no_files_for_a_device_is_an_error(self):
        empty = self.make_root("empty", {"README.md": "x\n"})
        r = subprocess.run([sys.executable, "-I", str(empty / "tests/agent-desktop/proof_sources.py"), "g14"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no source files", r.stderr)


class RoundTrip(Case):
    """What the driver's recorder writes is what the checker reads: run rows with a fake device, then check the record."""

    def fake_device(self, lr):
        class Fake(lr.Device):
            name = "mac-mini"

            def sh(self, cmd, timeout=60, stdin=None):
                if "fail-me" in cmd:
                    return lr.Result(3, "boom: it broke\n")
                return lr.Result(0, "ok\n")

            def tmp(self, name):
                return "/scratch/" + name

            def pull(self, remote, local):
                Path(local).write_bytes(PNG)

        return Fake()

    def test_rows_saved_by_the_recorder_pass_the_checker(self):
        lr = load_from(self.root)
        out = self.tmp / "rt"
        rec = lr.Rec(self.fake_device(lr), out)

        def good(rec):
            rec.ad("do it", "windows")
            rec.shot("full")

        rows = []
        for rid in ROWS:
            rows.append(lr.run_row(rec, rid, good))
        rec.begin("install")
        rec.sh("install", "echo installed")
        install = {"fresh": rec.cmds[-1]}
        lr.write_record(out, lr.build_record("mac-mini", self.root, rows, install))
        self.assertEqual(self.assert_accepted(self.run_check("mac-mini", out)).split()[:2], ["device=mac-mini", "score=14/14"])

    def test_a_row_that_raises_is_recorded_as_a_failure_with_its_error(self):
        lr = load_from(self.root)
        out = self.tmp / "rt2"
        rec = lr.Rec(self.fake_device(lr), out)

        def bad(rec):
            r = rec.sh("fail-me", "fail-me")
            lr.expect(r.exit == 0, "the tool exited %d: %s" % (r.exit, r.out.strip()))

        def crash(rec):
            raise KeyError("oops")

        a, b = lr.run_row(rec, "N3", bad), lr.run_row(rec, "N4", crash)
        self.assertEqual((a["status"], a["error"]), ("fail", "the tool exited 3: boom: it broke"))
        self.assertEqual(b["status"], "fail")
        self.assertIn("oops", b["error"])
        self.assertTrue((out / a["commands"][0]["output_file"]).read_text().startswith("$ fail-me\nexit=3"))

    def test_wait_for_gives_up_on_a_missing_fact_with_a_message_not_a_hang(self):
        lr = load_from(self.root)
        with self.assertRaises(lr.Fail) as cm:
            lr.wait_for("a window that never comes", lambda: False, timeout=0.3, interval=0.05)
        self.assertIn("a window that never comes", str(cm.exception))


class DryRun(unittest.TestCase):
    """live_run.py DEVICE --dry-run: prints the plan, touches nothing."""

    def run_dry(self, device):
        out = Path(tempfile.mkdtemp(prefix="live-dry-"))
        self.addCleanup(shutil.rmtree, out, True)
        r = subprocess.run([sys.executable, "-I", str(HERE / "live_run.py"), device, "--dry-run", "--out", str(out / "proof")],
                           capture_output=True, text=True, timeout=60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(list(out.iterdir()), [], "a dry run must write nothing")
        return r.stdout

    def test_every_device_plans_all_fourteen_rows(self):
        for device in ("omarchy", "mac-mini", "work-mac", "g14"):
            text = self.run_dry(device)
            for rid in ROWS:
                self.assertRegex(text, r"(?m)^row %s\b" % rid, "%s: %s" % (device, rid))

    def test_work_mac_plan_runs_here_with_no_ssh_and_no_copy_and_checks_it_is_a_mac(self):
        text = self.run_dry("work-mac")
        self.assertIn("no ssh, no copy", text)
        self.assertNotIn("ssh mac-mini", text)
        self.assertRegex(text, r"(?m)^  this machine is a Mac \(uname -s is Darwin\): (ok|MISSING)$")

    @unittest.skipIf(sys.platform == "darwin", "this test is about a machine that is not a Mac")
    def test_work_mac_run_on_a_machine_that_is_not_a_mac_stops_before_doing_anything(self):
        out = Path(tempfile.mkdtemp(prefix="live-notmac-"))
        self.addCleanup(shutil.rmtree, out, True)
        r = subprocess.run([sys.executable, "-I", str(HERE / "live_run.py"), "work-mac", "--out", str(out / "proof")],
                           capture_output=True, text=True, timeout=60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("precondition this machine is a Mac (uname -s is Darwin): MISSING", r.stdout)
        self.assertEqual([p.name for p in (out / "proof").iterdir()], [], "nothing is run or saved when the precondition is missing")

    def test_g14_plan_has_the_locked_screen_check_before_the_rows(self):
        text = self.run_dry("g14")
        self.assertLess(text.index("locked_screen"), text.index("row J0"))
        self.assertIn("ui_via_task", text)

    def test_omarchy_plan_marks_label_rows_not_offered(self):
        text = self.run_dry("omarchy")
        for rid in ("N1", "N2", "N3", "N4"):
            self.assertRegex(text, r"(?m)^row %s\b.*not_offered" % rid)


if __name__ == "__main__":
    unittest.main()
