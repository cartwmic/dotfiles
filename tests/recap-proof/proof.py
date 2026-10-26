#!/usr/bin/env python3
"""Source-only proof driver for session-recap, passage-review and chezmoi profile mapping.

Every scenario runs in isolated temporary homes with a scripted recap backend;
none touches the owner's Herdr, Pi sessions or live config. Run one scenario at
a time and keep each JSON result by command_id.
"""

from __future__ import annotations

import argparse
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_COMMANDS = {
    "recap": "proof-recap-cli",
    "review": "proof-review-lifecycle",
    "chezmoi-dry-run": "proof-chezmoi-target-dry-run",
}
RUN_ID_RE = __import__("re").compile(r"^[0-9a-f]{16}$")
REVIEW_ID_RE = __import__("re").compile(r"^rv-[0-9a-f]{12}$")
NOTE_ID_RE = __import__("re").compile(r"^n-[0-9a-f]{8}$")
SUCCESS_SUMMARY = "Recent work is complete. Present state: ready for the next step."


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
        fake = ROOT / "tests/recap-proof/fake_recap_backend.py"
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
        # Pi policy is not imported; the CLI is driven directly.
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
        "~/.local/share/agent-harness/canonical/skills/herdr/SKILL.md",
        "~/.pi/agent/extensions/README.md",
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
    if "./tests/" not in ignore and "tests/recap-proof" not in ignore:
        raise ProofFailure("source-only proof tree is not excluded from chezmoi deployment")
    if not (ROOT / "tests/recap-proof/fake_recap_backend.py").is_file():
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
                if "bin/passage-review" not in paths:
                    raise ProofFailure("Termux profile does not own the phone-side reviewer source")
                if any(path == ".config" or path.startswith(".config/") for path in paths):
                    raise ProofFailure("Termux profile unexpectedly includes desktop .config files")
                if any(path == ".pi" or path.startswith(".pi/") for path in paths):
                    raise ProofFailure("Termux profile unexpectedly includes desktop Pi extensions")
                if any(path == ".local/share/session-recap" or path.startswith(".local/share/session-recap/") for path in paths):
                    raise ProofFailure("Termux profile unexpectedly includes the desktop recap producer")
            else:
                if "bin/passage-review" in paths:
                    raise ProofFailure(f"Termux-only reviewer helper leaked into the {profile} desktop profile")
            if any(path == "bin/herdr-overview-proof" or path.startswith(".pi/agent/extensions/herdr-overview/")
                   or path.startswith(".local/share/herdr-overview/") for path in paths):
                raise ProofFailure(f"{profile} profile still deploys the retired Herdr Overview")
    return {"targeted_dry_run": True, "current_profile": current_profile,
            "desktop_mappings_checked": mappings, "rendered_profiles": list(rendered_profiles),
            "recap_default_off": True,
            "profile_paths_checked": {profile: len(paths) for profile, paths in profile_paths.items()},
            "source_only_tests_excluded": True, "real_apply": False}



def scenario_result(args: argparse.Namespace) -> int:
    scenario = args.scenario
    command_id = SCENARIO_COMMANDS[scenario]
    try:
        if scenario == "recap":
            return result(command_id, scenario, "PASS", **scenario_recap())
        if scenario == "review":
            return result(command_id, scenario, "PASS", **scenario_review())
        return result(command_id, scenario, "PASS", **scenario_chezmoi())
    except ProofBlocked as exc:
        return result(command_id, scenario, "BLOCKED", reason=str(exc))
    except ProofFailure as exc:
        return result(command_id, scenario, "FAIL", reason=str(exc))
    except Exception as exc:
        return result(command_id, scenario, "FAIL", reason=f"{type(exc).__name__}: {bounded(str(exc), 2500)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", choices=[*SCENARIO_COMMANDS])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.scenario:
        build_parser().print_help()
        return 0
    return scenario_result(args)


if __name__ == "__main__":
    raise SystemExit(main())
