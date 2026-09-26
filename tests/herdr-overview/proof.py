#!/usr/bin/env python3
"""Outside-in proof driver for the Herdr overview and its portable tools.

The desktop driver uses only isolated temporary homes and a separately recorded
Herdr socket. It never targets the owner's default Herdr socket. Run scenarios
one at a time and retain each JSON result by command_id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pty
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_COMMANDS = {
    "recap": "proof-recap-cli",
    "review": "proof-review-lifecycle",
    "herdr-prepare": "proof-herdr-isolated-start",
    "herdr-wide": "proof-herdr-wide-journey",
    "pi-grouped": "proof-pi-grouped-journey",
    "termux-ssh": "proof-herdr-termux-ssh-journey",
    "herdr-cleanup": "proof-herdr-isolated-cleanup",
    "chezmoi-dry-run": "proof-chezmoi-target-dry-run",
}
RUN_ID_RE = __import__("re").compile(r"^[0-9a-f]{16}$")
REVIEW_ID_RE = __import__("re").compile(r"^rv-[0-9a-f]{12}$")
NOTE_ID_RE = __import__("re").compile(r"^n-[0-9a-f]{8}$")
SUCCESS_SUMMARY = "Recent work is complete. Present state: ready for the next step."
PROOF_MARKER = ".herdr-overview-proof.json"


class ProofBlocked(Exception):
    """The requested path cannot be driven in the current environment."""


class ProofFailure(Exception):
    """An observed proof assertion failed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def json_dump(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ProofFailure(f"expected a JSON object at {path}")
    return value


def bounded(text: str, limit: int = 3000) -> str:
    text = text.strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def result(command_id: str, scenario: str, status: str, **details: Any) -> int:
    record = {
        "command_id": command_id,
        "scenario": scenario,
        "status": status,
        "finished_at": utc_now(),
        **details,
    }
    print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[status]


def run_process(
    argv: list[str],
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: float = 30,
    check: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProofBlocked(f"could not complete {' '.join(argv[:3])}: {exc}") from exc
    if check and completed.returncode != 0:
        raise ProofFailure(
            f"command exited {completed.returncode}: {' '.join(argv)}\n"
            f"stdout: {bounded(completed.stdout, 1500)}\nstderr: {bounded(completed.stderr, 1500)}"
        )
    return completed


def write_exec(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o700)


def copy_recap_install(root: Path) -> tuple[Path, Path, Path]:
    """Make a private T1 install/config/data tree; never use the live home."""
    config_home = root / "config"
    data_home = root / "data"
    home = root / "home"
    config_dir = config_home / "session-recap"
    data_dir = data_home / "session-recap"
    bin_dir = home / ".local" / "bin"
    share_dir = home / ".local" / "share" / "session-recap"
    for path in (config_dir, data_dir, bin_dir, share_dir, root / "tmp"):
        path.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "dot_local/share/session-recap/session_recap.py", share_dir / "session_recap.py")
    wrapper = ROOT / "dot_local/bin/executable_session-recap"
    shutil.copy2(wrapper, bin_dir / "session-recap")
    (bin_dir / "session-recap").chmod(0o700)
    for name in ("single-prompt.md.tmpl", "group-prompt.md.tmpl"):
        shutil.copy2(ROOT / "dot_config/session-recap" / name, config_dir / name)
    return home, config_dir, data_dir


def recap_env(root: Path, *, home: Path, config_dir: Path, data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(config_dir.parent),
        "XDG_DATA_HOME": str(data_dir.parent),
        "TMPDIR": str(root / "tmp"),
        "PATH": os.pathsep.join([str(home / ".local/bin"), env.get("PATH", "/usr/bin:/bin")]),
        "PASSAGE_REVIEW_CLIPBOARD": "off",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def cli_recap(home: Path, env: dict[str, str], *args: str, stdin: str = "", check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_process([str(home / ".local/bin/session-recap"), *args], env=env, input_text=stdin, check=check)


def find_record(data_dir: Path, record_id: str) -> tuple[Path, dict[str, Any]]:
    for path in sorted((data_dir / "records").glob("*/*.json")):
        record = read_json(path)
        if record.get("record_id") == record_id:
            return path, record
    raise ProofFailure(f"dated recap record not found: {record_id}")


def latest_entry(data_dir: Path, kind: str, source_id: str) -> dict[str, Any] | None:
    index_path = data_dir / "latest.json"
    if not index_path.exists():
        return None
    index = read_json(index_path)
    return next((entry for entry in index.get("sources", [])
                 if entry.get("source_kind") == kind and entry.get("source_id") == source_id), None)


def scenario_recap() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="herdr-proof-recap-") as temp:
        root = Path(temp)
        home, config_dir, data_dir = copy_recap_install(root)
        env = recap_env(root, home=home, config_dir=config_dir, data_dir=data_dir)
        fake = ROOT / "tests/herdr-overview/fake_recap_backend.py"
        mode_file = root / "backend-mode"
        capture_log = root / "backend-captures.jsonl"
        selected_log = root / "selected-executable.jsonl"
        env.update({
            "FAKE_RECAP_MODE_FILE": str(mode_file),
            "FAKE_RECAP_CAPTURE_LOG": str(capture_log),
            "PROOF_SELECTED_EXECUTABLE": str(selected_log),
        })
        mode_file.write_text("success\n", encoding="utf-8")
        base_backend = root / "base-backend.py"
        local_backend = root / "local-backend.py"
        for path, role in ((base_backend, "base"), (local_backend, "config.local")):
            write_exec(path, "#!/usr/bin/env python3\n"
                       "import json, os, sys\n"
                       "from pathlib import Path\n"
                       f"Path(os.environ['PROOF_SELECTED_EXECUTABLE']).open('a', encoding='utf-8').write(json.dumps({{'role': {role!r}, 'argv': sys.argv[1:]}}) + '\\n')\n"
                       f"os.execv(sys.executable, [sys.executable, {str(fake)!r}, 'success'])\n")
        (config_dir / "config.toml").write_text(
            f"command = [{json.dumps(sys.executable)}, {json.dumps(str(base_backend))}, \"base-argv\"]\n",
            encoding="utf-8",
        )
        single_template = "SINGLE_TEMPLATE_EDIT [[LABEL]]\nEXACT_INPUT_BEGIN\n[[TEXT]]EXACT_INPUT_END\n"
        group_template = "GROUP_TEMPLATE_EDIT [[LABEL]]\nMEMBER_INPUT_BEGIN\n[[MEMBERS]]\nMEMBER_INPUT_END\n"
        (config_dir / "single-prompt.md").write_text(single_template, encoding="utf-8")
        (config_dir / "group-prompt.md").write_text(group_template, encoding="utf-8")
        (config_dir / "config.local.toml").write_text(
            f"command = [{json.dumps(sys.executable)}, {json.dumps(str(local_backend))}, \"host-argv-override\"]\n",
            encoding="utf-8",
        )

        single_input = "Fix the parser and leave the migration untouched.\n"
        single_id = cli_recap(home, env, "create", "--kind", "single", "--source-id", "proof-single", stdin=single_input).stdout.strip()
        if not __import__("re").fullmatch(r"[0-9a-f]{32}", single_id):
            raise ProofFailure("single recap command did not return a record ID")
        single_path, single = find_record(data_dir, single_id)
        expected_single_prompt = single_template.replace("[[LABEL]]", "(none)").replace("[[TEXT]]", single_input)
        captures = [json.loads(line) for line in capture_log.read_text(encoding="utf-8").splitlines()]
        if captures[-1] != {"mode": "success", "prompt": expected_single_prompt}:
            raise ProofFailure("single prompt edit or exact backend stdin was ignored")
        selected = [json.loads(line) for line in selected_log.read_text(encoding="utf-8").splitlines()]
        if selected[-1] != {"role": "config.local", "argv": ["host-argv-override"]}:
            raise ProofFailure("config.local.toml argv override was not used")

        group_input_obj = {"members": [
            {"label": "parser", "text": "Parser behavior now matches the fixture."},
            {"text": "Migration work remains untouched."},
        ]}
        group_stdin = json.dumps(group_input_obj, ensure_ascii=False) + "\n"
        group_id = cli_recap(home, env, "create", "--kind", "group", "--label", "Proof group", stdin=group_stdin).stdout.strip()
        group_path, group = find_record(data_dir, group_id)
        group_capture = [json.loads(line) for line in capture_log.read_text(encoding="utf-8").splitlines()][-1]
        if group_capture["prompt"] != group_template.replace("[[LABEL]]", "Proof group").replace(
            "[[MEMBERS]]", "Member 1 (label: parser):\nParser behavior now matches the fixture.\n\nMember 2:\nMigration work remains untouched."
        ):
            raise ProofFailure("group prompt edit, labels, or exact backend stdin was ignored")

        old_latest = latest_entry(data_dir, "manual", "proof-single")
        if not old_latest or old_latest.get("latest_success_id") != single_id:
            raise ProofFailure("successful single recap was not indexed as latest")
        for mode, name in (("blank", "blank"), ("nonzero", "nonzero")):
            mode_file.write_text(mode + "\n", encoding="utf-8")
            failed = cli_recap(home, env, "create", "--kind", "single", "--source-id", "proof-single",
                               stdin=f"Failure mode {name}\n", check=False)
            if failed.returncode == 0:
                raise ProofFailure(f"{name} backend output unexpectedly published")
            entry = latest_entry(data_dir, "manual", "proof-single")
            if not entry or entry.get("latest_success_id") != single_id:
                raise ProofFailure(f"{name} attempt replaced the latest good recap")
            failure_path, failure = find_record(data_dir, entry["last_attempt_id"])
            if failure.get("status") != "failed":
                raise ProofFailure(f"{name} attempt was not recorded as failed")
        mode_file.write_text("success\n", encoding="utf-8")

        # Exercise prepare/publish attribution, workspace grouping, session grouping,
        # and retained member IDs using the same T1 command/store as the Pi adapter.
        pi_ids: list[str] = []
        for suffix in ("a", "b"):
            prepared = cli_recap(home, env, "prepare", "--source-id", f"proof-pi-{suffix}",
                                 "--pane-id", f"pane-{suffix}", stdin=f"Pi response {suffix}.\n").stdout.strip()
            published = cli_recap(home, env, "publish", "--prepared-id", prepared,
                                  "--workspace-id", "workspace-proof").stdout.strip()
            if published != prepared:
                raise ProofFailure("prepared Pi recap did not publish under its stable record ID")
            _path, record = find_record(data_dir, published)
            if record.get("workspace_id") != "workspace-proof" or record.get("pane_id") != f"pane-{suffix}":
                raise ProofFailure("Pi recap lost its publication-time pane/workspace attribution")
            pi_ids.append(published)
        workspace_group_input = json.dumps({"members": [
            {"record_id": record_id, "label": f"pane {index}", "text": find_record(data_dir, record_id)[1]["summary"]}
            for index, record_id in enumerate(pi_ids, 1)
        ]}) + "\n"
        workspace_id = cli_recap(home, env, "create", "--kind", "group", "--source-kind", "workspace",
                                 "--source-id", "workspace-proof", stdin=workspace_group_input).stdout.strip()
        _path, workspace_record = find_record(data_dir, workspace_id)
        if workspace_record.get("member_record_ids") != pi_ids:
            raise ProofFailure("workspace recap did not retain its published Pi member IDs")
        session_input = json.dumps({"members": [{
            "record_id": workspace_id,
            "label": "workspace-proof",
            "text": workspace_record["summary"],
        }]}) + "\n"
        session_id = cli_recap(home, env, "create", "--kind", "group", "--source-kind", "herdr-session",
                               "--source-id", "active", stdin=session_input).stdout.strip()
        _path, session_record = find_record(data_dir, session_id)
        if session_record.get("member_record_ids") != [workspace_id]:
            raise ProofFailure("Herdr-session recap did not retain its workspace member ID")

        # A fresh CLI process above must not erase earlier dated history.
        for record_id in [single_id, group_id, *pi_ids, workspace_id, session_id]:
            record_path, record = find_record(data_dir, record_id)
            if not record_path.parent.name or record.get("status") != "published":
                raise ProofFailure(f"dated history is missing after fresh CLI processes: {record_id}")
        if single_path.parent.name != datetime.fromisoformat(single["created_at"].replace("Z", "+00:00")).date().isoformat():
            raise ProofFailure("single recap was not stored under its UTC date")
        return {
            "single_record_id": single_id,
            "manual_group_record_id": group_id,
            "workspace_record_id": workspace_id,
            "session_record_id": session_id,
            "dated_records_checked": len([single_id, group_id, *pi_ids, workspace_id, session_id]),
            "latest_preserved_after_blank_and_nonzero": True,
            "template_and_host_argv_edits_observed": True,
        }


def run_pty_command(
    argv: list[str],
    env: dict[str, str],
    *,
    initial_input: bytes = b"",
    waits: list[tuple[bytes, bytes]] | None = None,
    timeout: float = 20,
    cwd: Path | None = None,
) -> tuple[int, str]:
    """Run an interactive CLI on a private PTY and answer after visible prompts."""
    pid, master = pty.fork()
    if pid == 0:
        if cwd is not None:
            os.chdir(cwd)
        os.environ.clear()
        os.environ.update(env)
        os.execvpe(argv[0], argv, env)
        raise SystemExit(127)
    output = bytearray()
    watch_from = 0
    try:
        if initial_input:
            os.write(master, initial_input)
        for needle, answer in waits or []:
            deadline = time.monotonic() + timeout
            while needle not in output[watch_from:]:
                if time.monotonic() >= deadline:
                    raise ProofFailure(f"interactive CLI did not show prompt {needle!r}: {bounded(output.decode('utf-8', 'replace'))}")
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break
                    output.extend(chunk)
                child, status = os.waitpid(pid, os.WNOHANG)
                if child:
                    pid = -1
                    raise ProofFailure(f"interactive CLI exited before {needle!r}: {os.waitstatus_to_exitcode(status)}")
            os.write(master, answer)
            watch_from = len(output)
        deadline = time.monotonic() + timeout
        while pid > 0:
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    chunk = b""
                if chunk:
                    output.extend(chunk)
            child, status = os.waitpid(pid, os.WNOHANG)
            if child:
                pid = -1
                code = os.waitstatus_to_exitcode(status)
                if code != 0:
                    raise ProofFailure(f"interactive CLI exited {code}: {bounded(output.decode('utf-8', 'replace'))}")
                return code, output.decode("utf-8", "replace")
            if time.monotonic() >= deadline:
                raise ProofFailure(f"interactive CLI timed out: {bounded(output.decode('utf-8', 'replace'))}")
        return 0, output.decode("utf-8", "replace")
    finally:
        if pid > 0:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        os.close(master)


def scenario_review() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="herdr-proof-review-") as temp:
        root = Path(temp)
        home = root / "home"
        home.mkdir()
        local_bin = home / ".local/bin"
        local_share = home / ".local/share/passage-review"
        local_bin.mkdir(parents=True)
        local_share.mkdir(parents=True)
        shutil.copy2(ROOT / "dot_local/bin/executable_passage-review", local_bin / "passage-review")
        (local_bin / "passage-review").chmod(0o700)
        shutil.copy2(ROOT / "dot_local/share/passage-review/passage_review.py", local_share / "passage_review.py")
        env = os.environ.copy()
        env.update({
            "HOME": str(home),
            "XDG_DATA_HOME": str(home / ".local/share"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PASSAGE_REVIEW_CLIPBOARD": "off",
            "PAGER": "cat",
            "VISUAL": str(root / "proof-editor.sh"),
            "EDITOR": str(root / "proof-editor.sh"),
            "PATH": os.pathsep.join([str(local_bin), env.get("PATH", "/usr/bin:/bin")]),
        })
        editor_count = root / "editor-count"
        write_exec(root / "proof-editor.sh",
                   "#!/bin/sh\nset -eu\nn=0\n[ ! -f \"$PROOF_EDITOR_COUNT\" ] || IFS= read -r n < \"$PROOF_EDITOR_COUNT\"\nn=$((n + 1))\nprintf '%s\\n' \"$n\" > \"$PROOF_EDITOR_COUNT\"\nfor arg do target=$arg; done\n"
                   "case $n in\n  1) printf 'Keep this part as the compatibility contract.\\n' > \"$target\" ;;\n"
                   "  2) printf 'Check this follow-up before merging.\\n' > \"$target\" ;;\n"
                   "  *) printf 'Review the phone output boundary.\\n' > \"$target\" ;;\nesac\n")
        env["PROOF_EDITOR_COUNT"] = str(editor_count)
        snapshot_file = root / "chosen-design.md"
        snapshot_text = "Compatibility must remain stable.\nThe parser accepts empty labels.\nThe migration is still pending.\n"
        snapshot_file.write_text(snapshot_text, encoding="utf-8")
        original_hash = hashlib.sha256(snapshot_file.read_bytes()).hexdigest()
        cli = str(local_bin / "passage-review")
        _, transcript = run_pty_command(
            [cli, "new", "--file", str(snapshot_file)], env,
            waits=[
                (b"[a]dd passage comment", b"a\n1\n"),
                (b"Saved pending note", b"a\n3\n"),
                (b"Saved pending note", b"q\n"),
            ],
            timeout=20,
            cwd=root,
        )
        if "chosen-design.md" not in transcript or "Pending comments (2)" not in transcript:
            raise ProofFailure("file review did not save and show two passage comments")
        review_dirs = list((home / ".local/share/passage-review/reviews").glob("rv-*"))
        if len(review_dirs) != 1:
            raise ProofFailure("review CLI did not create exactly one isolated review")
        review_dir = review_dirs[0]
        review_id = review_dir.name
        if not REVIEW_ID_RE.fullmatch(review_id):
            raise ProofFailure("review CLI returned an invalid review ID")
        metadata = read_json(review_dir / "review.json")
        snapshot = review_dir / "snapshot.txt"
        snapshot_bytes = snapshot.read_bytes()
        snapshot_hash = hashlib.sha256(snapshot_bytes).hexdigest()
        if snapshot_hash != metadata.get("snapshot_sha256") or snapshot_file.read_bytes() != snapshot_bytes:
            raise ProofFailure("review snapshot changed or did not match the selected file")
        note_paths = sorted((review_dir / "notes").glob("n-*.json"))
        if len(note_paths) != 2:
            raise ProofFailure("review CLI did not save two pending notes")
        notes = [read_json(path) for path in note_paths]
        note_ids = [note["note_id"] for note in notes]
        for note in notes:
            if not NOTE_ID_RE.fullmatch(note["note_id"]) or note.get("review_id") != review_id:
                raise ProofFailure("saved review note has invalid attribution")
        first_note = next((note for note in notes if note.get("quote", "").strip() == "Compatibility must remain stable."), None)
        second_note = next((note for note in notes if note.get("quote", "").strip() == "The migration is still pending."), None)
        if not first_note or not second_note:
            raise ProofFailure("saved comments are not attached to their selected source passages")
        note_bytes_before = [path.read_bytes() for path in note_paths]

        _, reopened = run_pty_command(
            [cli, "open", review_id], env,
            waits=[(b"Pending comments (2)", b"q\n")], timeout=20, cwd=root,
        )
        if "chosen-design.md" not in reopened or all(note_id not in reopened for note_id in note_ids):
            raise ProofFailure("reopening did not show the frozen source and saved notes")
        export = run_process([cli, "export", review_id, "--note", first_note["note_id"]], env=env)
        export_files = list((review_dir / "exports").glob("*.md"))
        if len(export_files) != 1:
            raise ProofFailure("selective export did not leave exactly one accessible result")
        exported = export_files[0].read_text(encoding="utf-8")
        if f"## Note {first_note['note_id']} " not in exported or second_note["note_id"] in exported:
            raise ProofFailure("export did not contain exactly the selected pending note")
        if ("> Compatibility must remain stable." not in exported
                or "Keep this part as the compatibility contract." not in exported
                or "Check this follow-up before merging." in exported):
            raise ProofFailure("export omitted the selected quote/feedback or included an unselected note")
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != snapshot_hash:
            raise ProofFailure("export changed the frozen source snapshot")
        if [path.read_bytes() for path in note_paths] != note_bytes_before or list((review_dir / "notes/archived").glob("*.json")):
            raise ProofFailure("export changed pending-note state")
        if hashlib.sha256(snapshot_file.read_bytes()).hexdigest() != original_hash:
            raise ProofFailure("review workflow modified the original document")
        return {
            "review_id": review_id,
            "pending_note_ids": note_ids,
            "selected_export_note_id": note_ids[0],
            "source_unchanged": True,
            "pending_state_unchanged_after_export": True,
            "pi_or_herdr_process_required": False,
            "export_path": str(export_files[0].relative_to(root)),
            "cli_export_bytes": len(export.stdout.encode("utf-8")),
        }


def default_cache_root() -> Path:
    # The phone helper invokes this driver through SSH, which does not promise
    # to forward XDG_CACHE_HOME. Keep the shared run lookup stable by design.
    return Path.home() / ".cache" / "herdr-overview-proof"


def make_run_id() -> str:
    return uuid.uuid4().hex[:16]


def run_root(run_id: str, base: Path | None = None) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ProofFailure("run ID must be 16 lowercase hexadecimal characters")
    return (base or default_cache_root()) / run_id


def make_herdr_env(root: Path) -> dict[str, str]:
    home = root / "home"
    config_home = root / "config"
    data_home = root / "data"
    state_home = root / "state"
    for path in (home, config_home / "herdr", data_home, state_home, root / "tmp", root / "server", root / "bin"):
        path.mkdir(parents=True, exist_ok=True)
    path_parts = [os.environ.get("PATH", "/usr/bin:/bin")]
    for executable in (shutil.which("node"), shutil.which("pi"), shutil.which("herdr"), sys.executable):
        if executable:
            path_parts.insert(0, str(Path(executable).resolve().parent))
    path_parts.insert(0, str(root / "bin"))
    inherited = os.environ
    env = {key: inherited[key] for key in ("PATH", "TERM", "LANG", "LC_ALL", "LC_CTYPE", "COLORTERM") if key in inherited}
    env.update({
        "HOME": str(home),
        "SHELL": "/bin/sh",
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_DATA_HOME": str(data_home),
        "XDG_STATE_HOME": str(state_home),
        "TMPDIR": str(root / "tmp"),
        "HERDR_CONFIG_PATH": str(config_home / "herdr/config.toml"),
        "HERDR_SOCKET_PATH": str(root / "server/herdr.sock"),
        "HERDR_PLUGIN_STATE_DIR": str(state_home / "herdr/plugins/overview"),
        "PI_CODING_AGENT_DIR": str(root / "pi-agent"),
        "PI_OFFLINE": "1",
        "PI_TELEMETRY": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "SESSION_RECAP_BIN": str(home / ".local/bin/session-recap"),
        "SESSION_RECAP_PYTHON": sys.executable,
        "HERDR_OVERVIEW_PROOF_RUN_ID": root.name,
        "PATH": os.pathsep.join(dict.fromkeys(path_parts)),
    })
    return env


def setup_herdr_run(run_id: str, base: Path | None = None) -> tuple[Path, dict[str, Any], dict[str, str]]:
    root = run_root(run_id, base)
    marker = root / PROOF_MARKER
    if root.exists():
        if marker.exists():
            raise ProofFailure(f"proof run already exists; use its run ID for the existing fixture: {root}")
        raise ProofFailure(f"refusing to reuse unmarked proof directory: {root}")
    root.mkdir(parents=True, mode=0o700)
    env = make_herdr_env(root)
    recap_home, recap_config, recap_data = copy_recap_install(root)
    env["HOME"] = str(root / "home")
    env["XDG_CONFIG_HOME"] = str(root / "config")
    env["XDG_DATA_HOME"] = str(root / "data")
    env["SESSION_RECAP_BIN"] = str(recap_home / ".local/bin/session-recap")
    env["FAKE_RECAP_MODE_FILE"] = str(root / "backend-mode")
    env["FAKE_RECAP_CAPTURE_LOG"] = str(root / "backend-captures.jsonl")
    env["HERDR_OVERVIEW_COMMAND_LOG"] = str(root / "recap-commands.jsonl")
    env["HERDR_OVERVIEW_PI_REPLY"] = str(root / "scripted-pi-reply.txt")
    env["HERDR_OVERVIEW_TEST_PROVIDER_URL"] = ""
    env["HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE"] = str(root / "provider-url")
    env["PI_CODING_AGENT_DIR"] = str(root / "pi-agent")
    env["PI_SESSION_DIR"] = str(root / "pi-sessions")
    (root / "backend-mode").write_text("success\n", encoding="utf-8")
    fake = ROOT / "tests/herdr-overview/fake_recap_backend.py"
    (recap_config / "config.toml").write_text(
        f"command = [{json.dumps(sys.executable)}, {json.dumps(str(fake))}, \"success\"]\n",
        encoding="utf-8",
    )
    (recap_config / "single-prompt.md").write_text(
        (ROOT / "dot_config/session-recap/single-prompt.md.tmpl").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (recap_config / "group-prompt.md").write_text(
        (ROOT / "dot_config/session-recap/group-prompt.md.tmpl").read_text(encoding="utf-8"), encoding="utf-8"
    )
    command_log_wrapper = recap_home / ".local/bin/session-recap"
    # Keep the source wrapper's T1 behavior and add a bounded argv trace for this fixture only.
    source_wrapper = (ROOT / "dot_local/bin/executable_session-recap").read_text(encoding="utf-8")
    log_anchor = 'script_dir=$(dirname "$script_path")'
    if source_wrapper.count(log_anchor) != 1:
        raise ProofFailure("session-recap wrapper no longer has the expected command-log insertion point")
    source_wrapper = source_wrapper.replace(
        log_anchor,
        'printf \'%s\\n\' "$(python3 -c \'import json,sys; print(json.dumps(sys.argv[1:]))\' "$@")" >> "${HERDR_OVERVIEW_COMMAND_LOG:?}"\n' + log_anchor,
        1,
    )
    command_log_wrapper.write_text(source_wrapper, encoding="utf-8")
    command_log_wrapper.chmod(0o700)
    plugin_state = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": utc_now(),
        "root": str(root.resolve()),
        "home": str((root / "home").resolve()),
        "config_path": str((root / "config/herdr/config.toml").resolve()),
        "socket_path": str((root / "server/herdr.sock").resolve()),
        "herdr_bin": shutil.which("herdr"),
        "repo_root": str(ROOT.resolve()),
        "fixture": {"workspaces": [], "pi_pane_id": None, "non_pi_pane_id": None, "overview_pane_id": None},
        "server_started": False,
    }
    config = """onboarding = false
[server]
headless_cols = 160
headless_rows = 80
[ui]
mobile_width_threshold = 64
[theme]
name = \"tokyo-night\"
auto_switch = false
[update]
version_check = false
manifest_check = false
"""
    (root / "config/herdr/config.toml").write_text(config, encoding="utf-8")
    (root / "pi-agent").mkdir(parents=True)
    (root / "pi-sessions").mkdir(parents=True)
    json_dump(marker, plugin_state)
    # Link only in the isolated XDG config tree. The private nonexistent socket
    # prevents plugin link from contacting or starting any live Herdr server.
    link_env = dict(env)
    link_env["HERDR_SOCKET_PATH"] = str(root / "server/plugin-link-only.sock")
    herdr_bin = plugin_state["herdr_bin"]
    if not herdr_bin:
        raise ProofBlocked("Herdr is not installed; install the pinned 0.9.1 desktop release first")
    version = run_process([herdr_bin, "--version"], env=link_env, check=False)
    if version.returncode != 0 or "0.9.1" not in version.stdout:
        raise ProofBlocked(f"Herdr 0.9.1 is required; found {bounded(version.stdout or version.stderr, 200)}")
    node = shutil.which("node")
    if not node:
        raise ProofBlocked("Node.js is required to run the source-managed Herdr plugin")
    link = run_process([herdr_bin, "plugin", "link", str(ROOT / "dot_local/share/herdr-overview"), "--enabled"],
                       env=link_env, check=False)
    if link.returncode != 0:
        raise ProofFailure(f"could not link the overview into the isolated config: {bounded(link.stderr)}")
    registry = root / "config/herdr/plugins.json"
    if not registry.is_file() or not any(item.get("plugin_id") == "overview" for item in json.loads(registry.read_text(encoding="utf-8"))):
        raise ProofFailure("isolated plugin link did not register the Herdr Overview plugin")
    return root, plugin_state, env


def load_run(run_id: str, base: Path | None = None) -> tuple[Path, dict[str, Any], dict[str, str]]:
    root = run_root(run_id, base).resolve()
    marker = root / PROOF_MARKER
    if not root.is_dir() or not marker.is_file():
        raise ProofBlocked(f"no recorded isolated Herdr fixture for run {run_id}; run herdr-prepare first")
    state = read_json(marker)
    if state.get("run_id") != run_id or Path(state.get("root", "")).resolve() != root:
        raise ProofFailure("isolated fixture marker does not match the requested run ID/path")
    expected_socket = (root / "server/herdr.sock").resolve()
    if Path(state.get("socket_path", "")).resolve() != expected_socket:
        raise ProofFailure("recorded Herdr socket is not the isolated fixture socket")
    env = make_herdr_env(root)
    env.update({
        "HERDR_CONFIG_PATH": state["config_path"],
        "HERDR_SOCKET_PATH": state["socket_path"],
        "HERDR_PLUGIN_STATE_DIR": str(root / "state/herdr/plugins/overview"),
        "SESSION_RECAP_BIN": str(root / "home/.local/bin/session-recap"),
        "FAKE_RECAP_MODE_FILE": str(root / "backend-mode"),
        "FAKE_RECAP_CAPTURE_LOG": str(root / "backend-captures.jsonl"),
        "HERDR_OVERVIEW_COMMAND_LOG": str(root / "recap-commands.jsonl"),
        "HERDR_OVERVIEW_PI_REPLY": str(root / "scripted-pi-reply.txt"),
        "HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE": str(root / "provider-url"),
        "PI_CODING_AGENT_DIR": str(root / "pi-agent"),
        "PI_SESSION_DIR": str(root / "pi-sessions"),
    })
    return root, state, env


def herdr_cmd(state: dict[str, Any], env: dict[str, str], *args: str, check: bool = True,
              timeout: float = 35) -> subprocess.CompletedProcess[str]:
    binary = state.get("herdr_bin") or shutil.which("herdr")
    if not binary:
        raise ProofBlocked("Herdr is unavailable")
    return run_process([binary, *args], env=env, check=check, timeout=timeout)


def api_request(state: dict[str, Any], method: str, params: dict[str, Any] | None = None, timeout: float = 5) -> dict[str, Any]:
    socket_path = state["socket_path"]
    if Path(socket_path).resolve() != (Path(state["root"]) / "server/herdr.sock").resolve():
        raise ProofFailure("refusing API request to a socket outside the isolated proof directory")
    request_id = f"herdr-overview-proof:{uuid.uuid4().hex}"
    request = {"id": request_id, "method": method, "params": params or {}}
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(socket_path)
        client.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buffer = b""
        while b"\n" not in buffer:
            chunk = client.recv(65536)
            if not chunk:
                break
            buffer += chunk
    except OSError as exc:
        raise ProofBlocked(f"isolated Herdr socket is unavailable: {exc}") from exc
    finally:
        client.close()
    try:
        response = json.loads(buffer.split(b"\n", 1)[0].decode("utf-8"))
    except (ValueError, IndexError) as exc:
        raise ProofFailure(f"invalid Herdr API response to {method}") from exc
    if response.get("id") != request_id:
        raise ProofFailure(f"Herdr response ID mismatch for {method}")
    if response.get("error"):
        raise ProofFailure(f"Herdr API {method} failed: {response['error']}")
    result_value = response.get("result")
    return result_value if isinstance(result_value, dict) else {"result": result_value}


def snapshot(state: dict[str, Any], timeout: float = 5) -> dict[str, Any]:
    result_value = api_request(state, "session.snapshot", timeout=timeout)
    value = result_value.get("snapshot")
    if not isinstance(value, dict) or value.get("protocol") != 22 or value.get("version") != "0.9.1":
        raise ProofFailure(f"isolated server is not Herdr v0.9.1/protocol-22: {value!r}")
    return value


def server_status(state: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    completed = herdr_cmd(state, env, "status", "server", "--json", check=False)
    if completed.returncode != 0:
        return {"running": False, "raw": bounded(completed.stdout + completed.stderr, 800)}
    try:
        info = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProofFailure("Herdr status did not return JSON") from exc
    if info.get("socket") != state["socket_path"]:
        raise ProofFailure("Herdr status resolved to a socket other than the recorded isolated socket")
    return info


def wait_for(predicate: Callable[[], Any], description: str, timeout: float = 20, interval: float = 0.15) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (OSError, ProofBlocked):
            pass
        time.sleep(interval)
    raise ProofFailure(f"timed out waiting for {description}")


def one_by(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    found = [item for item in items if item.get(key) == value]
    if len(found) != 1:
        raise ProofFailure(f"expected exactly one Herdr object with {key}={value!r}, found {len(found)}")
    return found[0]


def overview_state_path(root: Path) -> Path:
    # Herdr 0.9.1 owns the plugin's state directory and overrides the caller env.
    return root / "state/herdr/plugins/overview/overview.json"


def wait_plugin_state(root: Path, timeout: float = 20) -> dict[str, Any]:
    path = overview_state_path(root)
    def read() -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            state = read_json(path)
        except (OSError, ValueError):
            return None
        return state if state.get("model") is not None and state.get("overviewPaneId") else None
    return wait_for(read, "the real overview plugin pane and state", timeout=timeout)


def scenario_herdr_prepare(run_id: str | None, base: Path | None) -> tuple[str, dict[str, Any]]:
    run_id = run_id or make_run_id()
    try:
        root, state, env = setup_herdr_run(run_id, base)
    except Exception:
        # setup only links an offline manifest into a private config; it does
        # not start a server. Remove that exact unstarted tree on setup failure.
        root = run_root(run_id, base)
        marker = root / PROOF_MARKER
        if marker.is_file() and not Path(root / "server/herdr.sock").exists():
            shutil.rmtree(root)
        raise
    try:
        herdr_bin = state["herdr_bin"]
        if not herdr_bin:
            raise ProofBlocked("the pinned Herdr 0.9.1 binary is not installed")
        first_workdir = root / "workspaces/bootstrap"
        first_workdir.mkdir(parents=True)
        # Workspace commands require a running server. Start only with this
        # fixture's private config and socket, then verify status before mutation.
        server_log = root / "server/herdr-server.log"
        with server_log.open("ab") as output:
            server_process = subprocess.Popen(
                [herdr_bin, "server"], cwd=root, env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
            )

        def isolated_status() -> dict[str, Any] | None:
            if server_process.poll() is not None:
                raise ProofFailure(f"isolated Herdr server exited {server_process.returncode}: "
                                   f"{bounded(server_log.read_text(errors='replace'), 1000)}")
            return server_status(state, env) if Path(state["socket_path"]).exists() else None

        try:
            info = wait_for(isolated_status, "the isolated v0.9.1 server", timeout=25)
        except BaseException:
            if server_process.poll() is None:
                server_process.terminate()
                try:
                    server_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server_process.kill()
                    server_process.wait(timeout=5)
            raise
        herdr_cmd(state, env, "workspace", "create", "--cwd", str(first_workdir),
                  "--label", "Proof Bootstrap", "--no-focus")
        if not info.get("running") or info.get("version") != "0.9.1" or info.get("protocol") != 22:
            raise ProofFailure(f"isolated Herdr server is not running v0.9.1/protocol 22: {info}")
        state["server_started"] = True
        json_dump(root / PROOF_MARKER, state)
        # Reuse the isolated bootstrap workspace as Proof Alpha; no operation
        # reads, closes, or restarts the owner's default Herdr session.
        first = snapshot(state)
        bootstrap = one_by(first.get("workspaces", []), "label", "Proof Bootstrap")
        herdr_cmd(state, env, "workspace", "rename", bootstrap["workspace_id"], "Proof Alpha")
        workdir = root / "workspaces/workspace-1"
        workdir.mkdir(parents=True)
        live = snapshot(state)
        alpha = one_by(live.get("workspaces", []), "label", "Proof Alpha")
        # The first workspace already exists and is the bootstrap fixture.
        # Build its shell/tab directly, then create only Bravo and Charlie.
        root_tab = next(tab for tab in live["tabs"] if tab.get("workspace_id") == alpha["workspace_id"]
                        and tab.get("label") != "Herdr Overview")
        root_pane = next(pane for pane in live["panes"] if pane.get("tab_id") == root_tab["tab_id"])
        herdr_cmd(state, env, "pane", "run", root_pane["pane_id"],
                  "printf 'T8 proof output: Proof Alpha line one\\nT8 proof output: Proof Alpha line two\\n'")
        herdr_cmd(state, env, "pane", "wait-output", root_pane["pane_id"], "--match", "T8 proof output:", "--timeout", "10000")
        herdr_cmd(state, env, "pane", "rename", root_pane["pane_id"], "Owner Proof Alpha shell")
        herdr_cmd(state, env, "tab", "rename", root_tab["tab_id"], "Owner Proof Alpha tab")
        second_tab_label = "Owner Proof Alpha second tab"
        herdr_cmd(state, env, "tab", "create", "--workspace", alpha["workspace_id"], "--cwd", str(workdir),
                  "--label", second_tab_label, "--no-focus")
        live = snapshot(state)
        second_tab = one_by(live["tabs"], "label", second_tab_label)
        second_pane = next(pane for pane in live["panes"] if pane.get("tab_id") == second_tab["tab_id"])
        herdr_cmd(state, env, "pane", "run", second_pane["pane_id"], "printf 'T8 second-tab output: Proof Alpha\\n'")
        herdr_cmd(state, env, "pane", "wait-output", second_pane["pane_id"], "--match", "T8 second-tab output:", "--timeout", "10000")
        herdr_cmd(state, env, "pane", "rename", second_pane["pane_id"], "Owner Proof Alpha second shell")
        split = herdr_cmd(state, env, "pane", "split", root_pane["pane_id"], "--direction", "right",
                          "--cwd", str(workdir), "--no-focus")
        split_value = json.loads(split.stdout)
        pi_pane_id = split_value.get("result", {}).get("pane", {}).get("pane_id")
        if not pi_pane_id:
            live = snapshot(state)
            pi_pane_id = next(pane["pane_id"] for pane in live["panes"]
                              if pane.get("workspace_id") == alpha["workspace_id"]
                              and pane["pane_id"] not in {root_pane["pane_id"], second_pane["pane_id"]})
        herdr_cmd(state, env, "pane", "rename", pi_pane_id, "Owner Pi proof pane")
        created = [{"workspace_id": alpha["workspace_id"], "label": "Proof Alpha",
                    "root_pane_id": root_pane["pane_id"], "root_tab_id": root_tab["tab_id"], "pi_pane_id": pi_pane_id}]
        for index, label in enumerate(("Proof Bravo", "Proof Charlie"), start=2):
            workdir = root / "workspaces" / f"workspace-{index}"
            workdir.mkdir(parents=True)
            herdr_cmd(state, env, "workspace", "create", "--cwd", str(workdir), "--label", label, "--no-focus")
            live = snapshot(state)
            workspace = one_by(live["workspaces"], "label", label)
            tab = next(tab for tab in live["tabs"] if tab["workspace_id"] == workspace["workspace_id"])
            pane = next(pane for pane in live["panes"] if pane["tab_id"] == tab["tab_id"])
            herdr_cmd(state, env, "pane", "run", pane["pane_id"],
                      f"printf 'T8 proof output: {label} line one\\nT8 proof output: {label} line two\\n'")
            herdr_cmd(state, env, "pane", "wait-output", pane["pane_id"], "--match", "T8 proof output:", "--timeout", "10000")
            herdr_cmd(state, env, "pane", "rename", pane["pane_id"], f"Owner {label} shell")
            herdr_cmd(state, env, "tab", "rename", tab["tab_id"], f"Owner {label} tab")
            second_label = f"Owner {label} second tab"
            herdr_cmd(state, env, "tab", "create", "--workspace", workspace["workspace_id"], "--cwd", str(workdir),
                      "--label", second_label, "--no-focus")
            live = snapshot(state)
            second = one_by(live["tabs"], "label", second_label)
            second_pane = next(item for item in live["panes"] if item["tab_id"] == second["tab_id"])
            herdr_cmd(state, env, "pane", "run", second_pane["pane_id"], f"printf 'T8 second-tab output: {label}\\n'")
            herdr_cmd(state, env, "pane", "wait-output", second_pane["pane_id"], "--match", "T8 second-tab output:", "--timeout", "10000")
            herdr_cmd(state, env, "pane", "rename", second_pane["pane_id"], f"Owner {label} second shell")
            created.append({"workspace_id": workspace["workspace_id"], "label": label,
                            "root_pane_id": pane["pane_id"], "root_tab_id": tab["tab_id"]})
        # Keep a second non-Pi pane ID as the phone review source.
        fixture = {
            "workspaces": created,
            "pi_pane_id": pi_pane_id,
            "non_pi_pane_id": created[1]["root_pane_id"],
            "overview_pane_id": None,
            "manual_workspace_labels": [item["label"] for item in created],
            "manual_tab_labels": [f"Owner {item['label']} tab" for item in created],
        }
        herdr_cmd(state, env, "workspace", "focus", created[0]["workspace_id"])
        api_request(state, "plugin.action.invoke", {"action_id": "overview.reconcile"})
        overview = wait_plugin_state(root)
        fixture["overview_pane_id"] = overview.get("overviewPaneId")
        if not fixture["overview_pane_id"]:
            raise ProofFailure("the overview startup/reconcile action did not open a pane")
        def fixture_ready() -> dict[str, Any] | None:
            live = snapshot(state)
            model = plugin_state(root).get("model") or {}
            native_panes = {pane["pane_id"] for pane in live.get("panes", [])
                            if pane.get("pane_id") != fixture["overview_pane_id"]}
            if set((model.get("panes") or {}).keys()) != native_panes:
                return None
            if set((model.get("workspaces") or {}).keys()) != {item["workspace_id"] for item in created}:
                return None
            screen = plain_terminal(pane_text(state, env, fixture["overview_pane_id"], fmt="ansi", lines=260))
            for item in created:
                count = sum(pane.get("workspace_id") == item["workspace_id"] for pane in live["panes"]
                            if pane.get("pane_id") != fixture["overview_pane_id"])
                if f"{item['label']} [{item['workspace_id']}]" not in screen or f"· {count} panes" not in screen:
                    return None
            return live

        live = wait_for(fixture_ready, "the full native pane set in the visible overview", timeout=30)
        if not (2 <= len(live.get("workspaces", [])) <= 5):
            raise ProofFailure("isolated fixture must have 2-5 workspaces")
        state.update({
            "server_started": True,
            "fixture": fixture,
            "server_version": "0.9.1",
            "server_protocol": 22,
            "prepared_at": utc_now(),
        })
        json_dump(root / PROOF_MARKER, state)
        return run_id, {
            "run_id": run_id,
            "server_version": "0.9.1",
            "protocol": 22,
            "socket_path": state["socket_path"],
            "workspaces": [item["label"] for item in created],
            "pane_count": len(live.get("panes", [])),
            "manual_labels_recorded": True,
            "mixed_pi_non_pi_panes": True,
        }
    except BaseException:
        # Keep only a marker-backed isolated server for explicit cleanup. Never
        # use a process-name kill or any user's default Herdr socket here.
        if (root / PROOF_MARKER).exists():
            try:
                saved = read_json(root / PROOF_MARKER)
                saved["prepare_failed_at"] = utc_now()
                json_dump(root / PROOF_MARKER, saved)
            except Exception:
                pass
        raise


def pane_text(state: dict[str, Any], env: dict[str, str], pane_id: str, *, source: str = "visible",
              fmt: str = "text", lines: int = 180) -> str:
    completed = herdr_cmd(state, env, "pane", "read", pane_id, "--source", source,
                          "--lines", str(lines), "--format", fmt, check=False, timeout=20)
    if completed.returncode != 0:
        raise ProofFailure(f"could not read isolated pane {pane_id}: {bounded(completed.stderr)}")
    try:
        value = json.loads(completed.stdout)
        text = value.get("result", {}).get("read", {}).get("text") or value.get("read", {}).get("text") or ""
        if isinstance(text, str):
            return text
    except json.JSONDecodeError:
        pass
    return completed.stdout


def send_overview_key(state: dict[str, Any], env: dict[str, str], key: str) -> None:
    pane_id = state.get("fixture", {}).get("overview_pane_id")
    if not pane_id:
        raise ProofFailure("isolated overview pane ID is missing")
    herdr_cmd(state, env, "pane", "send-keys", pane_id, key, timeout=10)
    time.sleep(0.25)


def invoke_overview(state: dict[str, Any], env: dict[str, str]) -> None:
    api_request(state, "plugin.action.invoke", {"action_id": "overview.reconcile"})


def plugin_state(root: Path) -> dict[str, Any]:
    return read_json(overview_state_path(root))


def require_manual_names(state: dict[str, Any], env: dict[str, str]) -> None:
    live = snapshot(state)
    fixture = state["fixture"]
    for item in fixture["workspaces"]:
        workspace = one_by(live.get("workspaces", []), "workspace_id", item["workspace_id"])
        if workspace.get("label") != item["label"]:
            raise ProofFailure(f"manual workspace label changed: {item['label']}")
        pane = next(pane for pane in live["panes"] if pane.get("pane_id") == item["root_pane_id"])
        if pane.get("label") != f"Owner {item['label']} shell":
            raise ProofFailure(f"manual pane label changed for {item['label']}: {pane.get('label')!r}")
        tab = next(tab for tab in live["tabs"] if tab.get("tab_id") == item["root_tab_id"])
        if tab.get("label") != f"Owner {item['label']} tab":
            raise ProofFailure(f"manual tab label changed for {item['label']}: {tab.get('label')!r}")


def plain_terminal(text: str) -> str:
    return __import__("re").sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def overview_text(state: dict[str, Any], env: dict[str, str]) -> str:
    return plain_terminal(pane_text(state, env, state["fixture"]["overview_pane_id"], fmt="ansi", lines=260))


def open_pane_from_workspace(state: dict[str, Any], env: dict[str, str], pane_id: str) -> str:
    # Cards prioritize task labels and can truncate their ID. The detail header
    # identifies the selected native pane, so drive the actual selection path.
    for _ in range(40):
        send_overview_key(state, env, "enter")
        detail = wait_for(
            lambda: (lambda text: text if "selected pane" in text else None)(overview_text(state, env)),
            "workspace selection to open a pane detail", timeout=4,
        )
        if f"[{pane_id}]" in detail:
            return detail
        send_overview_key(state, env, "esc")
        wait_for(lambda: (lambda text: text if "· Mosaic · workspace" in text else None)(overview_text(state, env)),
                 "pane detail to return to the workspace grid", timeout=4)
        send_overview_key(state, env, "j")
    raise ProofFailure(f"workspace grid could not reach pane {pane_id}")


def return_to_all_workspaces(state: dict[str, Any], env: dict[str, str]) -> str:
    for _ in range(3):
        text = overview_text(state, env)
        if "Herdr Overview" in text and "· Mosaic" in text and "· Mosaic · workspace" not in text and "· selected pane" not in text:
            return text
        send_overview_key(state, env, "esc")
    text = overview_text(state, env)
    if "· Mosaic · workspace" in text or "· selected pane" in text:
        raise ProofFailure("overview could not return to its all-workspaces level")
    return text


def select_workspace(state: dict[str, Any], env: dict[str, str], workspace: dict[str, Any]) -> str:
    text = return_to_all_workspaces(state, env)
    for _ in range(len(state["fixture"]["workspaces"]) + 1):
        if f"[{workspace['workspace_id']}]" in text and any(
            line.lstrip().startswith("›") and f"[{workspace['workspace_id']}]" in line for line in text.splitlines()
        ):
            send_overview_key(state, env, "enter")
            opened = overview_text(state, env)
            if "· Mosaic · workspace" not in opened or workspace["label"] not in opened:
                raise ProofFailure(f"opening {workspace['label']} did not enter its Mosaic workspace grid")
            return opened
        send_overview_key(state, env, "j")
        text = overview_text(state, env)
    raise ProofFailure(f"all-workspaces navigation could not select {workspace['label']}")


def focus_pane_from_workspace(state: dict[str, Any], env: dict[str, str], pane_id: str) -> None:
    detail = open_pane_from_workspace(state, env, pane_id)
    if "selected pane" not in detail or f"[{pane_id}]" not in detail:
        raise ProofFailure(f"selected-pane detail did not display native pane {pane_id}")
    send_overview_key(state, env, "f")
    focused = snapshot(state).get("focused_pane_id")
    if focused != pane_id:
        raise ProofFailure(f"overview focus did not target native pane {pane_id}: {focused}")
    send_overview_key(state, env, "esc")


def navigate_wide_fixture(state: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    root = Path(state["root"])
    require_manual_names(state, env)
    overview_id = state["fixture"]["overview_pane_id"]
    all_screen = return_to_all_workspaces(state, env)
    if "Mosaic" not in all_screen:
        raise ProofFailure("wide overview did not render the Mosaic presenter")
    if "Output subscription failed" in all_screen:
        raise ProofFailure("live output refresh failed during the wide overview journey")
    live = snapshot(state)
    for item in state["fixture"]["workspaces"]:
        if item["label"] not in all_screen:
            raise ProofFailure(f"wide all-workspaces Mosaic omitted {item['label']}")
        workspace = one_by(live["workspaces"], "workspace_id", item["workspace_id"])
        overview_pane = one_by(live["panes"], "pane_id", overview_id)
        tabs = [tab for tab in live["tabs"] if tab.get("workspace_id") == item["workspace_id"]
                and tab.get("tab_id") != overview_pane.get("tab_id")]
        pane_ids = [pane["pane_id"] for pane in live["panes"] if pane.get("workspace_id") == item["workspace_id"]
                    and pane["pane_id"] != overview_id]
        heading = f"{item['label']} [{item['workspace_id']}]"
        start = all_screen.find(heading)
        if start < 0:
            raise ProofFailure(f"wide all-workspaces Mosaic omitted heading {heading}")
        later = [all_screen.find(f"{other['label']} [{other['workspace_id']}]", start + len(heading))
                 for other in state["fixture"]["workspaces"] if other is not item]
        end = min([position for position in later if position >= 0] + [len(all_screen)])
        section = all_screen[start:end]
        borders = sum(line.count("+----") for line in section.splitlines() if line.lstrip().startswith("+"))
        rendered_cards = borders // 2
        if borders % 2 or rendered_cards != len(pane_ids):
            raise ProofFailure(f"wide all-workspaces Mosaic rendered {rendered_cards} cards for "
                               f"{item['label']}, expected {len(pane_ids)}")
        workspace_screen = select_workspace(state, env, {**item, "workspace_id": workspace["workspace_id"]})
        current_tab_id = workspace.get("active_tab_id")
        for tab in tabs:
            if tab.get("label", "").startswith("Owner ") and tab["label"] not in workspace_screen:
                raise ProofFailure(f"workspace grid omitted tab group {tab['label']}")
            tab_panes = [pane["pane_id"] for pane in live["panes"] if pane.get("tab_id") == tab["tab_id"]
                         and pane["pane_id"] != overview_id]
            if not tab_panes:
                raise ProofFailure(f"fixture tab has no reachable panes: {tab['tab_id']}")
            # Bracket navigation is the actual workspace-level tab control.
            # `active_tab_id` is Herdr's selected tab when entering a workspace.
            tab_order = workspace.get("tab_ids") or [value["tab_id"] for value in live["tabs"]
                                                   if value.get("workspace_id") == item["workspace_id"]]
            if current_tab_id not in tab_order:
                current_tab_id = tab_order[0]
            current_index = tab_order.index(current_tab_id)
            target_index = tab_order.index(tab["tab_id"])
            for _ in range((target_index - current_index) % len(tab_order)):
                send_overview_key(state, env, "]")
            current_tab_id = tab["tab_id"]
            for pane_id in tab_panes:
                focus_pane_from_workspace(state, env, pane_id)
        send_overview_key(state, env, "esc")
    require_manual_names(state, env)
    if state.get("theme_changed") is not True:
        config = Path(state["config_path"])
        config.write_text(
            "onboarding = false\n[server]\nheadless_cols = 160\nheadless_rows = 80\n"
            "[ui]\nmobile_width_threshold = 64\n[theme]\nname = \"dracula\"\nauto_switch = false\n"
            "[theme.custom]\naccent = \"#ff00aa\"\n",
            encoding="utf-8",
        )
        after = wait_for(
            lambda: (lambda text: text if "38;2;255;0;170" in text else None)(
                pane_text(state, env, overview_id, fmt="ansi")
            ),
            "the live overview to render the changed Herdr theme accent", timeout=8, interval=0.2,
        )
        if "38;2;255;121;198" not in after:
            raise ProofFailure("live wide overview did not adopt Dracula's built-in palette")
        state["theme_changed"] = True
        json_dump(root / PROOF_MARKER, state)
    # Overview presentation and selection must not execute a recap producer.
    log_path = root / "recap-commands.jsonl"
    commands = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()] if log_path.exists() else []
    if any(args and args[0] in ("create", "prepare") for args in commands):
        raise ProofFailure("overview open/navigation triggered recap generation")
    return {"workspace_count": len(state["fixture"]["workspaces"]), "all_panes_rendered": True,
            "native_focus_confirmed": True, "manual_names_preserved": True, "theme_change_visible": True,
            "overview_did_not_run_recap": True}


class ScriptedCompletionState:
    def __init__(self) -> None:
        self.count = 0
        self.started = threading.Event()
        self.release_first = threading.Event()
        self.lock = threading.Lock()
        self.prompts: list[str] = []
        self.reply = "\n".join(
            [f"Scripted Pi proof reply, review line {i:02d}: deterministic response content." for i in range(1, 38)]
            + ["Present state: the scripted response is complete; no external model was called."]
        )


class ScriptedProviderHandler(BaseHTTPRequestHandler):
    provider_state: ScriptedCompletionState

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        state = type(self).provider_state
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", "replace")
        with state.lock:
            state.count += 1
            current = state.count
            state.prompts.append(body)
        if current == 1:
            state.started.set()
            state.release_first.wait(75)
        text = state.reply if current == 1 else "Scripted second Pi response: present state remains unchanged."
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        common = {"id": f"t8-scripted-{current}", "object": "chat.completion.chunk", "created": 1,
                  "model": "scripted-model"}
        chunks = [
            {**common, "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
            {**common, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60}},
        ]
        for chunk in chunks:
            try:
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def start_scripted_provider() -> tuple[ThreadingHTTPServer, ScriptedCompletionState, threading.Thread, str]:
    state = ScriptedCompletionState()
    handler = type("T8ProviderHandler", (ScriptedProviderHandler,), {"provider_state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="herdr-proof-pi-provider", daemon=True)
    thread.start()
    return server, state, thread, f"http://127.0.0.1:{server.server_address[1]}/v1"


def make_pi_provider_extension(path: Path) -> None:
    path.write_text(
        "export default function (pi) {\n"
        "  pi.registerProvider('herdr-proof-scripted', {\n"
        "    name: 'Herdr proof scripted provider', api: 'openai-completions',\n"
        "    baseUrl: process.env.HERDR_OVERVIEW_TEST_PROVIDER_URL, apiKey: 'local-test-only',\n"
        "    models: [{ id: 'scripted-model', name: 'Scripted proof model', reasoning: false, input: ['text'],\n"
        "      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 4096, maxTokens: 256 }],\n"
        "  });\n}\n",
        encoding="utf-8",
    )


def read_pi_prompt(data_root: Path, pane_id: str) -> dict[str, Any] | None:
    for path in (data_root / "prompts").glob("*.json"):
        try:
            value = read_json(path)
        except (OSError, ValueError):
            continue
        if value.get("pane_id") == pane_id:
            return value
    return None


def read_latest_pi_record(data_root: Path, pane_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    entry = None
    latest_path = data_root / "latest.json"
    if not latest_path.exists():
        return None, None
    for item in read_json(latest_path).get("sources", []):
        if item.get("source_kind") != "pi-session":
            continue
        try:
            _path, record = find_record(data_root, item.get("latest_success_id", ""))
        except ProofFailure:
            record = None
        if record and record.get("pane_id") == pane_id:
            entry = item
            break
    if not entry:
        return None, None
    try:
        _path, latest = find_record(data_root, entry.get("latest_success_id", ""))
    except ProofFailure:
        latest = None
    try:
        _path, attempt = find_record(data_root, entry.get("last_attempt_id", ""))
    except ProofFailure:
        attempt = None
    return latest, attempt


def scenario_pi_grouped(run_id: str, base: Path | None) -> dict[str, Any]:
    root, state, env = load_run(run_id, base)
    if not state.get("server_started") or not state.get("fixture", {}).get("pi_pane_id"):
        raise ProofBlocked("isolated server/Pi fixture is not ready")
    if not state.get("wide_proof_passed"):
        raise ProofBlocked("run herdr-wide first on this same isolated server")
    state["fixture"].get("overview_pane_id") or (_ for _ in ()).throw(ProofFailure("overview pane is missing"))
    provider, provider_state, provider_thread, provider_url = start_scripted_provider()
    pi_bin = shutil.which("pi")
    if not pi_bin:
        provider.shutdown()
        raise ProofBlocked("Pi is not installed; the settlement journey cannot run")
    provider_extension = root / "scripted-pi-provider.mjs"
    make_pi_provider_extension(provider_extension)
    real_pi = pi_bin
    write_exec(root / "bin/pi", "#!/bin/sh\nset -eu\n"
               "if [ -r \"$HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE\" ]; then\n"
               "  IFS= read -r HERDR_OVERVIEW_TEST_PROVIDER_URL < \"$HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE\"\n"
               "  export HERDR_OVERVIEW_TEST_PROVIDER_URL\n"
               "fi\n"
               f"exec {shlex.quote(real_pi)} \"$@\"\n")
    Path(env["HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE"]).write_text(provider_url + "\n", encoding="utf-8")
    env["HERDR_OVERVIEW_TEST_PROVIDER_URL"] = provider_url
    reply_path = Path(env["HERDR_OVERVIEW_PI_REPLY"])
    reply_path.write_text(provider_state.reply + "\n", encoding="utf-8")
    pane_id = state["fixture"]["pi_pane_id"]
    agent_name = "t8-proof-pi"
    try:
        herdr_cmd(state, env, "agent", "start", agent_name, "--kind", "pi", "--pane", pane_id,
                  "--timeout", "120000", "--", "--provider", "herdr-proof-scripted", "--model", "scripted-model",
                  "--extension", str(ROOT / "dot_pi/private_agent/extensions/herdr-overview/index.ts"),
                  "--extension", str(provider_extension), "--no-skills", "--no-prompt-templates", "--no-themes",
                  "--no-context-files", "--no-tools", "--offline", "--approve", "--session-dir", str(root / "pi-sessions"),
                  "--session-id", f"herdr-proof-{run_id}", timeout=130)
        current_prompt = f"Proof request {run_id}: inspect the current parser and report the completed work."
        prompt_process = subprocess.Popen(
            [state["herdr_bin"], "agent", "prompt", agent_name, current_prompt, "--wait", "--timeout", "120000"],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if not provider_state.started.wait(60):
            raise ProofFailure("the scripted provider did not receive Pi's prompt")
        data_root = root / "data/session-recap"
        working_prompt = wait_for(lambda: read_pi_prompt(data_root, pane_id), "Pi's current prompt publication", timeout=20)
        if working_prompt.get("text") != current_prompt or working_prompt.get("working") is not True:
            raise ProofFailure("the current Pi prompt was not published separately while the agent was working")
        def current_prompt_in_model() -> dict[str, Any] | None:
            model = plugin_state(root).get("model") or {}
            pane = (model.get("panes") or {}).get(pane_id) or {}
            prompt = pane.get("prompt") or {}
            return prompt if prompt.get("text") == current_prompt else None

        wait_for(current_prompt_in_model, "the current prompt to reach the overview model through pane updates", timeout=30)
        pi_workspace = state["fixture"]["workspaces"][0]
        select_workspace(state, env, pi_workspace)
        overview_text_value = open_pane_from_workspace(state, env, pane_id)
        if current_prompt not in overview_text_value or "CURRENT PI PROMPT" not in overview_text_value:
            raise ProofFailure("the live selected-pane view omitted the current Pi prompt")

        provider_state.release_first.set()
        try:
            out, err = prompt_process.communicate(timeout=140)
        except subprocess.TimeoutExpired:
            prompt_process.kill()
            out, err = prompt_process.communicate()
            raise ProofFailure("Herdr agent prompt did not settle after the scripted response")
        if prompt_process.returncode != 0:
            raise ProofFailure(f"Herdr Pi prompt failed: {bounded(out + err)}")
        first_latest, first_attempt = wait_for(
            lambda: (lambda pair: pair if pair[0] and pair[0].get("status") == "published" else None)(read_latest_pi_record(data_root, pane_id)),
            "published settled Pi recap",
            timeout=35,
        )
        if first_latest.get("summary") != SUCCESS_SUMMARY or first_latest.get("workspace_id") != state["fixture"]["workspaces"][0]["workspace_id"]:
            raise ProofFailure("settled Pi recap is missing or has incorrect publication-time workspace attribution")
        first_workspace_id = first_latest["workspace_id"]
        recap_state_path = overview_state_path(root)
        after_publish_state = wait_for(
            lambda: ((read_json(recap_state_path).get("recapCoordinator") or {}).get("workspaceDeadlines") or {}).get(first_workspace_id),
            "the first workspace quiet deadline",
            timeout=20,
        )
        expected_deadline = datetime.fromisoformat(first_latest["published_at"].replace("Z", "+00:00")).timestamp() + 30
        actual_deadline = datetime.fromisoformat(after_publish_state.replace("Z", "+00:00")).timestamp()
        if abs(actual_deadline - expected_deadline) > 2:
            raise ProofFailure("successful Pi publication did not start the exact 30-second workspace interval")
        if not provider_state.prompts or "Proof request" not in provider_state.prompts[0]:
            raise ProofFailure("the real Pi session did not use the scripted response provider")

        # A second settled Pi response gets blank T1 output. It must neither
        # replace the first good session recap nor move the quiet deadline.
        Path(env["FAKE_RECAP_MODE_FILE"]).write_text("blank\n", encoding="utf-8")
        provider_state.release_first.set()
        second_prompt = f"Proof request {run_id}: this recap backend will return blank output."
        second = herdr_cmd(state, env, "agent", "prompt", agent_name, second_prompt, check=False, timeout=15)
        if second.returncode != 0:
            raise ProofFailure(f"second Pi prompt was not submitted: {bounded(second.stderr)}")
        second_latest, second_attempt = wait_for(
            lambda: (lambda pair: pair if pair[1] and pair[1].get("status") == "failed" else None)(read_latest_pi_record(data_root, pane_id)),
            "blank recap failure record after the settled second response",
            timeout=30,
        )
        Path(env["FAKE_RECAP_MODE_FILE"]).write_text("success\n", encoding="utf-8")
        if second_latest.get("record_id") != first_latest.get("record_id"):
            raise ProofFailure("failed recap replaced the latest successful Pi recap")
        state_after_failure = read_json(recap_state_path)
        deadline_after_failure = ((state_after_failure.get("recapCoordinator") or {}).get("workspaceDeadlines") or {}).get(first_workspace_id)
        if deadline_after_failure != after_publish_state:
            raise ProofFailure("failed recap reset the 30-second quiet deadline")
        due = datetime.fromisoformat(after_publish_state.replace("Z", "+00:00")).timestamp()
        time_left = due - time.time()
        if time_left > 0:
            time.sleep(time_left + 0.8)
        def grouped() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            latest_workspace = latest_entry(data_root, "workspace", first_workspace_id)
            latest_session = latest_entry(data_root, "herdr-session", "active")
            if not latest_workspace or not latest_session:
                return (None, None)
            try:
                _, workspace_record = find_record(data_root, latest_workspace.get("latest_success_id", ""))
                _, session_record = find_record(data_root, latest_session.get("latest_success_id", ""))
            except ProofFailure:
                return (None, None)
            if workspace_record.get("status") == "published" and session_record.get("status") == "published":
                return workspace_record, session_record
            return (None, None)
        workspace_record, session_record = wait_for(grouped, "30-second workspace and session group publication", timeout=40)
        workspace_published = datetime.fromisoformat(workspace_record["published_at"].replace("Z", "+00:00")).timestamp()
        if workspace_published < due - 2:
            raise ProofFailure("workspace recap appeared before the persisted quiet deadline")
        if first_latest["record_id"] not in workspace_record.get("member_record_ids", []):
            raise ProofFailure("workspace recap did not retain the Pi member recap ID")
        if workspace_record["record_id"] not in session_record.get("member_record_ids", []):
            raise ProofFailure("session recap did not retain the workspace recap ID")
        def session_recap_in_model() -> dict[str, Any] | None:
            value = read_json(recap_state_path)
            latest = ((value.get("model") or {}).get("recap") or {}).get("latest") or {}
            return value if latest.get("record_id") == session_record["record_id"] else None

        state_now = wait_for(session_recap_in_model, "session recap publication in the overview model", timeout=20)
        # All-workspaces overview must display the current session recap, not only
        # leave it in the backing JSON store.
        overview_id = state["fixture"]["overview_pane_id"]
        send_overview_key(state, env, "esc")
        send_overview_key(state, env, "esc")
        invoke_overview(state, env)
        visible = pane_text(state, env, overview_id, fmt="ansi", lines=260)
        plain = __import__("re").sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", visible)
        if session_record["summary"] not in plain:
            raise ProofFailure("all-workspaces overview did not display the published Herdr-session recap")
        return {
            "pi_pane_id": pane_id,
            "pi_session_id": first_latest["source_id"],
            "current_prompt_visible_while_working": True,
            "pi_recap_id": first_latest["record_id"],
            "workspace_recap_id": workspace_record["record_id"],
            "session_recap_id": session_record["record_id"],
            "quiet_period_seconds": round(workspace_published - datetime.fromisoformat(first_latest["published_at"].replace("Z", "+00:00")).timestamp(), 1),
            "failed_recap_preserved_latest_and_deadline": True,
            "overview_displays_session_recap": True,
            "response_provider": "scripted local OpenAI-compatible SSE provider",
        }
    finally:
        provider_state.release_first.set()
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=3)
        # If an unexpected error leaves the prompt CLI alive, stop only that
        # child launched by this scenario. Herdr's isolated server is retained
        # for explicit herdr-cleanup.
        try:
            if "prompt_process" in locals() and prompt_process.poll() is None:
                prompt_process.terminate()
                prompt_process.wait(timeout=5)
        except Exception:
            pass


def validate_phone_receipt(root: Path, run_id: str) -> dict[str, Any]:
    path = root / "phone-receipt.json"
    if not path.is_file():
        raise ProofBlocked(
            "no receipt returned from the Termux phone route; run ~/bin/herdr-overview-proof "
            f"{run_id} macbook on the attended phone. A narrow local PTY is not phone proof."
        )
    receipt = read_json(path)
    if receipt.get("run_id") != run_id or receipt.get("schema_version") != 1:
        raise ProofFailure("phone receipt does not match this isolated proof run")
    if receipt.get("route") != "phone-to-desktop-ssh" or receipt.get("terminal") != "termux":
        raise ProofFailure("phone receipt does not prove the declared Termux-over-SSH control route")
    route = read_json(root / "phone-client.json") if (root / "phone-client.json").is_file() else {}
    if route.get("run_id") != run_id or route.get("exit_code") != 0:
        raise ProofFailure("the attached Herdr client route did not finish successfully")
    if route.get("terminal_columns", 999) > 64:
        raise ProofBlocked("the phone route was not narrow (terminal width is above 64); do not substitute width emulation")
    if not route.get("journey_attested"):
        raise ProofFailure("the attended phone user did not confirm Board/workspace/detail/focus navigation")
    expected_pane = read_json(root / PROOF_MARKER)["fixture"]["pi_pane_id"]
    if route.get("focused_pane_id") != expected_pane:
        raise ProofFailure("phone focus did not reach the actual selected native Pi pane")
    reviews = receipt.get("reviews", {})
    reply = reviews.get("whole_reply", {})
    pane = reviews.get("recent_pane_output", {})
    if not REVIEW_ID_RE.fullmatch(str(reply.get("review_id", ""))) or int(reply.get("pending_note_count", 0)) < 2:
        raise ProofFailure("phone did not save multiple passage notes against the complete Pi reply")
    if not NOTE_ID_RE.fullmatch(str(reply.get("exported_note_id", ""))):
        raise ProofFailure("phone did not selectively export a pending reply note")
    if not REVIEW_ID_RE.fullmatch(str(pane.get("review_id", ""))) or int(pane.get("pending_note_count", 0)) < 1:
        raise ProofFailure("phone did not create a review from recent Herdr pane output inside the reviewer")
    if not NOTE_ID_RE.fullmatch(str(pane.get("exported_note_id", ""))) or not receipt.get("snapshot_and_pending_state_unchanged"):
        raise ProofFailure("phone pane-output review did not preserve its snapshot/pending state after export")
    if receipt.get("status") != "PASS":
        raise ProofBlocked(receipt.get("reason") or "Termux helper returned a non-PASS phone receipt")
    return {"phone_receipt": str(path), "terminal_columns": route["terminal_columns"],
            "focused_pane_id": route["focused_pane_id"], "whole_reply_review_id": reply["review_id"],
            "pane_output_review_id": pane["review_id"], "phone_to_desktop_ssh_receipt": True}


def phone_client(run_id: str, base: Path | None) -> int:
    root, state, env = load_run(run_id, base)
    columns, rows = shutil.get_terminal_size(fallback=(0, 0))
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ProofBlocked("phone-client must run through an interactive SSH PTY from Termux")
    if columns <= 0 or rows <= 0:
        raise ProofBlocked("SSH did not provide real Termux terminal dimensions")
    print(json.dumps({"proof": "herdr-overview-phone-client", "run_id": run_id,
                      "terminal_columns": columns, "terminal_rows": rows,
                      "expected_pi_pane_id": state["fixture"]["pi_pane_id"]}), flush=True)
    if columns > 64:
        print("BLOCKED: this phone SSH terminal is wider than the Board threshold; do not resize/emulate it.", flush=True)
    print("Open Herdr Overview. Visit every Proof workspace, its tabs/panes, open the Pi pane detail, and press f to focus it.", flush=True)
    print(f"Expected selected native Pi pane: {state['fixture']['pi_pane_id']}", flush=True)
    print("Quit the Herdr client only after that phone journey, then confirm below.", flush=True)
    completed = subprocess.run([state["herdr_bin"]], env=env, check=False)
    focused: str | None = None
    if completed.returncode == 0:
        try:
            focused = snapshot(state).get("focused_pane_id")
        except Exception:
            focused = None
    if columns <= 64 and completed.returncode == 0 and focused == state["fixture"]["pi_pane_id"]:
        print("Did you reach every workspace/tab/pane in the Board and read the whole Pi reply in detail? [y/N] ", end="", flush=True)
        answer = sys.stdin.readline().strip().lower()
        attested = answer in ("y", "yes")
    else:
        attested = False
    route = {
        "schema_version": 1,
        "run_id": run_id,
        "route": "phone-to-desktop-ssh",
        "terminal_columns": columns,
        "terminal_rows": rows,
        "exit_code": completed.returncode,
        "focused_pane_id": focused,
        "journey_attested": attested,
        "returned_at": utc_now(),
    }
    json_dump(root / "phone-client.json", route)
    print("HERDR_OVERVIEW_PHONE_ROUTE=" + json.dumps(route, sort_keys=True), flush=True)
    if columns > 64:
        return 2
    if completed.returncode != 0 or not attested or focused != state["fixture"]["pi_pane_id"]:
        return 1
    return 0


def phone_source(run_id: str, kind: str, base: Path | None) -> None:
    root, state, env = load_run(run_id, base)
    if kind == "pi-reply":
        path = Path(env["HERDR_OVERVIEW_PI_REPLY"])
        if not path.is_file():
            raise ProofBlocked("scripted Pi response is not available; run pi-grouped first")
        text = path.read_text(encoding="utf-8")
    elif kind == "pane-output":
        pane_id = state["fixture"]["non_pi_pane_id"]
        text = pane_text(state, env, pane_id, source="recent-unwrapped", lines=60)
        if "T8 proof output:" not in text:
            raise ProofFailure("isolated Herdr pane has no fixture output to review")
        text = f"Herdr pane {pane_id} recent output\n{text}"
    else:
        raise ProofFailure(f"unknown phone review source: {kind}")
    if not text.strip() or len(text.encode("utf-8")) > 250_000:
        raise ProofFailure("phone source is empty or exceeds the bounded transfer size")
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")


def phone_record(args: argparse.Namespace, base: Path | None) -> int:
    root, state, _env = load_run(args.run_id, base)
    route_path = root / "phone-client.json"
    route = read_json(route_path) if route_path.is_file() else {}
    reply_ids = args.reply_note_ids.split(",") if args.reply_note_ids else []
    pane_ids = args.pane_note_ids.split(",") if args.pane_note_ids else []
    receipt = {
        "schema_version": 1,
        "run_id": args.run_id,
        "route": "phone-to-desktop-ssh",
        "terminal": "termux",
        "status": args.status,
        "reason": args.reason or None,
        "reviews": {
            "whole_reply": {"review_id": args.reply_review_id, "pending_note_count": args.reply_note_count,
                            "exported_note_id": args.reply_exported_note_id, "note_ids": reply_ids},
            "recent_pane_output": {"review_id": args.pane_review_id, "pending_note_count": args.pane_note_count,
                                    "exported_note_id": args.pane_exported_note_id, "note_ids": pane_ids},
        },
        "snapshot_and_pending_state_unchanged": args.snapshot_unchanged,
        "received_at": utc_now(),
    }
    json_dump(root / "phone-receipt.json", receipt)
    # Bounded machine-readable receipt returned over the phone-to-desktop SSH route.
    print(json.dumps({"command_id": SCENARIO_COMMANDS["termux-ssh"], "status": args.status,
                      "run_id": args.run_id, "receipt": "phone-receipt.json",
                      "terminal_columns": route.get("terminal_columns")}, sort_keys=True), flush=True)
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[args.status]


def maybe_start_adb(serial: str, run_id: str) -> None:
    adb = shutil.which("adb")
    if not adb:
        raise ProofBlocked("ADB is not installed; use an attended physical Termux phone instead")
    if not serial or not __import__("re").fullmatch(r"[A-Za-z0-9._:-]{1,128}", serial):
        raise ProofFailure("invalid explicit ADB serial")
    state = run_process([adb, "-s", serial, "get-state"], check=False, timeout=10)
    if state.returncode or state.stdout.strip() != "device":
        raise ProofBlocked(f"ADB serial {serial!r} is not an attached device")
    package = run_process([adb, "-s", serial, "shell", "pm", "path", "com.termux"], check=False, timeout=10)
    if package.returncode or "package:" not in package.stdout:
        raise ProofBlocked("Termux is not installed on this ADB device; the proof will not install or push dotfiles/config")
    # This is UI control only. It never uses adb push, scp, app-data access, or
    # host-generated Termux config; the phone's own chezmoi profile owns the helper.
    launched = run_process([adb, "-s", serial, "shell", "monkey", "-p", "com.termux", "1"], check=False, timeout=15)
    if launched.returncode != 0:
        launched = run_process([adb, "-s", serial, "shell", "am", "start", "-n", "com.termux/.app.TermuxActivity"],
                               check=False, timeout=15)
    if launched.returncode != 0:
        raise ProofBlocked("could not open Termux on the explicitly selected ADB device")
    time.sleep(3)
    command = f"~/bin/herdr-overview-proof%20{run_id}%20macbook"
    typed = run_process([adb, "-s", serial, "shell", "input", "text", command], check=False, timeout=10)
    entered = run_process([adb, "-s", serial, "shell", "input", "keyevent", "66"], check=False, timeout=10)
    if typed.returncode != 0 or entered.returncode != 0:
        raise ProofBlocked("ADB could not type the phone-owned helper into Termux")


def scenario_termux_ssh(run_id: str, base: Path | None, adb_serial: str | None) -> dict[str, Any]:
    root, _state, _env = load_run(run_id, base)
    if adb_serial:
        maybe_start_adb(adb_serial, run_id)
        route_path = root / "phone-client.json"
        try:
            wait_for(lambda: route_path.is_file(), "the attended Termux Herdr client journey", timeout=900, interval=2)
        except ProofFailure as exc:
            raise ProofBlocked("ADB opened Termux but the phone did not return from the Herdr journey within 15 minutes") from exc
        route = read_json(route_path)
        if route.get("terminal_columns", 999) > 64 or route.get("exit_code") != 0 or not route.get("journey_attested"):
            return validate_phone_receipt(root, run_id)
        receipt_path = root / "phone-receipt.json"
        try:
            wait_for(lambda: receipt_path.is_file(), "the attended Termux review receipt", timeout=900, interval=2)
        except ProofFailure as exc:
            raise ProofBlocked("ADB-controlled phone review did not return its SSH receipt within 15 minutes") from exc
    return validate_phone_receipt(root, run_id)


def scenario_cleanup(run_id: str, base: Path | None) -> dict[str, Any]:
    root, state, env = load_run(run_id, base)
    root_resolved = root.resolve()
    expected_root = run_root(run_id, base).resolve()
    if root_resolved != expected_root or root_resolved.name != run_id:
        raise ProofFailure("refusing cleanup outside the exact recorded isolated run directory")
    marker = read_json(root / PROOF_MARKER)
    if marker.get("run_id") != run_id or Path(marker.get("root", "")).resolve() != root_resolved:
        raise ProofFailure("cleanup marker does not match the isolated run directory")
    expected_socket = (root / "server/herdr.sock").resolve()
    if Path(marker.get("socket_path", "")).resolve() != expected_socket:
        raise ProofFailure("cleanup refused a socket not owned by this test run")
    info = server_status(state, env)
    if info.get("running"):
        if info.get("socket") != str(expected_socket):
            raise ProofFailure("cleanup refused to stop a server on a non-test socket")
        herdr_cmd(state, env, "server", "stop", timeout=20)
        wait_for(lambda: not server_status(state, env).get("running"), "the isolated server to stop", timeout=20)
    elif info.get("socket") not in (None, str(expected_socket)):
        raise ProofFailure("cleanup found a server status for a non-test socket")
    # A live isolated socket after stop means cleanup must fail closed; preserve
    # the record for inspection instead of deleting config under a live server.
    if Path(expected_socket).exists():
        try:
            api_request(state, "session.snapshot", timeout=1)
        except ProofBlocked:
            pass
        else:
            raise ProofFailure("isolated Herdr socket still responds after stop")
    shutil.rmtree(root)
    return {"run_id": run_id, "isolated_server_stopped": True, "temporary_root_removed": True,
            "owner_server_touched": False, "stopped_socket": str(expected_socket)}


def scenario_chezmoi() -> dict[str, Any]:
    binary = shutil.which("chezmoi")
    if not binary:
        raise ProofBlocked("chezmoi is not installed")
    desktop_targets = [
        "~/.config/mise/config.toml",
        "~/.config/herdr/config.toml",
        "~/.config/session-recap",
        "~/.local/bin/session-recap",
        "~/.local/share/session-recap",
        "~/.local/bin/passage-review",
        "~/.local/share/passage-review",
        "~/.local/share/herdr-overview",
        "~/.local/share/agent-harness/canonical/skills/herdr/SKILL.md",
        "~/.pi/agent/extensions/README.md",
        "~/.pi/agent/extensions/herdr-overview",
        "~/.pi/agent/extensions/passage-review",
    ]
    mappings: dict[str, str] = {}
    for dest in desktop_targets:
        mapped = run_process([binary, "source-path", dest], check=False, timeout=10)
        if mapped.returncode == 0 and mapped.stdout.strip():
            mappings[dest] = mapped.stdout.strip()
    if not mappings:
        raise ProofFailure("chezmoi did not map any requested desktop destinations to source")
    data = run_process([binary, "data", "--format", "json"], check=False, timeout=20)
    if data.returncode != 0:
        raise ProofFailure(f"could not read the active chezmoi profile: {bounded(data.stderr)}")
    try:
        data_value = json.loads(data.stdout)
        current_profile = data_value.get("profile") or data_value.get("data", {}).get("profile") \
            or data_value.get("chezmoi", {}).get("config", {}).get("data", {}).get("profile")
    except json.JSONDecodeError as exc:
        raise ProofFailure("chezmoi data did not return JSON") from exc
    dry_run = run_process([binary, "apply", "--dry-run", "--verbose", "--no-tty", *desktop_targets],
                          check=False, timeout=120)
    if dry_run.returncode != 0:
        raise ProofFailure(f"targeted chezmoi dry-run failed: {bounded(dry_run.stdout + dry_run.stderr)}")
    ignore = (ROOT / ".chezmoiignore").read_text(encoding="utf-8")
    if "./tests/" not in ignore and "tests/herdr-overview" not in ignore:
        raise ProofFailure("source-only proof tree is not excluded from chezmoi deployment")
    if not (ROOT / "tests/herdr-overview/fake_recap_backend.py").is_file():
        raise ProofFailure("source-only fake recap backend is missing")
    rendered_profiles: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="herdr-proof-profile-") as temp:
        tmp = Path(temp)
        for profile in ("personal", "axon-work-computer"):
            override = tmp / f"{profile}.json"
            override.write_text(json.dumps({"profile": profile}) + "\n", encoding="utf-8")
            rendered = run_process([binary, "--override-data-file", str(override), "execute-template", "{{ .profile }}"],
                                  check=False, timeout=20)
            if rendered.returncode != 0 or rendered.stdout.strip() != profile:
                raise ProofFailure(f"could not render the {profile} profile template")
            template = run_process([binary, "--override-data-file", str(override), "execute-template", "--file",
                                    str(ROOT / "dot_config/session-recap/config.toml.tmpl")],
                                   check=False, timeout=20)
            if template.returncode != 0 or "command =" not in template.stdout:
                raise ProofFailure(f"could not render session-recap defaults for {profile}")
            rendered_profiles[profile] = template.stdout
    profile_paths: dict[str, list[str]] = {}
    with tempfile.TemporaryDirectory(prefix="herdr-proof-profile-map-") as temp:
        tmp = Path(temp)
        for profile in ("personal", "axon-work-computer", "termux"):
            override = tmp / f"{profile}.json"
            override.write_text(json.dumps({"profile": profile}) + "\n", encoding="utf-8")
            destination = tmp / profile
            destination.mkdir()
            managed = run_process([
                binary, "--source", str(ROOT), "--destination", str(destination),
                "--override-data-file", str(override), "managed", "--path-style", "relative", "--no-tty",
            ], check=False, timeout=30)
            if managed.returncode != 0:
                raise ProofFailure(f"could not inspect chezmoi managed paths for {profile}: {bounded(managed.stderr)}")
            paths = managed.stdout.splitlines()
            profile_paths[profile] = paths
            if any(path == "tests" or path.startswith("tests/") for path in paths):
                raise ProofFailure(f"source-only proof files would deploy in {profile}")
            if profile == "termux":
                if "bin/herdr-overview-proof" not in paths or "bin/passage-review" not in paths:
                    raise ProofFailure("Termux profile does not own the phone-side helper/reviewer sources")
                if any(path == ".config" or path.startswith(".config/") for path in paths):
                    raise ProofFailure("Termux profile unexpectedly includes desktop .config files")
                if any(path == ".pi" or path.startswith(".pi/") for path in paths):
                    raise ProofFailure("Termux profile unexpectedly includes desktop Pi extensions")
                if any(path == ".local/share/session-recap" or path.startswith(".local/share/session-recap/") for path in paths):
                    raise ProofFailure("Termux profile unexpectedly includes the desktop recap producer")
            else:
                if "bin/herdr-overview-proof" in paths:
                    raise ProofFailure(f"Termux-only proof helper leaked into the {profile} desktop profile")
                if not any(path.startswith(".pi/agent/extensions/herdr-overview/") for path in paths):
                    raise ProofFailure(f"{profile} profile omits the desktop Pi publication adapter")
    for profile, rendered in rendered_profiles.items():
        if "claude" not in rendered:
            raise ProofFailure(f"{profile} session-recap default did not render a configured command")
    return {"targeted_dry_run": True, "current_profile": current_profile,
            "desktop_mappings_checked": mappings, "rendered_profiles": list(rendered_profiles),
            "profile_paths_checked": {profile: len(paths) for profile, paths in profile_paths.items()},
            "source_only_tests_excluded": True, "real_apply": False}


def scenario_result(args: argparse.Namespace) -> int:
    scenario = args.scenario
    command_id = SCENARIO_COMMANDS.get(scenario)
    if not command_id:
        return result("unknown", scenario, "FAIL", reason="unknown scenario")
    try:
        if scenario == "recap":
            details = scenario_recap()
            return result(command_id, scenario, "PASS", **details)
        if scenario == "review":
            details = scenario_review()
            return result(command_id, scenario, "PASS", **details)
        if scenario == "herdr-prepare":
            args.run_id = args.run_id or make_run_id()
            run_id, details = scenario_herdr_prepare(args.run_id, args.state_base)
            return result(command_id, scenario, "PASS", **details)
        if scenario == "herdr-wide":
            if not args.run_id:
                raise ProofBlocked("herdr-wide requires the run ID printed by herdr-prepare")
            root, state, env = load_run(args.run_id, args.state_base)
            details = navigate_wide_fixture(state, env)
            state["wide_proof_passed"] = True
            state["wide_proof_at"] = utc_now()
            json_dump(root / PROOF_MARKER, state)
            return result(command_id, scenario, "PASS", run_id=args.run_id, **details)
        if scenario == "pi-grouped":
            if not args.run_id:
                raise ProofBlocked("pi-grouped requires the run ID printed by herdr-prepare")
            return result(command_id, scenario, "PASS", run_id=args.run_id,
                          **scenario_pi_grouped(args.run_id, args.state_base))
        if scenario == "termux-ssh":
            if not args.run_id:
                raise ProofBlocked("termux-ssh requires the run ID printed by herdr-prepare")
            details = scenario_termux_ssh(args.run_id, args.state_base, args.adb_serial)
            return result(command_id, scenario, "PASS", run_id=args.run_id, **details)
        if scenario == "herdr-cleanup":
            if not args.run_id:
                raise ProofBlocked("herdr-cleanup requires the run ID printed by herdr-prepare")
            return result(command_id, scenario, "PASS", **scenario_cleanup(args.run_id, args.state_base))
        if scenario == "chezmoi-dry-run":
            return result(command_id, scenario, "PASS", **scenario_chezmoi())
        return result(command_id, scenario, "FAIL", reason="unimplemented scenario")
    except ProofBlocked as exc:
        return result(command_id, scenario, "BLOCKED", run_id=args.run_id, reason=str(exc))
    except ProofFailure as exc:
        return result(command_id, scenario, "FAIL", run_id=args.run_id, reason=str(exc))
    except Exception as exc:
        return result(command_id, scenario, "FAIL", run_id=args.run_id,
                      reason=f"{type(exc).__name__}: {bounded(str(exc), 2500)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", choices=[*SCENARIO_COMMANDS, "phone-client", "phone-source", "phone-record"])
    parser.add_argument("--run-id")
    parser.add_argument("--state-base", type=Path, help="override the private cache root; must be reused for every scenario")
    parser.add_argument("--adb-serial", help="explicit attached ADB emulator serial; UI input only, no app/config push")
    parser.add_argument("--kind", choices=("pi-reply", "pane-output"))
    parser.add_argument("--status", choices=("PASS", "FAIL", "BLOCKED"))
    parser.add_argument("--reason", default="")
    parser.add_argument("--reply-review-id", default="")
    parser.add_argument("--reply-note-count", type=int, default=0)
    parser.add_argument("--reply-note-ids", default="")
    parser.add_argument("--reply-exported-note-id", default="")
    parser.add_argument("--pane-review-id", default="")
    parser.add_argument("--pane-note-count", type=int, default=0)
    parser.add_argument("--pane-note-ids", default="")
    parser.add_argument("--pane-exported-note-id", default="")
    parser.add_argument("--snapshot-unchanged", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.scenario:
        build_parser().print_help()
        return 0
    if args.scenario == "phone-client":
        if not args.run_id:
            print(json.dumps({"status": "FAIL", "reason": "phone-client requires --run-id"}))
            return 1
        try:
            return phone_client(args.run_id, args.state_base)
        except ProofBlocked as exc:
            print("BLOCKED: " + str(exc), flush=True)
            return 2
        except (ProofFailure, Exception) as exc:
            print("FAIL: " + str(exc), flush=True)
            return 1
    if args.scenario == "phone-source":
        if not args.run_id or not args.kind:
            print("phone-source requires --run-id and --kind", file=sys.stderr)
            return 1
        try:
            phone_source(args.run_id, args.kind, args.state_base)
            return 0
        except Exception as exc:
            print(f"phone-source: {exc}", file=sys.stderr)
            return 1
    if args.scenario == "phone-record":
        if not args.run_id or not args.status:
            print("phone-record requires --run-id and --status", file=sys.stderr)
            return 1
        try:
            return phone_record(args, args.state_base)
        except ProofBlocked as exc:
            print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), flush=True)
            return 2
        except Exception as exc:
            print(json.dumps({"status": "FAIL", "reason": str(exc)}), flush=True)
            return 1
    return scenario_result(args)


if __name__ == "__main__":
    raise SystemExit(main())
