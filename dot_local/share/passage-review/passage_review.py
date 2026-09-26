#!/usr/bin/env python3
"""Standalone passage reviewer with immutable snapshots and a local note library."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


class ReviewError(Exception):
    """An expected user-facing error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def library_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home).expanduser() / "passage-review"


def _review_id(value: str) -> str:
    if len(value) != 15 or not value.startswith("rv-") or any(c not in "0123456789abcdef" for c in value[3:]):
        raise ReviewError(f"invalid review ID: {value}")
    return value


def _note_id(value: str) -> str:
    if len(value) != 10 or not value.startswith("n-") or any(c not in "0123456789abcdef" for c in value[2:]):
        raise ReviewError(f"invalid note ID: {value}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewError(f"could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewError(f"expected a JSON object in {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _review_dir(review_id: str) -> Path:
    return library_path() / "reviews" / _review_id(review_id)


def create_review(title: str, source_kind: str, source_reference: str, text: str) -> str:
    title = title.strip()
    if not title:
        raise ReviewError("review title must not be blank")
    if not text:
        raise ReviewError("source snapshot is empty")
    try:
        snapshot = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ReviewError("source snapshot must be valid UTF-8 text") from exc

    root = library_path() / "reviews"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for _ in range(5):
        review_id = f"rv-{uuid.uuid4().hex[:12]}"
        directory = root / review_id
        try:
            directory.mkdir(mode=0o700)
            break
        except FileExistsError:
            continue
    else:
        raise ReviewError("could not allocate a unique review ID")

    try:
        (directory / "notes").mkdir(mode=0o700)
        (directory / "exports").mkdir(mode=0o700)
        snapshot_path = directory / "snapshot.txt"
        snapshot_path.write_bytes(snapshot)
        snapshot_path.chmod(0o400)
        _write_json(
            directory / "review.json",
            {
                "schema_version": 1,
                "review_id": review_id,
                "title": title,
                "source": {"kind": source_kind, "reference": source_reference},
                "created_at": utc_now(),
                "snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
                "snapshot_bytes": len(snapshot),
                "line_count": len(text.splitlines()),
            },
        )
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return review_id


def load_review(review_id: str) -> tuple[Path, dict[str, Any], str]:
    directory = _review_dir(review_id)
    metadata = _read_json(directory / "review.json")
    if metadata.get("schema_version") != 1 or metadata.get("review_id") != review_id:
        raise ReviewError(f"invalid review metadata for {review_id}")
    try:
        snapshot_bytes = (directory / "snapshot.txt").read_bytes()
        text = snapshot_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReviewError(f"could not read UTF-8 snapshot for {review_id}: {exc}") from exc
    if hashlib.sha256(snapshot_bytes).hexdigest() != metadata.get("snapshot_sha256"):
        raise ReviewError(f"snapshot integrity check failed for {review_id}; refusing to use a changed snapshot")
    return directory, metadata, text


def _note_path(directory: Path, note_id: str, archived: bool = False) -> Path:
    note_id = _note_id(note_id)
    if archived:
        return directory / "notes" / "archived" / f"{note_id}.json"
    return directory / "notes" / f"{note_id}.json"


def pending_notes(directory: Path) -> list[dict[str, Any]]:
    notes_dir = directory / "notes"
    notes: list[dict[str, Any]] = []
    if not notes_dir.exists():
        return notes
    for path in sorted(notes_dir.glob("n-*.json")):
        note = _read_json(path)
        if note.get("note_id") != path.stem:
            raise ReviewError(f"note ID mismatch in {path}")
        notes.append(note)
    return notes


def archived_notes(directory: Path) -> list[dict[str, Any]]:
    notes_dir = directory / "notes" / "archived"
    if not notes_dir.exists():
        return []
    return [_read_json(path) for path in sorted(notes_dir.glob("n-*.json"))]


def _format_range(value: str, line_count: int) -> tuple[int, int]:
    raw = value.strip().replace(":", "-")
    try:
        pieces = raw.split("-", 1)
        start = int(pieces[0])
        end = int(pieces[1]) if len(pieces) == 2 else start
    except ValueError as exc:
        raise ReviewError("enter a line number or range, for example 3-5") from exc
    if start < 1 or end < start or end > line_count:
        raise ReviewError(f"line range must be between 1 and {line_count}")
    return start, end


def _next_note_id(directory: Path) -> str:
    occupied = {path.stem for path in (directory / "notes").rglob("n-*.json")}
    for _ in range(8):
        note_id = f"n-{uuid.uuid4().hex[:8]}"
        if note_id not in occupied:
            return note_id
    raise ReviewError("could not allocate a unique note ID")


def _edit_comment(tty: TextIO) -> str | None:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    try:
        command = shlex.split(editor)
    except ValueError as exc:
        raise ReviewError(f"invalid VISUAL/EDITOR command: {exc}") from exc
    if not command:
        raise ReviewError("VISUAL/EDITOR command is blank")

    fd, path_string = tempfile.mkstemp(prefix="passage-review-comment-", suffix=".txt")
    path = Path(path_string)
    os.fchmod(fd, 0o600)
    os.close(fd)
    try:
        print("Write the passage comment in your editor; save and close to keep it.", flush=True)
        try:
            result = subprocess.run(command + [str(path)], stdin=tty, stdout=sys.stdout, stderr=sys.stderr, check=False)
        except OSError as exc:
            raise ReviewError(f"could not start editor {command[0]}: {exc}") from exc
        if result.returncode != 0:
            raise ReviewError(f"editor exited with status {result.returncode}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ReviewError(f"could not read comment text: {exc}") from exc
        return text if text.strip() else None
    finally:
        path.unlink(missing_ok=True)


def add_note(directory: Path, metadata: dict[str, Any], source: str, tty: TextIO) -> None:
    line_count = len(source.splitlines())
    if line_count == 0:
        print("This snapshot has no selectable lines.", flush=True)
        return
    raw_range = _prompt(tty, f"Passage line or range (1-{line_count}; q cancels): ")
    if raw_range.lower() == "q":
        return
    try:
        start, end = _format_range(raw_range, line_count)
    except ReviewError as exc:
        print(f"Not saved: {exc}", flush=True)
        return
    lines = source.splitlines(keepends=True)
    quote = "".join(lines[start - 1 : end])
    print(f"\nSelected passage, lines {start}-{end}:\n{quote}", flush=True)
    comment = _edit_comment(tty)
    if comment is None:
        print("Blank comment; nothing saved.", flush=True)
        return

    note_id = _next_note_id(directory)
    note = {
        "schema_version": 1,
        "note_id": note_id,
        "review_id": metadata["review_id"],
        "created_at": utc_now(),
        "line_start": start,
        "line_end": end,
        "quote": quote,
        "comment": comment,
    }
    path = _note_path(directory, note_id)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_json(path, note)
    print(f"Saved pending note {note_id}.", flush=True)


def _prompt(tty: TextIO, text: str) -> str:
    print(text, end="", flush=True)
    value = bytearray()
    while True:
        chunk = os.read(tty.fileno(), 1)
        if not chunk:
            return "q"
        if chunk in (b"\n", b"\r"):
            return value.decode("utf-8", errors="replace").strip()
        value.extend(chunk)


def _print_note(note: dict[str, Any], state: str = "pending") -> None:
    print(f"[{note['note_id']}] {state} — lines {note['line_start']}-{note['line_end']}")
    print(f"  Quote: {note['quote'].strip()}")
    print(f"  Comment: {note['comment'].strip()}")


def _run_pager(text: str, tty: TextIO) -> None:
    configured = os.environ.get("PAGER")
    if configured:
        try:
            command = shlex.split(configured)
        except ValueError:
            command = []
    elif shutil.which("less"):
        command = ["less", "-FRX"]
    elif shutil.which("more"):
        command = ["more"]
    else:
        command = []
    if command:
        try:
            result = subprocess.run(
                command,
                input=text.encode("utf-8"),
                stdout=sys.stdout,
                stderr=sys.stderr,
                check=False,
            )
            if result.returncode == 0:
                return
        except OSError:
            pass
    _builtin_pager(text, tty)


def _builtin_pager(text: str, tty: TextIO) -> None:
    lines = text.splitlines(keepends=True)
    if not lines:
        print("(empty snapshot)", flush=True)
        return
    height = max(5, shutil.get_terminal_size(fallback=(80, 24)).lines - 3)
    start = 0
    while start < len(lines):
        end = min(start + height, len(lines))
        sys.stdout.write("".join(lines[start:end]))
        sys.stdout.flush()
        if end >= len(lines):
            break
        action = _prompt(tty, f"-- lines {start + 1}-{end}/{len(lines)}; Enter next, b back, q done -- ")
        if action.lower() == "q":
            break
        if action.lower() == "b":
            start = max(0, start - height)
        else:
            start = end


def open_interactive(review_id: str, tty: TextIO) -> None:
    directory, metadata, source = load_review(review_id)
    print(
        f"\nReview {review_id}: {metadata['title']}\n"
        f"Source: {metadata['source']['kind']} — {metadata['source']['reference']}\n"
        f"Snapshot: {metadata['line_count']} lines, SHA-256 {metadata['snapshot_sha256']}\n",
        flush=True,
    )
    _run_pager(source, tty)
    while True:
        notes = pending_notes(directory)
        old_notes = archived_notes(directory)
        print(f"\nPending comments ({len(notes)}):", flush=True)
        for note in notes:
            _print_note(note)
        print(f"Archived comments: {len(old_notes)}", flush=True)
        action = _prompt(tty, "[a]dd passage comment, [q]uit: ").lower()
        if action in ("q", "quit", ""):
            return
        if action in ("a", "add"):
            try:
                add_note(directory, metadata, source, tty)
            except ReviewError as exc:
                print(f"Not saved: {exc}", flush=True)


def open_review(review_id: str) -> None:
    try:
        tty = open("/dev/tty", "r", encoding="utf-8", newline="")
    except OSError:
        tty = None
    if tty is None:
        directory, metadata, source = load_review(review_id)
        print(f"Review {review_id}: {metadata['title']}")
        print(f"Source: {metadata['source']['kind']} — {metadata['source']['reference']}")
        print(source, end="" if source.endswith("\n") else "\n")
        for note in pending_notes(directory):
            _print_note(note)
        return
    try:
        open_interactive(review_id, tty)
    finally:
        tty.close()


def _markdown_quote(quote: str) -> str:
    lines = quote.splitlines()
    if not lines:
        lines = [""]
    return "\n".join("> " + line for line in lines)


def _markdown_value(value: str) -> str:
    return "`" + value.replace("`", "\\`").replace("\n", " ") + "`"


def build_export(metadata: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    source = metadata["source"]
    chunks = [
        f"# Passage review: {metadata['title']}",
        "",
        f"Review ID: {_markdown_value(metadata['review_id'])}",
        f"Source: {_markdown_value(source['kind'])} — {_markdown_value(source['reference'])}",
        f"Snapshot SHA-256: {_markdown_value(metadata['snapshot_sha256'])}",
    ]
    for note in notes:
        chunks.extend(
            [
                "",
                f"## Note {note['note_id']} — source lines {note['line_start']}-{note['line_end']}",
                "",
                _markdown_quote(note["quote"]),
                "",
                "Feedback:",
                "",
                note["comment"].rstrip(),
            ]
        )
    return "\n".join(chunks) + "\n"


def _osc52(text: str) -> str:
    payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
    if os.environ.get("TMUX"):
        return f"\033Ptmux;\033\033]52;c;{payload}\a\033\\"
    return f"\033]52;c;{payload}\a"


def copy_to_viewing_terminal(text: str) -> str:
    if os.environ.get("PASSAGE_REVIEW_CLIPBOARD") == "off":
        return "not attempted (disabled)"
    if not sys.stdout.isatty():
        return "not available without a viewing terminal"
    payload = text.encode("utf-8")
    if len(payload) > 100_000:
        return "not copied (over the 100 KB terminal clipboard limit)"

    if os.environ.get("SSH_TTY") or os.environ.get("SSH_CONNECTION"):
        term = os.environ.get("TERM", "")
        if term and term != "dumb":
            sys.stdout.write(_osc52(text))
            sys.stdout.flush()
            return "clipboard request sent to the viewing terminal via OSC 52"
        return "not available (terminal clipboard protocol is not enabled)"

    candidates: list[list[str]] = []
    if shutil.which("termux-clipboard-set"):
        candidates.append(["termux-clipboard-set"])
    elif sys.platform == "darwin":
        candidates.append(["pbcopy"])
    else:
        candidates.extend([["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]])
    for command in candidates:
        if not shutil.which(command[0]):
            continue
        try:
            result = subprocess.run(command, input=payload, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return f"copied using {command[0]}"

    term = os.environ.get("TERM", "")
    if term and term != "dumb":
        sys.stdout.write(_osc52(text))
        sys.stdout.flush()
        return "clipboard request sent to the viewing terminal via OSC 52"
    return "not available; use the saved export file"


def export_notes(review_id: str, note_ids: list[str]) -> None:
    directory, metadata, _source = load_review(review_id)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_id in note_ids:
        note_id = _note_id(raw_id)
        if note_id in seen:
            raise ReviewError(f"note {note_id} was selected more than once")
        seen.add(note_id)
        path = _note_path(directory, note_id)
        if not path.is_file():
            raise ReviewError(f"note {note_id} is not pending; only pending notes can be exported")
        note = _read_json(path)
        if note.get("review_id") != review_id or note.get("note_id") != note_id:
            raise ReviewError(f"invalid note record: {note_id}")
        selected.append(note)

    text = build_export(metadata, selected)
    exports = directory / "exports"
    exports.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_path = exports / f"{stamp}-{uuid.uuid4().hex[:8]}.md"
    output_path.write_text(text, encoding="utf-8")
    output_path.chmod(0o600)
    clipboard_status = copy_to_viewing_terminal(text)
    print("\n--- Selected passage feedback ---")
    print(text, end="")
    print("--- End feedback ---")
    print(f"Saved export: {output_path}")
    print(f"Clipboard: {clipboard_status}")


def change_note_state(review_id: str, note_ids: list[str], action: str) -> None:
    directory, _metadata, _source = load_review(review_id)
    selected = [_note_id(raw_id) for raw_id in note_ids]
    if len(set(selected)) != len(selected):
        raise ReviewError("a note ID was selected more than once")
    for note_id in selected:
        pending = _note_path(directory, note_id)
        archived = _note_path(directory, note_id, archived=True)
        if action == "archive" and not pending.is_file():
            raise ReviewError(f"note {note_id} is not pending")
        if action == "delete" and not pending.is_file() and not archived.is_file():
            raise ReviewError(f"note not found: {note_id}")
    for note_id in selected:
        pending = _note_path(directory, note_id)
        archived = _note_path(directory, note_id, archived=True)
        if action == "archive":
            archived.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            pending.replace(archived)
            print(f"Archived {note_id}.")
        else:
            (pending if pending.is_file() else archived).unlink()
            print(f"Deleted {note_id}.")


def list_reviews() -> None:
    root = library_path() / "reviews"
    if not root.exists():
        print("No passage reviews yet.")
        return
    found = False
    for path in sorted(root.glob("rv-*/review.json"), reverse=True):
        metadata = _read_json(path)
        found = True
        print(
            f"{metadata['review_id']}\t{metadata['title']}\t"
            f"{len(pending_notes(path.parent))} pending\t{metadata['created_at']}"
        )
    if not found:
        print("No passage reviews yet.")


def _read_source_file(path_string: str) -> tuple[str, str]:
    path = Path(path_string).expanduser()
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReviewError(f"could not read UTF-8 source file {path}: {exc}") from exc
    return text, str(path.resolve())


def _read_stdin_snapshot() -> str:
    try:
        return sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewError("stdin snapshot must contain valid UTF-8 text") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="passage-review",
        description="Freeze source text, add pending passage comments, and selectively export attributed feedback.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="snapshot a file or stdin and start a review")
    source = new.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", metavar="PATH", help="snapshot this UTF-8 file")
    source.add_argument("--title", metavar="TITLE", help="title for a UTF-8 snapshot read from stdin")

    reopen = commands.add_parser("open", help="reopen a saved review and add passage comments")
    reopen.add_argument("review_id")

    export = commands.add_parser("export", help="export only the selected pending notes")
    export.add_argument("review_id")
    export.add_argument("--note", action="append", required=True, metavar="NOTE_ID")

    for name in ("archive", "delete"):
        change = commands.add_parser(name, help=f"explicitly {name} selected notes")
        change.add_argument("review_id")
        change.add_argument("--note", action="append", required=True, metavar="NOTE_ID")

    commands.add_parser("list", help="list saved reviews and pending-note counts")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "new":
            if args.file:
                text, reference = _read_source_file(args.file)
                title = Path(args.file).name or args.file
                source_kind = "file"
            else:
                text = _read_stdin_snapshot()
                title = args.title
                reference = "supplied stdin snapshot"
                source_kind = "stdin"
            review_id = create_review(title, source_kind, reference, text)
            print(f"Saved immutable review snapshot {review_id}.", flush=True)
            open_review(review_id)
        elif args.command == "open":
            open_review(args.review_id)
        elif args.command == "export":
            export_notes(args.review_id, args.note)
        elif args.command in ("archive", "delete"):
            change_note_state(args.review_id, args.note, args.command)
        elif args.command == "list":
            list_reviews()
        return 0
    except (ReviewError, OSError) as exc:
        print(f"passage-review: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
