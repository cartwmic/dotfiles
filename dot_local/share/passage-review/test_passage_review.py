from __future__ import annotations

import base64
import hashlib
import json
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


CLI = Path(__file__).resolve().parents[3] / "dot_local" / "bin" / "executable_passage-review"
NVIM_MODULE = Path(__file__).resolve().with_name("passage_review.lua")
MD_RENDER = Path.home() / ".local" / "share" / "nvim" / "lazy" / "md-render.nvim"
REVIEW_ID_RE = re.compile(r"rv-[0-9a-f]{12}")


class PassageReviewCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="passage-review-test-")
        self.root = Path(self.temp.name)
        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.root / "home"),
                "XDG_DATA_HOME": str(self.root / "data"),
                "PAGER": "cat",
                "PASSAGE_REVIEW_CLIPBOARD": "off",
                "EDITOR": "vi",
            }
        )
        self.env.pop("VISUAL", None)
        for name in tuple(self.env):
            if name.startswith(("PI_", "HERDR_")):
                self.env.pop(name)
        Path(self.env["HOME"]).mkdir()
        Path(self.env["XDG_DATA_HOME"]).mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cli(self, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI), *args],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            check=False,
        )

    def run_tty(self, *args: str, steps: list[tuple[str, str]], timeout: float = 10) -> str:
        pid, master = pty.fork()
        if pid == 0:
            os.environ.update(self.env)
            os.execv(str(CLI), [str(CLI), *args])
        output = bytearray()
        deadline = time.monotonic() + timeout
        status: int | None = None
        step_index = 0
        search_from = 0
        try:
            while time.monotonic() < deadline:
                if step_index < len(steps):
                    marker = steps[step_index][0].encode()
                    found = output.find(marker, search_from)
                    if found >= 0:
                        search_from = found + len(marker)
                        os.write(master, steps[step_index][1].encode())
                        step_index += 1
                        continue
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        _finished, status = os.waitpid(pid, 0)
                        break
                    if not chunk:
                        _finished, status = os.waitpid(pid, 0)
                        break
                    output.extend(chunk)
                finished, child_status = os.waitpid(pid, os.WNOHANG)
                if finished:
                    status = child_status
                    while select.select([master], [], [], 0)[0]:
                        try:
                            output.extend(os.read(master, 65536))
                        except OSError:
                            break
                    break
            if status is None:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
                self.fail(f"command timed out; terminal output:\n{output.decode(errors='replace')}")
            if step_index != len(steps):
                self.fail(f"command exited before scripted input; terminal output:\n{output.decode(errors='replace')}")
        finally:
            os.close(master)
        self.assertTrue(os.WIFEXITED(status), output.decode(errors="replace"))
        self.assertEqual(os.WEXITSTATUS(status), 0, output.decode(errors="replace"))
        return output.decode(errors="replace")

    def make_editor(self, comments: list[str]) -> None:
        script = self.root / "fake-editor.py"
        calls = self.root / "editor-call-count"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys\n"
            "from pathlib import Path\n"
            "count = Path(os.environ['EDITOR_CALLS'])\n"
            "index = int(count.read_text()) if count.exists() else 0\n"
            "values = os.environ['EDITOR_TEXTS'].split('\\x1e')\n"
            "Path(sys.argv[-1]).write_text(values[index], encoding='utf-8')\n"
            "count.write_text(str(index + 1))\n",
            encoding="utf-8",
        )
        script.chmod(0o700)
        self.env["VISUAL"] = f"{sys.executable} {script}"
        self.env["EDITOR_CALLS"] = str(calls)
        self.env["EDITOR_TEXTS"] = "\x1e".join(comments)

    def review_directory(self, review_id: str) -> Path:
        return Path(self.env["XDG_DATA_HOME"]) / "passage-review" / "reviews" / review_id

    def test_stdin_snapshot_saves_without_pi_or_herdr(self) -> None:
        snapshot = "supplied source\nwith second line\n"
        result = self.cli("new", "--title", "Supplied snapshot", input_text=snapshot)
        self.assertEqual(result.returncode, 0, result.stderr)
        match = REVIEW_ID_RE.search(result.stdout)
        self.assertIsNotNone(match, result.stdout)
        review_id = match.group(0)
        directory = self.review_directory(review_id)
        self.assertEqual((directory / "snapshot.txt").read_text(), snapshot)
        metadata = json.loads((directory / "review.json").read_text())
        self.assertEqual(metadata["source"], {"kind": "stdin", "reference": "supplied stdin snapshot"})
        self.assertEqual(metadata["snapshot_sha256"], hashlib.sha256(snapshot.encode()).hexdigest())
        self.assertEqual(list((directory / "notes").glob("n-*.json")), [])

    def test_add_reopen_and_selectively_export_without_changing_notes_or_snapshot(self) -> None:
        source = self.root / "design.md"
        original = b"First line\nQuoted passage starts\nQuoted passage ends\nFourth line\nFinal line"
        source.write_bytes(original)
        self.make_editor(["First feedback", "Second feedback"])

        terminal = self.run_tty(
            "new",
            "--file",
            str(source),
            steps=[
                ("[a]dd passage comment", "a\n"),
                ("Passage line or range", "2-3\n"),
                ("[a]dd passage comment", "a\n"),
                ("Passage line or range", "5\n"),
                ("[a]dd passage comment", "q\n"),
            ],
        )
        match = REVIEW_ID_RE.search(terminal)
        self.assertIsNotNone(match, terminal)
        review_id = match.group(0)
        directory = self.review_directory(review_id)
        metadata = json.loads((directory / "review.json").read_text())
        note_paths = sorted((directory / "notes").glob("n-*.json"))
        self.assertEqual(len(note_paths), 2, terminal)
        notes = [json.loads(path.read_text()) for path in note_paths]
        notes_by_comment = {note["comment"]: note for note in notes}
        self.assertEqual(notes_by_comment["First feedback"]["line_start"], 2)
        self.assertEqual(notes_by_comment["First feedback"]["line_end"], 3)
        self.assertEqual(notes_by_comment["First feedback"]["quote"], "Quoted passage starts\nQuoted passage ends\n")
        self.assertEqual(notes_by_comment["Second feedback"]["quote"], "Final line")
        self.assertEqual(metadata["source"]["reference"], str(source.resolve()))
        self.assertEqual((directory / "snapshot.txt").read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)

        reopened = self.run_tty("open", review_id, steps=[("[a]dd passage comment", "q\n")])
        self.assertIn("First feedback", reopened)
        self.assertIn("Second feedback", reopened)
        self.assertIn("Quoted passage starts", reopened)

        selected = notes_by_comment["First feedback"]
        unselected = notes_by_comment["Second feedback"]
        exported = self.cli("export", review_id, "--note", selected["note_id"])
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertIn("First feedback", exported.stdout)
        self.assertNotIn("Second feedback", exported.stdout)
        self.assertIn("Quoted passage starts", exported.stdout)
        self.assertIn(str(source.resolve()), exported.stdout)
        self.assertEqual((directory / "snapshot.txt").read_bytes(), original)
        pending_after_export = [json.loads(path.read_text()) for path in sorted((directory / "notes").glob("n-*.json"))]
        self.assertEqual(pending_after_export, notes)
        self.assertFalse((directory / "notes" / "archived").exists())
        export_path_match = re.search(r"Saved export: (.+)", exported.stdout)
        self.assertIsNotNone(export_path_match, exported.stdout)
        self.assertIn("First feedback", Path(export_path_match.group(1)).read_text())
        self.assertNotIn("Second feedback", Path(export_path_match.group(1)).read_text())

        self.env.pop("PASSAGE_REVIEW_CLIPBOARD", None)
        self.env["SSH_TTY"] = "/dev/pts/passage-review-test"
        self.env["TERM"] = "xterm-256color"
        copied = self.run_tty("export", review_id, "--note", selected["note_id"], steps=[])
        payloads = re.findall(r"\x1b\]52;c;([A-Za-z0-9+/=]+)\x07", copied)
        self.assertEqual(len(payloads), 1, copied)
        copied_text = base64.b64decode(payloads[0]).decode("utf-8")
        self.assertIn("First feedback", copied_text)
        self.assertNotIn("Second feedback", copied_text)
        self.assertIn("Saved export:", copied)
        self.assertIn("First feedback", copied)

    def test_builtin_pager_scrolls_and_selects_a_late_passage(self) -> None:
        source_text = "".join(f"passage line {number}\n" for number in range(1, 46))
        created = self.cli("new", "--title", "long phone source", input_text=source_text)
        review_id = REVIEW_ID_RE.search(created.stdout).group(0)  # type: ignore[union-attr]
        self.env["PAGER"] = "false"
        self.env["LINES"] = "9"
        self.env["COLUMNS"] = "24"
        self.make_editor(["Comment on a later pane passage"])
        steps = [
            ("-- lines 1-6/45", "\n"),
            ("-- lines 7-12/45", "b\n"),
            ("-- lines 1-6/45", "\n"),
            ("-- lines 7-12/45", "\n"),
            ("-- lines 13-18/45", "\n"),
            ("-- lines 19-24/45", "\n"),
            ("-- lines 25-30/45", "\n"),
            ("-- lines 31-36/45", "\n"),
            ("-- lines 37-42/45", "q\n"),
            ("[a]dd passage comment", "a\n"),
            ("Passage line or range", "38-39\n"),
            ("[a]dd passage comment", "q\n"),
        ]
        terminal = self.run_tty("open", review_id, steps=steps)
        note = json.loads(next(self.review_directory(review_id).joinpath("notes").glob("n-*.json")).read_text())
        self.assertEqual((note["line_start"], note["line_end"]), (38, 39))
        self.assertEqual(note["quote"], "passage line 38\npassage line 39\n")
        self.assertIn("passage line 38", terminal)
        self.assertIn("Comment on a later pane passage", terminal)

    def test_archive_and_delete_are_the_only_note_state_changes(self) -> None:
        result = self.cli("new", "--title", "state test", input_text="line one\n")
        review_id = REVIEW_ID_RE.search(result.stdout).group(0)  # type: ignore[union-attr]
        self.make_editor(["keep pending", "archive me", "delete me"])
        self.run_tty(
            "open",
            review_id,
            steps=[
                ("[a]dd passage comment", "a\n"),
                ("Passage line or range", "1\n"),
                ("[a]dd passage comment", "a\n"),
                ("Passage line or range", "1\n"),
                ("[a]dd passage comment", "a\n"),
                ("Passage line or range", "1\n"),
                ("[a]dd passage comment", "q\n"),
            ],
        )
        notes = [json.loads(path.read_text()) for path in sorted((self.review_directory(review_id) / "notes").glob("n-*.json"))]
        by_comment = {note["comment"]: note["note_id"] for note in notes}
        archived = self.cli("archive", review_id, "--note", by_comment["archive me"])
        self.assertEqual(archived.returncode, 0, archived.stderr)
        deleted = self.cli("delete", review_id, "--note", by_comment["delete me"])
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        directory = self.review_directory(review_id)
        self.assertEqual({p.stem for p in (directory / "notes").glob("n-*.json")}, {by_comment["keep pending"]})
        self.assertTrue((directory / "notes" / "archived" / f"{by_comment['archive me']}.json").is_file())
        export_archived = self.cli("export", review_id, "--note", by_comment["archive me"])
        self.assertNotEqual(export_archived.returncode, 0)
        self.assertIn("only pending notes", export_archived.stderr)

    def test_changed_snapshot_fails_closed(self) -> None:
        result = self.cli("new", "--title", "integrity", input_text="immutable bytes\n")
        review_id = REVIEW_ID_RE.search(result.stdout).group(0)  # type: ignore[union-attr]
        snapshot = self.review_directory(review_id) / "snapshot.txt"
        snapshot.chmod(0o600)
        snapshot.write_text("changed bytes\n")
        opened = self.cli("open", review_id)
        self.assertNotEqual(opened.returncode, 0)
        self.assertIn("integrity check failed", opened.stderr)

    def new_review(self, text: str) -> str:
        result = self.cli("new", "--title", "nvim test", "--no-open", input_text=text)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^rv-[0-9a-f]{12}$")
        return result.stdout.strip()

    def test_note_command_anchors_lines_or_exact_text_and_show_lists_them(self) -> None:
        review_id = self.new_review("line one\nthe quick brown fox\nlast line\n")
        whole = self.cli("note", review_id, "--lines", "1-2", input_text="whole lines\n")
        self.assertEqual(whole.returncode, 0, whole.stderr)
        exact = self.cli("note", review_id, "--lines", "2", "--quote", "brown fox", input_text="exact text\n")
        self.assertEqual(exact.returncode, 0, exact.stderr)
        outside = self.cli("note", review_id, "--lines", "1", "--quote", "brown", input_text="no\n")
        self.assertNotEqual(outside.returncode, 0)
        blank = self.cli("note", review_id, "--lines", "1", input_text="  \n")
        self.assertNotEqual(blank.returncode, 0)

        shown = json.loads(self.cli("show", review_id).stdout)
        self.assertEqual(Path(shown["snapshot_path"]), self.review_directory(review_id) / "snapshot.txt")
        by_id = {note["note_id"]: note for note in shown["notes"]}
        self.assertEqual(set(by_id), {whole.stdout.strip(), exact.stdout.strip()})
        self.assertEqual(by_id[whole.stdout.strip()]["quote"], "line one\nthe quick brown fox\n")
        self.assertEqual(by_id[exact.stdout.strip()]["quote"], "brown fox")
        self.assertEqual(by_id[exact.stdout.strip()]["line_start"], 2)

    def test_open_with_nvim_editor_reads_snapshot_in_nvim_with_the_plugin(self) -> None:
        review_id = self.new_review("readable text\n")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        record = self.root / "nvim-call.json"
        fake = bin_dir / "nvim"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            f"open({str(record)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], "
            "'lua': os.environ.get('PASSAGE_REVIEW_LUA'), 'id': os.environ.get('PASSAGE_REVIEW_ID'), "
            "'tty': os.isatty(0)}))\n",
            encoding="utf-8",
        )
        fake.chmod(0o700)
        self.env["VISUAL"] = str(fake)
        terminal = self.run_tty("open", review_id, steps=[])
        call = json.loads(record.read_text())
        self.assertEqual(call["argv"][0], str(self.review_directory(review_id) / "snapshot.txt"))
        self.assertIn("-c", call["argv"])
        self.assertEqual(Path(call["lua"]), NVIM_MODULE)
        self.assertEqual(call["id"], review_id)
        self.assertTrue(call["tty"])
        self.assertIn("0 pending comment(s)", terminal)
        self.assertNotIn("[a]dd passage comment", terminal)

    @unittest.skipUnless(shutil.which("nvim"), "nvim is not installed")
    def test_real_nvim_visual_selection_saves_and_renders_notes(self) -> None:
        review_id = self.new_review("line one\nthe quick brown fox\nlast line\n")
        script = self.root / "drive.lua"
        script.write_text(
            """
local ok, err = pcall(function()
vim.g.mapleader = " "
local M = dofile(vim.env.PASSAGE_REVIEW_LUA)
M.open(vim.env.PASSAGE_REVIEW_ID)
local review = vim.api.nvim_get_current_buf()
assert(not vim.bo.modifiable, "snapshot must not be modifiable")
for _, mode in ipairs({ "n", "x" }) do
  for _, map in ipairs(vim.api.nvim_buf_get_keymap(review, mode)) do
    assert(map.lhs ~= "c" and map.lhs ~= "q", "review must not remap " .. map.lhs)
  end
end
local function comment(keys, texts)
  vim.api.nvim_set_current_win(vim.fn.bufwinid(review))
  vim.api.nvim_feedkeys(vim.keycode(keys), "x", false)
  assert(vim.bo.buftype == "" and vim.api.nvim_buf_get_name(0):match("%.md$"), "comment must be a normal file")
  for _, text in ipairs(texts) do
    vim.api.nvim_buf_set_lines(0, 0, -1, false, { text })
    vim.cmd("stopinsert | write")
  end
  vim.cmd("quit")
end
comment("2G0wwve<Space>zc", { "first draft", "charwise note" })  -- selects "brown"; second :w replaces the note
comment("1GVj<Space>zc", { "linewise note" })
local marks = vim.api.nvim_buf_get_extmarks(review, vim.api.nvim_create_namespace("passage_review"), 0, -1, { details = true })
local virt = 0
for _, mark in ipairs(marks) do
  if mark[4].virt_lines then virt = virt + 1 end
end
assert(virt == 2, "expected two rendered comments, got " .. virt)
end)
if not ok then
  io.stderr:write(tostring(err))
  vim.cmd("cquit 1")
end
vim.cmd("qa!")
""",
            encoding="utf-8",
        )
        self.env["PASSAGE_REVIEW_LUA"] = str(NVIM_MODULE)
        self.env["PASSAGE_REVIEW_ID"] = review_id
        result = subprocess.run(
            ["nvim", "--clean", "--headless", "-c", f"luafile {script}"],
            env=self.env, text=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        notes = json.loads(self.cli("show", review_id).stdout)["notes"]
        by_comment = {note["comment"]: note for note in notes}
        self.assertEqual(set(by_comment), {"charwise note\n", "linewise note\n"})
        self.assertEqual(by_comment["charwise note\n"]["quote"], "brown")
        self.assertEqual((by_comment["charwise note\n"]["line_start"], by_comment["charwise note\n"]["line_end"]), (2, 2))
        self.assertEqual(by_comment["linewise note\n"]["quote"], "line one\nthe quick brown fox\n")

    def run_nvim(self, file: Path, lua: str) -> subprocess.CompletedProcess[str]:
        script = self.root / "drive.lua"
        script.write_text(
            "local ok, err = pcall(function()\n" + lua + "\nend)\n"
            "if not ok then io.stderr:write(tostring(err)); vim.cmd('cquit 1') end\n"
            "vim.cmd('qa!')\n",
            encoding="utf-8",
        )
        self.env["PASSAGE_REVIEW_LUA"] = str(NVIM_MODULE)
        return subprocess.run(
            ["nvim", "--clean", "--headless", str(file), "-c", f"luafile {script}"],
            env=self.env, text=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=30, check=False,
        )

    def review_ids(self) -> list[str]:
        return [line.split("\t")[0] for line in self.cli("list").stdout.splitlines() if line.startswith("rv-")]

    @unittest.skipUnless(shutil.which("nvim"), "nvim is not installed")
    def test_passage_review_command_offers_to_reopen_a_review_with_pending_notes(self) -> None:
        doc = self.root / "doc.md"
        doc.write_text("first line\nsecond line\n", encoding="utf-8")
        old = self.cli("new", "--file", str(doc), "--no-open").stdout.strip()
        self.assertEqual(self.cli("note", old, "--lines", "1", input_text="keep me\n").returncode, 0)

        # Choosing the existing review reopens it; nothing new is created.
        result = self.run_nvim(doc, """
local M = dofile(vim.env.PASSAGE_REVIEW_LUA)
local offered
vim.ui.select = function(items, opts, choice)
  offered = items
  choice(items[1])
end
vim.cmd("PassageReview")
assert(#offered == 3, "expected reopen, new and delete, got " .. #offered)
assert(offered[1].label:find("Reopen " .. vim.env.OLD_ID, 1, true), offered[1].label)
assert(offered[2].label == "Start a new review", offered[2].label)
assert(offered[3].label == "Delete " .. vim.env.OLD_ID, offered[3].label)
assert(vim.b.passage_review_id == vim.env.OLD_ID, "reopened " .. tostring(vim.b.passage_review_id))
""".replace("vim.env.OLD_ID", repr(old)))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.review_ids(), [old])

        # Choosing "new" still starts a fresh review.
        result = self.run_nvim(doc, """
dofile(vim.env.PASSAGE_REVIEW_LUA)
vim.ui.select = function(items, opts, choice) choice(items[2]) end
vim.cmd("PassageReview")
assert(vim.b.passage_review_id and vim.b.passage_review_id ~= %r, "expected a new review")
""" % old)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(len(self.review_ids()), 2)

    @unittest.skipUnless(shutil.which("nvim"), "nvim is not installed")
    def test_passage_review_command_can_delete_a_pending_review_then_asks_again(self) -> None:
        doc = self.root / "doc.md"
        doc.write_text("first line\n", encoding="utf-8")
        old = self.cli("new", "--file", str(doc), "--no-open").stdout.strip()
        self.cli("note", old, "--lines", "1", input_text="pending\n")
        result = self.run_nvim(doc, """
dofile(vim.env.PASSAGE_REVIEW_LUA)
local prompts = {}
vim.ui.select = function(items, opts, choice)
  table.insert(prompts, opts.prompt)
  if #prompts == 1 then
    choice(items[3])  -- Delete <old>
  elseif #prompts == 2 then
    assert(items[1] == "Delete", "expected a confirmation")
    choice("Delete")
  end
end
vim.cmd("PassageReview")
vim.wait(1000, function() return #prompts >= 2 end)
vim.wait(200)
-- Nothing pending is left, so the picker comes back with just "new".
assert(#prompts == 3, "expected the picker again, got " .. #prompts .. " prompts")
""")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.review_ids(), [])

    def test_remove_deletes_a_whole_review(self) -> None:
        review_id = self.new_review("line\n")
        self.cli("note", review_id, "--lines", "1", input_text="note\n")
        removed = self.cli("remove", review_id)
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertFalse(self.review_directory(review_id).exists())
        again = self.cli("remove", review_id)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("not found", again.stderr)

    @unittest.skipUnless(shutil.which("nvim"), "nvim is not installed")
    def test_passage_review_delete_picks_current_review_and_confirms(self) -> None:
        doc = self.root / "doc.md"
        doc.write_text("only line\n", encoding="utf-8")
        keep = self.cli("new", "--file", str(doc), "--no-open").stdout.strip()
        target = self.cli("new", "--file", str(doc), "--no-open").stdout.strip()
        result = self.run_nvim(doc, """
local M = dofile(vim.env.PASSAGE_REVIEW_LUA)
M.open(%r)
local prompts = {}
vim.ui.select = function(items, opts, choice)
  table.insert(prompts, opts.prompt)
  if #prompts == 1 then
    assert(items[1].id == %r, "current review should be offered first")
    choice(items[1])
  else
    choice("Cancel")
  end
end
vim.cmd("PassageReviewDelete")
assert(#prompts == 2, "expected pick + confirm")
vim.ui.select = function(items, opts, choice) choice(items[1] == "Delete" and "Delete" or items[1]) end
vim.cmd("PassageReviewDelete " .. %r)
assert(not vim.b.passage_review_id, "deleted review buffer should be closed")
""" % (target, target, target))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.review_ids(), [keep])

    @unittest.skipUnless(shutil.which("nvim"), "nvim is not installed")
    def test_passage_review_command_starts_new_review_without_asking_when_nothing_is_pending(self) -> None:
        doc = self.root / "doc.md"
        doc.write_text("only line\n", encoding="utf-8")
        old = self.cli("new", "--file", str(doc), "--no-open").stdout.strip()
        result = self.run_nvim(doc, """
dofile(vim.env.PASSAGE_REVIEW_LUA)
vim.ui.select = function() error("should not ask") end
vim.cmd("PassageReview")
assert(vim.b.passage_review_id and vim.b.passage_review_id ~= %r, "expected a new review")
""" % old)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(len(self.review_ids()), 2)

    @unittest.skipUnless(
        shutil.which("nvim") and MD_RENDER.is_dir(), "nvim or the installed md-render.nvim plugin is missing"
    )
    def test_comment_from_md_render_view_maps_to_snapshot_lines(self) -> None:
        review_id = self.new_review("# Title\n\nIntro paragraph.\n\n- first item\n- second item\n")
        script = self.root / "drive.lua"
        script.write_text(
            """
local ok, err = pcall(function()
vim.g.mapleader = " "
vim.opt.rtp:prepend(vim.env.MD_RENDER)
local M = dofile(vim.env.PASSAGE_REVIEW_LUA)
M.open(vim.env.PASSAGE_REVIEW_ID)
require("md-render.preview").toggle()
vim.api.nvim_exec_autocmds("BufWinEnter", {})
vim.wait(200)
local view = vim.api.nvim_get_current_buf()
assert(vim.b[view].md_render, "expected the md-render view")
local row = vim.fn.search("second item")
assert(row > 0, "rendered text not found")
vim.api.nvim_feedkeys(vim.keycode("V<Space>zc"), "x", false)
vim.api.nvim_buf_set_lines(0, 0, -1, false, { "from the rendered view" })
vim.cmd("stopinsert | write | quit")
local virt = 0
for _, mark in ipairs(vim.api.nvim_buf_get_extmarks(view, vim.api.nvim_create_namespace("passage_review"), 0, -1, { details = true })) do
  if mark[4].virt_lines then virt = virt + 1 end
end
assert(virt == 1, "expected the comment in the rendered view, got " .. virt)
end)
if not ok then
  io.stderr:write(tostring(err))
  vim.cmd("cquit 1")
end
vim.cmd("qa!")
""",
            encoding="utf-8",
        )
        self.env.update(PASSAGE_REVIEW_LUA=str(NVIM_MODULE), PASSAGE_REVIEW_ID=review_id, MD_RENDER=str(MD_RENDER))
        result = subprocess.run(
            ["nvim", "--clean", "--headless", "-c", f"luafile {script}"],
            env=self.env, text=True, capture_output=True, stdin=subprocess.DEVNULL, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        notes = json.loads(self.cli("show", review_id).stdout)["notes"]
        self.assertEqual(len(notes), 1)
        self.assertEqual((notes[0]["line_start"], notes[0]["line_end"]), (6, 6))
        self.assertEqual(notes[0]["quote"], "- second item\n")


if __name__ == "__main__":
    unittest.main()
