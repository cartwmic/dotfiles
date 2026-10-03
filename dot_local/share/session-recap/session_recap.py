#!/usr/bin/env python3
"""Portable command-backed recap generation and local record storage."""

from __future__ import annotations

import argparse
import hashlib
import math
import signal
import time
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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Any, Callable, Iterator


class RecapError(Exception):
    """An expected user-facing error."""


# Closed, caller-agnostic failure protocol; never persist arbitrary backend stderr.
SAFE_FAILURES = {
    "timed_out": "attempt deadline exceeded",
    "input_limit": "input exceeds transport budget; recursive reduction is disabled",
    "context_limit": "backend context limit exceeded",
    "model_limits": "backend model limits unavailable or unusable",
}


class GenerationFailure(RecapError):
    def __init__(self, message: str, exit_code: int | None = None, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.failure: dict[str, Any] = {"message": message}
        if reason in SAFE_FAILURES:
            self.failure["reason"] = reason
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


def _read_config(directory: Path) -> dict[str, Any]:
    config_path = directory / "config.toml"
    if not config_path.is_file():
        raise RecapError(f"missing configuration: {config_path}")
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        local_path = directory / "config.local.toml"
        if local_path.is_file():
            config = _merge_config(config, tomllib.loads(local_path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RecapError(f"could not read configuration: {exc}") from exc
    return config


def load_config(directory: Path) -> tuple[list[str], str, str]:
    command = _read_config(directory).get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(arg, str) for arg in command)
        or not command[0]
    ):
        raise RecapError(f"configure a non-empty command array in {directory / 'config.local.toml'}")

    for name in ("single-prompt.md", "group-prompt.md"):
        if not (directory / name).is_file():
            raise RecapError(f"missing prompt template: {directory / name}")
    return command, "single-prompt.md", "group-prompt.md"


def auto_publish_enabled(directory: Path) -> bool:
    enabled = _read_config(directory).get("auto_publish", False)
    if not isinstance(enabled, bool):
        raise RecapError("auto_publish must be a boolean")
    if enabled:
        load_config(directory)
    return enabled


def presentation_zone(override: str | None = None) -> tuple[str, ZoneInfo | None]:
    directory = config_dir()
    if override is None:
        config = _read_config(directory) if (directory / 'config.toml').is_file() else {}
        override = config.get('time_zone', 'local')
    if not isinstance(override, str) or not override:
        raise RecapError('time_zone must be local, UTC or an IANA time zone')
    if override == 'local':
        return override, None
    try:
        return override, ZoneInfo(override)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise RecapError(f'invalid time zone: {override}') from exc


def presentation_time(timestamp: str, zone: tuple[str, ZoneInfo | None]) -> str:
    try:
        moment = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if moment.tzinfo is None:
            return timestamp  # Preserve honest readability of legacy values.
        local = moment.astimezone(zone[1]) if zone[1] is not None else moment.astimezone()
        return f"{local.isoformat(timespec='seconds')} {local.tzname()} [{zone[0]}]"
    except ValueError:
        return timestamp


def presentation(record: dict[str, Any], zone: tuple[str, ZoneInfo | None]) -> dict[str, str]:
    return {field: presentation_time(record[field], zone) for field in ('created_at', 'published_at') if isinstance(record.get(field), str)}


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


def _atomic_create_json(path: Path, value: dict[str, Any], before_commit: Callable[[], None] | None = None) -> None:
    """Create a JSON file atomically without replacing an existing record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_json_text(value))
            handle.flush()
            os.fsync(handle.fileno())
        if before_commit is not None:
            before_commit()
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
        try:
            _update_latest(root, record)
        except (OSError, RecapError, KeyError, TypeError, ValueError):
            pass  # Dated records are authoritative; indexing is best effort.


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
        "schema_version": 2,
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
        source_kind = args.source_kind or "manual"
        source_id = args.source_id or record_id
        prompt = _generation_prompt(
            directory,
            single_template,
            {"TEXT": raw_input, "LABEL": label or "(none)"},
        )
    else:
        members = _read_members(root, raw_input)
        source_kind = args.source_kind or "manual"

        source_id = args.source_id or record_id
        coordinator_owned = False
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
        record["metadata"] = args.metadata
        record["annotations"] = {}
        _save_attempt(root, record)
        raise

    record = {
        "schema_version": 2,
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
    record["metadata"] = args.metadata
    record["annotations"] = {}
    _save_attempt(root, record)
    print(record_id)


def _metadata_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecapError(f"metadata must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RecapError("metadata must be a JSON object")
    return value


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    version = record.get("schema_version")
    if version not in (1, 2):
        raise RecapError(f"unsupported record schema: {version}")
    # Legacy records have no generic caller metadata contract. Only expose
    # known narrative/identity fields, never arbitrary historical payloads.
    fields = ("schema_version", "record_id", "source_kind", "source_id", "kind",
              "status", "summary", "created_at", "published_at", "label",
              "member_record_ids", "pane_id", "workspace_id")
    result = {key: record[key] for key in fields if key in record}
    if version == 2:
        result["metadata"] = record.get("metadata", {})
        result["annotations"] = record.get("annotations", {})
        for field in ("request_key", "token", "attempt", "backend_identity", "reduced"):
            if field in record:
                result[field] = record[field]
    if version == 1:
        result["annotations"] = record.get("generic_annotations", {})
    if isinstance(record.get("failure"), dict):
        failure = record["failure"]
        result["failure"] = {"message": "recap generation failed"}
        # Only our closed, supervisor-owned classification crosses the public
        # boundary. Never expose arbitrary stored/backend failure messages.
        if version == 2 and failure.get("reason") in SAFE_FAILURES:
            reason = failure["reason"]
            result["failure"] = {"message": SAFE_FAILURES[reason], "reason": reason}
        if isinstance(failure.get("exit_code"), int):
            result["failure"]["exit_code"] = failure["exit_code"]
    return result


def _run_records(args: argparse.Namespace, root: Path) -> None:
    if args.subcommand == "list":
        records = [_public_record(_read_json(path))
                   for path in sorted((root / "records").glob("*/*.json"))]
        records = [record for record in records if all(
            getattr(args, field) is None or record.get(field) == getattr(args, field)
            for field in ("source_kind", "source_id", "status"))]
        records.sort(key=lambda record: (record.get("created_at", ""), record["record_id"]))
        if args.json:
            print(_json_text({"records": records, "presentation": {"time_zone": args.zone[0], "records": {r["record_id"]: presentation(r, args.zone) for r in records}}}), end="")
        else:
            for record in records:
                print(f"{presentation_time(record.get('created_at', ''), args.zone)} {record['record_id']} {record['status']} {record['source_kind']} {record['source_id']}")
        return
    with _store_lock(root):
        paths = [path for path in (root / "records").glob("*/*.json")
                 if _read_json(path).get("record_id") == args.record_id]
        if len(paths) != 1:
            raise RecapError(f"record not found or ambiguous: {args.record_id}")
        path = paths[0]
        record = _read_json(path)
        if args.subcommand == "annotate":
            namespace = _required_id(args.namespace, "--namespace")
            metadata = _metadata_object(args.metadata_json)
            _public_record(record)  # Reject unknown schemas before writing.
            field = "annotations" if record["schema_version"] == 2 else "generic_annotations"
            annotations = dict(record.get(field, {}))
            annotations[namespace] = metadata
            record[field] = annotations
            _atomic_write_json(path, record)
        result = _public_record(record)
    # Print only after releasing the lock: a caller that stops draining stdout
    # must not hold every other store operation hostage.
    if args.subcommand == 'annotate':
            print(_json_text({"record": result}), end="")
    elif args.json:
        print(_json_text({"record": result, "presentation": {"time_zone": args.zone[0], **presentation(result, args.zone)}}), end="")
    else:
        if args.with_metadata:
            print(f"{result['record_id']} {result['status']} {presentation_time(result.get('published_at', result.get('created_at', '')), args.zone)}")
        print(result.get('summary', ''))


def _required_id(value: str, argument: str) -> str:
    if not value.strip():
        raise RecapError(f"{argument} must not be blank")
    return value


def _request_path(root: Path, key: str) -> Path:
    return root / "requests" / (hashlib.sha256(key.encode()).hexdigest() + ".json")


def _current_request(root: Path, key: str) -> dict[str, Any]:
    path = _request_path(root, key)
    return _read_json(path) if path.exists() else {"request_key": key, "token": None, "status": "absent"}


def _request_control(args: argparse.Namespace, root: Path) -> None:
    key = _required_id(args.key, "--key")
    with _store_lock(root):
        state = _current_request(root, key)
        if args.subcommand == "reserve":
            state = {"request_key": key, "token": uuid.uuid4().hex, "status": "reserved"}
            _atomic_write_json(_request_path(root, key), state)
        elif args.subcommand == "cancel":
            state = {"request_key": key, "token": None, "status": "canceled"}
            _atomic_write_json(_request_path(root, key), state)
    print(json.dumps(state))


class RequestStopped(RecapError):
    pass


def _fence(root: Path, request: dict[str, Any], deadline: float) -> None:
    state = _current_request(root, request["request_key"])
    if state["token"] != request["token"] or state["status"] not in ("reserved", "running"):
        raise RequestStopped("canceled" if state["status"] == "canceled" else "superseded")
    if time.monotonic() >= deadline:
        raise GenerationFailure("attempt deadline exceeded", reason="timed_out")


def _emit(event: dict[str, Any]) -> None:
    # The caller can detach or close its pipe without changing persistence.
    try:
        sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        # Avoid Python's exit-time flush of the broken pipe as well.
        sys.stdout = open(os.devnull, "w")


def _load_request(path: Path) -> dict[str, Any]:
    try:
        request = _read_json(path)
    finally:
        path.unlink(missing_ok=True)
    if request.get("schema_version") != 1:
        raise RecapError("request schema_version must be 1")
    for name in ("request_key", "token", "source_kind", "source_id"):
        if not isinstance(request.get(name), str) or not request[name].strip():
            raise RecapError(f"request {name} must be a nonblank string")
    if request.get("kind") not in ("single", "group"):
        raise RecapError("request kind must be single or group")
    for name in ("material", "instructions"):
        if not isinstance(request.get(name), str):
            raise RecapError(f"request {name} must be a string")
    for name in ("background", "label"):
        if name in request and not isinstance(request[name], str):
            raise RecapError(f"request {name} must be a string")
    command = request.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
        raise RecapError("request command must be a nonempty argv array")
    preflight = request.get("preflight")
    if "preflight" in request:
        if not isinstance(preflight, dict) or set(preflight) != {"command"}:
            raise RecapError("request preflight accepts only command")
        argv = preflight["command"]
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
            raise RecapError("request preflight command must be a nonempty argv array")
    timeout = request.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise RecapError("request timeout_seconds must be finite and positive")
    budget = request.get("input_budget_bytes")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        raise RecapError("request input_budget_bytes must be positive")
    if not isinstance(request.get("recursive"), bool):
        raise RecapError("request recursive must be boolean")
    for name in ("metadata", "backend_identity"):
        if not isinstance(request.get(name, {}), dict):
            raise RecapError(f"request {name} must be an object")
    identity = request.get("backend_identity", {})
    if set(identity) - {"provider", "model"} or not all(isinstance(x, str) for x in identity.values()):
        raise RecapError("backend_identity accepts only safe provider/model strings")
    return request


def _supervised_call(root: Path, request: dict[str, Any], prompt: str, deadline: float) -> str:
    _fence(root, request, deadline)
    try:
        process = subprocess.Popen(request["command"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        raise GenerationFailure("could not start backend") from exc
    try:
        payload: bytes | None = prompt.encode("utf-8")
        while True:
            _fence(root, request, deadline)
            try:
                output, _ = process.communicate(payload, timeout=min(0.05, max(0.001, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                payload = None
        _fence(root, request, deadline)
        if process.returncode != 0:
            reason = next((code for code in ("context_limit", "model_limits")
                           if output == f"SESSION_RECAP_FAILURE:{code}\n".encode()), None)
            raise GenerationFailure(SAFE_FAILURES.get(reason, "backend exited nonzero"), process.returncode, reason=reason)
        try:
            text = output.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise GenerationFailure("backend returned non-UTF-8 stdout") from exc
        if not text:
            raise GenerationFailure("backend returned blank stdout")
        return text
    finally:
        # This group belongs to this invocation, never a persisted PID.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def _chunks(text: str, budget: int) -> list[str]:
    result: list[str] = []
    chunk = ""
    size = 0
    for character in text:
        width = len(character.encode("utf-8"))
        if width > budget:
            raise GenerationFailure("input budget cannot hold a UTF-8 character")
        if size + width > budget:
            # Prefer semantic whitespace boundaries without discarding a byte.
            boundary = max(chunk.rfind(" "), chunk.rfind("\n"), chunk.rfind("\t")) + 1
            if boundary:
                result.append(chunk[:boundary])
                chunk = chunk[boundary:]
                size = len(chunk.encode("utf-8"))
            else:
                result.append(chunk)
                chunk, size = "", 0
        chunk += character
        size += width
    if chunk:
        result.append(chunk)
    return result


def _preflight_request(root: Path, request: dict[str, Any], deadline: float) -> dict[str, Any]:
    """Opaque caller policy, supervised anew inside each complete attempt."""
    if "preflight" not in request:
        return request
    output = _supervised_call(root, dict(request, command=request["preflight"]["command"]),
                              request["material"], deadline)
    try:
        result = json.loads(output)
    except (ValueError, RecursionError) as exc:
        raise GenerationFailure("invalid preflight output") from exc
    if not isinstance(result, dict) or set(result) - {"input_budget_bytes", "command"}:
        raise GenerationFailure("invalid preflight output")
    budget = result.get("input_budget_bytes")
    if isinstance(budget, bool) or not isinstance(budget, int) or not 0 < budget <= request["input_budget_bytes"]:
        raise GenerationFailure("invalid preflight input budget")
    command = result.get("command", request["command"])
    if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
        raise GenerationFailure("invalid preflight command")
    _fence(root, request, deadline)
    return dict(request, input_budget_bytes=budget, command=command)


def _generate_request(root: Path, request: dict[str, Any], deadline: float) -> tuple[str, bool]:
    header = request["instructions"] + "\n\n"
    material = request["material"]
    if request.get("background"):
        material = "Background only (not new activity):\n" + request["background"] + "\n\nNew material:\n" + material
    budget = request["input_budget_bytes"]
    room = budget - len(header.encode("utf-8"))
    if room <= 0:
        raise GenerationFailure("instructions exceed input budget", reason="input_limit")
    reduced = len(material.encode("utf-8")) > room
    if reduced and not request["recursive"]:
        raise GenerationFailure(SAFE_FAILURES["input_limit"], reason="input_limit")
    reduction_header = ("Reduce this complete chunk, preserving meaningful facts, identifiers, outcomes, "
                        "uncertainties and unresolved work. Do not omit unresolved material.\n\n")
    chunk_room = budget - len(reduction_header.encode("utf-8"))
    rounds = 0
    while len(material.encode("utf-8")) > room:
        if chunk_room <= 0 or rounds >= 32:
            raise GenerationFailure("recursive reduction cannot fit input budget")
        before = len(material.encode("utf-8"))
        summaries = [_supervised_call(root, request, reduction_header + chunk, deadline)
                     for chunk in _chunks(material, chunk_room)]
        material = "\n\n".join(summaries)
        if len(material.encode("utf-8")) >= before:
            raise GenerationFailure("recursive reduction did not shrink; no material was dropped")
        rounds += 1
    summary = _supervised_call(root, request, header + material, deadline)
    if reduced:
        summary = "[Input was recursively chunked and reduced.]\n\n" + summary
    return summary, reduced


def _run_request(args: argparse.Namespace, root: Path) -> None:
    request = _load_request(Path(args.request_file))
    base = {"request_key": request["request_key"], "token": request["token"]}
    try:
        with _store_lock(root):
            _fence(root, request, float("inf"))
            if _current_request(root, request["request_key"])["status"] != "reserved":
                raise RequestStopped("superseded")
            state = dict(base, status="running")
            _atomic_write_json(_request_path(root, request["request_key"]), state)
    except RequestStopped as exc:
        _emit(dict(base, event="terminal", status=str(exc)))
        return
    _emit(dict(base, event="accepted", status="running"))
    generated_text = None
    for attempt in (1, 2):
        deadline = time.monotonic() + request["timeout_seconds"]
        record = {"schema_version": 2, "record_id": _new_record_id(), "created_at": utc_now(),
                  "source_kind": request["source_kind"], "source_id": request["source_id"],
                  "kind": request["kind"], "metadata": request.get("metadata", {}),
                  "request_key": request["request_key"], "token": request["token"],
                  "attempt": attempt, "backend_identity": request.get("backend_identity", {})}
        if "label" in request:
            record["label"] = request["label"]
        summary = None
        stopped = None
        try:
            attempt_request = _preflight_request(root, request, deadline)
            if "preflight" in request:
                _emit(dict(base, event="preflight", status="running", attempt=attempt,
                           input_budget_bytes=attempt_request["input_budget_bytes"]))
            summary, reduced = _generate_request(root, attempt_request, deadline)
            generated_text = summary
            record.update(status="published", summary=summary, published_at=utc_now(), reduced=reduced)
            with _store_lock(root):
                _fence(root, request, deadline)
                _atomic_create_json(_record_path(root, record), record,
                                    before_commit=lambda: _fence(root, request, deadline))
                # From here the authoritative dated record is success.
                try:
                    _update_latest(root, record)
                    _atomic_write_json(_request_path(root, request["request_key"]),
                                       dict(base, status="published", record_id=record["record_id"]))
                except (OSError, RecapError):
                    pass
            _emit(dict(base, event="terminal", status="published", record_id=record["record_id"], attempt=attempt))
            return
        except RequestStopped as exc:
            stopped = str(exc)
            record.update(status=stopped, failure={"message": stopped})
            record.pop("summary", None)
            record.pop("published_at", None)
        except (GenerationFailure, OSError, RecapError) as exc:
            message = str(exc) if isinstance(exc, GenerationFailure) else "storage operation failed"
            record.update(status="generated-unsaved" if summary is not None else "failed",
                          failure=exc.failure if isinstance(exc, GenerationFailure) else {"message": message})
            record.pop("summary", None)
            record.pop("published_at", None)
        # Failed attempts are honest history, not a successful coverage baseline.
        attempt_saved = False
        try:
            with _store_lock(root):
                _atomic_create_json(_record_path(root, record), record)
                attempt_saved = True
        except (OSError, RecapError):
            pass
        if stopped:
            event = dict(base, event="terminal", status=stopped, attempt=attempt)
            if attempt_saved:
                event["record_id"] = record["record_id"]
            _emit(event)
            return
        if attempt == 2:
            status = "generated-unsaved" if generated_text is not None else record["status"]
            try:
                with _store_lock(root):
                    _fence(root, request, float("inf"))
                    _atomic_write_json(_request_path(root, request["request_key"]), dict(base, status=status))
            except RequestStopped as exc:
                _emit(dict(base, event="terminal", status=str(exc), attempt=attempt))
                return
            except (OSError, RecapError):
                pass
            event = dict(base, event="terminal", status=status, attempt=attempt, failure=record["failure"])
            if attempt_saved:
                event["record_id"] = record["record_id"]
            if generated_text is not None:
                event.update(text=generated_text, warning="Generated recap was not saved; no coverage was advanced.")
            _emit(event)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="session-recap", description="Generate and store dated session recaps.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    for action in ("reserve", "current", "cancel"):
        control = subparsers.add_parser(action, help="inspect or replace a request fence")
        control.add_argument("--key", required=True)
        control.add_argument("--json", action="store_true", required=True)
    run = subparsers.add_parser("run", help="supervise a captured generic request")
    run.add_argument("--request-file", required=True)
    run.add_argument("--json-lines", action="store_true", required=True)

    config = subparsers.add_parser("config", help="inspect automatic recap policy")
    config_subparsers = config.add_subparsers(dest="config_action", required=True)
    config_subparsers.add_parser("auto-publish", help="print enabled or disabled")

    create = subparsers.add_parser("create", help="generate and publish a recap from stdin")
    create.add_argument("--kind", required=True, choices=("single", "group"))
    create.add_argument("--label")
    create.add_argument("--source-kind")
    create.add_argument("--metadata-json", default="{}")
    create.add_argument("--source-id")

    listing = subparsers.add_parser("list", help="list authoritative dated records")
    listing.add_argument("--json", action="store_true")
    for field in ("source-kind", "source-id", "status"):
        listing.add_argument("--" + field)
    reading = subparsers.add_parser("read", help="read a safe structured record")
    reading.add_argument("record_id")
    reading.add_argument("--json", action="store_true")
    reading.add_argument("--with-metadata", action="store_true", help="show timestamp and identity before the narrative")
    for command in (create, listing, reading):
        command.add_argument("--time-zone", help="local (default), UTC or IANA name; overrides time_zone config")
    annotation = subparsers.add_parser("annotate", help="replace one opaque annotation namespace")
    annotation.add_argument("record_id")
    annotation.add_argument("--namespace", required=True)
    annotation.add_argument("--metadata-json", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = data_dir()
    directory = config_dir()
    try:
        if args.subcommand in ('create', 'list', 'read'):
            args.zone = presentation_zone(args.time_zone)  # Before backend calls or store mutation.
        if args.subcommand in ("reserve", "current", "cancel"):
            _request_control(args, root)
        elif args.subcommand == "run":
            _run_request(args, root)
        elif args.subcommand == "config":
            print("enabled" if auto_publish_enabled(directory) else "disabled")
        elif args.subcommand in ("list", "read", "annotate"):
            _run_records(args, root)
        elif args.subcommand == "create":
            if args.source_id is not None:
                args.source_id = _required_id(args.source_id, "--source-id")
            if args.source_kind is not None:
                args.source_kind = _required_id(args.source_kind, "--source-kind")
            args.metadata = _metadata_object(args.metadata_json)
            _run_create(args, directory, root)
        return 0
    except RecapError as exc:
        print(f"session-recap: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"session-recap: filesystem error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
