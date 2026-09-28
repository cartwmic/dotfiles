#!/usr/bin/env python3
"""Black-box Pi conversation/editor scenario inside a private Herdr session.

No live model, default Herdr server, home Pi config, or user session is used.
Receipts contain only synthetic test conversation text. Run from the source
checkout with: python3 dot_pi/private_agent/extensions/inspect-prompt/scenario.py
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import pty
import select
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import termios
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[4]
INSPECT_EXTENSION = ROOT / "dot_pi/private_agent/extensions/inspect-prompt/index.ts"
EXPECTED_PI = "0.87.1"
EXPECTED_HERDR = "herdr 0.9.1"


class ScenarioBlocked(RuntimeError):
    """A required isolated runtime or outer path was unavailable."""


class ScenarioFailure(RuntimeError):
    """The observed user path failed an assertion."""


def run(
    argv: list[str], env: dict[str, str], *, timeout: float = 15, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            env=env,
            cwd=cwd or ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ScenarioBlocked(f"could not run {argv[:3]!r}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-1800:]
        raise ScenarioFailure(f"command failed ({result.returncode}): {' '.join(argv)}\n{detail}")
    return result


def resolve_runtime() -> tuple[str, str, Path, Path]:
    pi = shutil.which("pi")
    mise = shutil.which("mise")
    if not pi or not mise:
        raise ScenarioBlocked("Pi and mise are required for the isolated operator-path proof")
    pi_real = Path(os.path.realpath(pi))
    if not pi_real.is_file():
        raise ScenarioBlocked(f"Pi executable could not be resolved: {pi}")
    version = run([pi, "--version"], os.environ.copy(), timeout=10).stdout.strip()
    if version != EXPECTED_PI:
        raise ScenarioBlocked(f"this scenario is pinned to Pi {EXPECTED_PI}; found {version!r}")
    located = run(
        [mise, "where", "github:herdrdev/herdr@0.9.1"], os.environ.copy(), timeout=20
    ).stdout.strip()
    herdr = str((Path(located) / "herdr").resolve())
    if not os.access(herdr, os.X_OK):
        raise ScenarioBlocked(f"the pinned Herdr binary is missing: {herdr}")
    herdr_version = run([herdr, "--version"], os.environ.copy(), timeout=10).stdout.strip()
    if herdr_version != EXPECTED_HERDR:
        raise ScenarioBlocked(f"expected {EXPECTED_HERDR}, found {herdr_version!r}")
    # The installed Pi package owns the faux provider and TypeBox used by the
    # scripted extension. Resolve from the actual CLI, not a hard-coded home.
    package_root = pi_real.parents[2]
    faux = package_root / "node_modules/@earendil-works/pi-ai/dist/providers/faux.js"
    typebox = package_root / "node_modules/typebox/build/index.mjs"
    if not faux.is_file() or not typebox.is_file():
        raise ScenarioBlocked(f"Pi {EXPECTED_PI} is missing the faux provider test modules under {package_root}")
    if not INSPECT_EXTENSION.is_file():
        raise ScenarioFailure(f"source inspector extension is missing: {INSPECT_EXTENSION}")
    return pi, herdr, faux, typebox


def parse_object(text: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScenarioFailure(f"{label} did not return JSON: {text[-1000:]!r}") from exc
    if not isinstance(value, dict):
        raise ScenarioFailure(f"{label} did not return a JSON object")
    return value


def result_object(text: str, label: str) -> dict[str, Any]:
    value = parse_object(text, label)
    result = value.get("result", value)
    if not isinstance(result, dict):
        raise ScenarioFailure(f"{label} returned no result object")
    return result


def extract_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [part for item in value for part in extract_strings(item)]
    if isinstance(value, dict):
        return [part for item in value.values() for part in extract_strings(item)]
    return []


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def wait_for(
    predicate: Callable[[], Any], description: str, *, timeout: float = 15, interval: float = 0.12
) -> Any:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except (OSError, subprocess.SubprocessError) as exc:
            last_error = exc
        time.sleep(interval)
    suffix = f"; last error: {last_error}" if last_error else ""
    raise ScenarioFailure(f"timed out waiting for {description}{suffix}")


def repeated_bash_command(counter_file: Path, done_file: Path) -> str:
    prefix = base64.b64encode(b"T3_POST_COMPACTION_REPEAT_BASH").decode("ascii")
    source = (
        "import base64,pathlib,time;"
        f"counter=pathlib.Path({str(counter_file)!r});"
        "count=int(counter.read_text())+1 if counter.exists() else 1;"
        "counter.write_text(str(count));"
        f"print(base64.b64decode({prefix!r}).decode()+f'_{{count:02d}}',flush=True);"
        "time.sleep(0.3);"
        f"pathlib.Path({str(done_file)!r}).write_text('done')"
    )
    return "!python3 -c " + shlex.quote(source)


def marker_command(
    marker: str,
    release_file: Path,
    done_file: Path | None = None,
    started_file: Path | None = None,
) -> str:
    encoded = base64.b64encode(marker.encode("utf-8")).decode("ascii")
    started = f"pathlib.Path({str(started_file)!r}).write_text('started');" if started_file else ""
    done = f"; pathlib.Path({str(done_file)!r}).write_text('done')" if done_file else ""
    source = (
        "import base64,pathlib,time;"
        f"print(base64.b64decode({encoded!r}).decode(),flush=True);"
        f"{started}"
        f"p=pathlib.Path({str(release_file)!r});"
        "exec('while not p.exists(): time.sleep(0.08)')"
        f"{done}"
    )
    # The unique marker is encoded so a rendered command line cannot satisfy
    # the same assertion as the actual Bash output in an editor receipt.
    return "!python3 -c " + shlex.quote(source)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def isolated_environment(root: Path, session: str, pi: str, artifacts: Path) -> tuple[dict[str, str], Path]:
    home = root / "h"
    config_home = root / "c"
    config_dir = config_home / "herdr"
    data_home = root / "d"
    state_home = root / "s"
    temp_home = root / "t"
    agent_dir = root / "a"
    session_dir = root / "ps"
    work = root / "w"
    for directory in (home, config_dir, data_home, state_home, temp_home, agent_dir, session_dir, work):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)

    herdr_config = config_dir / "config.toml"
    herdr_config.write_text(
        "onboarding = false\n"
        "[server]\nheadless_cols = 120\nheadless_rows = 36\n"
        "[keys]\nprefix = \"ctrl+b\"\ndetach = \"prefix+q\"\nedit_scrollback = \"prefix+e\"\n"
        "[ui]\nsidebar_width = 26\n",
        encoding="utf-8",
    )
    settings = {
        "tuiMode": "fullscreen",
        "externalEditor": f"{sys.executable} {root / 'dummy-editor.py'}",
        "quietStartup": True,
        "compaction": {"keepRecentTokens": 8},
    }
    write_json(agent_dir / "settings.json", settings)

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "SHELL": "/bin/sh",
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "XDG_CONFIG_HOME": str(config_home),
        "XDG_DATA_HOME": str(data_home),
        "XDG_STATE_HOME": str(state_home),
        "TMPDIR": str(temp_home),
        "HERDR_CONFIG_PATH": str(herdr_config),
        "EDITOR": f"{sys.executable} {root / 'dummy-editor.py'}",
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "PI_CODING_AGENT_SESSION_DIR": str(session_dir),
        "PI_OFFLINE": "1",
        "PI_TELEMETRY": "0",
        "T3_STATE_FILE": str(root / "scenario-state.json"),
        "T3_TOOL_RELEASE": str(root / "tool-release"),
        "T3_TOOL_STARTED": str(root / "tool-started"),
        "T3_TOOL_DONE": str(root / "tool-done"),
        "T3_ARTIFACT_DIR": str(artifacts),
        "T3_EDITOR_SEQUENCE": str(root / "editor-sequence"),
        "T3_EDITOR_RELEASE_PREFIX": str(root / "editor-release-"),
        "T3_EDITOR_OPEN_PREFIX": str(root / "editor-open-"),
        "T3_REPEAT_BASH_COMMAND_FILE": str(root / "repeat-bash-command"),
    }
    session_socket = config_dir / "sessions" / session / "herdr.sock"
    if len(os.fsencode(session_socket)) >= 100:
        raise ScenarioBlocked(f"private Herdr named-session socket path is too long: {session_socket}")
    if Path(pi).resolve().is_relative_to(home.resolve()):
        raise ScenarioFailure("Pi executable unexpectedly resolves inside the isolated HOME")
    return env, work


def write_fixtures(root: Path, faux_module: Path, typebox_module: Path) -> tuple[Path, Path]:
    marker_stream = "T3_ASSISTANT_PARTIAL_MARKER\n" + "\n".join(
        f"T3_INITIAL_ROW_{index:03d} | stable passage text for fullscreen viewport anchoring"
        for index in range(1, 91)
    )
    pending_stream = "T3_BOTTOM_FOLLOW_START\n" + "\n".join(
        f"T3_FOLLOW_ROW_{index:03d} | streaming at the live end of the conversation"
        for index in range(1, 151)
    )
    faux_extension = root / "scripted-backend.mjs"
    faux_extension.write_text(
        f'''import {{ fauxProvider, fauxAssistantMessage, fauxToolCall }} from {json.dumps(str(faux_module))};
import {{ Type }} from {json.dumps(str(typebox_module))};
import {{ existsSync, readFileSync, writeFileSync }} from "node:fs";
import {{ setTimeout as delay }} from "node:timers/promises";

export default function (pi) {{
const statePath = process.env.T3_STATE_FILE;
const readState = () => {{ try {{ return JSON.parse(readFileSync(statePath, "utf8")); }} catch {{ return {{}}; }} }};
const updateState = (update) => {{ const state = readState(); Object.assign(state, update); writeFileSync(statePath, JSON.stringify(state)); }};
const contentText = (content) => typeof content === "string" ? content : (content ?? []).filter(x => x.type === "text").map(x => x.text).join("\\n");
const previousState = readState();
let progressCount = Number(previousState.progressCount ?? 0);
let assistantEnds = Number(previousState.assistantEnds ?? 0);
let toolEnds = Number(previousState.toolEnds ?? 0);
let agentEnds = Number(previousState.agentEnds ?? 0);
let agentSettled = Number(previousState.agentSettled ?? 0);
let branchSwitches = Number(previousState.branchSwitches ?? 0);
let providerCalls = Number(previousState.providerCalls ?? 0);
let compactions = Number(previousState.compactions ?? 0);
const faux = fauxProvider({{ provider: "t3-scripted", api: "t3-scripted-api", tokensPerSecond: 120, tokenSize: {{ min: 5, max: 5 }} }});
const responses = [
  fauxAssistantMessage({json.dumps(marker_stream)}),
  fauxAssistantMessage(fauxToolCall("scenario_stream_tool", {{}}, {{ id: "t3-partial-tool-call" }}), {{ stopReason: "toolUse" }}),
  fauxAssistantMessage("T3_TOOL_TURN_FINAL_MARKER"),
  fauxAssistantMessage({json.dumps(pending_stream)}),
  fauxAssistantMessage("T3_ABANDONED_BRANCH_MARKER"),
  fauxAssistantMessage("T3_SUBSEQUENT_TURN_MARKER"),
];
faux.setResponses(responses.slice(providerCalls).map(response => async () => {{
  providerCalls += 1;
  updateState({{ providerCalls }});
  return response;
}}));
pi.registerProvider(faux.provider);
writeFileSync(statePath, JSON.stringify({{ ...previousState, progressCount, assistantEnds, toolEnds, agentEnds, agentSettled, branchSwitches, providerCalls, compactions }}));
const publish = () => updateState({{ progressCount, assistantEnds, toolEnds, agentEnds, agentSettled, branchSwitches, providerCalls, compactions }});
pi.on("session_before_compact", (event) => {{
  if (event.reason !== "manual") return;
  updateState({{ manualCompactionPrepared: true, compactionFirstKeptEntryId: event.preparation.firstKeptEntryId }});
  return {{ compaction: {{
    summary: "T3_TEST_COMPACTION_SUMMARY",
    firstKeptEntryId: event.preparation.firstKeptEntryId,
    tokensBefore: event.preparation.tokensBefore,
  }} }};
}});
pi.on("session_compact", (event) => {{
  compactions += 1;
  updateState({{ compactions, compactionReason: event.reason, compactionFromExtension: event.fromExtension,
    compactionSummary: event.compactionEntry.summary }});
}});
pi.on("message_update", (event) => {{
  if (event.message?.role === "assistant") {{
    progressCount += 1;
    const text = contentText(event.message.content);
    writeFileSync(process.env.T3_STATE_FILE + ".assistant", text);
    publish();
  }}
}});
pi.on("message_end", (event) => {{ if (event.message?.role === "assistant") {{ assistantEnds += 1; publish(); }} }});
pi.on("tool_execution_update", () => {{ progressCount += 1; publish(); }});
pi.on("tool_execution_end", () => {{ toolEnds += 1; publish(); }});
pi.on("agent_end", (_event, ctx) => {{
  agentEnds += 1;
  const active = ctx.sessionManager.getBranch().map(entry => JSON.stringify(entry)).join("\\n");
  publish();
  updateState({{ branchContainsAbandonedMarker: active.includes("T3_ABANDONED_BRANCH_MARKER"), branchContainsSubsequentMarker: active.includes("T3_SUBSEQUENT_TURN_MARKER") }});
}});
pi.on("agent_settled", (_event, ctx) => {{
  agentSettled += 1;
  const settledPendingBashResults = ctx.sessionManager.getBranch()
    .filter(entry => entry.type === "message" && entry.message?.role === "bashExecution" &&
      typeof entry.message.output === "string" && entry.message.output.includes("T3_AGENT_PENDING_RUNNING_MARKER"))
    .map(entry => ({{ command: entry.message.command, output: entry.message.output }}));
  updateState({{ settledPendingBashResults }});
  publish();
}});
pi.on("session_start", (_event, ctx) => {{
  branchSwitches += 1;
  const visible = ctx.sessionManager.getBranch().map(entry => JSON.stringify(entry)).join("\\n");
  updateState({{ progressCount, assistantEnds, toolEnds, agentEnds, agentSettled, branchSwitches, forkBranchHasAbandonedMarker: visible.includes("T3_ABANDONED_BRANCH_MARKER") }});
}});
pi.registerShortcut("ctrl+alt+shift+i", {{
  description: "Record the isolated test's live pending Bash component",
  handler: async (ctx) => {{
    await ctx.ui.custom((tui, _theme, _keybindings, done) => {{
      try {{
        const roots = Array.isArray(tui.children) ? tui.children : [];
        const pending = Array.isArray(roots[1]?.children) ? roots[1].children : [];
        const components = pending
          .filter(component => component?.constructor?.name === "BashExecutionComponent")
          .map(component => ({{
            command: component.command,
            status: component.status,
            outputLines: Array.isArray(component.outputLines) ? [...component.outputLines] : [],
          }}));
        updateState({{ settledPendingDockProbe: {{ mode: tui.mode, rootCount: roots.length, components }} }});
      }} catch (error) {{
        updateState({{ settledPendingDockProbeError: String(error) }});
      }} finally {{
        done(undefined);
      }}
      return {{ render: () => [] }};
    }});
  }},
}});

pi.registerTool({{
  name: "scenario_stream_tool",
  label: "scenario stream",
  description: "Emit deterministic partial tool updates for the isolated TUI proof.",
  parameters: Type.Object({{}}),
  async execute(_id, _params, _signal, onUpdate) {{
    let n = 0;
    writeFileSync(process.env.T3_TOOL_STARTED, "started");
    while (!existsSync(process.env.T3_TOOL_RELEASE)) {{
      const text = n === 0 ? "T3_TOOL_PARTIAL_MARKER" : "T3_TOOL_PARTIAL_MARKER\\nT3_TOOL_UPDATE_" + String(n).padStart(3, "0");
      onUpdate?.({{ content: [{{ type: "text", text }}] }});
      n += 1;
      await delay(160);
    }}
    writeFileSync(process.env.T3_TOOL_DONE, "done");
    return {{ content: [{{ type: "text", text: "T3_TOOL_FINAL_MARKER" }}] }};
  }},
}});

pi.registerCommand("scenario-check-repeated-bash", {{
  description: "Record finalized repeated Bash occurrences for the isolated compaction check.",
  handler: async (_args, ctx) => {{
    const expectedCommand = readFileSync(process.env.T3_REPEAT_BASH_COMMAND_FILE, "utf8");
    const branch = ctx.sessionManager.getBranch();
    const results = branch
      .filter(entry => entry.type === "message" && entry.message?.role === "bashExecution" && entry.message.command === expectedCommand)
      .map(entry => ({{ command: entry.message.command, output: entry.message.output }}));
    const summaries = branch
      .filter(entry => entry.type === "compaction" && entry.summary === "T3_TEST_COMPACTION_SUMMARY")
      .map(entry => entry.summary);
    updateState({{ repeatedBashBranchResults: results, testCompactionSummaries: summaries }});
  }},
}});

pi.registerCommand("scenario-abandon-branch", {{
  description: "Create a real sibling session branch for the snapshot exclusion assertion.",
  handler: async (_args, ctx) => {{
    const branch = ctx.sessionManager.getBranch();
    const index = branch.findIndex(entry => entry.type === "message" && entry.message?.role === "user" && contentText(entry.message.content).includes("T3_ABANDONED_BRANCH_PROMPT"));
    if (index < 1) throw new Error("could not find the synthetic branch prompt and its parent entry");
    const parent = branch[index - 1];
    const result = await ctx.fork(parent.id, {{
      position: "at",
      withSession: async next => {{
        const active = next.sessionManager.getBranch().map(entry => JSON.stringify(entry)).join("\\n");
        updateState({{ progressCount, assistantEnds, toolEnds, agentEnds, agentSettled, branchSwitches, forkCommandReturned: true, forkCommandHasAbandonedMarker: active.includes("T3_ABANDONED_BRANCH_MARKER") }});
      }},
    }});
    if (result.cancelled) throw new Error("synthetic branch creation was cancelled");
  }},
}});
}}
''',
        encoding="utf-8",
    )
    faux_extension.chmod(0o600)

    dummy_editor = root / "dummy-editor.py"
    dummy_editor.write_text(
        '''#!/usr/bin/env python3
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit(31)
source = Path(sys.argv[1])
root = Path(os.environ["T3_ARTIFACT_DIR"])
sequence_path = Path(os.environ["T3_EDITOR_SEQUENCE"])
try:
    index = int(sequence_path.read_text()) + 1
except (OSError, ValueError):
    index = 1
sequence_path.write_text(str(index))
sequence_path.chmod(0o600)
receipt = root / f"editor-{index:02d}.md"
shutil.copyfile(source, receipt)
receipt.chmod(0o600)
try:
    progress = json.loads(Path(os.environ["T3_STATE_FILE"]).read_text()).get("progressCount", 0)
except (OSError, json.JSONDecodeError):
    progress = 0
metadata = {
    "index": index,
    "source_path": str(source),
    "source_sha256_at_open": hashlib.sha256(source.read_bytes()).hexdigest(),
    "receipt_path": str(receipt),
    "progress_count_at_open": progress,
    "opened_at": time.time(),
}
open_path = Path(os.environ["T3_EDITOR_OPEN_PREFIX"] + str(index))
open_path.write_text(json.dumps(metadata))
open_path.chmod(0o600)
release = Path(os.environ["T3_EDITOR_RELEASE_PREFIX"] + str(index))
deadline = time.monotonic() + 70
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.04)
metadata["released"] = release.exists()
metadata["sha256_at_release"] = hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None
metadata["closed_at"] = time.time()
open_path.write_text(json.dumps(metadata))
if not release.exists():
    raise SystemExit(32)
''',
        encoding="utf-8",
    )
    dummy_editor.chmod(0o700)
    return faux_extension, dummy_editor


class AttachedHerdrClient:
    """A real Herdr terminal client attached through its own PTY."""

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
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", 36, 120, 0, 0))

    def pump(self, timeout: float = 0.1) -> None:
        if self.exit_code is not None:
            return
        ready, _, _ = select.select([self.master], [], [], timeout)
        while ready:
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            self.output.extend(chunk)
            ready, _, _ = select.select([self.master], [], [], 0)
        waited, status = os.waitpid(self.pid, os.WNOHANG)
        if waited:
            self.exit_code = os.waitstatus_to_exitcode(status)

    def send(self, data: bytes) -> None:
        if self.exit_code is not None:
            raise ScenarioFailure(f"private Herdr client exited early with {self.exit_code}")
        os.write(self.master, data)
        self.pump(0.08)

    def type_line(self, text: str) -> None:
        self.send(text.encode("utf-8") + b"\r")

    def wait_for_text(self, text: str, description: str, timeout: float = 12) -> None:
        deadline = time.monotonic() + timeout
        expected = text.encode("utf-8")
        while time.monotonic() < deadline:
            if expected in self.output:
                return
            self.pump(0.1)
            if self.exit_code is not None:
                break
        tail = self.output.decode("utf-8", "replace")[-1200:]
        raise ScenarioFailure(f"attached Herdr client did not render {description} {text!r}; exit={self.exit_code}, output={tail!r}")

    def shortcut(self) -> None:
        # Kitty keyboard protocol encoding for a Ctrl+Alt+E key press. Herdr
        # enables flags 7 on the attached client terminal, including event type.
        self.send(b"\x1b[101;7:1u\x1b[101;7:3u")

    def detach(self) -> None:
        if self.exit_code is not None:
            return
        try:
            os.write(self.master, b"\x02")
            time.sleep(0.12)
            os.write(self.master, b"q")
        except OSError:
            pass
        deadline = time.monotonic() + 3
        while self.exit_code is None and time.monotonic() < deadline:
            self.pump(0.1)
        if self.exit_code is None:
            try:
                os.killpg(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 2
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


def assert_contains(text: str, marker: str, where: str) -> None:
    if marker not in text:
        raise ScenarioFailure(f"{where} did not contain {marker!r}: {text[-1400:]!r}")


def assert_absent(text: str, marker: str, where: str) -> None:
    if marker in text:
        raise ScenarioFailure(f"{where} unexpectedly contained {marker!r}")


def assert_once(text: str, marker: str, where: str) -> None:
    count = text.count(marker)
    if count != 1:
        raise ScenarioFailure(f"{where} contained {marker!r} {count} times, expected exactly once")


def row_numbers(text: str, prefix: str) -> list[int]:
    import re

    return [int(value) for value in re.findall(re.escape(prefix) + r"(\d{3})", text)]


class OperatorScenario:
    def __init__(self, pi: str, herdr: str, root: Path, artifacts: Path):
        self.pi = pi
        self.herdr = herdr
        self.root = root
        self.artifacts = artifacts
        self.session = f"p3-{uuid.uuid4().hex[:7]}"
        self.env, self.work = isolated_environment(root, self.session, pi, artifacts)
        self.server_log = root / "herdr-server.log"
        self.server: subprocess.Popen[bytes] | None = None
        self.server_output: Any = None
        self.client: AttachedHerdrClient | None = None
        self.pane = ""
        self.socket = ""
        self.evidence: dict[str, Any] = {
            "status": "RUNNING",
            "pi_version": EXPECTED_PI,
            "herdr_version": "0.9.1",
            "session": self.session,
            "client_path": "PTY-attached Herdr named-session client; pane text and keys routed through its private server",
            "provider": "Pi faux provider; no live model/network call",
            "shortcut": "Ctrl+Alt+E Kitty key-press bytes written to the private attached Herdr client PTY and routed to the focused Pi pane",
            "positive_assertions": [],
            "negative_assertions": [],
            "screens": [],
            "editors": [],
            "cleanup": {},
        }
        self.receipt_names: dict[str, int] = {}

    def herdr_cmd(self, *args: str, timeout: float = 15) -> str:
        return run(
            [self.herdr, "--session", self.session, *args], self.env, timeout=timeout, cwd=self.root
        ).stdout

    def status(self) -> dict[str, Any]:
        return parse_object(
            run([self.herdr, "--session", self.session, "status", "server", "--json"], self.env).stdout,
            "private Herdr server status",
        )

    def start(self) -> None:
        self.server_output = self.server_log.open("wb")
        self.server = subprocess.Popen(
            [self.herdr, "--session", self.session, "server"],
            cwd=self.root,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=self.server_output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        ready = wait_for(
            lambda: (lambda state: state if state.get("running") else None)(self.status()),
            "the private named Herdr server",
            timeout=20,
        )
        if ready.get("version") != "0.9.1" or ready.get("protocol") != 22 or ready.get("session") != self.session:
            raise ScenarioFailure(f"private Herdr server identity/version mismatch: {ready!r}")
        socket = Path(str(ready.get("socket", ""))).resolve()
        if not socket.is_relative_to(self.root.resolve()):
            raise ScenarioFailure(f"private Herdr socket escaped its temp root: {socket}")
        sessions_text = run([self.herdr, "session", "list", "--json"], self.env).stdout
        sessions = parse_object(sessions_text, "private Herdr session list").get("sessions", [])
        matches = [entry for entry in sessions if entry.get("name") == self.session]
        if len(matches) != 1 or Path(matches[0].get("session_dir", "")).resolve() != socket.parent:
            raise ScenarioFailure(f"named session catalog is not private and unique: {matches!r}")
        self.socket = str(socket)
        self.evidence.update({
            "protocol": ready["protocol"],
            "private_socket": self.socket,
            "private_session_catalog_verified": True,
        })

        editor_env = [
            "HOME", "PATH", "TMPDIR", "EDITOR", "PI_CODING_AGENT_DIR",
            "PI_CODING_AGENT_SESSION_DIR", "PI_OFFLINE", "PI_TELEMETRY",
            "T3_STATE_FILE", "T3_TOOL_RELEASE", "T3_TOOL_STARTED", "T3_TOOL_DONE",
            "T3_ARTIFACT_DIR", "T3_EDITOR_SEQUENCE", "T3_EDITOR_RELEASE_PREFIX",
            "T3_EDITOR_OPEN_PREFIX", "T3_REPEAT_BASH_COMMAND_FILE",
        ]
        create = result_object(
            self.herdr_cmd(
                "workspace", "create", "--cwd", str(self.work), "--label", "T3 isolated Pi operator proof",
                "--focus", *[item for name in editor_env for item in ("--env", f"{name}={self.env[name]}")],
            ),
            "private workspace create",
        )
        pane = create.get("root_pane")
        if not isinstance(pane, dict) or not pane.get("pane_id"):
            raise ScenarioFailure(f"Herdr did not return the isolated Pi pane: {create!r}")
        self.pane = str(pane["pane_id"])
        self.evidence["pi_pane"] = self.pane

        # Attach the actual terminal client before launching Pi. All user input,
        # including the extension shortcut, goes through this client PTY.
        self.client = AttachedHerdrClient(self.herdr, self.session, self.env, self.root)
        wait_for(lambda: self.client and self.client.exit_code is None, "the private attached Herdr client", timeout=8)
        self.herdr_cmd("pane", "run", self.pane, "printf '\\nT3_HERDR_CLIENT_READY_MARKER\\n'")
        self.wait_visible("T3_HERDR_CLIENT_READY_MARKER", "initial Herdr pane readiness marker", timeout=8)
        self.client.wait_for_text("T3_HERDR_CLIENT_READY_MARKER", "initial Herdr pane readiness marker", timeout=8)
        # Verify ordinary keyboard input is routed to the focused pane, not
        # just that Herdr's server reports it selected.
        self.activate_pane_input("attached client selected the Pi pane for keyboard input")
        self.client.send(b"T3_CLIENT_INPUT_PROBE")
        assert_contains(self.visible(), "T3_CLIENT_INPUT_PROBE", "attached client keyboard-input probe")
        self.client.send(b"\x15")
        assert_absent(self.visible(), "T3_CLIENT_INPUT_PROBE", "cleared attached client keyboard-input probe")
        self.evidence["attached_client_keyboard_route_verified"] = True
        self.record_assertion("attached Herdr client PTY can type into and clear the focused pane before driving Pi")

    def launch_pi(self) -> None:
        fixture, _editor = write_fixtures(self.root, self.faux_module, self.typebox_module)
        self.evidence["fixture_extension"] = str(fixture)
        args = [
            self.pi, "--offline", "--no-session", "--no-extensions", "--no-skills",
            "--no-prompt-templates", "--no-context-files", "--no-themes", "--no-builtin-tools",
            "--tui-mode", "fullscreen", "--provider", "t3-scripted", "--model", "t3-scripted/faux-1",
            "--extension", str(INSPECT_EXTENSION), "--extension", str(fixture),
            "--append-system-prompt", "T3_SYSTEM_INTERNAL_MARKER",
        ]
        # Sessions are private but persistent within this one Pi run so the real
        # fork API can generate a discarded sibling branch for the negative check.
        args.remove("--no-session")
        args.extend(["--session-dir", str(self.env["PI_CODING_AGENT_SESSION_DIR"])])
        self.herdr_cmd("pane", "run", self.pane, shlex.join(args), timeout=15)
        state_path = Path(self.env["T3_STATE_FILE"])
        try:
            wait_for(
                lambda: int(load_state(state_path).get("branchSwitches", 0)) >= 1,
                "Pi interactive startup and session_start hook",
                timeout=45,
            )
        except ScenarioFailure as exc:
            try:
                startup_screen = self.visible("pi-startup-failure")
            except Exception as read_error:
                startup_screen = f"pane read failed: {read_error}"
            try:
                process_snapshot = self.herdr_cmd("pane", "process-info", "--pane", self.pane)
            except Exception as process_error:
                process_snapshot = f"process-info failed: {process_error}"
            client_tail = self.client.output.decode("utf-8", "replace")[-1800:] if self.client else ""
            raise ScenarioFailure(
                f"Pi test extension did not register: {exc}; process={process_snapshot[-1000:]!r}; "
                f"screen={startup_screen[-1600:]!r}; client={client_tail!r}"
            ) from exc
        def pi_is_foreground() -> dict[str, Any] | None:
            process = result_object(self.herdr_cmd("pane", "process-info", "--pane", self.pane), "Pi pane process")
            info = process.get("process_info", {})
            foreground = info.get("foreground_processes", [])
            if any(item.get("argv0") == "pi" for item in foreground):
                return info
            return None

        process_info = wait_for(pi_is_foreground, "Pi to own the isolated pane foreground", timeout=30)
        self.evidence["pane_process_info"] = process_info
        initial_screen = self.visible("pi-ready")
        if "Trust project folder?" in initial_screen or "Unknown provider" in initial_screen:
            raise ScenarioFailure(f"Pi did not reach its trusted fullscreen input state: {initial_screen[-1600:]!r}")

    def visible(self, label: str | None = None) -> str:
        if self.client:
            self.client.pump(0)
        result = self.herdr_cmd("pane", "read", self.pane, "--source", "visible", "--lines", "120")
        try:
            payload: Any = json.loads(result)
            text = "\n".join(extract_strings(payload))
        except json.JSONDecodeError:
            text = result
        if self.client:
            self.client.pump(0)
        if label:
            path = self.artifacts / f"screen-{label}.txt"
            path.write_text(text, encoding="utf-8")
            path.chmod(0o600)
            self.evidence["screens"].append({"name": label, "path": str(path)})
        return text

    def wait_visible(self, marker: str, label: str, *, timeout: float = 20) -> str:
        def visible_match() -> str | None:
            text = self.visible()
            return text if marker in text else None

        return wait_for(visible_match, label, timeout=timeout)

    def send_line(self, text: str) -> None:
        if not self.client:
            raise ScenarioFailure("the isolated Herdr client is not attached")
        self.herdr_cmd("pane", "send-text", self.pane, text)
        self.herdr_cmd("pane", "send-keys", self.pane, "enter")

    def herdr_snapshot(self) -> dict[str, Any]:
        value = parse_object(self.herdr_cmd("api", "snapshot"), "private Herdr API snapshot")
        snapshot = value.get("result", value)
        if isinstance(snapshot, dict) and isinstance(snapshot.get("snapshot"), dict):
            snapshot = snapshot["snapshot"]
        if not isinstance(snapshot, dict):
            raise ScenarioFailure(f"private Herdr API snapshot has an unexpected shape: {value!r}")
        return snapshot

    def assert_focused_pane(self, stage: str) -> dict[str, Any]:
        snapshot = self.herdr_snapshot()
        focused = snapshot.get("focused_pane_id")
        if focused != self.pane:
            raise ScenarioFailure(f"{stage}: expected Pi pane {self.pane} to remain focused, got {focused!r}")
        self.evidence.setdefault("focus_checks", []).append({
            "stage": stage,
            "focused_pane_id": focused,
            "pi_pane_id": self.pane,
        })
        return snapshot

    def activate_pane_input(self, stage: str) -> dict[str, Any]:
        if not self.client:
            raise ScenarioFailure("the isolated Herdr client is not attached")
        # The attached client requires a real terminal click to route normal
        # keystrokes into the selected pane; API focus alone is only selection.
        self.client.send(b"\x1b[<0;50;10M")
        time.sleep(0.2)
        self.client.pump(0)
        snapshot = self.assert_focused_pane(stage)
        self.evidence.setdefault("input_events", []).append({
            "description": stage,
            "route": "mouse press through attached Herdr client PTY",
            "bytes_hex": "1b5b3c303b35303b31304d",
        })
        return snapshot

    def send_herdr_key(self, data: bytes, description: str) -> None:
        if not self.client:
            raise ScenarioFailure("the isolated Herdr client is not attached")
        self.activate_pane_input(f"activate pane before {description}")
        self.client.send(data)
        self.evidence.setdefault("input_events", []).append({
            "description": description,
            "route": "raw bytes through attached Herdr client PTY",
            "bytes_hex": data.hex(),
        })

    def wait_signal(self, predicate: Callable[[], Any], description: str, *, timeout: float = 20) -> Any:
        def poll() -> Any:
            if self.client:
                self.client.pump(0)
            return predicate()

        return wait_for(poll, description, timeout=timeout)

    def wait_state(self, predicate: Callable[[dict[str, Any]], bool], description: str, *, timeout: float = 20) -> dict[str, Any]:
        def read_if_ready() -> dict[str, Any] | None:
            state = load_state(Path(self.env["T3_STATE_FILE"]))
            return state if predicate(state) else None

        return self.wait_signal(read_if_ready, description, timeout=timeout)

    def wait_progress(self, predicate: Callable[[dict[str, Any]], bool], description: str, *, timeout: float = 20) -> dict[str, Any]:
        return self.wait_state(predicate, description, timeout=timeout)

    def open_editor(self, label: str, *, timeout: float = 8) -> tuple[int, Path, dict[str, Any]]:
        before = int(Path(self.env["T3_EDITOR_SEQUENCE"]).read_text()) if Path(self.env["T3_EDITOR_SEQUENCE"]).exists() else 0
        self.send_herdr_key(b"\x1b[101;7:1u\x1b[101;7:3u", "Ctrl+Alt+E through attached Herdr client PTY")
        expected = before + 1
        marker = Path(f"{self.env['T3_EDITOR_OPEN_PREFIX']}{expected}")
        self.wait_signal(
            lambda: marker.is_file(),
            f"configured dummy editor open for {label}",
            timeout=timeout,
        )
        metadata = json.loads(marker.read_text(encoding="utf-8"))
        if metadata.get("index") != expected:
            raise ScenarioFailure(f"editor invocation counter changed unexpectedly: {metadata!r}")
        focused = self.assert_focused_pane(f"editor {label} opened through the Herdr client")
        metadata["focused_pane_id_at_open"] = focused.get("focused_pane_id")
        self.receipt_names[label] = expected
        self.evidence["editors"].append({"stage": label, **metadata})
        return expected, Path(metadata["receipt_path"]), metadata

    def hold_progress(self, index: int, opened: dict[str, Any], *, minimum_delta: int = 4, timeout: float = 15) -> dict[str, Any]:
        start = int(opened.get("progress_count_at_open", 0))
        result = self.wait_progress(
            lambda state: int(state.get("progressCount", 0)) >= start + minimum_delta,
            f"agent progress to advance by {minimum_delta} while editor {index} remains open",
            timeout=timeout,
        )
        # Hash the real editor input again before release; the editor receipt is
        # a copy made by the dummy configured editor at invocation time.
        meta_path = Path(f"{self.env['T3_EDITOR_OPEN_PREFIX']}{index}")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if not metadata.get("source_path") or not Path(metadata["source_path"]).is_file():
            raise ScenarioFailure(f"Pi removed its editor source before release: {metadata!r}")
        import hashlib

        current_hash = hashlib.sha256(Path(metadata["source_path"]).read_bytes()).hexdigest()
        if current_hash != metadata.get("source_sha256_at_open"):
            raise ScenarioFailure("the editor source changed while open; snapshot was not static")
        release = Path(f"{self.env['T3_EDITOR_RELEASE_PREFIX']}{index}")
        release.write_text("release\n", encoding="utf-8")
        release.chmod(0o600)
        self.evidence["editors"][-1].update({
            "progress_count_before_release": int(result.get("progressCount", 0)),
            "progress_delta_while_open": int(result.get("progressCount", 0)) - start,
            "static_source_verified": True,
        })
        wait_for(lambda: json.loads(meta_path.read_text()).get("released"), f"dummy editor {index} exit", timeout=12)
        self.assert_focused_pane(f"editor {index} return")
        source = Path(metadata["source_path"])
        wait_for(lambda: not source.exists(), f"Pi to remove editor snapshot source {index}", timeout=8)
        if self.client and self.client.exit_code is not None:
            raise ScenarioFailure(f"Herdr client exited while editor {index} was open: {self.client.exit_code}")
        return result

    def finish_editor(self, index: int, opened: dict[str, Any], *, minimum_delta: int = 4, timeout: float = 15) -> dict[str, Any]:
        return self.hold_progress(index, opened, minimum_delta=minimum_delta, timeout=timeout)

    def record_assertion(self, assertion: str, *, negative: bool = False) -> None:
        key = "negative_assertions" if negative else "positive_assertions"
        self.evidence[key].append(assertion)

    def run_scenario(self) -> dict[str, Any]:
        self.start()
        self.launch_pi()
        state_path = Path(self.env["T3_STATE_FILE"])
        editor_dir = self.artifacts

        # Idle Pi user Bash command: the visible running chat component must be
        # captured by Ctrl+Alt+E before its output is finalized or branch saved.
        idle_release = self.root / "idle-bash-release"
        idle_done = self.root / "idle-bash-done"
        self.send_line(marker_command("T3_IDLE_CHAT_RUNNING_MARKER", idle_release, idle_done))
        self.wait_visible("T3_IDLE_CHAT_RUNNING_MARKER", "idle ! output in Pi chat", timeout=20)
        idle_screen = self.visible("idle-bash-running")
        assert_contains(idle_screen, "T3_IDLE_CHAT_RUNNING_MARKER", "live idle ! chat pane")
        index, receipt, opened = self.open_editor("idle-bash-running")
        idle_snapshot = receipt.read_text(encoding="utf-8")
        assert_contains(idle_snapshot, "T3_IDLE_CHAT_RUNNING_MARKER", "idle-running ! editor receipt")
        assert_contains(idle_snapshot, "Status: running", "idle-running ! editor receipt")
        self.record_assertion("idle-running ! chat output copied from the live Pi component through Ctrl+Alt+E")
        self.finish_editor(index, opened, minimum_delta=0, timeout=10)
        idle_release.write_text("release\n", encoding="utf-8")
        self.wait_signal(idle_done.exists, "idle ! shell to finish", timeout=12)
        self.wait_state(lambda state: int(state.get("agentEnds", 0)) == 0, "Pi remains idle after ! output")

        # First scripted assistant response: invoke the shortcut after its
        # unique marker is on screen but before message_end, then prove progress
        # continues while the editor holds the terminal.
        self.send_line("T3_FIRST_STREAM_PROMPT")
        self.wait_visible("T3_ASSISTANT_PARTIAL_MARKER", "partial assistant text in Pi viewport", timeout=20)
        assistant_screen = self.visible("assistant-before-editor")
        self.wait_visible("T3_INITIAL_ROW_020", "assistant text at the live bottom", timeout=20)
        bottom_start = self.visible("bottom-follow-initial")
        bottom_start_rows = row_numbers(bottom_start, "T3_INITIAL_ROW_")
        if not bottom_start_rows:
            raise ScenarioFailure("no assistant rows were visible at the live bottom")
        assert_absent(bottom_start, "Jump to latest message", "initial bottom-follow view")
        self.wait_visible("T3_INITIAL_ROW_040", "newer assistant rows following at the live bottom", timeout=20)
        bottom_later = self.visible("bottom-follow-later")
        bottom_later_rows = row_numbers(bottom_later, "T3_INITIAL_ROW_")
        if not bottom_later_rows or max(bottom_later_rows) <= max(bottom_start_rows):
            raise ScenarioFailure(f"Pi did not follow new output at the bottom: {bottom_start_rows[-5:]!r} -> {bottom_later_rows[-5:]!r}")
        assert_absent(bottom_later, "Jump to latest message", "later bottom-follow view")
        self.evidence["bottom_follow"] = {
            "first_max_row": max(bottom_start_rows),
            "later_max_row": max(bottom_later_rows),
            "newer_rows_followed": True,
            "latest_message_affordance_absent": True,
        }
        self.record_assertion("at-bottom viewport followed later assistant rows independently of the scrolled-up anchor")

        # Exercise the independent scrolled-up assistant-text path before this
        # response finalizes. Progress is sampled from the faux provider's
        # message_update hook and the streamed body itself, not from elapsed
        # time or later tool output.
        self.send_herdr_key(b"\x1b[5~", "PageUp during assistant text streaming through Herdr pane input")
        scrolled_before = self.wait_signal(
            lambda: (
                lambda screen: screen
                if "Jump to latest message" in screen and row_numbers(screen, "T3_INITIAL_ROW_")
                else None
            )(self.visible()),
            "scrolled-up assistant text viewport and latest-message affordance",
            timeout=8,
        )
        scrolled_before = self.visible("assistant-text-scrolled-up-before-update")
        assert_contains(scrolled_before, "Jump to latest message", "scrolled-up assistant text view before updates")
        assistant_rows_before = row_numbers(scrolled_before, "T3_INITIAL_ROW_")
        if not assistant_rows_before:
            raise ScenarioFailure("no assistant passage was visible after scrolling up during text streaming")
        assistant_anchor = f"T3_INITIAL_ROW_{assistant_rows_before[len(assistant_rows_before) // 2]:03d}"
        assistant_anchor_y_before = next(
            i for i, line in enumerate(scrolled_before.splitlines()) if assistant_anchor in line
        )
        assistant_state_before = load_state(state_path)
        assistant_ends_at_scroll = int(assistant_state_before.get("assistantEnds", 0))
        if assistant_ends_at_scroll != 0:
            raise ScenarioFailure(f"assistant text finalized before the scrolled-up observation: {assistant_state_before!r}")
        assistant_text_path = Path(str(state_path) + ".assistant")
        assistant_body_before = assistant_text_path.read_text(encoding="utf-8")
        assistant_progress_before_scroll = int(assistant_state_before.get("progressCount", 0))

        def assistant_advanced() -> dict[str, Any] | None:
            state = load_state(state_path)
            try:
                body = assistant_text_path.read_text(encoding="utf-8")
            except OSError:
                return None
            if (
                int(state.get("progressCount", 0)) >= assistant_progress_before_scroll + 2
                and body != assistant_body_before
            ):
                return {"state": state, "body": body}
            return None

        assistant_update = self.wait_signal(
            assistant_advanced,
            "at least two additional assistant text updates while scrolled up",
            timeout=8,
        )
        scrolled_after = self.visible("assistant-text-scrolled-up-during-updates")
        assistant_state_after = load_state(state_path)
        assistant_ends_after_scroll = int(assistant_state_after.get("assistantEnds", 0))
        if assistant_ends_after_scroll != 0:
            raise ScenarioFailure(f"assistant text finalized before the post-update scrolled-up observation: {assistant_state_after!r}")
        assert_contains(scrolled_after, "Jump to latest message", "scrolled-up assistant text view after updates")
        if assistant_anchor not in scrolled_after:
            raise ScenarioFailure(f"Pi lost scrolled-up assistant passage during text updates: {assistant_anchor!r}")
        assistant_anchor_y_after = next(
            i for i, line in enumerate(scrolled_after.splitlines()) if assistant_anchor in line
        )
        assistant_anchor_shift = abs(assistant_anchor_y_after - assistant_anchor_y_before)
        if assistant_anchor_shift > 5:
            raise ScenarioFailure(
                f"Pi moved the scrolled-up assistant passage by {assistant_anchor_shift} visible rows (limit 5)"
            )
        self.evidence["assistant_text_anchor"] = {
            "marker": assistant_anchor,
            "visible_row_before": assistant_anchor_y_before,
            "visible_row_after": assistant_anchor_y_after,
            "row_shift": assistant_anchor_shift,
            "progress_before_updates": assistant_progress_before_scroll,
            "progress_after_updates": int(assistant_update["state"].get("progressCount", 0)),
            "assistant_text_bytes_before": len(assistant_body_before.encode("utf-8")),
            "assistant_text_bytes_after": len(assistant_update["body"].encode("utf-8")),
            "assistant_ends_before": assistant_ends_at_scroll,
            "assistant_ends_after": assistant_ends_after_scroll,
            "latest_message_affordance_visible_before": True,
            "latest_message_affordance_visible_after": True,
            "additional_assistant_updates": int(assistant_update["state"].get("progressCount", 0))
            - assistant_progress_before_scroll,
        }
        self.record_assertion(
            "scrolled-up passage stayed in the same visible context while at least two new assistant text updates arrived before message finalization"
        )
        self.send_herdr_key(b"\x1b[4~", "End to return to the live bottom after assistant text anchoring")
        assistant_bottom = self.wait_signal(
            lambda: (
                lambda screen: screen
                if "T3_INITIAL_ROW_" in screen and "Jump to latest message" not in screen
                else None
            )(self.visible()),
            "assistant text viewport to return to bottom-follow after the anchor check",
            timeout=8,
        )
        assistant_bottom = self.visible("assistant-text-return-to-bottom")
        assert_absent(assistant_bottom, "Jump to latest message", "assistant text return-to-bottom view")
        self.record_assertion("returned to bottom-follow after the assistant-text anchor check")

        state_before = load_state(state_path)
        assistant_ends_before = int(state_before.get("assistantEnds", 0))
        if assistant_ends_before != 0:
            raise ScenarioFailure(f"assistant message finalized before its snapshot shortcut: {state_before!r}")
        index, receipt, opened = self.open_editor("assistant-partial")
        assistant_snapshot = receipt.read_text(encoding="utf-8")
        assert_contains(assistant_snapshot, "T3_FIRST_STREAM_PROMPT", "partial assistant editor receipt")
        assert_once(assistant_snapshot, "T3_ASSISTANT_PARTIAL_MARKER", "partial assistant editor receipt")
        assert_absent(assistant_snapshot, "T3_SYSTEM_INTERNAL_MARKER", "partial assistant editor receipt")
        self.record_assertion("already-displayed, not-yet-finalized assistant marker is present exactly once in the shortcut receipt")
        self.record_assertion("system-instruction marker is absent from conversation snapshot", negative=True)
        assistant_progress = self.finish_editor(index, opened, minimum_delta=4, timeout=15)
        self.record_assertion("agent progress count increased while the assistant snapshot editor remained open")
        self.evidence["assistant_progress"] = {
            "assistant_message_end_count_at_shortcut": assistant_ends_before,
            "progress_at_open": opened["progress_count_at_open"],
            "progress_before_release": assistant_progress["progressCount"],
        }
        self.wait_state(lambda state: int(state.get("agentSettled", 0)) >= 1, "first scripted response to settle", timeout=40)

        # PageUp through the attached Herdr client while more tool updates are
        # actively streaming. This is a separate real TUI phase from bottom
        # following below.
        self.send_line("T3_TRIGGER_TOOL_TURN")
        self.wait_signal(lambda: Path(self.env["T3_TOOL_STARTED"]).exists(), "scripted Pi tool to start", timeout=20)
        self.wait_visible("T3_TOOL_PARTIAL_MARKER", "partial tool update displayed in Pi", timeout=20)
        tool_progress_start = int(load_state(state_path).get("progressCount", 0))
        self.wait_progress(
            lambda state: int(state.get("progressCount", 0)) >= tool_progress_start + 4,
            "tool partial output and its side panel to finish their initial layout updates",
            timeout=8,
        )
        self.wait_visible("T3_TOOL_UPDATE_", "stable partial tool output before scroll anchoring", timeout=8)
        tool_screen_before = self.visible("tool-before-scroll")
        if "T3_INITIAL_ROW_" not in tool_screen_before:
            assert_contains(tool_screen_before, "T3_FIRST_STREAM_PROMPT", "tool pre-scroll pane")
        self.send_herdr_key(b"\x1b[5~", "PageUp through Herdr pane input")
        time.sleep(0.15)
        tool_screen_scrolled = self.visible("tool-scrolled-up-before-update")
        tool_anchor_candidates = row_numbers(tool_screen_scrolled, "T3_INITIAL_ROW_")
        if tool_anchor_candidates:
            anchor_marker = f"T3_INITIAL_ROW_{tool_anchor_candidates[len(tool_anchor_candidates) // 2]:03d}"
        else:
            anchor_marker = "T3_FIRST_STREAM_PROMPT"
        if anchor_marker not in tool_screen_scrolled:
            raise ScenarioFailure(f"Pi PageUp did not retain nearby passage {anchor_marker!r}: {tool_screen_scrolled[-1600:]!r}")
        anchor_y_before = next(i for i, line in enumerate(tool_screen_scrolled.splitlines()) if anchor_marker in line)
        progress_before_tool_update = int(load_state(state_path).get("progressCount", 0))
        self.wait_progress(
            lambda state: int(state.get("progressCount", 0)) > progress_before_tool_update,
            "additional tool update",
            timeout=5,
        )
        time.sleep(0.45)
        tool_screen_after = self.visible("tool-scrolled-up-during-updates")
        if anchor_marker not in tool_screen_after:
            raise ScenarioFailure(f"Pi lost the scrolled-up passage during tool updates: {anchor_marker!r}")
        anchor_y_after = next(i for i, line in enumerate(tool_screen_after.splitlines()) if anchor_marker in line)
        anchor_shift = abs(anchor_y_after - anchor_y_before)
        if anchor_shift > 5:
            raise ScenarioFailure(f"Pi moved the scrolled-up passage by {anchor_shift} visible rows (limit 5)")
        self.evidence["scrolled_up_anchor"] = {
            "marker": anchor_marker,
            "visible_row_before": anchor_y_before,
            "visible_row_after": anchor_y_after,
            "row_shift": anchor_shift,
            "tool_updates_active": True,
        }
        self.record_assertion("scrolled-up passage remains in the same visible context during partial tool updates")

        tool_state = load_state(state_path)
        if int(tool_state.get("toolEnds", 0)) != 0:
            raise ScenarioFailure(f"tool finalized before its shortcut snapshot: {tool_state!r}")
        index, receipt, opened = self.open_editor("tool-partial")
        tool_snapshot = receipt.read_text(encoding="utf-8")
        assert_once(tool_snapshot, "T3_TOOL_PARTIAL_MARKER", "partial tool editor receipt")
        assert_contains(tool_snapshot, "Tool output (in progress): scenario_stream_tool", "partial tool editor receipt")
        assert_absent(tool_snapshot, "T3_TOOL_FINAL_MARKER", "partial tool editor receipt")
        self.record_assertion("already-displayed, not-yet-finalized tool marker is in the actual shortcut receipt")
        tool_progress = self.finish_editor(index, opened, minimum_delta=3, timeout=12)
        self.evidence["tool_progress"] = {
            "tool_end_count_at_shortcut": int(tool_state.get("toolEnds", 0)),
            "progress_at_open": opened["progress_count_at_open"],
            "progress_before_release": tool_progress["progressCount"],
        }
        self.record_assertion("tool update progress advanced while its snapshot editor remained open")
        Path(self.env["T3_TOOL_RELEASE"]).write_text("release\n", encoding="utf-8")
        self.wait_signal(lambda: Path(self.env["T3_TOOL_DONE"]).exists(), "scripted tool to finish", timeout=15)
        self.wait_state(lambda state: int(state.get("agentSettled", 0)) >= 2, "tool turn and final response to settle", timeout=30)
        self.send_herdr_key(b"\x1b[4~", "End to return to the live bottom through Herdr pane input")
        # A second long scripted response demonstrates independent bottom-follow
        # and up-scroll behavior. While it streams, run ! into pending, snapshot
        # the running component, then complete it before agent_end and snapshot
        # the deferred-complete component separately.
        self.send_line("T3_STREAM_WITH_PENDING_BASH_PROMPT")
        assistant_progress_file = Path(str(state_path) + ".assistant")
        self.wait_signal(
            lambda: assistant_progress_file.exists() and "T3_FOLLOW_ROW_010" in assistant_progress_file.read_text(encoding="utf-8"),
            "scripted assistant to stream while Pi stays in fullscreen",
            timeout=20,
        )
        pending_started = self.root / "pending-bash-started"
        pending_command = marker_command(
            "T3_AGENT_PENDING_RUNNING_MARKER",
            self.root / "pending-bash-release",
            self.root / "pending-bash-done",
            pending_started,
        )
        self.send_line(pending_command)
        self.wait_signal(pending_started.exists, "agent-streaming ! command to emit its output", timeout=20)
        index, receipt, opened = self.open_editor("pending-bash-running")
        pending_snapshot = receipt.read_text(encoding="utf-8")
        assert_contains(pending_snapshot, "T3_AGENT_PENDING_RUNNING_MARKER", "running pending ! editor receipt")
        assert_contains(pending_snapshot, "Status: running", "running pending ! editor receipt")
        self.record_assertion("agent-streaming ! output in the pending UI component is in the shortcut receipt")
        pending_progress = self.finish_editor(index, opened, minimum_delta=4, timeout=15)
        self.evidence["pending_bash_progress"] = {
            "progress_at_open": opened["progress_count_at_open"],
            "progress_before_release": pending_progress["progressCount"],
        }

        # Allow Pi's pending user Bash process to finish while the faux assistant
        # continues streaming. The completion sentinel is written by the Bash
        # command itself, not by the editor or the provider fixture.
        (self.root / "pending-bash-release").write_text("release\n", encoding="utf-8")
        self.wait_signal(lambda: (self.root / "pending-bash-done").exists(), "pending Bash command completion", timeout=12)
        state_after_bash = load_state(state_path)
        if int(state_after_bash.get("agentEnds", 0)) != 2:
            raise ScenarioFailure(f"agent ended before the completed ! output could be inspected: {state_after_bash!r}")
        progress_after_bash = int(state_after_bash.get("progressCount", 0))
        self.wait_state(
            lambda state: int(state.get("progressCount", 0)) > progress_after_bash,
            "assistant to continue after Bash completion and before agent_end",
            timeout=12,
        )
        index2, receipt2, opened2 = self.open_editor("pending-bash-deferred-complete")
        deferred_snapshot = receipt2.read_text(encoding="utf-8")
        assert_once(deferred_snapshot, "T3_AGENT_PENDING_RUNNING_MARKER", "deferred-complete ! editor receipt")
        assert_contains(deferred_snapshot, "Status: complete", "deferred-complete ! editor receipt")
        self.record_assertion("completed ! output is captured while agent output remains active and before agent_end")
        follow_progress = self.finish_editor(index2, opened2, minimum_delta=3, timeout=12)
        self.evidence["deferred_bash_progress"] = {
            "bash_completed_before_shortcut": True,
            "agent_end_count_at_shortcut": int(load_state(state_path).get("agentEnds", 0)),
            "progress_at_open": opened2["progress_count_at_open"],
            "progress_before_release": follow_progress["progressCount"],
        }

        # This is the adversarial flush interval: the agent has settled and
        # SessionManager has saved the Bash result, but Pi still displays the
        # completed component in its pending dock. Do not submit another normal
        # user prompt before the client-routed Ctrl+Alt+E shortcut below.
        settled_pending = self.wait_state(
            lambda state: int(state.get("agentSettled", 0)) >= 3 and
                len(state.get("settledPendingBashResults", [])) == 1,
            "agent settlement with the completed pending Bash result persisted",
            timeout=50,
        )
        saved_pending = settled_pending["settledPendingBashResults"][0]
        expected_pending_command = pending_command[1:]
        if saved_pending.get("command") != expected_pending_command:
            raise ScenarioFailure(f"settled Bash result command changed: {saved_pending!r}")
        assert_once(saved_pending.get("output", ""), "T3_AGENT_PENDING_RUNNING_MARKER", "persisted settled Bash result")
        self.evidence["post_settlement_pending_bash_state"] = {
            "agent_settled_count": int(settled_pending.get("agentSettled", 0)),
            "agent_end_count": int(settled_pending.get("agentEnds", 0)),
            "persisted_branch_result_count": len(settled_pending["settledPendingBashResults"]),
            "persisted_command": saved_pending.get("command"),
            "persisted_output": saved_pending.get("output"),
        }
        settled_screen = self.visible("pending-bash-settled-before-next-input")
        self.send_herdr_key(
            b"\x1b[105;8:1u\x1b[105;8:3u",
            "probe the settled pending Bash dock through the isolated Pi TUI",
        )
        dock_probe_state = self.wait_state(
            lambda state: isinstance(state.get("settledPendingDockProbe"), dict) or
                "settledPendingDockProbeError" in state,
            "the fixture to inspect Pi's live pending Bash dock",
            timeout=10,
        )
        if "settledPendingDockProbeError" in dock_probe_state:
            raise ScenarioFailure(f"could not inspect settled Pi pending dock: {dock_probe_state['settledPendingDockProbeError']}")
        dock_probe = dock_probe_state["settledPendingDockProbe"]
        if dock_probe.get("mode") != "fullscreen" or dock_probe.get("rootCount") != 7:
            raise ScenarioFailure(f"settled Pi TUI layout changed: {dock_probe!r}")
        dock_components = dock_probe.get("components", [])
        if len(dock_components) != 1:
            raise ScenarioFailure(f"expected one completed Bash component in the settled pending dock: {dock_probe!r}")
        dock_component = dock_components[0]
        if dock_component.get("command") != expected_pending_command or dock_component.get("status") != "complete":
            raise ScenarioFailure(f"settled pending dock component does not match the persisted Bash result: {dock_component!r}")
        assert_once("\\n".join(dock_component.get("outputLines", [])), "T3_AGENT_PENDING_RUNNING_MARKER", "settled pending dock component")
        self.record_assertion("Pi's live fullscreen pending dock still contains the completed ! component after settlement and before another user turn")
        index3, receipt3, opened3 = self.open_editor("pending-bash-after-settlement")
        settled_snapshot = receipt3.read_text(encoding="utf-8")
        assert_once(settled_snapshot, expected_pending_command, "post-settlement pending ! editor receipt")
        assert_once(settled_snapshot, "T3_AGENT_PENDING_RUNNING_MARKER", "post-settlement pending ! editor receipt")
        assert_contains(settled_snapshot, "Status: exit 0", "post-settlement pending ! editor receipt")
        self.record_assertion("after agent settlement, saved Bash command and unique output coexist with the completed pending UI component before any new normal user prompt; Ctrl+Alt+E captures each exactly once")
        self.evidence["post_settlement_pending_bash"] = {
            "agent_settled_count_at_shortcut": int(settled_pending.get("agentSettled", 0)),
            "agent_end_count_at_shortcut": int(settled_pending.get("agentEnds", 0)),
            "persisted_branch_result_count": len(settled_pending["settledPendingBashResults"]),
            "persisted_output_marker_count": saved_pending.get("output", "").count("T3_AGENT_PENDING_RUNNING_MARKER"),
            "live_pending_dock_component_count": len(dock_components),
            "live_pending_dock_component_status": dock_component.get("status"),
            "live_pending_dock_output_marker_count": "\\n".join(dock_component.get("outputLines", [])).count("T3_AGENT_PENDING_RUNNING_MARKER"),
            "snapshot_command_count": settled_snapshot.count(expected_pending_command),
            "snapshot_output_marker_count": settled_snapshot.count("T3_AGENT_PENDING_RUNNING_MARKER"),
            "normal_user_prompt_sent_before_shortcut": False,
            "terminal_screen_marker_visible": "T3_AGENT_PENDING_RUNNING_MARKER" in settled_screen,
            "screen_capture": str(self.artifacts / "screen-pending-bash-settled-before-next-input.txt"),
        }
        self.finish_editor(index3, opened3, minimum_delta=0, timeout=10)

        # Repeat the same idle ! command across a real Pi compaction. Its output
        # changes by occurrence, so the post-compaction editor receipt must keep
        # both finalized outputs and reconcile the newest chat component once.
        repeat_counter = self.root / "repeat-bash-counter"
        repeat_done = self.root / "repeat-bash-done"
        repeat_command = repeated_bash_command(repeat_counter, repeat_done)
        command_body = repeat_command[1:]
        command_file = Path(self.env["T3_REPEAT_BASH_COMMAND_FILE"])
        command_file.write_text(command_body, encoding="utf-8")
        command_file.chmod(0o600)
        self.send_line(repeat_command)
        # The viewport may still be anchored above this command after the
        # explicit scroll-up proof; the completion sentinel proves the ! command
        # ran, and the post-compaction editor receipt below proves its output.
        self.wait_signal(repeat_done.exists, "first repeated idle ! command to finish", timeout=15)
        self.send_line("/compact")
        compacted = self.wait_state(
            lambda state: int(state.get("compactions", 0)) >= 1,
            "Pi manual compaction to complete",
            timeout=25,
        )
        if compacted.get("manualCompactionPrepared") is not True or compacted.get("compactionReason") != "manual":
            raise ScenarioFailure(f"Pi did not complete the scripted manual compaction: {compacted!r}")
        if compacted.get("compactionFromExtension") is not True or compacted.get("compactionSummary") != "T3_TEST_COMPACTION_SUMMARY":
            raise ScenarioFailure(f"Pi did not use the deterministic compaction fixture: {compacted!r}")
        self.record_assertion("Pi completed a real manual compaction before the repeated ! command")

        repeat_done.unlink()
        self.send_line(repeat_command)
        self.wait_signal(repeat_done.exists, "post-compaction repeated ! command to finish", timeout=15)
        self.send_line("/scenario-check-repeated-bash")
        repeated = self.wait_state(
            lambda state: len(state.get("repeatedBashBranchResults", [])) == 2,
            "both repeated Bash results to finalize on the current branch",
            timeout=15,
        )
        repeat_results = repeated["repeatedBashBranchResults"]
        if repeat_results[0].get("command") != repeat_results[1].get("command"):
            raise ScenarioFailure(f"the post-compaction ! invocation did not repeat the same command: {repeat_results!r}")
        if [item.get("output", "").strip() for item in repeat_results] != [
            "T3_POST_COMPACTION_REPEAT_BASH_01", "T3_POST_COMPACTION_REPEAT_BASH_02"
        ]:
            raise ScenarioFailure(f"Pi did not finalize both distinct repeated ! outputs: {repeat_results!r}")
        if repeated.get("testCompactionSummaries") != ["T3_TEST_COMPACTION_SUMMARY"]:
            raise ScenarioFailure(f"the active branch lacks exactly one test compaction summary: {repeated!r}")
        repeat_index, repeat_receipt, repeat_opened = self.open_editor("post-compaction-repeated-bash")
        repeat_snapshot = repeat_receipt.read_text(encoding="utf-8")
        assert_once(repeat_snapshot, "T3_POST_COMPACTION_REPEAT_BASH_01", "post-compaction repeated ! editor receipt")
        assert_once(repeat_snapshot, "T3_POST_COMPACTION_REPEAT_BASH_02", "post-compaction repeated ! editor receipt")
        assert_contains(repeat_snapshot, "T3_TEST_COMPACTION_SUMMARY", "post-compaction repeated ! editor receipt")
        assert_once(repeat_snapshot, "Tool call: scenario_stream_tool", "post-compaction editor receipt")
        self.record_assertion("post-compaction repeated ! command has each finalized output exactly once in the actual shortcut receipt")
        self.record_assertion("finalized scenario_stream_tool assistant call appears exactly once after compaction")
        self.finish_editor(repeat_index, repeat_opened, minimum_delta=0, timeout=10)

        # Build a real sibling session branch containing an abandoned answer,
        # fork back to its parent through Pi's session API, then capture after
        # the fork so absence is meaningful rather than a premature snapshot.
        self.send_line("T3_ABANDONED_BRANCH_PROMPT")
        self.wait_state(lambda state: int(state.get("agentSettled", 0)) >= 4, "abandoned sibling response to finish", timeout=25)
        branch_state_before = load_state(state_path)
        if int(branch_state_before.get("branchSwitches", 0)) < 1:
            raise ScenarioFailure(f"test extension did not see Pi's active session: {branch_state_before!r}")
        if branch_state_before.get("branchContainsAbandonedMarker") is not True:
            raise ScenarioFailure(f"source sibling branch did not contain the abandoned marker: {branch_state_before!r}")
        self.send_line("/scenario-abandon-branch")
        self.wait_state(lambda state: bool(state.get("forkCommandReturned")), "Pi to fork back before abandoned turn", timeout=20)
        fork_state = load_state(state_path)
        if fork_state.get("forkCommandHasAbandonedMarker") is not False:
            raise ScenarioFailure(f"fork did not select a branch without the abandoned marker: {fork_state!r}")
        self.record_assertion("real Pi sibling branch contains abandoned marker and active fork excludes it")

        index4, receipt4, opened4 = self.open_editor("current-branch-exclusion")
        branch_snapshot = receipt4.read_text(encoding="utf-8")
        assert_absent(branch_snapshot, "T3_ABANDONED_BRANCH_MARKER", "post-fork current-branch editor receipt")
        assert_absent(branch_snapshot, "T3_SYSTEM_INTERNAL_MARKER", "post-fork current-branch editor receipt")
        assert_contains(branch_snapshot, "T3_TOOL_TURN_FINAL_MARKER", "post-fork current-branch editor receipt")
        assert_once(branch_snapshot, "Tool call: scenario_stream_tool", "post-fork current-branch editor receipt")
        assert_once(branch_snapshot, "T3_AGENT_PENDING_RUNNING_MARKER", "post-fork current-branch editor receipt")
        self.record_assertion("post-fork editor snapshot excludes the actual abandoned sibling branch marker", negative=True)
        self.record_assertion("post-fork editor snapshot still includes current-branch completed conversation")
        self.finish_editor(index4, opened4, minimum_delta=0, timeout=10)

        # Same Herdr-hosted Pi process, after its editor and branch transition.
        self.send_line("T3_SUBSEQUENT_TURN_PROMPT")
        self.wait_state(lambda state: int(state.get("agentSettled", 0)) >= 5, "subsequent Pi turn to finish", timeout=25)
        final_state = load_state(state_path)
        if final_state.get("branchContainsSubsequentMarker") is not True:
            raise ScenarioFailure(f"subsequent response was not finalized on the active branch: {final_state!r}")
        if int(final_state.get("providerCalls", 0)) != 6:
            raise ScenarioFailure(f"scripted provider consumed an unexpected response count: {final_state!r}")
        final_process = result_object(self.herdr_cmd("pane", "process-info", "--pane", self.pane), "post-turn Pi process")
        final_foreground = final_process.get("process_info", {}).get("foreground_processes", [])
        initial_pid = self.evidence["pane_process_info"].get("foreground_processes", [{}])[0].get("pid")
        if not any(item.get("argv0") == "pi" and item.get("pid") == initial_pid for item in final_foreground):
            raise ScenarioFailure(f"post-editor turn did not use the same Herdr-hosted Pi process: {final_process!r}")
        self.record_assertion("same Herdr-hosted Pi process accepted and completed a subsequent user turn after editor return")
        if not self.client or self.client.exit_code is not None:
            raise ScenarioFailure("attached Herdr client was not alive after the subsequent Pi turn")

        self.evidence.update({
            "editor_receipts": {
                label: str(editor_dir / f"editor-{index:02d}.md")
                for label, index in self.receipt_names.items()
            },
            "artifact_directory": str(self.artifacts),
            "transcript": str(self.artifacts / f"editor-{len(self.receipt_names):02d}.md"),
            "editor_receipt_count": len(self.receipt_names),
            "shortcut_route": "Kitty key-press bytes delivered via private AttachedHerdrClient PTY; focused_pane_id verified at editor open and return",
            "post_compaction_repeated_bash": {
                "compaction_count": int(load_state(state_path).get("compactions", 0)),
                "commands_identical": True,
                "finalized_outputs_once": ["T3_POST_COMPACTION_REPEAT_BASH_01", "T3_POST_COMPACTION_REPEAT_BASH_02"],
            },
            "scripted_provider_calls": 6,
            "agent_end_count_at_success": int(load_state(state_path).get("agentEnds", 0)),
            "client_alive_after_return": True,
        })
        return self.evidence

    def cleanup(self) -> None:
        # Release any dummy editor/tool gates first; they belong only to this
        # script's private temporary root and child process tree.
        for index in range(1, 12):
            Path(f"{self.env['T3_EDITOR_RELEASE_PREFIX']}{index}").touch(mode=0o600, exist_ok=True)
        Path(self.env["T3_TOOL_RELEASE"]).touch(mode=0o600, exist_ok=True)
        if self.client:
            self.client.detach()
        client_detached = self.client is None or self.client.exit_code is not None
        server_stopped = self.server is None
        session_deleted = self.server is None
        if self.server is not None:
            try:
                if self.status().get("running"):
                    self.herdr_cmd("server", "stop", timeout=10)
            except Exception:
                if self.server.poll() is None:
                    try:
                        os.killpg(self.server.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            try:
                self.server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.server.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self.server.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.server.kill()
                    self.server.wait(timeout=3)
            try:
                server_stopped = not self.status().get("running", False)
            except Exception:
                server_stopped = self.server.poll() is not None
            if server_stopped:
                try:
                    run([self.herdr, "session", "delete", "--json", self.session], self.env, cwd=self.root)
                    session_deleted = True
                except Exception as exc:
                    self.evidence.setdefault("cleanup_errors", []).append(f"named-session delete: {exc}")
        if self.server_output:
            self.server_output.close()
        if self.server_log.exists():
            try:
                archived_log = self.artifacts / "herdr-server.log"
                shutil.copyfile(self.server_log, archived_log)
                archived_log.chmod(0o600)
            except OSError as exc:
                self.evidence.setdefault("cleanup_errors", []).append(f"server log receipt: {exc}")
        self.evidence["editor_receipts"] = {
            label: str(self.artifacts / f"editor-{index:02d}.md")
            for label, index in self.receipt_names.items()
        }
        self.evidence["editor_receipt_count"] = len(self.receipt_names)
        if self.receipt_names:
            self.evidence["transcript"] = str(
                self.artifacts / f"editor-{max(self.receipt_names.values()):02d}.md"
            )
        self.evidence["cleanup"] = {
            "client_detached": client_detached,
            "private_named_server_stopped": server_stopped,
            "private_named_session_deleted": session_deleted,
            "owner_default_server_touched": False,
            "private_root_removed": False,
        }
        if client_detached and server_stopped and session_deleted:
            shutil.rmtree(self.root, ignore_errors=False)
            self.evidence["cleanup"]["private_root_removed"] = True
        else:
            self.evidence["cleanup"]["preserved_private_root"] = str(self.root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=None,
        help="directory for synthetic editor receipts and screen captures (default: a private temporary directory)",
    )
    args = parser.parse_args()
    scenario: OperatorScenario | None = None
    private_root: Path | None = None
    artifact_dir = args.artifact_dir
    status = "FAIL"
    reason: str | None = None
    receipt_error: str | None = None
    try:
        if artifact_dir is None:
            artifact_dir = Path(tempfile.mkdtemp(prefix="pi-inspect-session-receipts-"))
        else:
            artifact_dir = artifact_dir.expanduser().resolve()
            artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            artifact_dir.chmod(0o700)
        pi, herdr, faux, typebox = resolve_runtime()
        private_root = Path(tempfile.mkdtemp(prefix="p3-", dir="/tmp"))
        private_root.chmod(0o700)
        scenario = OperatorScenario(pi, herdr, private_root, artifact_dir)
        scenario.faux_module = faux
        scenario.typebox_module = typebox
        scenario.artifacts = artifact_dir
        scenario.evidence["artifact_directory"] = str(artifact_dir)
        scenario.evidence = scenario.run_scenario()
        status = "PASS"
    except ScenarioBlocked as exc:
        status = "BLOCKED"
        reason = str(exc)
    except Exception as exc:
        status = "FAIL"
        reason = f"{type(exc).__name__}: {exc}"
        if scenario:
            scenario.evidence["failed_probe"] = reason
            try:
                if scenario.server and scenario.server.poll() is None and scenario.pane:
                    scenario.evidence["failure_screen"] = scenario.visible("failure-last-screen")[-2400:]
            except Exception as diagnostic_error:
                scenario.evidence["failure_screen_error"] = str(diagnostic_error)
            if scenario.client:
                scenario.evidence["failure_client_tail"] = scenario.client.output.decode("utf-8", "replace")[-1600:]
            try:
                if scenario.server_log.exists():
                    target = scenario.artifacts / "herdr-server.log"
                    shutil.copyfile(scenario.server_log, target)
                    target.chmod(0o600)
            except Exception:
                pass
    finally:
        if scenario:
            try:
                scenario.cleanup()
                if not all(scenario.evidence["cleanup"].get(key) for key in (
                    "client_detached", "private_named_server_stopped", "private_named_session_deleted", "private_root_removed"
                )):
                    status = "FAIL"
                    reason = "isolated Herdr resources did not all clean up"
            except Exception as exc:
                status = "FAIL"
                reason = f"cleanup failure: {exc}"
                scenario.evidence.setdefault("cleanup_errors", []).append(str(exc))
        elif private_root and private_root.exists():
            try:
                shutil.rmtree(private_root, ignore_errors=False)
            except OSError as exc:
                status = "FAIL"
                reason = f"private temporary-root cleanup failed: {exc}"
        if artifact_dir:
            outcome = {
                **(scenario.evidence if scenario else {}),
                "status": status,
                **({"reason": reason} if reason else {}),
            }
            try:
                write_json(artifact_dir / "outcome.json", outcome)
            except OSError as exc:
                receipt_error = f"could not write outcome receipt: {exc}"
            if receipt_error is None:
                print(json.dumps(outcome, ensure_ascii=False, sort_keys=True))
    if receipt_error:
        print(json.dumps({"status": "FAIL", "reason": receipt_error}))
        return 1
    return 0 if status == "PASS" else 2 if status == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
