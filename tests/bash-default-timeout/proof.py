#!/usr/bin/env python3
"""Black-box proof for bash-default-timeout: a real Pi (the installed one, in print mode) runs bash calls from a scripted model.

Pi gets a private agent directory and only two extensions: the scripted model and a copy of bash-default-timeout whose
config.json sets a 3 second default. Nothing under ~/.pi is read or written. Needs `pi` on PATH; takes about 25 seconds.

Checks, each from what Pi itself reports:
  1. a bash call with no timeout that sleeps 60 s is stopped after about 3 s, says so, and the model is told how to ask for longer;
  2. the sleeping process is gone afterwards (the process tree was killed);
  3. a call that sets its own timeout (20 s) and runs 5 s is not cut short at 3 s;
  4. the same holds for a bash call made from a codemode script;
  5. with the extension absent, the same no-timeout call is NOT stopped (the control: the default really comes from the extension).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "dot_pi/private_agent/extensions/bash-default-timeout"
PROVIDER = Path(__file__).resolve().parent / "scripted_provider.ts"
LIMIT = 3


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def run_pi(work: Path, turns: list[dict], with_extension: bool, *, timeout: int, tools: str | None = None) -> tuple[list[dict], float]:
    agent_dir = work / "agent"
    agent_dir.mkdir(exist_ok=True)
    script = work / "script.json"
    script.write_text(json.dumps({"turns": turns}))
    extension = work / "ext" / "bash-default-timeout"
    if with_extension and not extension.exists():
        extension.mkdir(parents=True)
        shutil.copy(EXTENSION / "index.ts", extension / "index.ts")
        (extension / "config.json").write_text(json.dumps({"defaultTimeoutSeconds": LIMIT}))
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent_dir), "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1",
           "PI_TELEMETRY": "0", "SCRIPTED_MODEL_SCRIPT": str(script)}
    command = ["pi", "--no-extensions", "-e", str(PROVIDER)]
    if with_extension:
        command += ["-e", str(extension / "index.ts")]
    if tools:
        command += ["-e", "builtin:codemode", "--tools", tools]
    command += ["--provider", "scripted", "--model", "scripted-1", "--no-approve", "--no-session", "--mode", "json", "-p", "go"]
    started = time.monotonic()
    done = subprocess.run(command, cwd=work, env=env, text=True, capture_output=True, timeout=timeout)
    elapsed = time.monotonic() - started
    events = [json.loads(line) for line in done.stdout.splitlines() if line.startswith("{")]
    if done.returncode != 0:
        raise SystemExit(f"pi exited {done.returncode}\n{done.stderr[-2000:]}\n{done.stdout[-2000:]}")
    return events, elapsed


def bash(command: str, **more) -> dict:
    return {"call": {"name": "bash", "arguments": {"command": command, **more}}}


def tool_results(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "tool_execution_end"]


def text_of(result: dict) -> str:
    return "".join(block.get("text", "") for block in result.get("result", {}).get("content", []))


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="bash-default-timeout-"))
    try:
        pidfile = work / "child.pid"
        hang = f"sh -c 'echo $$ > {pidfile}; sleep 60' ; echo not-reached"
        events, elapsed = run_pi(work, [bash(hang), {"text": "done"}], True, timeout=50)
        [result] = tool_results(events)
        text = text_of(result)
        assert result.get("isError") is True, f"the hung call should fail: {text!r}"
        assert f"Command timed out after {LIMIT} seconds" in text, text
        assert "default" in text and "larger `timeout`" in text, f"the model should be told how to ask for longer: {text!r}"
        assert LIMIT <= elapsed < 30, f"stopped after {elapsed:.1f}s, expected about {LIMIT}s"
        print(f"ok 1: no-timeout call stopped after {elapsed:.1f}s with the hint")

        pid = int(pidfile.read_text())
        time.sleep(0.5)
        assert not alive(pid), f"process {pid} (the sleep) survived the timeout"
        print("ok 2: the process tree was killed")

        events, elapsed = run_pi(work, [bash("sleep 5; echo finished-on-its-own-limit", timeout=20), {"text": "done"}], True, timeout=50)
        [result] = tool_results(events)
        assert result.get("isError") is not True and "finished-on-its-own-limit" in text_of(result), text_of(result)
        assert elapsed >= 5, elapsed
        print(f"ok 3: a call with its own timeout ran {elapsed:.1f}s past the {LIMIT}s default")

        code = "const r = await tools.bash({ command: 'sleep 60' }); return typeof r === 'string' ? r : r.output;"
        events, elapsed = run_pi(work, [{"call": {"name": "codemode", "arguments": {"code": code}}}, {"text": "done"}], True, timeout=50, tools="+codemode")
        codemode = " ".join(text_of(e) for e in tool_results(events))
        assert f"Command timed out after {LIMIT} seconds" in codemode, f"codemode bash call was not limited: {codemode!r}"
        assert LIMIT <= elapsed < 30, elapsed
        print(f"ok 4: a bash call made from a codemode script was stopped after {elapsed:.1f}s")

        events, elapsed = run_pi(work, [bash("sleep 6; echo control-finished"), {"text": "done"}], False, timeout=50)
        [result] = tool_results(events)
        assert result.get("isError") is not True and "control-finished" in text_of(result), text_of(result)
        print("ok 5: without the extension the same kind of call is not stopped (control)")
        print("PASS")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
