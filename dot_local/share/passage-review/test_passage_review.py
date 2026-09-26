from __future__ import annotations

import base64
import hashlib
import json
import os
import pty
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


CLI = Path(__file__).resolve().parents[3] / "dot_local" / "bin" / "executable_passage-review"
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
            }
        )
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


if __name__ == "__main__":
    unittest.main()
