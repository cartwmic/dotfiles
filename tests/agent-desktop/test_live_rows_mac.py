"""The Mac rows of live_run.py, run against a scripted Mac mini (no device touched).

A fake device answers the `agent-desktop` commands the rows send, the way the real mini did in the first full run:
  - TextEdit capitalises the first letter of what is typed (type 'hello x' reads back 'Hello x').
  - Calculator shows a result only in the display's `native_id` (`StandardInputView;value:408`); the text child goes away.
  - Finder has no window an accessibility snapshot can read until something opens one.
Each test runs one real row function from `desktop_rows` and says what the row must conclude.
"""
import importlib.util
import json
import re
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 24


def load():
    spec = importlib.util.spec_from_file_location("live_run_rows", HERE / "live_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lr = load()

BUTTONS = ["Delete", "All Clear", "Percent", "Divide", "7", "8", "9", "Multiply", "4", "5", "6", "Subtract", "1", "2", "3", "Add", "Change Sign", "0", "Point", "Equals"]
DIGITS = "0123456789"


class FakeMini(lr.Device):
    name = "mac-mini"
    scratch = "/scratch"

    def __init__(self, autocap=True, typing_works=True, finder_window=False, calc_text_child_after_equals=False):
        self.autocap, self.typing_works = autocap, typing_works
        self.apps = {"System Settings": True}
        self.finder_pre = finder_window
        if finder_window:
            self.apps["Finder"] = True
        self.focused = "System Settings"
        self.text = ""
        self.selected = False
        self.entry, self.acc, self.op, self.shown = "", None, None, "0"
        self.calls = []
        self.finder_windows = 1 if finder_window else 0

    # ---- Device surface
    def sh(self, cmd, timeout=60, stdin=None):
        self.calls.append(cmd)
        argv = shlex.split(cmd)
        if argv[:1] == ["agent-desktop"]:
            return self.agent_desktop(argv[1:])
        if argv[:2] == ["open", "-a"]:
            self.apps[argv[2]] = True
            self.focused = argv[2]
            return lr.Result(0, "")
        if argv[:2] == ["open", "~"] or argv[:1] == ["open"] and len(argv) == 2:
            self.apps["Finder"] = True
            self.finder_windows += 1
            self.focused = "Finder"
            return lr.Result(0, "")
        if argv[:1] == ["pkill"]:
            self.apps.pop(argv[-1].replace(";", ""), None)
            return lr.Result(0, "")
        return lr.Result(0, "")

    def tmp(self, name):
        return "/scratch/" + name

    def pull(self, remote, local):
        Path(local).write_bytes(PNG)

    # ---- agent-desktop
    def agent_desktop(self, a):
        verb = a[0]
        if verb == "windows":
            return lr.Result(0, "app\ttitle\n" + "".join("%s\t%s\n" % (n, n) for n in self.apps))
        if verb == "focus":
            self.focused = a[1]
            return lr.Result(0, "")
        if verb == "type":
            if self.focused == "TextEdit" and self.typing_works:
                s = a[1]
                if self.autocap and not self.text and s:
                    s = s[0].upper() + s[1:]
                self.text += s
            return lr.Result(0, "")
        if verb == "key":
            if a[1:3] == ["a", "cmd"]:
                self.selected = True
            elif a[1] == "delete" and self.focused == "TextEdit":
                if self.selected:
                    self.text = ""
                    self.selected = False
            elif a[1:3] == ["w", "cmd"] and self.focused == "Finder":
                self.finder_windows = max(0, self.finder_windows - 1)
                if not self.finder_windows:
                    self.apps.pop("Finder", None) if not self.finder_pre else None
            return lr.Result(0, "")
        if verb == "ui":
            return self.ui(a[1:])
        return lr.Result(0, "")

    def envelope(self, data=None, ok=True, code=None):
        body = {"version": "2.6", "ok": ok, "data": data}
        if code:
            body["error"] = {"code": code}
        return lr.Result(0 if ok else 1, json.dumps(body) + "\n")

    def ui(self, a):
        verb = a[0]
        if verb == "list-windows":
            data = [{"id": "w-%d" % i, "app_name": n, "title": n, "is_focused": n == self.focused} for i, n in enumerate(self.apps)]
            return self.envelope(data)
        if verb == "snapshot":
            app = a[a.index("--app") + 1]
            if app == "TextEdit":
                return self.envelope({"app": app, "tree": {"role": "window", "children": [{"role": "textfield", "ref_id": "@s:e1", "available_actions": ["TypeText"]}]}})
            if app == "Finder":
                if self.finder_windows == 0 or not self.finder_readable():
                    return self.envelope(None, ok=False, code="WINDOW_NOT_FOUND")
                return self.envelope({"app": app, "tree": {"role": "window", "children": [{"role": "button", "name": n, "ref_id": "@s:f%d" % i} for i, n in enumerate(["Back", "Forward", "Tags", "Share", "Documents", "Downloads"])]}})
            if app == "System Settings":
                return self.envelope({"app": app, "tree": {"role": "window", "children": [{"role": "button", "name": n, "ref_id": "@s:g%d" % i} for i, n in enumerate("abcdefg")]}})
            if app == "Calculator":
                kids = [{"role": "button", "name": n, "ref_id": "@s:e%d" % i} for i, n in enumerate(BUTTONS, 3)]
                inner = [{"role": "statictext", "name": self.shown, "value": self.shown}] if self.shown == "0" else []
                disp = {"role": "scrollarea", "ref_id": "@s:e1", "native_id": {"kind": "ax_identifier", "value": "StandardInputView;value:%s" % self.shown}, "children": inner}
                return self.envelope({"app": app, "tree": {"role": "window", "children": [disp] + kids}})
        if verb == "get":
            return self.envelope({"value": self.text})
        if verb == "click":
            ref = a[1]
            m = re.match(r"@s:e(\d+)$", ref)
            if m:
                self.press(BUTTONS[int(m.group(1)) - 3])
            return self.envelope({"action": "click"})
        return self.envelope({})

    def finder_readable(self):
        # the desktop is the only Finder window until a real folder window is opened
        return self.finder_windows >= 1 and (self.finder_pre or any(c.split()[:1] == ["open"] and "~" in c for c in self.calls))

    def press(self, name):
        if name == "All Clear":
            self.entry, self.acc, self.op, self.shown = "", None, None, "0"
        elif name in DIGITS:
            self.entry += name
            self.shown = self.entry
        elif name == "Multiply":
            self.acc, self.op, self.entry = int(self.entry or "0"), "*", ""
        elif name == "Equals" and self.op:
            self.shown = str(self.acc * int(self.entry or "0"))
            self.acc, self.op, self.entry = None, None, ""


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mac-rows-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def rows(self, mini):
        # the polling in the rows would wait up to 15 s on a row that is meant to fail; speed it up
        self.addCleanup(setattr, lr.time, "sleep", lr.time.sleep)
        lr.time.sleep = lambda s: None
        real_wait = lr.wait_for
        self.addCleanup(setattr, lr, "wait_for", real_wait)
        lr.wait_for = lambda what, fn, timeout=30.0, interval=0.4: real_wait(what, fn, timeout=min(timeout, 0.2), interval=0.01)
        rec = lr.Rec(mini, self.tmp / "out")
        rec.begin("T")
        rows, _close_editor, _close_calc = lr.desktop_rows(rec, mini)
        return dict(rows), rec


class J6(Case):
    def test_passes_when_textedit_capitalises_the_first_letter(self):
        mini = FakeMini(autocap=True)
        rows, rec = self.rows(mini)
        rows["J6"](rec)
        self.assertEqual(mini.text[:5], "Hello")

    def test_proves_shift_live_with_capital_letters_that_must_stay_capital(self):
        mini = FakeMini(autocap=True)
        rows, rec = self.rows(mini)
        rows["J6"](rec)
        self.assertIn("ABC 123", mini.text)

    def test_fails_when_nothing_arrives_in_the_editor(self):
        mini = FakeMini(typing_works=False)
        rows, rec = self.rows(mini)
        with self.assertRaises(lr.Fail) as cm:
            rows["J6"](rec)
        self.assertIn("typed text", str(cm.exception))


class J7(Case):
    def test_fails_when_the_text_was_never_there(self):
        mini = FakeMini()
        rows, rec = self.rows(mini)
        with self.assertRaises(lr.Fail) as cm:
            rows["J7"](rec)
        self.assertIn("no text", str(cm.exception))

    def test_passes_when_text_is_there_and_gets_erased(self):
        mini = FakeMini()
        rows, rec = self.rows(mini)
        rows["J6"](rec)
        self.assertTrue(mini.text)
        rows["J7"](rec)
        self.assertEqual(mini.text, "")

    def test_fails_when_select_all_and_delete_leave_the_text(self):
        mini = FakeMini()
        rows, rec = self.rows(mini)
        rows["J6"](rec)
        mini.selected_ignored = True
        real = mini.agent_desktop

        def ignore_erase(a):
            if a[:1] == ["key"] and a[1] == "delete":
                return lr.Result(0, "")
            return real(a)

        mini.agent_desktop = ignore_erase
        with self.assertRaises(lr.Fail):
            rows["J7"](rec)


class N1(Case):
    def test_opens_a_finder_window_when_only_the_desktop_exists(self):
        mini = FakeMini(finder_window=False)
        rows, rec = self.rows(mini)
        rows["N1"](rec)
        self.assertTrue(any(c.startswith("open ") and "~" in c for c in mini.calls), mini.calls)

    def test_closes_only_the_window_it_opened(self):
        mini = FakeMini(finder_window=False)
        rows, rec = self.rows(mini)
        rows["N1"](rec)
        self.assertEqual(mini.finder_windows, 0)
        self.assertTrue(any("key" in c and " w " in c and "cmd" in c for c in mini.calls), mini.calls)

    def test_leaves_a_finder_window_that_was_already_open(self):
        mini = FakeMini(finder_window=True)
        rows, rec = self.rows(mini)
        rows["N1"](rec)
        self.assertEqual(mini.finder_windows, 1)
        self.assertFalse(any(c.startswith("open ") and "~" in c for c in mini.calls))


class N2N3(Case):
    def test_reads_408_when_it_is_only_in_the_display_native_id(self):
        mini = FakeMini()
        rows, rec = self.rows(mini)
        rows["N2"](rec)
        self.assertEqual(mini.shown, "408")

    def test_three_runs_in_a_row(self):
        mini = FakeMini()
        rows, rec = self.rows(mini)
        rows["N3"](rec)
        self.assertEqual(mini.shown, "408")

    def test_fails_when_the_display_never_shows_408(self):
        mini = FakeMini()
        mini.press = lambda name: None
        rows, rec = self.rows(mini)
        with self.assertRaises(lr.Fail) as cm:
            rows["N2"](rec)
        self.assertIn("408", str(cm.exception))


class Helpers(unittest.TestCase):
    def test_display_texts_reads_the_value_out_of_a_native_id(self):
        env = {"data": {"tree": {"role": "scrollarea", "native_id": {"kind": "ax_identifier", "value": "StandardInputView;value:408"}}}}
        self.assertIn("408", lr.texts(env))

    def test_native_id_without_a_value_adds_nothing(self):
        env = {"data": {"tree": {"role": "group", "native_id": {"kind": "ax_identifier", "value": "main, SidebarNavigationSplitView"}}}}
        self.assertEqual(lr.texts(env), [])


if __name__ == "__main__":
    unittest.main()
