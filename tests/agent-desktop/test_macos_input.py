"""The JavaScript inside the macOS agent-desktop script, for `focus`, `type` and `key`: it must need only Accessibility.

The script hands each action to osascript as JavaScript for Automation. Here that JavaScript is cut out of the script and run in node
against a fake macOS bridge (`$`, `ObjC`, `Application`) that records what the code asks macOS to do: which keyboard events it posts
(code, down or up, modifier flags, text), which app it activates, how often it sleeps. `Application` throws if it is ever called, so
anything that talks to System Events (the Automation permission) fails the test. The shell side (arguments, exit codes, log lines) is
`test_macos.py`. That the events really land in an app on a Mac is the live proof's job (docs/agent-desktop.md).
Run: python3 -m unittest discover -s tests/agent-desktop -p 'test_macos_input.py'
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BODY = REPO / ".chezmoitemplates/agent-desktop-macos.sh"

HARNESS = r"""
const [src, argvJson, appsJson] = process.argv.slice(1);
const posted = [], activated = [], sleeps = [];
const apps = JSON.parse(appsJson).map(a => ({
  localizedName: a.name, processIdentifier: a.pid, activationPolicy: a.policy === undefined ? 0 : a.policy,
  activateWithOptions(o) { activated.push(a.name + "#" + a.pid); return true; },
  activate() { activated.push(a.name + "#" + a.pid); return true; },
  unhide() { return true; },
}));
const $ = function () { return null; };
Object.assign($, {
  kCGHIDEventTap: 0,
  NSApplicationActivateIgnoringOtherApps: 2,
  NSApplicationActivateAllWindows: 1,
  CGEventCreateKeyboardEvent: (s, code, down) => ({ code, down: !!down, flags: 0, text: null }),
  CGEventSetFlags: (ev, f) => { ev.flags = f; },
  CGEventKeyboardSetUnicodeString: (ev, n, s) => { ev.text = s; ev.length = n; },
  CGEventPost: (tap, ev) => { posted.push({ code: ev.code, down: ev.down, flags: ev.flags, text: ev.text, length: ev.length }); },
  NSThread: { sleepForTimeInterval: s => { sleeps.push(s); } },
  NSWorkspace: { sharedWorkspace: { runningApplications: apps } },
});
const ObjC = { import() {}, bindFunction() {}, unwrap: x => x, deepUnwrap: x => x, castRefToObject: x => x };
const Application = function () { throw new Error("Application() was called: that is the Automation permission"); };
let out;
try {
  const run = new Function("$", "ObjC", "Application", src + "\nreturn run;")($, ObjC, Application);
  out = { result: run(JSON.parse(argvJson)) };
} catch (e) {
  out = { error: String(e && e.message || e) };
}
out.posted = posted; out.activated = activated; out.sleeps = sleeps;
console.log(JSON.stringify(out));
"""

COMMAND, SHIFT, OPTION, CONTROL = 0x100000, 0x20000, 0x80000, 0x40000
KEY_COMMAND, KEY_SHIFT, KEY_OPTION, KEY_CONTROL = 55, 56, 58, 59
KEY_A, KEY_COMMA, KEY_RETURN, KEY_TAB = 0, 43, 36, 48
APPS = [{"name": "Calculator", "pid": 511}, {"name": "TextEdit", "pid": 620}, {"name": "Google Chrome", "pid": 15242}]


def jxa_text():
    m = re.search(r"^JXA='\n(.*?)\n'$", BODY.read_text(), re.S | re.M)
    assert m, "cannot find the JXA string in the script"
    return m.group(1)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class InputJavaScriptTest(unittest.TestCase):
    def run_js(self, *argv, apps=APPS):
        r = subprocess.run(["node", "-e", HARNESS, jxa_text(), json.dumps(list(argv)), json.dumps(apps)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def keys(self, out, code):
        return [e for e in out["posted"] if e["code"] == code]

    def test_the_script_never_asks_for_the_automation_permission(self):
        text = jxa_text()
        self.assertNotIn("System Events", text)
        self.assertNotIn("Application(", text)

    # key
    def test_key_posts_a_down_and_an_up_with_no_flags_when_there_is_no_modifier(self):
        out = self.run_js("key", str(KEY_A))
        self.assertNotIn("error", out)
        self.assertEqual([(e["code"], e["down"], e["flags"]) for e in out["posted"]], [(KEY_A, True, 0), (KEY_A, False, 0)])

    def test_key_with_a_modifier_holds_it_while_the_key_goes_down_and_up(self):
        out = self.run_js("key", str(KEY_A), "command")
        self.assertNotIn("error", out)
        self.assertEqual([(e["code"], e["down"], e["flags"]) for e in out["posted"]],
                         [(KEY_COMMAND, True, COMMAND), (KEY_A, True, COMMAND), (KEY_A, False, COMMAND), (KEY_COMMAND, False, 0)])

    def test_key_with_two_modifiers_sets_both_flags_and_lets_go_of_all(self):
        out = self.run_js("key", str(KEY_COMMA), "control", "shift")
        self.assertNotIn("error", out)
        down = [e for e in self.keys(out, KEY_COMMA) if e["down"]]
        self.assertEqual([e["flags"] for e in down], [CONTROL | SHIFT])
        self.assertEqual(out["posted"][-1]["flags"], 0)
        held = {KEY_CONTROL, KEY_SHIFT}
        self.assertEqual({e["code"] for e in out["posted"]} - {KEY_COMMA}, held)
        self.assertEqual(sum(1 for e in out["posted"] if e["code"] in held and e["down"]), 2)
        self.assertEqual(sum(1 for e in out["posted"] if e["code"] in held and not e["down"]), 2)

    def test_key_modifier_flags_are_the_four_macos_masks(self):
        for name, mask, code in (("command", COMMAND, KEY_COMMAND), ("shift", SHIFT, KEY_SHIFT),
                                 ("option", OPTION, KEY_OPTION), ("control", CONTROL, KEY_CONTROL)):
            with self.subTest(modifier=name):
                out = self.run_js("key", str(KEY_A), name)
                self.assertEqual([e["flags"] for e in self.keys(out, KEY_A)], [mask, mask])
                self.assertEqual([e["code"] for e in out["posted"]][0], code)

    def test_key_pauses_between_the_events_so_the_app_sees_the_modifier_first(self):
        out = self.run_js("key", str(KEY_A), "command")
        self.assertGreaterEqual(len(out["sleeps"]), 1)

    # type: US keyboard keys only. Setting a Unicode string on a key event did nothing on the Mac mini (macOS 27), so characters are
    # sent as the key that makes them, with Shift held when the layout needs it.
    def key_presses(self, out):
        """(code, shift?) for each non-modifier key that went down, in order."""
        return [(e["code"], bool(e["flags"] & SHIFT)) for e in out["posted"] if e["down"] and e["code"] not in (KEY_SHIFT,)]

    def test_type_posts_each_character_as_the_key_that_makes_it_down_then_up(self):
        out = self.run_js("type", "hi there")
        self.assertNotIn("error", out)
        h, i, space, t, e, r = 4, 34, 49, 17, 14, 15
        self.assertEqual(self.key_presses(out), [(h, False), (i, False), (space, False), (t, False), (h, False), (e, False), (r, False), (e, False)])
        self.assertEqual([e["down"] for e in out["posted"]], [True, False] * len("hi there"))
        self.assertTrue(all(e["flags"] == 0 for e in out["posted"]))

    def test_type_is_paced_one_pause_between_characters(self):
        out = self.run_js("type", "abcd")
        self.assertGreaterEqual(len(out["sleeps"]), 3)

    def test_type_holds_shift_for_capitals_and_shifted_symbols(self):
        out = self.run_js("type", "A!")
        self.assertNotIn("error", out)
        self.assertEqual([(e["code"], e["down"], e["flags"]) for e in out["posted"]],
                         [(KEY_SHIFT, True, SHIFT), (0, True, SHIFT), (0, False, SHIFT), (KEY_SHIFT, False, 0),
                          (KEY_SHIFT, True, SHIFT), (18, True, SHIFT), (18, False, SHIFT), (KEY_SHIFT, False, 0)])

    def test_type_uses_the_us_layout_for_punctuation(self):
        cases = {"-": (27, False), "_": (27, True), "=": (24, False), "+": (24, True), "[": (33, False), "{": (33, True),
                 "]": (30, False), "}": (30, True), "\\": (42, False), "|": (42, True), ";": (41, False), ":": (41, True),
                 "'": (39, False), '"': (39, True), ",": (43, False), "<": (43, True), ".": (47, False), ">": (47, True),
                 "/": (44, False), "?": (44, True), "`": (50, False), "~": (50, True), "1": (18, False), "0": (29, False),
                 "@": (19, True), "#": (20, True), "$": (21, True), "%": (23, True), "^": (22, True), "&": (26, True),
                 "*": (28, True), "(": (25, True), ")": (29, True), " ": (49, False), "z": (6, False), "Z": (6, True)}
        for ch, want in cases.items():
            with self.subTest(char=ch):
                self.assertEqual(self.key_presses(self.run_js("type", ch)), [want])

    def test_every_printable_ascii_character_is_a_different_key_and_shift_pair(self):
        text = "".join(chr(c) for c in range(0x20, 0x7F))
        out = self.run_js("type", text)
        self.assertNotIn("error", out)
        presses = self.key_presses(out)
        self.assertEqual(len(presses), len(text))
        self.assertEqual(len(set(presses)), len(text))

    def test_type_sends_newline_as_return_and_tab_as_tab(self):
        out = self.run_js("type", "a\nb\tc")
        self.assertEqual(self.key_presses(out), [(0, False), (KEY_RETURN, False), (11, False), (KEY_TAB, False), (8, False)])

    def test_type_keeps_quotes_backslashes_and_leading_dashes_as_text(self):
        text = "-n \"it's\" \\ $HOME `x`"
        out = self.run_js("type", text)
        self.assertNotIn("error", out)
        self.assertEqual(len(self.key_presses(out)), len(text))

    def test_type_refuses_a_character_the_us_keyboard_cannot_make_and_types_nothing(self):
        out = self.run_js("type", "ab\u00e9cd")
        self.assertIn("cannot type", out["error"])
        self.assertEqual(out["posted"], [])

    def test_type_of_nothing_posts_nothing(self):
        out = self.run_js("type", "")
        self.assertNotIn("error", out)
        self.assertEqual(out["posted"], [])

    # focus
    def test_focus_activates_the_app_with_that_name_and_no_other(self):
        out = self.run_js("focus", "TextEdit")
        self.assertNotIn("error", out)
        self.assertEqual(out["activated"], ["TextEdit#620"])
        self.assertEqual(out["posted"], [])

    def test_focus_matches_the_whole_name_including_spaces(self):
        out = self.run_js("focus", "Google Chrome")
        self.assertEqual(out["activated"], ["Google Chrome#15242"])

    def test_focus_names_are_not_matched_by_part(self):
        out = self.run_js("focus", "Text")
        self.assertIn("no running app named Text", out["error"])
        self.assertEqual(out["activated"], [])

    def test_focus_of_an_app_that_is_not_running_is_an_error_that_names_it(self):
        out = self.run_js("focus", "Nope")
        self.assertIn("no running app named Nope", out["error"])
        self.assertEqual(out["activated"], [])

    def test_focus_skips_background_processes_that_share_a_name(self):
        apps = [{"name": "TextEdit", "pid": 1, "policy": 2}, {"name": "TextEdit", "pid": 2, "policy": 0}]
        out = self.run_js("focus", "TextEdit", apps=apps)
        self.assertEqual(out["activated"], ["TextEdit#2"])


if __name__ == "__main__":
    unittest.main()
