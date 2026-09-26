#!/usr/bin/env python3
"""Portable command-backed recap generation and local record storage."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote


class RecapError(Exception):
    """An expected user-facing error."""


class GenerationFailure(RecapError):
    def __init__(self, message: str, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.failure: dict[str, Any] = {"message": message}
        if exit_code is not None:
            self.failure["exit_code"] = exit_code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def config_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home).expanduser() / "session-recap"


def data_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home).expanduser() / "session-recap"


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(directory: Path) -> tuple[list[str], str, str]:
    config_path = directory / "config.toml"
    if not config_path.is_file():
        raise RecapError(f"missing configuration: {config_path}")
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        local_path = directory / "config.local.toml"
        if local_path.is_file():
            local = tomllib.loads(local_path.read_text(encoding="utf-8"))
            config = _merge_config(config, local)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RecapError(f"could not read configuration: {exc}") from exc

    command = config.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(arg, str) for arg in command)
        or not command[0]
    ):
        raise RecapError(f"{config_path} must define a non-empty command string array")

    for name in ("single-prompt.md", "group-prompt.md"):
        if not (directory / name).is_file():
            raise RecapError(f"missing prompt template: {directory / name}")
    return command, "single-prompt.md", "group-prompt.md"


def _render_template(template: str, values: dict[str, str]) -> str:
    token_re = re.compile(r"\[\[(TEXT|LABEL|MEMBERS)\]\]")
    return token_re.sub(lambda match: values.get(match.group(1), match.group(0)), template)


def _run_command(command: list[str], prompt: str) -> str:
    try:
        completed = subprocess.run(
            command,
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise GenerationFailure(f"could not start configured command: {exc.strerror or exc}") from exc

    if completed.returncode != 0:
        raise GenerationFailure(
            f"configured command exited with status {completed.returncode}",
            completed.returncode,
        )
    try:
        summary = completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise GenerationFailure("configured command returned non-UTF-8 stdout") from exc
    if not summary:
        raise GenerationFailure("configured command returned blank stdout")
    return summary


def read_stdin_text() -> str:
    try:
        return sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecapError("stdin must contain valid UTF-8") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecapError(f"could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RecapError(f"expected a JSON object in {path}")
    return value


def _json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_json_text(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_create_json(path: Path, value: dict[str, Any]) -> None:
    """Create a JSON file atomically without replacing an existing record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_json_text(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    else:
        os.unlink(temp_name)


@contextmanager
def _store_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _latest_path(root: Path) -> Path:
    return root / "latest.json"


def _load_latest(root: Path) -> dict[str, Any]:
    path = _latest_path(root)
    if not path.exists():
        return {"schema_version": 1, "sources": []}
    latest = _read_json(path)
    if latest.get("schema_version") != 1 or not isinstance(latest.get("sources"), list):
        raise RecapError(f"invalid latest index: {path}")
    return latest


def _update_latest(root: Path, record: dict[str, Any]) -> None:
    latest = _load_latest(root)
    source_kind = record["source_kind"]
    source_id = record["source_id"]
    record_id = record["record_id"]
    entry = next(
        (
            item
            for item in latest["sources"]
            if isinstance(item, dict)
            and item.get("source_kind") == source_kind
            and item.get("source_id") == source_id
        ),
        None,
    )
    if entry is None:
        entry = {
            "source_kind": source_kind,
            "source_id": source_id,
            "latest_success_id": None,
            "last_attempt_id": record_id,
        }
        latest["sources"].append(entry)
    else:
        entry["last_attempt_id"] = record_id
    if record["status"] == "published":
        entry["latest_success_id"] = record_id
    latest["sources"].sort(key=lambda item: (item["source_kind"], item["source_id"]))
    _atomic_write_json(_latest_path(root), latest)


def _record_path(root: Path, record: dict[str, Any]) -> Path:
    day = record["created_at"][:10]
    return root / "records" / day / f"{record['record_id']}.json"


def _save_attempt(root: Path, record: dict[str, Any]) -> None:
    with _store_lock(root):
        _atomic_create_json(_record_path(root, record), record)
        _update_latest(root, record)


def _read_members(root: Path, stdin_text: str) -> list[dict[str, str | None]]:
    try:
        payload = json.loads(stdin_text)
    except json.JSONDecodeError as exc:
        raise RecapError(f"group input must be valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("members"), list):
        raise RecapError("group input must be a JSON object with a members array")
    if not payload["members"]:
        raise RecapError("group input must contain at least one member")

    members: list[dict[str, str | None]] = []
    for index, member in enumerate(payload["members"], start=1):
        if not isinstance(member, dict) or not isinstance(member.get("text"), str):
            raise RecapError(f"group member {index} must be an object with a text string")
        label = member.get("label")
        record_id = member.get("record_id")
        if label is not None and not isinstance(label, str):
            raise RecapError(f"group member {index} label must be a string")
        if record_id is not None and (not isinstance(record_id, str) or not record_id.strip()):
            raise RecapError(f"group member {index} record_id must be a non-empty string")
        members.append({"text": member["text"], "label": label, "record_id": record_id})
    return members


def _find_record(root: Path, record_id: str) -> dict[str, Any] | None:
    records_dir = root / "records"
    if not records_dir.exists():
        return None
    for path in records_dir.glob("*/*.json"):
        value = _read_json(path)
        if value.get("record_id") == record_id:
            return value
    return None


def _validate_group_members(
    root: Path, members: list[dict[str, str | None]], coordinator_owned: bool
) -> list[str]:
    record_ids: list[str] = []
    for index, member in enumerate(members, start=1):
        record_id = member["record_id"]
        if coordinator_owned and record_id is None:
            raise RecapError(f"coordinator-owned group member {index} requires record_id")
        if record_id is None:
            continue
        if coordinator_owned:
            record = _find_record(root, record_id)
            if record is None or record.get("status") != "published":
                raise RecapError(f"group member {index} record_id is not a published recap: {record_id}")
        record_ids.append(record_id)
    return record_ids


def _group_member_text(members: list[dict[str, str | None]]) -> str:
    blocks = []
    for index, member in enumerate(members, start=1):
        heading = f"Member {index}"
        if member["label"]:
            heading += f" (label: {member['label']})"
        blocks.append(f"{heading}:\n{member['text']}")
    return "\n\n".join(blocks)


def _generation_prompt(directory: Path, template_name: str, values: dict[str, str]) -> str:
    try:
        template = (directory / template_name).read_text(encoding="utf-8")
    except OSError as exc:
        raise RecapError(f"could not read prompt template {template_name}: {exc}") from exc
    return _render_template(template, values)


def _failure_record(
    *,
    record_id: str,
    source_kind: str,
    source_id: str,
    kind: str,
    created_at: str,
    failure: dict[str, Any],
    label: str | None = None,
    pane_id: str | None = None,
    member_record_ids: list[str] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 1,
        "record_id": record_id,
        "source_kind": source_kind,
        "source_id": source_id,
        "kind": kind,
        "status": "failed",
        "created_at": created_at,
        "failure": failure,
    }
    if label is not None:
        record["label"] = label
    if pane_id is not None:
        record["pane_id"] = pane_id
    if member_record_ids is not None:
        record["member_record_ids"] = member_record_ids
    return record


def _new_record_id() -> str:
    return uuid.uuid4().hex


def _run_create(args: argparse.Namespace, directory: Path, root: Path) -> None:
    raw_input = read_stdin_text()
    command, single_template, group_template = load_config(directory)
    record_id = _new_record_id()
    created_at = utc_now()
    label = args.label
    member_record_ids: list[str] | None = None

    if args.kind == "single":
        if args.source_kind not in (None, "manual"):
            raise RecapError("single create supports only the manual source kind")
        source_kind = "manual"
        source_id = args.source_id or record_id
        prompt = _generation_prompt(
            directory,
            single_template,
            {"TEXT": raw_input, "LABEL": label or "(none)"},
        )
    else:
        members = _read_members(root, raw_input)
        source_kind = args.source_kind or "manual"
        if source_kind in ("workspace", "herdr-session") and not args.source_id:
            raise RecapError(f"--source-id is required for source kind {source_kind}")
        source_id = args.source_id or record_id
        if source_kind == "herdr-session" and source_id != "active":
            raise RecapError("the host-local Herdr session source ID must be 'active'")
        coordinator_owned = source_kind in ("workspace", "herdr-session")
        member_record_ids = _validate_group_members(root, members, coordinator_owned)
        prompt = _generation_prompt(
            directory,
            group_template,
            {"MEMBERS": _group_member_text(members), "LABEL": label or "(none)"},
        )

    try:
        summary = _run_command(command, prompt)
    except GenerationFailure as exc:
        record = _failure_record(
            record_id=record_id,
            source_kind=source_kind,
            source_id=source_id,
            kind=args.kind,
            created_at=created_at,
            failure=exc.failure,
            label=label,
            member_record_ids=member_record_ids,
        )
        _save_attempt(root, record)
        raise

    record = {
        "schema_version": 1,
        "record_id": record_id,
        "source_kind": source_kind,
        "source_id": source_id,
        "kind": args.kind,
        "status": "published",
        "summary": summary,
        "created_at": created_at,
        "published_at": utc_now(),
    }
    if label is not None:
        record["label"] = label
    if member_record_ids is not None:
        record["member_record_ids"] = member_record_ids
    _save_attempt(root, record)
    print(record_id)


def _run_prepare(args: argparse.Namespace, directory: Path, root: Path) -> None:
    raw_input = read_stdin_text()
    command, single_template, _ = load_config(directory)
    record_id = _new_record_id()
    created_at = utc_now()
    prompt = _generation_prompt(directory, single_template, {"TEXT": raw_input, "LABEL": "(none)"})
    try:
        summary = _run_command(command, prompt)
    except GenerationFailure as exc:
        _save_attempt(
            root,
            _failure_record(
                record_id=record_id,
                source_kind="pi-session",
                source_id=args.source_id,
                kind="single",
                created_at=created_at,
                failure=exc.failure,
                pane_id=args.pane_id,
            ),
        )
        raise

    prepared: dict[str, Any] = {
        "schema_version": 1,
        "record_id": record_id,
        "source_kind": "pi-session",
        "source_id": args.source_id,
        "kind": "single",
        "summary": summary,
        "created_at": created_at,
    }
    if args.pane_id is not None:
        prepared["pane_id"] = args.pane_id
    with _store_lock(root):
        _atomic_create_json(root / "prepared" / f"{record_id}.json", prepared)
    print(record_id)


def _run_publish(args: argparse.Namespace, root: Path) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", args.prepared_id):
        raise RecapError("prepared ID must be a session-recap record ID")
    prepared_path = root / "prepared" / f"{args.prepared_id}.json"
    with _store_lock(root):
        if not prepared_path.is_file():
            raise RecapError(f"prepared recap not found: {args.prepared_id}")
        prepared = _read_json(prepared_path)
        if prepared.get("record_id") != args.prepared_id or prepared.get("source_kind") != "pi-session":
            raise RecapError(f"invalid prepared recap: {args.prepared_id}")

        if prepared.get("published_record_id"):
            published_id = prepared["published_record_id"]
            published = _find_record(root, published_id)
            if published is None or published.get("status") != "published":
                raise RecapError(f"prepared recap has an invalid publication: {args.prepared_id}")
            if args.workspace_id is not None and published.get("workspace_id") != args.workspace_id:
                raise RecapError("prepared recap was already published with different workspace attribution")
            print(published_id)
            return

        record = {
            "schema_version": 1,
            "record_id": prepared["record_id"],
            "source_kind": prepared["source_kind"],
            "source_id": prepared["source_id"],
            "kind": prepared["kind"],
            "status": "published",
            "summary": prepared["summary"],
            "created_at": prepared["created_at"],
            "published_at": utc_now(),
        }
        if "pane_id" in prepared:
            record["pane_id"] = prepared["pane_id"]
        if args.workspace_id is not None:
            record["workspace_id"] = args.workspace_id

        path = _record_path(root, record)
        if path.exists():
            existing = _read_json(path)
            if existing.get("record_id") != record["record_id"] or existing.get("status") != "published":
                raise RecapError(f"record already exists and cannot be published: {record['record_id']}")
            record = existing
        else:
            _atomic_create_json(path, record)
        _update_latest(root, record)
        prepared["published_record_id"] = record["record_id"]
        prepared["published_at"] = record["published_at"]
        _atomic_write_json(prepared_path, prepared)
    print(record["record_id"])


def _prompt_path(root: Path, session_id: str) -> Path:
    return root / "prompts" / f"{quote(session_id, safe='')}.json"


def _run_prompt_set(args: argparse.Namespace, root: Path) -> None:
    text = read_stdin_text()
    if not text.strip():
        raise RecapError("prompt text must not be blank")
    prompt: dict[str, Any] = {
        "schema_version": 1,
        "session_id": args.session_id,
        "text": text,
        "captured_at": utc_now(),
        "working": True,
    }
    if args.pane_id is not None:
        prompt["pane_id"] = args.pane_id
    with _store_lock(root):
        _atomic_write_json(_prompt_path(root, args.session_id), prompt)


def _run_prompt_settle(args: argparse.Namespace, root: Path) -> None:
    path = _prompt_path(root, args.session_id)
    with _store_lock(root):
        if not path.is_file():
            raise RecapError(f"no current prompt found for session: {args.session_id}")
        prompt = _read_json(path)
        if prompt.get("schema_version") != 1 or prompt.get("session_id") != args.session_id:
            raise RecapError(f"invalid current prompt for session: {args.session_id}")
        prompt["captured_at"] = utc_now()
        prompt["working"] = False
        _atomic_write_json(path, prompt)


def _required_id(value: str, argument: str) -> str:
    if not value.strip():
        raise RecapError(f"{argument} must not be blank")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="session-recap", description="Generate and store dated session recaps.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    create = subparsers.add_parser("create", help="generate and publish a recap from stdin")
    create.add_argument("--kind", required=True, choices=("single", "group"))
    create.add_argument("--label")
    create.add_argument("--source-kind", choices=("manual", "workspace", "herdr-session"))
    create.add_argument("--source-id")

    prepare = subparsers.add_parser("prepare", help="generate a Pi recap without publishing it")
    prepare.add_argument("--source-id", required=True, help="Pi session ID")
    prepare.add_argument("--pane-id", help="optional native Herdr pane ID")

    publish = subparsers.add_parser("publish", help="publish a prepared Pi recap")
    publish.add_argument("--prepared-id", required=True)
    publish.add_argument("--workspace-id", help="optional native Herdr workspace ID")

    prompt = subparsers.add_parser("prompt", help="store a Pi session's current prompt")
    prompt_subparsers = prompt.add_subparsers(dest="prompt_action", required=True)
    prompt_set = prompt_subparsers.add_parser("set", help="store a real user prompt as working")
    prompt_set.add_argument("--session-id", required=True)
    prompt_set.add_argument("--pane-id", help="optional native Herdr pane ID")
    prompt_settle = prompt_subparsers.add_parser("settle", help="mark the stored prompt as settled")
    prompt_settle.add_argument("--session-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = data_dir()
    directory = config_dir()
    try:
        if args.subcommand == "create":
            if args.source_id is not None:
                args.source_id = _required_id(args.source_id, "--source-id")
            if args.kind == "single" and args.source_kind not in (None, "manual"):
                raise RecapError("single create supports only the manual source kind")
            if args.kind == "group" and args.source_kind in ("workspace", "herdr-session") and not args.source_id:
                raise RecapError(f"--source-id is required for source kind {args.source_kind}")
            _run_create(args, directory, root)
        elif args.subcommand == "prepare":
            args.source_id = _required_id(args.source_id, "--source-id")
            if args.pane_id is not None:
                args.pane_id = _required_id(args.pane_id, "--pane-id")
            _run_prepare(args, directory, root)
        elif args.subcommand == "publish":
            if args.workspace_id is not None:
                args.workspace_id = _required_id(args.workspace_id, "--workspace-id")
            _run_publish(args, root)
        elif args.subcommand == "prompt" and args.prompt_action == "set":
            args.session_id = _required_id(args.session_id, "--session-id")
            if args.pane_id is not None:
                args.pane_id = _required_id(args.pane_id, "--pane-id")
            _run_prompt_set(args, root)
        elif args.subcommand == "prompt" and args.prompt_action == "settle":
            args.session_id = _required_id(args.session_id, "--session-id")
            _run_prompt_settle(args, root)
        return 0
    except RecapError as exc:
        print(f"session-recap: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"session-recap: filesystem error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
