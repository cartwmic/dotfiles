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
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_COMMANDS = {
    "recap": "proof-recap-cli",
    "review": "proof-review-lifecycle",
    "herdr-prepare": "proof-herdr-isolated-start",
    "herdr-wide": "proof-herdr-wide-journey",
    "pi-grouped": "proof-pi-grouped-journey",
    "herdr-native-move": "proof-herdr-native-move-journey",
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


def pi_pane_workspace_at_publication(env: dict[str, str], pane_id: str) -> str | None:
    node = shutil.which("node", path=env.get("PATH"))
    if not node:
        raise ProofBlocked("Node.js is required to run the Pi publication membership helper")
    helper = ROOT / "dot_pi/private_agent/extensions/herdr-overview/helpers.ts"
    helper_env = dict(env)
    helper_env["HERDR_OVERVIEW_PROOF_PANE_ID"] = pane_id
    helper_env["HERDR_OVERVIEW_PI_HELPERS"] = str(helper)
    script = """import { pathToFileURL } from 'node:url';
const { paneWorkspaceAtPublication } = await import(pathToFileURL(process.env.HERDR_OVERVIEW_PI_HELPERS));
const workspaceId = await paneWorkspaceAtPublication(process.env.HERDR_SOCKET_PATH, process.env.HERDR_OVERVIEW_PROOF_PANE_ID);
process.stdout.write(JSON.stringify(workspaceId));
"""
    completed = run_process(
        [node, "--input-type=module", "-e", script], env=helper_env, cwd=ROOT, timeout=10,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProofFailure("Pi membership helper did not return JSON") from exc
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ProofFailure("Pi membership helper returned an invalid workspace ID")
    return value


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

        # Exercise generic records/annotations and preserved group creation.
        # Pi policy is not imported; overview consumes records, not lifecycle commands.
        pi_ids: list[str] = []
        for suffix in ("a", "b"):
            metadata = {"pi": {"sessionId": f"proof-pi-{suffix}", "historyId": f"history-{suffix}"}}
            published = cli_recap(home, env, "create", "--kind", "single", "--source-kind", "pi",
                                  "--source-id", f"history-{suffix}", "--metadata-json", json.dumps(metadata),
                                  stdin=f"Pi response {suffix}.\n").stdout.strip()
            attribution = {"pane_id": f"pane-{suffix}", "workspace_id": "workspace-proof"}
            cli_recap(home, env, "annotate", published, "--namespace", "herdr",
                      "--metadata-json", json.dumps(attribution))
            _path, record = find_record(data_dir, published)
            if record.get("annotations", {}).get("herdr") != attribution or record.get("metadata") != metadata:
                raise ProofFailure("Generic annotation lost membership or changed Pi metadata")
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


def pinned_herdr() -> tuple[str, str]:
    """Resolve the Herdr this source pins (or HERDR_OVERVIEW_PROOF_HERDR, to try a
    candidate before bumping) and require that its API meets the plugin's needs.
    Returns (binary, version)."""
    import tomllib
    pin = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text(encoding="utf-8"))["tools"]["github:herdrdev/herdr"]
    wanted = os.environ.get("HERDR_OVERVIEW_PROOF_HERDR") or pin
    mise = shutil.which("mise")
    if not mise:
        raise ProofBlocked("mise is required to resolve the pinned Herdr binary")
    located = run_process([mise, "where", f"github:herdrdev/herdr@{wanted}"], cwd=ROOT, check=False, timeout=20)
    if located.returncode != 0:
        raise ProofBlocked(f"Herdr {wanted} is not installed; run `mise install github:herdrdev/herdr@{wanted}`")
    binary = (Path(located.stdout.strip()) / "herdr").resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ProofBlocked(f"the Herdr {wanted} binary is missing: {binary}")
    version = run_process([str(binary), "--version"], cwd=ROOT, check=False, timeout=10)
    if version.returncode != 0 or version.stdout.strip() != f"herdr {wanted}":
        raise ProofFailure(f"mise resolved a Herdr binary other than {wanted}: {bounded(version.stdout or version.stderr, 200)}")
    check = run_process([shutil.which("node") or "node", str(ROOT / "dot_local/share/herdr-overview/check-herdr-api.mjs"), str(binary)],
                        cwd=ROOT, check=False, timeout=20)
    if check.returncode != 0:
        raise ProofBlocked(f"Herdr {wanted} does not meet the plugin's API needs: {bounded(check.stderr or check.stdout, 1000)}")
    return str(binary), wanted


def make_herdr_env(root: Path, herdr_binary: str) -> dict[str, str]:
    home = root / "home"
    config_home = root / "config"
    data_home = root / "data"
    state_home = root / "state"
    for path in (home, config_home / "herdr", data_home, state_home, root / "tmp", root / "server", root / "bin"):
        path.mkdir(parents=True, exist_ok=True)
    path_parts = [os.environ.get("PATH", "/usr/bin:/bin")]
    for executable in (shutil.which("node"), shutil.which("pi"), herdr_binary, sys.executable):
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
    # One literal socket identity across prepare/load and inherited publishers;
    # macOS /tmp is a symlink, not a distinct server membership.
    root = run_root(run_id, base).resolve()
    marker = root / PROOF_MARKER
    if root.exists():
        if marker.exists():
            raise ProofFailure(f"proof run already exists; use its run ID for the existing fixture: {root}")
        raise ProofFailure(f"refusing to reuse unmarked proof directory: {root}")
    herdr_binary, herdr_version = pinned_herdr()
    root.mkdir(parents=True, mode=0o700)
    env = make_herdr_env(root, herdr_binary)
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
        # Pinned presentation zone: overview shows recap/digest times in it.
        f"auto_publish = true\ntime_zone = \"UTC\"\ncommand = [{json.dumps(sys.executable)}, {json.dumps(str(fake))}, \"success\"]\n",
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
        "herdr_bin": herdr_binary,
        "herdr_version": herdr_version,
        "repo_root": str(ROOT.resolve()),
        "fixture": {"workspaces": [], "pi_pane_id": None, "non_pi_pane_id": None},
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
        raise ProofBlocked("Herdr is not installed; install the pinned desktop release first")
    version = run_process([herdr_bin, "--version"], env=link_env, cwd=ROOT, check=False)
    if version.returncode != 0 or version.stdout.strip() != f"herdr {herdr_version}":
        raise ProofBlocked(f"Herdr {herdr_version} is required; found {bounded(version.stdout or version.stderr, 200)}")
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
    env = make_herdr_env(root, state["herdr_bin"])
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
    expected = state.get("herdr_version", "0.9.1")
    if not isinstance(value, dict) or value.get("version") != expected:
        raise ProofFailure(f"isolated server is not the fixture's Herdr {expected}: {value!r}")
    return value


def server_status(state: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    completed = herdr_cmd(state, env, "status", "server", "--json", check=False)
    if completed.returncode != 0:
        return {"running": False, "raw": bounded(completed.stdout + completed.stderr, 800)}
    try:
        info = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ProofFailure("Herdr status did not return JSON") from exc
    socket_path = info.get("socket")
    if not isinstance(socket_path, str) or Path(socket_path).resolve() != Path(state["socket_path"]).resolve():
        raise ProofFailure("Herdr status resolved to a socket other than the recorded isolated socket")
    # Herdr may report /tmp while Python canonicalizes the same path as /private/tmp.
    info["socket"] = str(Path(socket_path).resolve())
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
        return state if state.get("model") is not None else None
    return wait_for(read, "the real overview model state", timeout=timeout)


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
            raise ProofBlocked("the pinned Herdr binary is not installed")
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
            info = wait_for(isolated_status, "the isolated Herdr server", timeout=25)
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
        if not info.get("running") or info.get("version") != state["herdr_version"]:
            raise ProofFailure(f"isolated Herdr server is not running {state['herdr_version']}: {info}")
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
            "manual_workspace_labels": [item["label"] for item in created],
            "manual_tab_labels": [f"Owner {item['label']} tab" for item in created],
        }
        herdr_cmd(state, env, "workspace", "focus", created[0]["workspace_id"])
        api_request(state, "plugin.action.invoke", {"action_id": "overview.reconcile"})
        wait_plugin_state(root)
        def fixture_ready() -> dict[str, Any] | None:
            live = snapshot(state)
            model = plugin_state(root).get("model") or {}
            if set((model.get("panes") or {}).keys()) != {p["pane_id"] for p in live["panes"]}:
                return None
            if set((model.get("workspaces") or {}).keys()) != {item["workspace_id"] for item in created}:
                return None
            return live

        live = wait_for(fixture_ready, "the full native pane set in the visible overview", timeout=30)
        if not (2 <= len(live.get("workspaces", [])) <= 5):
            raise ProofFailure("isolated fixture must have 2-5 workspaces")
        state.update({
            "server_started": True,
            "fixture": fixture,
            "server_version": state["herdr_version"],
            "server_protocol": info.get("protocol"),
            "prepared_at": utc_now(),
        })
        json_dump(root / PROOF_MARKER, state)
        def manual_labels_ready() -> bool | None:
            try:
                require_manual_names(state, env)
                return True
            except ProofFailure:
                return None
        wait_for(manual_labels_ready, "owner-set fixture names to settle after startup reconciliation", timeout=12)
        return run_id, {
            "run_id": run_id,
            "server_version": state["herdr_version"],
            "protocol": state["server_protocol"],
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


_POPUP_CLIENTS = {}


def popup_client(state, env):
    """Owned attached client: popup is session-shared and has no native pane ID."""
    from map_journey import Client
    import atexit
    key = state['socket_path']
    client = _POPUP_CLIENTS.get(key)
    if client is None or client.closed:
        client = Client(state, env, 180)
        _POPUP_CLIENTS[key] = client
        atexit.register(client.close)
        client.drain(1)
    return client


def send_overview_key(state: dict[str, Any], env: dict[str, str], key: str) -> None:
    keys = {'esc': b'\x1b', 'enter': b'\r', 'q': b'q'}
    popup_client(state, env).key(keys.get(key, key.encode()))


def invoke_overview(state: dict[str, Any], env: dict[str, str]) -> None:
    from map_identity import wait_frame
    client = popup_client(state, env)
    api_request(state, "plugin.action.invoke", {"action_id": "overview.open"})
    wait_frame(client, 'arrows/hjkl select', 'n blocked')


def invoke_auto_name(state: dict[str, Any], kind: str, native_id: str) -> None:
    if kind == "pane":
        context = {"focused_pane_id": native_id}
    elif kind == "tab":
        context = {"tab_id": native_id}
    else:
        raise ProofFailure(f"unsupported automatic-name target: {kind}")
    api_request(state, "plugin.action.invoke", {
        "action_id": f"overview.auto_name_{kind}",
        "context": context,
    })


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
    return popup_client(state, env).frame()


def prove_reopened_output(state: dict[str, Any], root: Path, env: dict[str, str]) -> dict[str, Any]:
    """Close/reopen the transient view, then read current supplied data and focus."""
    pane_id = state['fixture']['pi_pane_id']
    before = (plugin_state(root)['model']['panes'][pane_id].get('prompt') or {}).get('text')
    if not before:
        raise ProofFailure('reopen fixture has no actual supplied prompt')
    invoke_overview(state, env)
    send_overview_key(state, env, 'q')
    from map_journey import popup_busy
    busy, response = popup_busy(state)
    if busy:
        raise ProofFailure('closed popup remains busy')
    # The allocation probe is itself a popup; dismiss only that owned viewer.
    from map_identity import wait_frame
    wait_frame(popup_client(state, env), 'arrows/hjkl select')
    send_overview_key(state, env, 'q')
    invoke_overview(state, env)
    detail = open_pane_from_workspace(state, env, pane_id)
    if not current_prompt_detail_visible(detail, pane_id, before, native_snapshot=snapshot(state)):
        raise ProofFailure('reopened detail omitted current supplied prompt')
    send_overview_key(state, env, 'f')
    wait_for(lambda: snapshot(state)['focused_pane_id'] == pane_id, 'exact reopened native focus')
    return {'closed_then_ordinary_reopen': True, 'current_supplied_prompt_visible': True,
            'native_focus_confirmed': True, 'popup_has_no_native_pane_id': True}


def overview_location(text: str) -> tuple[str, str] | None:
    """Recognize a completed current canvas, excluding native chrome/history."""
    from map_frames import canvas, contains
    try:
        rows = canvas(plain_terminal(text))
    except ProofFailure:
        return None
    plain = '\n'.join(rows)
    if 'Latest good recap' in plain or 'Supplied prompt' in plain:
        return ('Map', 'detail')
    if 'Session digest' in plain:
        return ('Map', 'digest')
    return ('Map', 'all')


def published_recap_detail_visible(text: str, summary: str) -> bool:
    from map_frames import contains
    return (overview_location(text) == ('Map', 'detail') and contains(text, 'Latest good recap')
            and bool(summary.strip()) and contains(text, summary))


def current_prompt_detail_visible(text: str, pane_id: str, prompt: str, *, require_id: bool = True, native_snapshot=None) -> bool:
    from map_frames import contains
    return (overview_location(text) == ('Map', 'detail') and contains(text, 'Supplied prompt')
            and (not require_id or native_snapshot is not None and any(p.get('pane_id') == pane_id and contains(text, p.get('label') or '') for p in native_snapshot['panes']))
            and bool(prompt.strip()) and contains(text, prompt))


def open_pane_from_workspace(state: dict[str, Any], env: dict[str, str], pane_id: str,
                             match_detail: Callable[[str], bool] | None = None) -> str:
    from map_frames import selected_in_frame
    return_to_all_workspaces(state, env)
    live = snapshot(state)
    target = next((p for p in live['panes'] if p['pane_id'] == pane_id), None)
    if not target or not target.get('terminal_id') or sum(p.get('terminal_id') == target['terminal_id'] for p in live['panes']) != 1:
        raise ProofFailure(f'exact target lacks a unique current native terminal: {pane_id}')
    for _ in range(len(live['panes'])):
        collapsed = overview_text(state, env)
        if selected_in_frame(collapsed, pane_id, live):
            send_overview_key(state, env, 'enter')
            detail = overview_text(state, env)
            current = snapshot(state)
            if not any(p['pane_id'] == pane_id and p.get('terminal_id') == target['terminal_id'] for p in current['panes']):
                raise ProofFailure('selected native target changed during detail expansion')
            if match_detail is None or match_detail(detail):
                return detail
            send_overview_key(state, env, 'esc')
        send_overview_key(state, env, ']')
    raise ProofFailure(f'native map could not select exact pane {pane_id}')


def return_to_all_workspaces(state: dict[str, Any], env: dict[str, str]) -> str:
    invoke_overview(state, env)
    for _ in range(3):
        text = overview_text(state, env)
        location = overview_location(text)
        if location == ('Map', 'all'):
            return text
        if location not in (('Map', 'detail'), ('Map', 'digest')):
            raise ProofFailure('current native map canvas unavailable')
        send_overview_key(state, env, 'esc')
    raise ProofFailure('layered Escape failed to return to map')


def select_workspace(state: dict[str, Any], env: dict[str, str], workspace: dict[str, Any]) -> str:
    # The map has no workspace screen/preset. Select an actual member card.
    live = snapshot(state)
    target = next((p for p in live['panes'] if p['workspace_id'] == workspace['workspace_id']), None)
    if not target:
        raise ProofFailure('selected workspace has no live native pane')
    open_pane_from_workspace(state, env, target['pane_id'])
    send_overview_key(state, env, 'esc')
    return overview_text(state, env)


def focus_pane_from_workspace(state: dict[str, Any], env: dict[str, str], pane_id: str) -> None:
    detail = open_pane_from_workspace(state, env, pane_id)
    send_overview_key(state, env, "f")
    focused = snapshot(state).get("focused_pane_id")
    if focused != pane_id:
        raise ProofFailure(f"overview focus did not target native pane {pane_id}: {focused}")


def navigate_wide_fixture(state: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    from map_journey import log_digest, require_busy
    root = Path(state['root'])
    receipts = root / 'wide-receipts'; receipts.mkdir(exist_ok=True)
    require_manual_names(state, env)
    baseline = log_digest(root)
    live = snapshot(state)
    order = [p['pane_id'] for w in live['workspaces'] for t in live['tabs']
             if t['workspace_id'] == w['workspace_id'] for p in live['panes'] if p['tab_id'] == t['tab_id']]
    for pane_id in order:
        invoke_overview(state, env)
        require_busy(state, receipts, 'wide-popup-busy')
        detail = open_pane_from_workspace(state, env, pane_id)
        (receipts / f'{pane_id}-frame.txt').write_text(detail)
        send_overview_key(state, env, 'f')
        wait_for(lambda: snapshot(state)['focused_pane_id'] == pane_id, 'exact selected native focus')
    require_manual_names(state, env)
    # Preserve the old live-theme obligation on actual popup cells, not a
    # dedicated pane's accumulated ANSI output or the outer native chrome.
    config = Path(env['HERDR_CONFIG_PATH'])
    original_config = config.read_text()
    try:
        invoke_overview(state, env)
        config.write_text(original_config.replace('tokyo-night', 'dracula'))
        client = popup_client(state, env)
        def accented_current_header():
            frame = client.frame()
            for row, line in enumerate(frame.splitlines()):
                marker = 'Herdr Overview'
                if marker in line:
                    column = line.index(marker)
                    if client.screen.buffer[row][column].fg == 'bd93f9':
                        return frame
            return None
        frame = wait_for(accented_current_header, 'live popup Dracula accent cells', timeout=8)
        (receipts / 'live-theme-frame.txt').write_text(frame)
        send_overview_key(state, env, 'q')
    finally:
        config.write_text(original_config)
    if baseline != log_digest(root):
        raise ProofFailure('wide navigation generated recap/backend work')
    return {'all_native_panes_selected_in_order': order, 'native_focus_confirmed': True,
            'manual_names_preserved': True, 'theme_change_visible': True,
            'overview_did_not_run_recap': True, 'transient_native_popup': True}


def scripted_pi_reply() -> str:
    return "\n".join(
        [f"Scripted Pi proof reply, review line {index:02d}: deterministic response content."
         for index in range(1, 38)]
        + ["Present state: the scripted response is complete; no external model was called."]
    )


def provider_requests(root: Path) -> list[dict[str, Any]]:
    path = root / "scripted-provider-requests.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def start_scripted_provider(root: Path, env: dict[str, str]) -> dict[str, Any]:
    ready_path = root / "scripted-provider-ready.json"
    release_path = root / "scripted-provider-release-first"
    ready_path.unlink(missing_ok=True)
    release_path.unlink(missing_ok=True)
    log_path = root / "scripted-provider-server.log"
    provider_script = ROOT / "tests/herdr-overview/scripted_pi_provider.py"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, str(provider_script), "--root", str(root.resolve())],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def ready() -> dict[str, Any] | None:
        if process.poll() is not None:
            raise ProofFailure(f"scripted Pi provider exited early: {bounded(log_path.read_text(errors='replace'), 1000)}")
        if not ready_path.is_file():
            return None
        value = read_json(ready_path)
        if value.get("pid") != process.pid or value.get("root") != str(root.resolve()):
            raise ProofFailure("scripted Pi provider readiness record does not match this isolated run")
        if value.get("host") != "127.0.0.1" or not isinstance(value.get("port"), int):
            raise ProofFailure("scripted Pi provider did not bind a valid loopback endpoint")
        return value

    ready_value = wait_for(ready, "the isolated scripted Pi provider", timeout=10)
    provider = {
        "pid": process.pid,
        "root": str(root.resolve()),
        "port": ready_value["port"],
        "url": f"http://127.0.0.1:{ready_value['port']}/v1",
        "release_file": str(release_path),
    }
    return provider


def provider_process_matches(provider: dict[str, Any], root: Path) -> bool:
    pid = provider.get("pid")
    if not isinstance(pid, int) or pid <= 0 or provider.get("root") != str(root.resolve()):
        return False
    completed = run_process(["ps", "-p", str(pid), "-o", "command="], check=False, timeout=5)
    command = completed.stdout.strip()
    return completed.returncode == 0 and str(ROOT / "tests/herdr-overview/scripted_pi_provider.py") in command \
        and str(root.resolve()) in command


def validate_recorded_scripted_provider(provider: Any, root: Path) -> dict[str, Any]:
    expected_root = str(root.resolve())
    if not isinstance(provider, dict) or provider.get("root") != expected_root:
        raise ProofFailure("recorded scripted Pi provider is not scoped to this isolated run")
    if not provider_process_matches(provider, root):
        raise ProofFailure("recorded isolated scripted Pi provider is not running or does not match this run")
    try:
        ready = read_json(root / "scripted-provider-ready.json")
    except (OSError, ValueError, ProofFailure) as exc:
        raise ProofFailure("recorded scripted Pi provider has no valid readiness record") from exc
    port = provider.get("port")
    if (ready.get("pid") != provider.get("pid") or ready.get("root") != expected_root
            or ready.get("host") != "127.0.0.1" or not isinstance(port, int) or not 1 <= port <= 65535
            or ready.get("port") != port or provider.get("url") != f"http://127.0.0.1:{port}/v1"
            or provider.get("release_file") != str(root / "scripted-provider-release-first")):
        raise ProofFailure("recorded scripted Pi provider endpoint does not match this isolated run")
    return provider


def ensure_scripted_provider(root: Path, state: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    if "scripted_provider" in state:
        return validate_recorded_scripted_provider(state["scripted_provider"], root)
    provider = start_scripted_provider(root, env)
    state["scripted_provider"] = provider
    json_dump(root / PROOF_MARKER, state)
    return validate_recorded_scripted_provider(provider, root)


def stop_scripted_provider(root: Path, marker: dict[str, Any]) -> bool:
    provider = marker.get("scripted_provider")
    if not provider:
        return False
    if not isinstance(provider, dict) or provider.get("root") != str(root.resolve()):
        raise ProofFailure("cleanup refused a scripted provider not recorded for this proof root")
    pid = provider.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        raise ProofFailure("cleanup refused an invalid scripted provider PID")
    if provider_process_matches(provider, root):
        os.kill(pid, signal.SIGTERM)
        def stopped() -> bool:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            return not provider_process_matches(provider, root)
        wait_for(stopped, "the isolated scripted Pi provider to stop", timeout=8, interval=0.1)
    elif run_process(["ps", "-p", str(pid), "-o", "command="], check=False, timeout=5).returncode == 0:
        raise ProofFailure("cleanup refused to signal a PID that no longer matches the recorded provider")
    return True


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
    # Native prompt publication belongs to the overview adapter, not recap storage.
    for path in (data_root.parent / "herdr-overview" / "prompts").glob("*.json"):
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
        if item.get("source_kind") not in ("pi-session", "pi"):
            continue
        try:
            _path, record = find_record(data_root, item.get("latest_success_id", ""))
        except ProofFailure:
            record = None
        if record and (record.get("annotations", {}).get("herdr", {}).get("pane_id")
                       if record.get("source_kind") == "pi" else record.get("pane_id")) == pane_id:
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
    # Match the plugin's read-only native projection without changing stored data.
    def native_projection(record):
        if not record or record.get("source_kind") != "pi":
            return record
        pi = record.get("metadata", {}).get("pi", {})
        session_id = pi.get("sessionId") or pi.get("nativeSessionId")
        if not session_id:
            raise ProofFailure("native Pi recap omitted metadata.pi session identity")
        return {**record, **record.get("annotations", {}).get("herdr", {}),
                "source_kind": "pi-session", "source_id": session_id}
    if latest and latest.get('source_kind') == 'pi':
        # Native run attempts are authoritative records, not legacy latest.json
        # attempt pointers. Failed attempts intentionally do not rewrite that index.
        identity = latest.get('metadata', {}).get('pi', {})
        native_session = identity.get('sessionId') or identity.get('nativeSessionId')
        candidates = []
        for path in (data_root / 'records').glob('*/*.json'):
            record = read_json(path)
            identity = record.get('metadata', {}).get('pi', {})
            if record.get('source_kind') == 'pi' and (identity.get('sessionId') or identity.get('nativeSessionId')) == native_session:
                candidates.append(record)
        if candidates:
            attempt = max(candidates, key=lambda record: (record.get('created_at', ''), record.get('record_id', '')))
    return native_projection(latest), native_projection(attempt)


def install_native_recap(root: Path, env: dict[str, str], backend: Path | None = None) -> Path:
    """Load the real recap extension with a private provider over the scripted backend."""
    backend = backend or ROOT / "tests/herdr-overview/fake_recap_backend.py"
    # Both foreground Pi and the independent recap helper load the same private
    # provider registration. The recap route delegates to the existing scripted
    # backend, preserving its call log and blank-output failure behavior.
    recap_provider = Path(env["PI_CODING_AGENT_DIR"]) / "extensions" / "recap-provider.ts"
    recap_provider.parent.mkdir(parents=True, exist_ok=True)
    recap_provider.write_text(
        "import { createAssistantMessageEventStream } from '@earendil-works/pi-ai';\n"
        "import { execFileSync } from 'node:child_process';\n"
        "export default function(pi) { pi.registerProvider('native-recap-proof', {\n"
        " api: 'openai-completions', baseUrl: 'http://unused.invalid', apiKey: 'fixture',\n"
        " models: [{id:'recap',name:'recap',reasoning:false,input:['text'],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:100000,maxTokens:4096}],\n"
        " streamSimple(model, context) { const stream=createAssistantMessageEventStream();\n"
        " queueMicrotask(() => { const message={role:'assistant',api:model.api,provider:model.provider,model:model.id,timestamp:Date.now(),content:[],stopReason:'stop',usage:{input:1,output:1,cacheRead:0,cacheWrite:0,totalTokens:2,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}};\n"
        f" try {{ const base=execFileSync({json.dumps(sys.executable)}, [{json.dumps(str(backend))}, 'success'], {{input:JSON.stringify(context),encoding:'utf8'}});\n"
        " const material=context.messages.map(m=>typeof m.content==='string'?m.content:(m.content??[]).filter(c=>c.type==='text').map(c=>c.text).join('\\n')).join('\\n');\n"
        " const observed=material.match(/Proof request [^\\n]+/); const text=base.trim()?base.trim()+'\\nObserved request: '+(observed?.[0]??'missing public request'):base; message.content=[{type:'text',text}]; }\n"
        " catch { message.stopReason='error'; message.errorMessage='Scripted recap failure'; }\n"
        " stream.push({type:'start',partial:message});\n"
        " if(message.stopReason==='error') stream.push({type:'error',reason:'error',error:message});\n"
        " else stream.push({type:'done',reason:'stop',message}); stream.end(); }); return stream; }\n"
        " }); }\n", encoding="utf-8")
    recap_extension = root / "recap-extension"
    shutil.copytree(ROOT / "dot_pi/private_agent/extensions/recap", recap_extension, dirs_exist_ok=True)
    json_dump(recap_extension / "config.json", {
        "model": {"provider": "native-recap-proof", "id": "recap"},
        "completed": True, "cadence": 1, "periodic": False, "beforeCompaction": False,
    })
    return recap_extension / "index.ts"


def scenario_pi_grouped(run_id: str, base: Path | None) -> dict[str, Any]:
    root, state, env = load_run(run_id, base)
    if not state.get("server_started") or not state.get("fixture", {}).get("pi_pane_id"):
        raise ProofBlocked("isolated server/Pi fixture is not ready")
    if not state.get("wide_proof_passed"):
        raise ProofBlocked("run herdr-wide first on this same isolated server")
    pi_bin = shutil.which("pi")
    if not pi_bin:
        raise ProofBlocked("Pi is not installed; the settlement journey cannot run")
    provider = ensure_scripted_provider(root, state, env)
    provider_url = provider["url"]
    Path(env["HERDR_OVERVIEW_PI_REPLY"]).write_text(scripted_pi_reply() + "\n", encoding="utf-8")
    provider_extension = root / "scripted-pi-provider.mjs"
    make_pi_provider_extension(provider_extension)
    provider_source = provider_extension.read_text()
    provider_extension.write_text(provider_source.replace(
        'export default function (pi) {',
        'export default function (pi) { pi.on("session_start", () => pi.setSessionName("Synthetic native recap session"));', 1))
    recap_index = install_native_recap(root, env)
    real_pi = pi_bin
    write_exec(root / "bin/pi", "#!/bin/sh\nset -eu\n"
               "if [ -r \"$HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE\" ]; then\n"
               "  IFS= read -r HERDR_OVERVIEW_TEST_PROVIDER_URL < \"$HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE\"\n"
               "  export HERDR_OVERVIEW_TEST_PROVIDER_URL\n"
               "fi\n"
               f"exec {shlex.quote(real_pi)} \"$@\"\n")
    Path(env["HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE"]).write_text(provider_url + "\n", encoding="utf-8")
    env["HERDR_OVERVIEW_TEST_PROVIDER_URL"] = provider_url
    pane_id = state["fixture"]["pi_pane_id"]
    try:
        command = [str(root / 'bin/pi'), '--provider', 'herdr-proof-scripted', '--model', 'scripted-model',
                   '--extension', str(ROOT / 'dot_pi/private_agent/extensions/herdr-overview/index.ts'),
                   '--extension', str(provider_extension), '--extension', str(recap_index),
                   '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files',
                   '--no-tools', '--offline', '--session-dir', str(root / 'pi-sessions')]
        # pane.run owns a real terminal; agent.start would force RPC mode.
        launch = 'env ' + ' '.join(shlex.quote(f'{key}={value}') for key, value in env.items()) + ' ' + shlex.join(command)
        herdr_cmd(state, env, 'pane', 'run', pane_id, launch)
        wait_for(lambda: 'Pi can explain its own features' in pane_text(state, env, pane_id, fmt='text', lines=100),
                 'interactive Pi to initialize in the native pane', timeout=30)
        current_prompt = f"Proof request {run_id}: inspect the current parser and report the completed work."
        herdr_cmd(state, env, 'pane', 'send-text', pane_id, current_prompt)
        herdr_cmd(state, env, 'pane', 'send-keys', pane_id, 'enter')
        first_request = wait_for(
            lambda: (lambda requests: requests[0] if requests else None)(provider_requests(root)),
            "the scripted provider to receive Pi's prompt", timeout=60,
        )
        if "Proof request" not in first_request.get("body", ""):
            raise ProofFailure("the scripted provider did not receive the real Pi request")
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
        (root / 'native-working-prompt-frame.txt').write_text(overview_text_value)
        if not current_prompt_detail_visible(overview_text_value, pane_id, current_prompt, native_snapshot=snapshot(state)):
            raise ProofFailure("the live selected-pane view omitted the current Pi prompt")

        # Return this already-recognized Pi pane to automatic naming while its
        # live prompt is visible but before any successful recap exists.
        pane_before_publication_snapshot = snapshot(state)
        pane_before_publication = one_by(pane_before_publication_snapshot.get("panes", []), "pane_id", pane_id)
        agent_before_publication = next((item for item in pane_before_publication_snapshot.get("agents", [])
                                         if item.get("pane_id") == pane_id), {})
        if pane_before_publication.get("agent") != "pi" and agent_before_publication.get("agent") != "pi":
            raise ProofFailure("the live prompt fixture is not recognized by Herdr as a Pi pane")
        if pane_before_publication.get("label") != "Owner Pi proof pane":
            raise ProofFailure("the Pi fixture label changed before its first successful publication")
        latest_before_publication, _attempt_before_publication = read_latest_pi_record(data_root, pane_id)
        if latest_before_publication and latest_before_publication.get("status") == "published":
            raise ProofFailure("the Pi naming gate started with an already-published recap")
        stable_subject = wait_for(lambda: (plugin_state(root)['model']['panes'][pane_id]).get('subject'),
                                  'stable naming subject before recap')
        invoke_auto_name(state, "pane", pane_id)

        def pi_name_before_publication() -> dict[str, Any] | None:
            current = plugin_state(root)
            native = one_by(snapshot(state).get("panes", []), "pane_id", pane_id)
            owner = (current.get("displayNameOwnership") or {}).get(f"pane:{pane_id}") or {}
            prompt = (((current.get("model") or {}).get("panes") or {}).get(pane_id) or {}).get("prompt") or {}
            return current if owner.get("mode") == "automatic" and native.get("label") == stable_subject \
                and prompt.get("text") == current_prompt and prompt.get("working") is True else None

        wait_for(pi_name_before_publication,
                 "automatic Pi naming to use stable subject before any recap", timeout=15)

        Path(provider["release_file"]).touch()
        wait_for(lambda: (read_pi_prompt(data_root, pane_id) or {}).get('working') is False,
                 'interactive Pi response settlement', timeout=140)
        first_latest, first_attempt = wait_for(
            lambda: (lambda pair: pair if pair[0] and pair[0].get("status") == "published" else None)(read_latest_pi_record(data_root, pane_id)),
            "published settled Pi recap",
            timeout=35,
        )
        expected_summary = SUCCESS_SUMMARY + '\nObserved request: ' + current_prompt
        if first_latest.get("summary") != expected_summary or first_latest.get("workspace_id") != state["fixture"]["workspaces"][0]["workspace_id"]:
            raise ProofFailure("settled Pi recap is missing input-derived narrative or correct publication-time workspace attribution")

        def pi_name_survives_publication() -> dict[str, Any] | None:
            current = plugin_state(root)
            native = one_by(snapshot(state).get("panes", []), "pane_id", pane_id)
            owner = (current.get("displayNameOwnership") or {}).get(f"pane:{pane_id}") or {}
            return current if owner.get("mode") == "automatic" and native.get("label") == stable_subject else None

        wait_for(pi_name_survives_publication,
                 "automatic Pi naming to remain stable after recap publication", timeout=20)
        from map_identity import current_metadata
        native_pane, bridge = wait_for(lambda: current_metadata(state, env, pane_id),
                                      'live caller-bound Pi UUID/name bridge', timeout=20)
        _saved_path, saved_record = find_record(data_root, first_latest['record_id'])
        pi_metadata = saved_record.get('metadata', {}).get('pi', {})
        if (saved_record.get('source_kind') != 'pi'
                or (pi_metadata.get('sessionId') or pi_metadata.get('nativeSessionId')) != bridge['sessionId']
                or not pi_metadata.get('historyId')
                or pi_metadata.get('historyId') == bridge['sessionId']
                or not pi_metadata.get('coverage')
                or saved_record.get('summary') != expected_summary
                or saved_record.get('annotations', {}).get('herdr') != {'pane_id': pane_id, 'workspace_id': first_latest['workspace_id']}):
            raise ProofFailure('native SDK record lost independent history, coverage, caller attribution or verified UUID join')
        json_dump(root / 'native-pi-identity.json', {'native': native_pane, 'adapter': bridge, 'saved_record': saved_record})
        first_workspace_id = first_latest["workspace_id"]
        recap_state_path = overview_state_path(root)
        after_publish_state = wait_for(
            lambda: ((read_json(recap_state_path).get("recapCoordinator") or {}).get("workspaceDeadlines") or {}).get(first_workspace_id),
            "the first workspace quiet deadline",
            timeout=20,
        )
        expected_deadline = datetime.fromisoformat(first_latest["published_at"].replace("Z", "+00:00")).timestamp() + 30
        actual_deadline = datetime.fromisoformat(after_publish_state.replace("Z", "+00:00")).timestamp()
        if abs(actual_deadline - expected_deadline) > .002:
            raise ProofFailure("successful Pi publication did not start the exact 30-second workspace interval")
        if not provider_requests(root) or "Proof request" not in provider_requests(root)[0].get("body", ""):
            raise ProofFailure("the real Pi session did not use the scripted response provider")

        # A second settled Pi response gets blank T1 output. It must neither
        # replace the first good session recap nor move the quiet deadline.
        Path(env["FAKE_RECAP_MODE_FILE"]).write_text("blank\n", encoding="utf-8")
        Path(provider["release_file"]).touch()
        second_prompt = f"Proof request {run_id}: this recap backend will return blank output."
        herdr_cmd(state, env, 'pane', 'send-text', pane_id, second_prompt)
        herdr_cmd(state, env, 'pane', 'send-keys', pane_id, 'enter')
        second_latest, second_attempt = wait_for(
            lambda: (lambda pair: pair if pair[1] and pair[1].get("status") == "failed" and pair[1].get('attempt', 2) == 2 else None)(read_latest_pi_record(data_root, pane_id)),
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
        workspace_record, session_record = wait_for(
            lambda: (lambda pair: pair if all(pair) else None)(grouped()),
            "30-second workspace and session group publication", timeout=40)
        workspace_published = datetime.fromisoformat(workspace_record["published_at"].replace("Z", "+00:00")).timestamp()
        if workspace_published < due - .002:
            raise ProofFailure("workspace recap appeared before the persisted quiet deadline")
        if first_latest["record_id"] not in workspace_record.get("member_record_ids", []):
            raise ProofFailure(f"workspace recap did not retain the Pi member recap ID: expected {first_latest['record_id']}, actual {workspace_record!r}")
        if workspace_record["record_id"] not in session_record.get("member_record_ids", []):
            raise ProofFailure("session recap did not retain the workspace recap ID")
        def session_recap_in_model() -> dict[str, Any] | None:
            value = read_json(recap_state_path)
            latest = ((value.get("model") or {}).get("recap") or {}).get("latest") or {}
            return value if latest.get("record_id") == session_record["record_id"] else None

        state_now = wait_for(session_recap_in_model, "session recap publication in the overview model", timeout=20)
        # Grouped member identities remain in the current session model;
        # the map discloses the selected pane's dated latest-good recap.
        invoke_overview(state, env)
        detail = open_pane_from_workspace(state, env, pane_id)
        (root / 'native-saved-recap-frame.txt').write_text(detail)
        if not published_recap_detail_visible(detail, first_latest['summary']):
            raise ProofFailure('current popup omitted selected published recap')

        # A manual single recap can be addressed to a native pane by source ID.
        # Verify the overview reads that independent source and keeps its failure
        # status separate from both Pi naming and the successful latest record.
        recap_home = Path(env["HOME"])
        manual_id = cli_recap(recap_home, env, "create", "--kind", "single", "--source-id", pane_id,
                              stdin="Manually supplied pane recap input.\n").stdout.strip()
        _manual_path, manual_record = find_record(data_root, manual_id)
        if manual_record.get("source_kind") != "manual" or manual_record.get("source_id") != pane_id or manual_record.get("pane_id"):
            raise ProofFailure("manual single recap did not use the native pane ID as its source attribution")
        manual_summary = manual_record.get("summary")
        Path(env["FAKE_RECAP_MODE_FILE"]).write_text("blank\n", encoding="utf-8")
        manual_failure = cli_recap(recap_home, env, "create", "--kind", "single", "--source-id", pane_id,
                                   stdin="Record an independent manual recap failure.\n", check=False)
        Path(env["FAKE_RECAP_MODE_FILE"]).write_text("success\n", encoding="utf-8")
        if manual_failure.returncode == 0:
            raise ProofFailure("blank manual recap attempt unexpectedly published")
        manual_source = latest_entry(data_root, "manual", pane_id)
        if not manual_source or manual_source.get("latest_success_id") != manual_id:
            raise ProofFailure("manual recap failure replaced its latest successful record")
        _failure_path, manual_failure_record = find_record(data_root, manual_source.get("last_attempt_id", ""))
        if manual_failure_record.get("status") != "failed":
            raise ProofFailure("manual pane recap failure was not retained as the latest attempt")

        # Explicit manual publication wake-up, not a viewing side effect.
        api_request(state, 'plugin.action.invoke', {'action_id': 'overview.reconcile'})
        invoke_overview(state, env)
        def manual_recap_in_model() -> dict[str, Any] | None:
            current = read_json(recap_state_path)
            pane = ((current.get("model") or {}).get("panes") or {}).get(pane_id) or {}
            recap = pane.get("recap") or {}
            latest = recap.get("latest") or {}
            attempt = recap.get("lastAttempt") or {}
            if latest.get("record_id") == manual_id and attempt.get("record_id") == manual_failure_record["record_id"]:
                return current
            return None

        state_with_manual = wait_for(manual_recap_in_model, "manual source-attributed recap and failure status in the pane model")
        manual_pane = state_with_manual["model"]["panes"][pane_id]
        if manual_pane["recap"]["latest"].get("source_kind") != "manual":
            raise ProofFailure("pane model did not preserve the independent manual recap source")
        select_workspace(state, env, pi_workspace)
        manual_detail = open_pane_from_workspace(state, env, pane_id)
        (root / 'native-manual-recap-frame.txt').write_text(manual_detail)
        if not published_recap_detail_visible(manual_detail, manual_summary) or "Newer attempt failed" not in manual_detail:
            raise ProofFailure("selected-pane detail omitted the manual recap or its latest failure status")
        if manual_pane.get("label") != stable_subject:
            raise ProofFailure("manual recap changed the stable Pi subject")
        _final_path, final_saved_record = find_record(data_root, first_latest['record_id'])
        if final_saved_record != saved_record:
            raise ProofFailure('annotated native saved record changed during grouping, failure or manual publication')

        return {
            "pi_pane_id": pane_id,
            "pi_session_id": first_latest["source_id"],
            "current_prompt_visible_while_working": True,
            "pi_recap_id": first_latest["record_id"],
            "workspace_recap_id": workspace_record["record_id"],
            "session_recap_id": session_record["record_id"],
            "quiet_period_seconds": round(workspace_published - datetime.fromisoformat(first_latest["published_at"].replace("Z", "+00:00")).timestamp(), 1),
            "failed_recap_preserved_latest_and_deadline": True,
            "grouped_session_model_and_selected_recap_visible": True,
            "manual_pane_source_recap_and_failure_visible": True,
            "pi_name_stable_before_after_publication": True,
            "stable_pi_name": stable_subject,
            "manual_recap_did_not_drive_pi_naming": True,
            "response_provider": "scripted local OpenAI-compatible SSE provider",
            "saved_recap_contains_public_user_request": True,
            "native_uuid_and_independent_history_coverage_join_verified": True,
        }
    except Exception:
        # Capture actual terminal diagnostics before orchestrated fixture cleanup.
        print(bounded(pane_text(state, env, pane_id, fmt='text', lines=160), 12000), file=sys.stderr)
        raise
    finally:
        # Keep this run-owned loopback provider alive for the post-phone native
        # pane-move proof, which sends real Pi input through the inherited caller ID.
        Path(provider["release_file"]).touch()
        # The real Pi terminal is owned by this isolated Herdr server; explicit
        # herdr-cleanup stops that server and its panes even after a failure.


def scenario_pi_provider_start(run_id: str, base: Path | None) -> dict[str, Any]:
    root, state, env = load_run(run_id, base)
    if not state.get("server_started") or not state.get("wide_proof_passed"):
        raise ProofBlocked("run herdr-prepare and herdr-wide first on this same isolated server")
    provider = ensure_scripted_provider(root, state, env)
    return {
        "setup_only": True,
        "run_id": run_id,
        "provider_pid": provider["pid"],
        "provider_root": provider["root"],
        "provider_url": provider["url"],
    }


def scenario_herdr_native_move(run_id: str, base: Path | None) -> dict[str, Any]:
    root, state, env = load_run(run_id, base)
    if not state.get("server_started") or not state.get("wide_proof_passed"):
        raise ProofBlocked("run herdr-prepare and herdr-wide first on this same isolated server")
    phone = validate_phone_receipt(root, run_id)
    provider = state.get("scripted_provider")
    if not isinstance(provider, dict) or not provider_process_matches(provider, root):
        raise ProofFailure("the recorded isolated scripted Pi provider is not running for the native-move input")
    if not Path(provider.get("release_file", "")).is_file():
        raise ProofFailure("the scripted Pi provider's first-response gate was not released")

    stale_reopen = prove_reopened_output(state, root, env)
    old_pane_id = state.get("fixture", {}).get("pi_pane_id")
    if not old_pane_id:
        raise ProofBlocked("the isolated fixture has no Pi pane")
    data_root = Path(env["XDG_DATA_HOME"]) / "session-recap"
    prior_session_entry = latest_entry(data_root, "herdr-session", "active")
    prior_session_record_id = prior_session_entry.get("latest_success_id") if prior_session_entry else None
    prior_recap, _attempt = read_latest_pi_record(data_root, old_pane_id)
    if not prior_recap or prior_recap.get("status") != "published":
        raise ProofBlocked("run pi-grouped first to publish a Pi recap on the fixture pane")
    pi_task_label = (plugin_state(root)["model"]["panes"][old_pane_id]).get("subject")
    if not isinstance(pi_task_label, str) or not pi_task_label.strip():
        raise ProofFailure("the current Pi pane has no stable subject for the automatic tab proof")
    session_id = prior_recap.get("source_id")
    before = snapshot(state)
    old_pane = one_by(before.get("panes", []), "pane_id", old_pane_id)
    terminal_id = old_pane.get("terminal_id")
    agent = next((item for item in before.get("agents", []) if item.get("pane_id") == old_pane_id), {})
    if not isinstance(terminal_id, str) or not terminal_id:
        raise ProofFailure("the live Pi pane has no native terminal_id")
    if old_pane.get("agent") != "pi" and agent.get("agent") != "pi":
        raise ProofFailure("Herdr no longer recognizes the fixture pane as Pi")
    if old_pane.get("agent_session") is not None or agent.get("agent_session") is not None:
        raise ProofFailure("the native-move proof expected the observed agent_session=null path (first seen on Herdr 0.9.1); recheck the terminal-ID fallback")

    identity = ((plugin_state(root).get("recapCoordinator") or {}).get("piTerminalIdsBySessionId") or {})
    if identity.get(session_id) != terminal_id:
        raise ProofFailure("overview.reconcile did not persist the published Pi source's native terminal_id")
    pre_move_prompt = read_pi_prompt(data_root, old_pane_id)
    if not pre_move_prompt or not pre_move_prompt.get("text"):
        raise ProofFailure("the fixture lacks a current Pi prompt to follow through the native pane move")

    # Exercise name ownership on the real server after the phone journey, so
    # these temporary labels cannot alter the phone's named fixture. The shell
    # edit after an automatic write must survive reconciliation; only the
    # explicit public reset may return it to the automatic candidate.
    alpha = state["fixture"]["workspaces"][0]
    root_pane_id = alpha["root_pane_id"]
    root_tab_id = alpha["root_tab_id"]
    names_before = snapshot(state)
    root_pane_before = one_by(names_before.get("panes", []), "pane_id", root_pane_id)
    root_tab_before = one_by(names_before.get("tabs", []), "tab_id", root_tab_id)
    if root_pane_before.get("tab_id") != root_tab_id or old_pane.get("tab_id") != root_tab_id:
        raise ProofFailure("the shell and stable Pi subjects no longer share their native tab")
    original_shell_label = root_pane_before.get("label")
    original_tab_label = root_tab_before.get("label")
    manual_source_terminal_id = root_pane_before.get("terminal_id")
    if not isinstance(manual_source_terminal_id, str) or not manual_source_terminal_id:
        raise ProofFailure("the manual recap pane has no native terminal_id")
    root_agent = next((item for item in names_before.get("agents", [])
                       if item.get("pane_id") == root_pane_id), {})
    if root_pane_before.get("agent") == "pi" or root_agent.get("agent") == "pi":
        raise ProofFailure("the manual pane-source fixture is not a non-Pi native pane")
    if not original_shell_label or not original_tab_label:
        raise ProofFailure("the name ownership fixture lost its owner-set shell or tab label")

    seed_label = f"Owner AC4 reset seed {run_id}"
    herdr_cmd(state, env, "pane", "rename", root_pane_id, seed_label)
    invoke_overview(state, env)
    wait_for(
        lambda: (lambda current: current if current.get("label") == seed_label
                 and ((plugin_state(root).get("displayNameOwnership") or {}).get(f"pane:{root_pane_id}") or {}).get("mode") == "manual"
                 else None)(one_by(snapshot(state).get("panes", []), "pane_id", root_pane_id)),
        "the native shell's owner-set seed label to be recorded as manual", timeout=15,
    )
    invoke_auto_name(state, "pane", root_pane_id)

    def automatic_shell_label() -> str | None:
        current = plugin_state(root)
        native = one_by(snapshot(state).get("panes", []), "pane_id", root_pane_id)
        ownership = (current.get("displayNameOwnership") or {}).get(f"pane:{root_pane_id}") or {}
        label = native.get("label")
        return label if ownership.get("mode") == "automatic" and isinstance(label, str) and label.strip() and label != seed_label else None

    auto_shell_label = wait_for(automatic_shell_label, "the public pane reset to apply an automatic shell name", timeout=15)
    manual_followup = f"Owner AC4 preserved edit {run_id}"
    herdr_cmd(state, env, "pane", "rename", root_pane_id, manual_followup)
    invoke_overview(state, env)

    def manual_shell_label() -> dict[str, Any] | None:
        current = plugin_state(root)
        native = one_by(snapshot(state).get("panes", []), "pane_id", root_pane_id)
        ownership = (current.get("displayNameOwnership") or {}).get(f"pane:{root_pane_id}") or {}
        return current if native.get("label") == manual_followup and ownership.get("mode") == "manual" else None

    wait_for(manual_shell_label, "a later owner pane rename to survive real reconciliation", timeout=15)
    invoke_auto_name(state, "pane", root_pane_id)
    if wait_for(automatic_shell_label, "the explicit pane reset to resume automatic naming", timeout=15) != auto_shell_label:
        raise ProofFailure("automatic pane reset did not restore the same live task name")

    invoke_auto_name(state, "tab", root_tab_id)

    def automatic_two_task_tab() -> dict[str, Any] | None:
        current = plugin_state(root)
        native = one_by(snapshot(state).get("tabs", []), "tab_id", root_tab_id)
        ownership = (current.get("displayNameOwnership") or {}).get(f"tab:{root_tab_id}") or {}
        label = native.get("label") or ""
        if ownership.get("mode") == "automatic" and " + " in label \
                and auto_shell_label in label and pi_task_label in label:
            return label
        return None

    combined_tab = wait_for(automatic_two_task_tab,
                            "the reset tab name to represent both its shell and stable Pi subjects", timeout=15)
    herdr_cmd(state, env, "pane", "rename", root_pane_id, original_shell_label)
    herdr_cmd(state, env, "tab", "rename", root_tab_id, original_tab_label)
    invoke_overview(state, env)

    def restored_owner_names() -> dict[str, Any] | None:
        current = plugin_state(root)
        live = snapshot(state)
        pane = one_by(live.get("panes", []), "pane_id", root_pane_id)
        tab = one_by(live.get("tabs", []), "tab_id", root_tab_id)
        owners = current.get("displayNameOwnership") or {}
        if (pane.get("label") == original_shell_label and tab.get("label") == original_tab_label
                and (owners.get(f"pane:{root_pane_id}") or {}).get("mode") == "manual"
                and (owners.get(f"tab:{root_tab_id}") or {}).get("mode") == "manual"):
            return current
        return None

    wait_for(restored_owner_names, "the original owner labels to be restored before pane.move", timeout=15)

    source_workspace_id = old_pane["workspace_id"]
    prior_source_group = latest_entry(data_root, "workspace", source_workspace_id)
    if not prior_source_group or not prior_source_group.get("latest_success_id"):
        raise ProofBlocked("pi-grouped must publish the original workspace recap before a move")
    prior_source_group_id = prior_source_group["latest_success_id"]
    prepared_before_move = cli_recap(
        Path(env["HOME"]), env, "prepare", "--source-id", session_id, "--pane-id", old_pane_id,
        stdin="Completed work in the original workspace before the native pane move.\n",
    ).stdout.strip()
    published_before_move = cli_recap(
        Path(env["HOME"]), env, "publish", "--prepared-id", prepared_before_move,
        "--workspace-id", source_workspace_id,
    ).stdout.strip()
    api_request(state, 'plugin.action.invoke', {'action_id': 'overview.reconcile'})
    invoke_overview(state, env)
    state_path = overview_state_path(root)
    def original_deadline() -> str | None:
        current = read_json(state_path)
        return ((current.get("recapCoordinator") or {}).get("workspaceDeadlines") or {}).get(source_workspace_id)

    original_deadline_text = wait_for(original_deadline, "the publication-time original-workspace deadline", timeout=20)

    # Publish a manual recap against a live non-Pi pane, then reconcile while
    # its source ID still resolves so the coordinator can persist terminal identity.
    manual_source_pane_id = root_pane_id
    manual_source_label = "Manual moved shell recap"
    manual_source_record_id = cli_recap(
        Path(env["HOME"]), env, "create", "--kind", "single", "--source-id", manual_source_pane_id,
        "--label", manual_source_label, stdin="A published manual recap for the shell before it moves.\n",
    ).stdout.strip()
    manual_source_record = find_record(data_root, manual_source_record_id)[1]
    if manual_source_record.get("source_kind") != "manual" or manual_source_record.get("source_id") != manual_source_pane_id:
        raise ProofFailure("manual recap did not preserve its native pane source ID")
    api_request(state, 'plugin.action.invoke', {'action_id': 'overview.reconcile'})
    invoke_overview(state, env)

    def manual_identity_persisted() -> dict[str, Any] | None:
        current = read_json(state_path)
        coordinator = current.get("recapCoordinator") or {}
        mapping = coordinator.get("manualTerminalIdsBySourceId") or {}
        pane = ((current.get("model") or {}).get("panes") or {}).get(manual_source_pane_id) or {}
        latest = (pane.get("recap") or {}).get("latest") or {}
        if (mapping.get(manual_source_pane_id) == manual_source_terminal_id
                and latest.get("record_id") == manual_source_record_id):
            return current
        return None

    wait_for(manual_identity_persisted, "the live manual pane recap and terminal association", timeout=20)
    if original_deadline() != original_deadline_text:
        raise ProofFailure("a manual pane recap changed the successful Pi publication's quiet deadline")

    target = state["fixture"]["workspaces"][1]
    if len(state["fixture"].get("workspaces", [])) < 3:
        raise ProofFailure("the isolated fixture needs a third workspace for the closed-workspace regression")
    moved_output = herdr_cmd(
        state, env, "pane", "move", old_pane_id, "--new-tab", "--workspace", target["workspace_id"], "--no-focus",
    )
    try:
        move_result = json.loads(moved_output.stdout).get("result", {}).get("move_result", {})
    except json.JSONDecodeError as exc:
        raise ProofFailure("Herdr pane move did not return its public move_result") from exc
    if move_result.get("previous_pane_id") != old_pane_id:
        raise ProofFailure("Herdr pane.move did not report the old native pane ID")
    new_pane = move_result.get("pane") or {}
    new_pane_id = new_pane.get("pane_id")
    if not isinstance(new_pane_id, str) or not new_pane_id:
        raise ProofFailure("Herdr pane.move did not return the rekeyed pane ID")

    moved_snapshot = wait_for(
        lambda: (lambda value: value if not any(pane.get("pane_id") == old_pane_id for pane in value.get("panes", []))
                 and any(pane.get("pane_id") == new_pane_id for pane in value.get("panes", [])) else None)(snapshot(state)),
        "the live snapshot to drop the old pane ID and expose the rekeyed pane", timeout=15,
    )
    moved_pane = one_by(moved_snapshot["panes"], "pane_id", new_pane_id)
    moved_agent = next((item for item in moved_snapshot.get("agents", []) if item.get("pane_id") == new_pane_id), {})
    if moved_pane.get("terminal_id") != terminal_id:
        raise ProofFailure("Herdr pane.move changed the native terminal_id")
    if moved_pane.get("agent") != "pi" and moved_agent.get("agent") != "pi":
        raise ProofFailure("the rekeyed pane no longer reports agent=pi")
    if moved_pane.get("agent_session") is not None or moved_agent.get("agent_session") is not None:
        raise ProofFailure("the moved pane unexpectedly exposed agent_session (Herdr 0.9.1 did not); recheck the terminal-ID fallback")

    manual_move_output = herdr_cmd(
        state, env, "pane", "move", manual_source_pane_id, "--new-tab", "--workspace",
        target["workspace_id"], "--no-focus",
    )
    try:
        manual_move_result = json.loads(manual_move_output.stdout).get("result", {}).get("move_result", {})
    except json.JSONDecodeError as exc:
        raise ProofFailure("manual non-Pi pane.move did not return its public move_result") from exc
    if manual_move_result.get("previous_pane_id") != manual_source_pane_id:
        raise ProofFailure("Herdr pane.move did not report the manual recap's old native pane ID")
    moved_manual_pane = manual_move_result.get("pane") or {}
    moved_manual_pane_id = moved_manual_pane.get("pane_id")
    if not isinstance(moved_manual_pane_id, str) or not moved_manual_pane_id:
        raise ProofFailure("manual non-Pi pane.move did not return a rekeyed pane ID")
    manual_moved_snapshot = wait_for(
        lambda: (lambda value: value if not any(pane.get("pane_id") == manual_source_pane_id
                                                for pane in value.get("panes", []))
                 and any(pane.get("pane_id") == moved_manual_pane_id
                         for pane in value.get("panes", [])) else None)(snapshot(state)),
        "the live snapshot to rekey the manual source pane", timeout=15,
    )
    moved_manual_native = one_by(manual_moved_snapshot.get("panes", []), "pane_id", moved_manual_pane_id)
    if moved_manual_native.get("terminal_id") != manual_source_terminal_id:
        raise ProofFailure("manual pane.move changed the source pane's native terminal_id")
    moved_manual_agent = next((item for item in manual_moved_snapshot.get("agents", [])
                               if item.get("pane_id") == moved_manual_pane_id), {})
    if moved_manual_native.get("agent") == "pi" or moved_manual_agent.get("agent") == "pi":
        raise ProofFailure("the moved manual recap pane unexpectedly became a Pi pane")

    def manual_recap_follows_native_move() -> dict[str, Any] | None:
        current = read_json(state_path)
        pane = ((current.get("model") or {}).get("panes") or {}).get(moved_manual_pane_id) or {}
        latest = (pane.get("recap") or {}).get("latest") or {}
        return current if latest.get("record_id") == manual_source_record_id else None

    wait_for(manual_recap_follows_native_move,
             "the published manual pane-source recap to follow terminal identity after pane.move", timeout=20)
    select_workspace(state, env, target)
    manual_detail = open_pane_from_workspace(state, env, moved_manual_pane_id)
    if not published_recap_detail_visible(manual_detail, manual_source_record["summary"]):
        raise ProofFailure("the rekeyed non-Pi pane detail omitted its published manual recap")

    def old_recap_and_prompt_in_new_detail() -> dict[str, Any] | None:
        current = read_json(state_path)
        pane = ((current.get("model") or {}).get("panes") or {}).get(new_pane_id) or {}
        latest = (pane.get("recap") or {}).get("latest") or {}
        prompt = pane.get("prompt") or {}
        if latest.get("record_id") == published_before_move \
                and prompt.get("text") == pre_move_prompt["text"] \
                and prompt.get("pane_id") == old_pane_id:
            return current
        return None

    wait_for(old_recap_and_prompt_in_new_detail,
             "the pre-move recap and current prompt to follow terminal_id into the rekeyed pane detail", timeout=20)
    original_due = datetime.fromisoformat(original_deadline_text.replace("Z", "+00:00")).timestamp()
    remaining = original_due - time.time()
    if remaining > 0:
        time.sleep(remaining + 0.8)
    wait_for(lambda: not original_deadline(), "the original quiet deadline to expire without its moved pane", timeout=40)
    source_group_after_move = latest_entry(data_root, "workspace", source_workspace_id)
    if not source_group_after_move or source_group_after_move.get("latest_success_id") != prior_source_group_id:
        raise ProofFailure("the original workspace incorrectly grouped a pane that moved away before its quiet deadline")

    # Materialize a real workspace recap, then close that workspace before the
    # next Pi-triggered grouping. Its history must remain stored but not enter
    # the active Herdr-session group.
    closed_workspace = state["fixture"]["workspaces"][2]
    closed_manual_id = cli_recap(
        Path(env["HOME"]), env, "create", "--kind", "single", "--source-id", closed_workspace["root_pane_id"],
        "--label", "Closed workspace proof member", stdin="This workspace will close before the next group.\n",
    ).stdout.strip()
    closed_manual = find_record(data_root, closed_manual_id)[1]
    closed_group_input = json.dumps({"members": [{
        "record_id": closed_manual_id,
        "label": "Closed workspace proof member",
        "text": closed_manual["summary"],
    }]}) + "\n"
    closed_workspace_record_id = cli_recap(
        Path(env["HOME"]), env, "create", "--kind", "group", "--source-kind", "workspace",
        "--source-id", closed_workspace["workspace_id"], stdin=closed_group_input,
    ).stdout.strip()
    closed_workspace_record = find_record(data_root, closed_workspace_record_id)[1]
    if closed_workspace_record.get("member_record_ids") != [closed_manual_id]:
        raise ProofFailure("the closed-workspace fixture recap did not retain its member record")
    herdr_cmd(state, env, "workspace", "close", closed_workspace["workspace_id"], timeout=20)
    wait_for(
        lambda: True if all(item.get("workspace_id") != closed_workspace["workspace_id"]
                            for item in snapshot(state).get("workspaces", [])) else None,
        "the native snapshot to remove the closed workspace", timeout=20,
    )

    # The old source ID stays immutable; the coordinator must follow its
    # persisted terminal association into the new workspace.
    manual_id = manual_source_record_id
    # Check the same public Pi adapter membership helper used by the live input
    # and publication path. Do not supply this value to the Pi or recap CLI.
    publication_workspace_id = pi_pane_workspace_at_publication(env, old_pane_id)
    if publication_workspace_id != target["workspace_id"]:
        raise ProofFailure(
            "Pi's caller-aware pane.current helper did not resolve the moved pane to its live workspace: "
            f"{publication_workspace_id!r} != {target['workspace_id']!r}"
        )

    post_move_prompt = f"Proof request {run_id}: after the native move, report the current pane state."
    herdr_cmd(state, env, "agent", "prompt", "t8-proof-pi", post_move_prompt)
    provider_calls = wait_for(
        lambda: (lambda calls: calls if len(calls) >= 3 else None)(provider_requests(root)),
        "the persistent scripted provider to receive real Pi input after pane.move", timeout=20,
    )
    if post_move_prompt not in provider_calls[-1].get("body", ""):
        raise ProofFailure("the scripted provider did not receive the post-move user prompt")

    def rekeyed_prompt() -> dict[str, Any] | None:
        prompt = read_pi_prompt(data_root, new_pane_id)
        return prompt if prompt and prompt.get("text") == post_move_prompt and prompt.get("working") is False else None

    current_prompt = wait_for(rekeyed_prompt, "the current prompt attributed to the rekeyed native pane", timeout=20)
    prompt_commands = [json.loads(line) for line in (root / "recap-commands.jsonl").read_text(encoding="utf-8").splitlines()]
    if not any(args[:2] == ["prompt", "set"] and "--pane-id" in args
               and args[args.index("--pane-id") + 1] == new_pane_id for args in prompt_commands):
        raise ProofFailure("the real Pi input adapter did not store the current prompt under Herdr's rekeyed pane ID")
    if current_prompt.get("pane_id") != new_pane_id:
        raise ProofFailure("the current Pi prompt retained its pre-move pane ID")

    def rekeyed_pi_recap() -> dict[str, Any] | None:
        latest, _attempt = read_latest_pi_record(data_root, new_pane_id)
        return latest if latest and latest.get("source_id") == session_id else None

    moved_recap = wait_for(rekeyed_pi_recap, "the settled Pi publication for the rekeyed native pane", timeout=30)
    published_id = moved_recap["record_id"]
    if moved_recap.get("pane_id") != new_pane_id or moved_recap.get("workspace_id") != publication_workspace_id:
        raise ProofFailure("the real Pi adapter publication did not use its live rekeyed pane/workspace attribution")
    if moved_recap.get("summary") != SUCCESS_SUMMARY:
        raise ProofFailure("the post-move Pi response did not use the deterministic recap backend")

    def deadline_state() -> tuple[dict[str, Any], str] | None:
        current = read_json(state_path)
        deadlines = ((current.get("recapCoordinator") or {}).get("workspaceDeadlines") or {})
        deadline = deadlines.get(publication_workspace_id)
        return (current, deadline) if deadline else None

    _current_state, deadline_text = wait_for(deadline_state, "the current-workspace quiet deadline", timeout=20)
    expected = datetime.fromisoformat(moved_recap["published_at"].replace("Z", "+00:00")).timestamp() + 30
    actual = datetime.fromisoformat(deadline_text.replace("Z", "+00:00")).timestamp()
    if abs(actual - expected) > .002:
        raise ProofFailure("the moved Pi recap did not start its publication-time quiet deadline")

    def current_prompt_and_recap_in_model() -> dict[str, Any] | None:
        current = read_json(state_path)
        pane = ((current.get("model") or {}).get("panes") or {}).get(new_pane_id) or {}
        prompt = pane.get("prompt") or {}
        recap = (pane.get("recap") or {}).get("latest") or {}
        return current if prompt.get("text") == post_move_prompt and recap.get("record_id") == published_id else None

    wait_for(current_prompt_and_recap_in_model, "the current prompt and recap in the rekeyed pane model", timeout=20)
    select_workspace(state, env, target)
    live = snapshot(state)
    moved_pane = one_by(live.get("panes", []), "pane_id", new_pane_id)
    workspace = one_by(live.get("workspaces", []), "workspace_id", target["workspace_id"])
    tab_order = workspace.get("tab_ids") or [item["tab_id"] for item in live.get("tabs", [])
                                                if item.get("workspace_id") == target["workspace_id"]]
    if not tab_order or moved_pane.get("tab_id") not in tab_order:
        raise ProofFailure("the moved Pi pane's tab is not reachable in the native target workspace")
    # Native active_tab_id is not the overview's selection. Its own j navigation
    # visits panes across tabs; pre-advancing from the native tab can skip one.
    moved_detail = open_pane_from_workspace(
        state, env, new_pane_id,
        match_detail=lambda detail: current_prompt_detail_visible(
            detail, new_pane_id, post_move_prompt, require_id=False),
    )
    if not current_prompt_detail_visible(moved_detail, new_pane_id, post_move_prompt, require_id=False):
        raise ProofFailure("rekeyed pane detail did not visibly show the current-prompt heading and full post-move Pi prompt")
    send_overview_key(state, env, "f")
    wait_for(lambda: True if snapshot(state).get("focused_pane_id") == new_pane_id else None,
             "the overview to focus the actual rekeyed native Pi pane", timeout=10)

    remaining = actual - time.time()
    if remaining > 0:
        time.sleep(remaining + 0.8)

    workspace_entry = wait_for(
        lambda: (lambda entry: entry if entry and entry.get("latest_success_id") else None)(
            latest_entry(data_root, "workspace", publication_workspace_id)
        ),
        "the native-move workspace group publication", timeout=40,
    )
    _group_path, group_record = find_record(data_root, workspace_entry["latest_success_id"])
    if group_record.get("status") != "published" or set(group_record.get("member_record_ids", [])) != {published_id, manual_id}:
        raise ProofFailure("workspace group omitted the moved Pi recap or the current manual non-Pi pane recap")
    if group_record.get("source_id") != publication_workspace_id:
        raise ProofFailure("workspace group output used the wrong adapter-observed native workspace ID")

    def session_group() -> dict[str, Any] | None:
        entry = latest_entry(data_root, "herdr-session", "active")
        if not entry or entry.get("latest_success_id") == prior_session_record_id:
            return None
        try:
            return find_record(data_root, entry["latest_success_id"])[1]
        except ProofFailure:
            return None

    session_record = wait_for(session_group, "the Herdr-session group after the live workspace group", timeout=20)
    expected_session_members = {prior_source_group_id, group_record["record_id"]}
    if set(session_record.get("member_record_ids", [])) != expected_session_members:
        raise ProofFailure("Herdr-session group did not use only latest recaps from currently live workspaces")
    if closed_workspace_record_id in session_record.get("member_record_ids", []):
        raise ProofFailure("Herdr-session group included a workspace that was closed before publication")
    if any(item.get("workspace_id") == closed_workspace["workspace_id"]
           for item in snapshot(state).get("workspaces", [])):
        raise ProofFailure("the closed workspace reappeared in the native session snapshot")

    return {
        "phone_receipt": phone["phone_receipt"],
        "closed_overview_reopen": stale_reopen,
        "manual_source_old_pane_id": manual_source_pane_id,
        "manual_source_new_pane_id": moved_manual_pane_id,
        "manual_source_terminal_id": manual_source_terminal_id,
        "manual_recap_followed_native_move": True,
        "manual_recap_visible_in_rekeyed_detail": True,
        "old_pane_id": old_pane_id,
        "new_pane_id": new_pane_id,
        "terminal_id_preserved": terminal_id,
        "agent_session_null": True,
        "publication_before_move_id": published_before_move,
        "old_workspace_recap_unchanged_after_move": True,
        "current_prompt_written_to_rekeyed_pane": current_prompt.get("pane_id") == new_pane_id,
        "current_prompt_visible_in_rekeyed_detail": True,
        "selected_rekeyed_pane_confirmed_by_native_focus": True,
        "published_recap_id": published_id,
        "workspace_id": publication_workspace_id,
        "membership_lookup": "real Pi adapter pane.current caller_pane_id over isolated socket",
        "manual_rename_survived_reconciliation": True,
        "automatic_pane_reset_restored": auto_shell_label,
        "automatic_tab_contains_shell_and_stable_pi_subjects": combined_tab,
        "owner_labels_restored_before_move": True,
        "group_record_id": group_record["record_id"],
        "group_contains_latest_moved_pi_and_manual_non_pi_recaps": True,
        "closed_workspace_record_id": closed_workspace_record_id,
        "session_group_id": session_record["record_id"],
        "closed_workspace_excluded_from_session_group": True,
        "quiet_period_seconds": round(time.time() - actual + 30, 1),
    }


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
        raise ProofFailure("the attended phone user did not confirm map/detail/digest/focus navigation")
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
        print("BLOCKED: this phone SSH terminal is wider than the supported narrow width; do not resize/emulate it.", flush=True)
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
        print("Did you reach every workspace/tab/pane in the native map and read the supplied prompt/recap/digest in detail? [y/N] ", end="", flush=True)
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
    command = f"/data/data/com.termux/files/home/bin/herdr-overview-proof%s{run_id}%smacbook"
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
    provider_stopped = stop_scripted_provider(root, marker)
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
    return {"run_id": run_id, "isolated_server_stopped": True, "scripted_provider_stopped": provider_stopped,
            "temporary_root_removed": True, "owner_server_touched": False, "stopped_socket": str(expected_socket)}


def scenario_chezmoi() -> dict[str, Any]:
    binary = shutil.which("chezmoi")
    if not binary:
        raise ProofBlocked("chezmoi is not installed")
    command = [binary, "--source", str(ROOT)]
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
        mapped = run_process([*command, "source-path", dest], check=False, timeout=10)
        if mapped.returncode == 0 and mapped.stdout.strip():
            mappings[dest] = mapped.stdout.strip()
    if not mappings:
        raise ProofFailure("chezmoi did not map any requested desktop destinations to source")
    data = run_process([*command, "data", "--format", "json"], check=False, timeout=20)
    if data.returncode != 0:
        raise ProofFailure(f"could not read the active chezmoi profile: {bounded(data.stderr)}")
    try:
        data_value = json.loads(data.stdout)
        current_profile = data_value.get("profile") or data_value.get("data", {}).get("profile") \
            or data_value.get("chezmoi", {}).get("config", {}).get("data", {}).get("profile")
    except json.JSONDecodeError as exc:
        raise ProofFailure("chezmoi data did not return JSON") from exc
    dry_run = run_process([*command, "apply", "--dry-run", "--verbose", "--no-tty", *desktop_targets],
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
            rendered = run_process([*command, "--override-data-file", str(override), "execute-template", "{{ .profile }}"],
                                  check=False, timeout=20)
            if rendered.returncode != 0 or rendered.stdout.strip() != profile:
                raise ProofFailure(f"could not render the {profile} profile template")
            template = run_process([*command, "--override-data-file", str(override), "execute-template", "--file",
                                    str(ROOT / "dot_config/session-recap/config.toml.tmpl")],
                                   check=False, timeout=20)
            if (template.returncode != 0
                or not re.search(r"(?m)^auto_publish\s*=\s*false\s*$", template.stdout)
                or re.search(r"(?m)^command\s*=", template.stdout)):
                raise ProofFailure(f"{profile} session-recap must default off without a managed backend")
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
                *command, "--destination", str(destination),
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
    return {"targeted_dry_run": True, "current_profile": current_profile,
            "desktop_mappings_checked": mappings, "rendered_profiles": list(rendered_profiles),
            "recap_default_off": True,
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
        if scenario == "herdr-native-move":
            if not args.run_id:
                raise ProofBlocked("herdr-native-move requires the run ID printed by herdr-prepare")
            return result(command_id, scenario, "PASS", run_id=args.run_id,
                          **scenario_herdr_native_move(args.run_id, args.state_base))
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
    parser.add_argument("scenario", nargs="?", choices=[*SCENARIO_COMMANDS, "pi-provider-start", "phone-client", "phone-source", "phone-record"])
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
    if args.scenario == "pi-provider-start":
        if not args.run_id:
            print(json.dumps({"scenario": "pi-provider-start", "status": "FAIL", "reason": "--run-id is required"}))
            return 1
        try:
            details = scenario_pi_provider_start(args.run_id, args.state_base)
            print(json.dumps({"scenario": "pi-provider-start", "status": "READY", **details}, sort_keys=True), flush=True)
            return 0
        except ProofBlocked as exc:
            print(json.dumps({"scenario": "pi-provider-start", "status": "BLOCKED", "reason": str(exc)}), flush=True)
            return 2
        except ProofFailure as exc:
            print(json.dumps({"scenario": "pi-provider-start", "status": "FAIL", "reason": str(exc)}), flush=True)
            return 1
        except Exception as exc:
            print(json.dumps({"scenario": "pi-provider-start", "status": "FAIL",
                              "reason": f"{type(exc).__name__}: {bounded(str(exc), 2500)}"}), flush=True)
            return 1
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
