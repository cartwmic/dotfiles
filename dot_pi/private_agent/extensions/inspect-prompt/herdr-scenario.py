#!/usr/bin/env python3
"""Outside-in check of non-Pi Herdr navigation and scrollback editing.

It starts a uniquely named Herdr 0.9.1 session under a private temporary
HOME/config tree and drives prefix keys through a real PTY client. If prefix+e
does not dispatch, it checks the same editor path through the private API and
reports BLOCKED instead of claiming the key worked. It never addresses the
user's default session.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import pty
import select
import shutil
import shlex
import signal
import socket
import struct
import subprocess
import tempfile
import termios
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[4]
HERDR_SOURCE = ROOT / "dot_config/herdr/config.toml"
EXPECTED_VERSION = "herdr 0.9.1"
MARKERS = [
    "T4_NONPI_SCROLLBACK_FIRST",
    "T4_NONPI_SCROLLBACK_MIDDLE",
    "T4_NONPI_SCROLLBACK_LAST",
]
ROOT_MARKER = "T4_NONPI_OTHER_PANE_ONLY"
OTHER_TAB_MARKER = "T4_NONPI_OTHER_TAB_ONLY"


class ProofBlocked(Exception):
    """The host cannot run the requested outer-path check."""


class ProofFailure(Exception):
    """An observed Herdr behavior did not meet the check."""


def run(argv: list[str], env: dict[str, str], *, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            env=env,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProofBlocked(f"could not run {argv[:3]!r}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-1600:]
        raise ProofFailure(f"command failed ({result.returncode}): {' '.join(argv)}\n{detail}")
    return result


def resolve_herdr() -> str:
    mise = shutil.which("mise")
    if not mise:
        raise ProofBlocked("mise is required to resolve the installed Herdr 0.9.1 binary")
    located = run([mise, "where", "github:herdrdev/herdr@0.9.1"], os.environ.copy(), timeout=20)
    binary = (Path(located.stdout.strip()) / "herdr").resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ProofBlocked(f"the pinned Herdr binary is missing: {binary}")
    version = run([str(binary), "--version"], os.environ.copy(), timeout=10).stdout.strip()
    if version != EXPECTED_VERSION:
        raise ProofBlocked(f"expected {EXPECTED_VERSION}, found {version!r}")
    return str(binary)


def required_keys() -> dict[str, Any]:
    try:
        config = tomllib.loads(HERDR_SOURCE.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProofFailure(f"cannot parse source-managed Herdr config {HERDR_SOURCE}: {exc}") from exc
    source_keys = config.get("keys")
    expected = {
        "prefix": "ctrl+b",
        "edit_scrollback": "prefix+e",
        "next_tab": ["prefix+n", "prefix+shift+]"],
        "previous_tab": ["prefix+p", "prefix+shift+["],
        "focus_pane_right": ["prefix+l", "ctrl+alt+l"],
        "focus_pane_left": ["prefix+h", "ctrl+alt+h"],
        "detach": "prefix+q",
    }
    if not isinstance(source_keys, dict):
        raise ProofFailure("the Herdr source config has no [keys] table")
    for key, value in expected.items():
        if source_keys.get(key) != value:
            raise ProofFailure(f"Herdr source key {key} changed: expected {value!r}, got {source_keys.get(key)!r}")
    return expected


def toml_value(value: Any) -> str:
    # The selected key values are strings or arrays of strings, also valid JSON.
    return json.dumps(value)


def isolated_env(root: Path, session: str) -> tuple[dict[str, str], Path, Path, Path]:
    home = root / "home"
    config_home = root / "cfg"
    config_dir = config_home / "herdr"
    data_home = root / "data"
    state_home = root / "state"
    temp_home = root / "tmp"
    for directory in (home, config_dir, data_home, state_home, temp_home, root / "work"):
        directory.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    keys = required_keys()
    lines = [
        "onboarding = false",
        "[server]",
        "headless_cols = 140",
        "headless_rows = 45",
        "[keys]",
    ]
    lines.extend(f"{key} = {toml_value(value)}" for key, value in keys.items())
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    editor = root / "dummy-editor"
    capture = root / "editor-scrollback.txt"
    source_record = root / "editor-source-path.txt"
    invocation_record = root / "editor-invocations.txt"
    editor.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f"capture={shlex.quote(str(capture))}\n"
        f"source_record={shlex.quote(str(source_record))}\n"
        f"invocation_record={shlex.quote(str(invocation_record))}\n"
        "[ \"$#\" -eq 1 ] || exit 31\n"
        "cp \"$1\" \"$capture\"\n"
        "printf '%s\\n' \"$1\" > \"$source_record\"\n"
        "printf 'invoked\\n' >> \"$invocation_record\"\n",
        encoding="utf-8",
    )
    editor.chmod(0o700)

    # Whitelist the child environment. In particular, discard any inherited
    # HERDR_SOCKET_PATH / HERDR_* caller IDs so no command can reach the live
    # default server or inherit its pane context.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "SHELL": "/bin/sh",
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_DATA_HOME": str(data_home),
        "XDG_STATE_HOME": str(state_home),
        "TMPDIR": str(temp_home),
        "HERDR_CONFIG_PATH": str(config_path),
        "EDITOR": str(editor),
    }
    # Herdr derives a named session socket below cfg/herdr/sessions/<name>.
    # Keep it well below macOS sockaddr_un.sun_path's 104-byte limit.
    session_socket = config_dir / "sessions" / session / "herdr.sock"
    if len(os.fsencode(str(session_socket))) >= 100:
        raise ProofBlocked(f"isolated named-session socket path is too long: {session_socket}")
    if "HERDR_SOCKET_PATH" in env:
        raise ProofFailure("the isolated client must use Herdr's named-session socket")
    return env, config_path, capture, source_record


def pane_env_args(env: dict[str, str]) -> list[str]:
    return ["--env", f"EDITOR={env['EDITOR']}"]


def herdr(binary: str, session: str, env: dict[str, str], *args: str, timeout: float = 15) -> str:
    return run([binary, "--session", session, *args], env, timeout=timeout).stdout


def parse_json(text: str, description: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProofFailure(f"{description} did not return JSON: {text[-800:]!r}") from exc
    if not isinstance(value, dict):
        raise ProofFailure(f"{description} did not return a JSON object")
    return value


def result_object(text: str, description: str) -> dict[str, Any]:
    value = parse_json(text, description)
    result = value.get("result", value)
    if not isinstance(result, dict):
        raise ProofFailure(f"{description} returned no result object")
    return result


def snapshot(binary: str, session: str, env: dict[str, str]) -> dict[str, Any]:
    value = parse_json(herdr(binary, session, env, "api", "snapshot"), "Herdr API snapshot")
    snap = value.get("result", value)
    if isinstance(snap, dict) and isinstance(snap.get("snapshot"), dict):
        snap = snap["snapshot"]
    if not isinstance(snap, dict):
        raise ProofFailure("Herdr API snapshot is not an object")
    return snap


def pane_process_info(binary: str, session: str, env: dict[str, str], pane: str) -> dict[str, Any]:
    result = result_object(
        herdr(binary, session, env, "pane", "process-info", "--pane", pane),
        "pane process-info",
    )
    info = result.get("process_info")
    if not isinstance(info, dict):
        raise ProofFailure(f"pane process-info returned no process details: {result!r}")
    return info


def wait_for(predicate: Callable[[], Any], description: str, timeout: float = 12) -> Any:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (ProofBlocked, OSError, subprocess.SubprocessError) as exc:
            last_error = exc
        time.sleep(0.12)
    suffix = f"; last error: {last_error}" if last_error else ""
    raise ProofFailure(f"timed out waiting for {description}{suffix}")


def command_result(text: str, kind: str, key: str) -> dict[str, Any]:
    result = result_object(text, kind)
    item = result.get(key)
    if not isinstance(item, dict):
        raise ProofFailure(f"{kind} returned no {key}: {text[-800:]!r}")
    return item


class AttachedClient:
    def __init__(self, binary: str, session: str, env: dict[str, str], cwd: Path):
        self.pid, self.master = pty.fork()
        self.output = bytearray()
        self.exit_code: int | None = None
        if self.pid == 0:
            os.chdir(cwd)
            os.environ.clear()
            os.environ.update(env)
            os.execv(binary, [binary, "session", "attach", session])
            os._exit(127)
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 140, 0, 0))

    def pump(self, timeout: float = 0.15) -> None:
        if self.exit_code is not None:
            return
        ready, _, _ = select.select([self.master], [], [], timeout)
        while ready:
            try:
                chunk = os.read(self.master, 8192)
            except OSError:
                chunk = b""
            if not chunk:
                break
            self.output.extend(chunk)
            # Drain everything already queued before waiting again. The client
            # can otherwise stall rendering/dispatching while its PTY fills.
            ready, _, _ = select.select([self.master], [], [], 0)
        waited, status = os.waitpid(self.pid, os.WNOHANG)
        if waited:
            self.exit_code = os.waitstatus_to_exitcode(status)

    def wait_for_text(self, text: str, description: str, timeout: float = 12) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if text.encode("utf-8") in self.output:
                return
            self.pump(0.1)
            if self.exit_code is not None:
                break
        screen = self.output.decode("utf-8", "replace")[-1200:]
        raise ProofFailure(f"attached Herdr client did not render {description} {text!r}; exit={self.exit_code}, output={screen!r}")

    def wait_for(self, predicate: Callable[[], bool], description: str, timeout: float = 12) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump(0.1)
            if predicate():
                return
            if self.exit_code is not None:
                break
        screen = self.output.decode("utf-8", "replace")[-1200:]
        raise ProofFailure(f"attached Herdr client did not observe {description}; exit={self.exit_code}, output={screen!r}")

    def key(self, byte: bytes) -> None:
        if self.exit_code is not None:
            raise ProofFailure(f"attached Herdr client exited early with {self.exit_code}")
        os.write(self.master, b"\x02")  # source-configured Ctrl+B prefix
        self.pump(0.12)
        os.write(self.master, byte)
        self.pump(0.22)

    def close(self) -> None:
        if self.exit_code is None:
            try:
                self.key(b"q")  # configured prefix+q detaches this test client
            except (OSError, ProofFailure):
                pass
            deadline = time.monotonic() + 3
            while self.exit_code is None and time.monotonic() < deadline:
                self.pump(0.1)
        if self.exit_code is None:
            # This is only the child created by this test's pty.fork().
            try:
                os.killpg(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 3
            while self.exit_code is None and time.monotonic() < deadline:
                try:
                    waited, status = os.waitpid(self.pid, os.WNOHANG)
                except ChildProcessError:
                    waited, status = self.pid, 0
                if waited:
                    self.exit_code = os.waitstatus_to_exitcode(status)
                else:
                    time.sleep(0.05)
        try:
            os.close(self.master)
        except OSError:
            pass


def status(binary: str, session: str, env: dict[str, str]) -> dict[str, Any]:
    return parse_json(herdr(binary, session, env, "status", "server", "--json"), "Herdr server status")


def api_request(socket_path: Path, method: str, params: dict[str, str]) -> dict[str, Any]:
    request_id = f"herdr-t4:{uuid.uuid4().hex}"
    request = {"id": request_id, "method": method, "params": params}
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(8)
    try:
        client.connect(str(socket_path))
        client.sendall((json.dumps(request) + "\n").encode("utf-8"))
        response = bytearray()
        while b"\n" not in response:
            chunk = client.recv(65536)
            if not chunk:
                break
            response.extend(chunk)
    except OSError as exc:
        raise ProofBlocked(f"could not reach the private test session's API socket: {exc}") from exc
    finally:
        client.close()
    return parse_json(response.decode("utf-8", "replace"), f"Herdr API {method}")


def assert_focus(
    binary: str,
    session: str,
    env: dict[str, str],
    *,
    tab: str,
    pane: str,
    why: str,
    client: AttachedClient | None = None,
) -> None:
    deadline = time.monotonic() + 5
    live: dict[str, Any] = {}
    while time.monotonic() < deadline:
        live = snapshot(binary, session, env)
        if live.get("focused_tab_id") == tab and live.get("focused_pane_id") == pane:
            return
        if client is not None:
            client.pump(0.05)
        time.sleep(0.1)
    output = client.output.decode("utf-8", "replace")[-1200:] if client is not None else ""
    raise ProofFailure(
        f"{why}: expected tab/pane {tab}/{pane}, got "
        f"{live.get('focused_tab_id')}/{live.get('focused_pane_id')}; recent client output={output!r}"
    )


def marker_command(text: str) -> str:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    # Keep known text out of the shell's echoed command so each marker has one
    # occurrence in terminal scrollback (the printed result), not two.
    return f"python3 -c 'import base64;print(base64.b64decode(\"{encoded}\").decode(),end=\"\")'"


def run_proof() -> dict[str, Any]:
    binary = resolve_herdr()
    keys = required_keys()
    # Use /tmp directly: macOS maps TMPDIR to a long /var/folders path, which
    # can exceed sockaddr_un.sun_path once Herdr adds its named-session dirs.
    root = Path(tempfile.mkdtemp(prefix="hsc-", dir="/tmp"))
    root.chmod(0o700)
    session = f"hsc-{uuid.uuid4().hex[:8]}"
    try:
        env, config_path, capture, source_record = isolated_env(root, session)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    server_log = root / "server.log"
    server_process: subprocess.Popen[bytes] | None = None
    server_output: Any = None
    client: AttachedClient | None = None
    cleanup: dict[str, Any] = {
        "client_detached": False,
        "named_session_stopped": False,
        "named_session_deleted": False,
        "temporary_root_removed": False,
        "owner_server_touched": False,
    }
    evidence: dict[str, Any] = {}
    try:
        work = root / "work"
        server_output = server_log.open("wb")
        server_process = subprocess.Popen(
            [binary, "--session", session, "server"],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=server_output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        ready = wait_for(
            lambda: (lambda info: info if info.get("running") else None)(status(binary, session, env)),
            "the private named Herdr server",
            timeout=20,
        )
        if ready.get("version") != "0.9.1" or ready.get("protocol") != 22 or ready.get("session") != session:
            raise ProofFailure(f"private server is not the requested Herdr 0.9.1 named session: {ready!r}")
        socket_path = Path(str(ready.get("socket", ""))).resolve()
        if not socket_path.is_relative_to(root.resolve()):
            raise ProofFailure(f"Herdr resolved the named-session socket outside the private temp root: {socket_path}")
        sessions = parse_json(run([binary, "session", "list", "--json"], env).stdout, "Herdr session list").get("sessions")
        own_sessions = [item for item in sessions or [] if item.get("name") == session]
        if len(own_sessions) != 1 or Path(own_sessions[0].get("session_dir", "")).resolve() != socket_path.parent:
            raise ProofFailure(f"named session catalog does not match its private socket: {own_sessions!r}")

        created_workspace = result_object(
            herdr(binary, session, env, "workspace", "create", "--cwd", str(work),
                  "--label", "T4 isolated non-Pi proof", *pane_env_args(env), "--focus"),
            "workspace create",
        )
        workspace = created_workspace.get("workspace")
        first_tab = created_workspace.get("tab")
        root_pane = created_workspace.get("root_pane")
        if not all(isinstance(item, dict) for item in (workspace, first_tab, root_pane)):
            raise ProofFailure(f"workspace create did not return its IDs: {created_workspace!r}")
        workspace_id = str(workspace.get("workspace_id", ""))
        root_tab = str(first_tab.get("tab_id", ""))
        root_pane_id = str(root_pane.get("pane_id", ""))
        if not workspace_id or not root_tab or not root_pane_id:
            raise ProofFailure(f"workspace create returned incomplete IDs: {created_workspace!r}")

        split = command_result(
            herdr(binary, session, env, "pane", "split", root_pane_id,
                  "--direction", "right", "--cwd", str(work), *pane_env_args(env), "--no-focus"),
            "pane split",
            "pane",
        )
        target_pane_id = str(split.get("pane_id", ""))
        created_tab = result_object(
            herdr(binary, session, env, "tab", "create", "--workspace", workspace_id,
                  "--cwd", str(work), "--label", "T4 second tab", *pane_env_args(env), "--no-focus"),
            "tab create",
        )
        tab2 = created_tab.get("tab")
        second_tab_pane = created_tab.get("root_pane")
        if not isinstance(tab2, dict) or not isinstance(second_tab_pane, dict):
            raise ProofFailure(f"tab create did not return its IDs: {created_tab!r}")
        second_tab_id = str(tab2.get("tab_id", ""))
        second_tab_pane_id = str(second_tab_pane.get("pane_id", ""))
        if not all((root_pane_id, target_pane_id, second_tab_id, second_tab_pane_id)):
            raise ProofFailure(f"Herdr did not return the test layout IDs: {split!r}, {tab2!r}")

        target_context = "\n".join(f"T4_NONPI_CONTEXT_{index:03d}" for index in range(1, 81)) + "\n"
        pane_outputs = {
            root_pane_id: ROOT_MARKER + "\n",
            target_pane_id: target_context + "\n".join(MARKERS) + "\n",
            second_tab_pane_id: OTHER_TAB_MARKER + "\n",
        }
        for pane_id, output in pane_outputs.items():
            herdr(binary, session, env, "pane", "run", pane_id, marker_command(output))
            first_marker = MARKERS[0] if pane_id == target_pane_id else output.splitlines()[0]
            herdr(binary, session, env, "pane", "wait-output", pane_id,
                  "--match", first_marker, "--timeout", "12000")
        if len(MARKERS) != 3 or not MARKERS[0].endswith("FIRST") or not MARKERS[1].endswith("MIDDLE") or not MARKERS[2].endswith("LAST"):
            raise ProofFailure("the fixed known-marker order in the scenario is malformed")

        client = AttachedClient(binary, session, env, root)
        client.wait_for_text(ROOT_MARKER, "the first non-Pi pane")
        assert_focus(binary, session, env, tab=root_tab, pane=root_pane_id, why="initial attached pane", client=client)

        client.key(b"n")
        assert_focus(binary, session, env, tab=second_tab_id, pane=second_tab_pane_id,
                     why="prefix+n next-tab navigation", client=client)
        client.wait_for_text(OTHER_TAB_MARKER, "the second tab after prefix+n")
        client.key(b"p")
        assert_focus(binary, session, env, tab=root_tab, pane=root_pane_id,
                     why="prefix+p previous-tab navigation", client=client)
        client.key(b"l")
        assert_focus(binary, session, env, tab=root_tab, pane=target_pane_id,
                     why="prefix+l right-pane navigation", client=client)
        client.wait_for_text(MARKERS[0], "the selected non-Pi pane")

        editor_env_probe = root / "pane-editor-env.txt"
        herdr(binary, session, env, "pane", "run", target_pane_id,
              "printf '%s\\n' \"$EDITOR\" > " + str(editor_env_probe))
        wait_for(lambda: editor_env_probe.is_file(), "the selected pane shell editor setting")
        if editor_env_probe.read_text(encoding="utf-8").strip() != env["EDITOR"]:
            raise ProofFailure("the selected non-Pi pane did not inherit the configured test editor")

        before_editor = snapshot(binary, session, env)
        pane_count_before_editor = len(before_editor.get("panes", []))
        process_before_editor = pane_process_info(binary, session, env, target_pane_id)
        client.key(b"e")
        try:
            client.wait_for(lambda: capture.is_file() and source_record.is_file(),
                            "prefix+e to invoke the configured editor", timeout=8)
            key_triggered_editor = True
            editor_route = "prefix+e through the attached Herdr client"
        except ProofFailure:
            key_triggered_editor = False
            after_key = snapshot(binary, session, env)
            process_after_key = pane_process_info(binary, session, env, target_pane_id)
            if (after_key.get("focused_pane_id") != target_pane_id
                    or len(after_key.get("panes", [])) != pane_count_before_editor
                    or process_after_key.get("shell_pid") != process_before_editor.get("shell_pid")
                    or process_after_key.get("foreground_processes") != process_before_editor.get("foreground_processes")):
                raise ProofFailure(
                    "prefix+e did not produce the editor receipt and changed the isolated pane focus/layout/process: "
                    f"focus={after_key.get('focused_pane_id')}, panes={len(after_key.get('panes', []))}, "
                    f"shell={process_after_key.get('shell_pid')}"
                )
            # The direct host endpoint is the closest independent substitute:
            # it exercises the same Herdr editor/scrollback operation without
            # claiming that the PTY-delivered prefix chord dispatched it.
            response = api_request(socket_path, "pane.edit_scrollback", {"pane_id": target_pane_id})
            if response.get("error") or (response.get("result") or {}).get("type") != "ok":
                raise ProofFailure(f"isolated Herdr pane.edit_scrollback substitute failed: {response!r}")
            wait_for(lambda: capture.is_file() and source_record.is_file(),
                     "the direct Herdr scrollback editor substitute", timeout=12)
            editor_route = "pane.edit_scrollback API substitute; prefix+e key dispatch not observed"
        wait_for(lambda: len((root / "editor-invocations.txt").read_text(encoding="utf-8").splitlines()) == 1,
                 "exactly one editor invocation")
        # The dummy editor exits immediately. Herdr must restore the same client
        # and keep the selected pane focused rather than leaving or switching it.
        assert_focus(binary, session, env, tab=root_tab, pane=target_pane_id,
                     why="prefix+e editor return", client=client)
        source_path = Path(source_record.read_text(encoding="utf-8").strip())
        wait_for(lambda: not source_path.exists(), "Herdr to remove its temporary scrollback file")

        captured = capture.read_text(encoding="utf-8")
        counts = {marker: captured.count(marker) for marker in MARKERS}
        positions = [captured.find(marker) for marker in MARKERS]
        if counts != {marker: 1 for marker in MARKERS}:
            raise ProofFailure(f"editor scrollback has missing or duplicated known markers: {counts}")
        if not (0 <= positions[0] < positions[1] < positions[2]):
            raise ProofFailure(f"editor scrollback changed known marker order: {positions}")
        if ROOT_MARKER in captured or OTHER_TAB_MARKER in captured:
            raise ProofFailure("the Herdr editor opened a different pane/tab's scrollback")

        # Exercise a left/right return after the editor round-trip. This proves
        # both that Herdr resumed the client and that focus remained pane-local.
        client.key(b"h")
        assert_focus(binary, session, env, tab=root_tab, pane=root_pane_id,
                     why="prefix+h pane navigation after editor return", client=client)
        client.key(b"l")
        assert_focus(binary, session, env, tab=root_tab, pane=target_pane_id,
                     why="prefix+l pane navigation after editor return", client=client)
        evidence = {
            "herdr_version": ready["version"],
            "protocol": ready["protocol"],
            "test_session": session,
            "private_socket": str(socket_path),
            "client_key_routing": "real PTY-attached herdr session client",
            "ordinary_navigation": {
                "next_tab_prefix_n": True,
                "previous_tab_prefix_p": True,
                "right_pane_prefix_l": True,
                "left_pane_prefix_h_after_editor": True,
                "return_to_selected_pane_after_editor": True,
            },
            "editor_binding": keys["edit_scrollback"],
            "editor_route": editor_route,
            "prefix_e_key_dispatched": key_triggered_editor,
            "editor_invocations": 1,
            "editor_markers_once_in_order": MARKERS,
            "foreign_pane_and_tab_markers_absent": True,
            "herdr_temp_scrollback_removed": True,
            "client_alive_and_navigable_after_editor": client.exit_code is None,
            "source_keybindings": keys,
        }
        if client.exit_code is not None:
            raise ProofFailure(f"Herdr client exited after editor return: {client.exit_code}")
        if not key_triggered_editor:
            evidence["blocking_observation"] = (
                f"The isolated PTY client routed prefix+n, prefix+p, and pane focus keys, but "
                f"prefix+e left focus on {target_pane_id} and did not launch the configured editor. "
                "The same test pane's pane.edit_scrollback API endpoint opened its scrollback in the dummy editor."
            )
    finally:
        if client is not None:
            client.close()
            cleanup["client_detached"] = client.exit_code is not None
        else:
            cleanup["client_detached"] = True
        if server_process is not None:
            try:
                current = status(binary, session, env)
            except Exception:
                current = {"running": False}
            if current.get("running"):
                # The command is scoped with --session and the status socket was
                # already checked to live under this script's private temp root.
                try:
                    herdr(binary, session, env, "server", "stop", timeout=10)
                except Exception:
                    if server_process.poll() is None:
                        try:
                            os.killpg(server_process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(server_process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    server_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    server_process.kill()
                    server_process.wait(timeout=3)
            try:
                final_status = status(binary, session, env)
            except Exception as exc:
                final_status = {"running": True, "status_check_error": str(exc)}
            cleanup["named_session_stopped"] = not final_status.get("running", False)
            if cleanup["named_session_stopped"]:
                try:
                    run([binary, "session", "delete", "--json", session], env)
                    cleanup["named_session_deleted"] = True
                except Exception as exc:
                    cleanup["session_delete_error"] = str(exc)
        if server_process is None:
            cleanup["named_session_stopped"] = True
            cleanup["named_session_deleted"] = True
        if server_process is None or cleanup["named_session_stopped"]:
            shutil.rmtree(root, ignore_errors=False)
            cleanup["temporary_root_removed"] = True
        else:
            cleanup["preserved_private_root"] = str(root)
        if server_output is not None:
            server_output.close()

    if not all(cleanup[key] for key in ("client_detached", "named_session_stopped", "named_session_deleted", "temporary_root_removed")):
        raise ProofFailure(f"proof outcome could not be fully cleaned up: {cleanup}")
    evidence["cleanup"] = cleanup
    evidence["status"] = "PASS" if evidence.get("prefix_e_key_dispatched") else "BLOCKED"
    return evidence


def main() -> int:
    try:
        evidence = run_proof()
    except ProofBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "reason": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if evidence.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
