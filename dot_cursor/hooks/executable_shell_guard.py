#!/usr/bin/env python3
"""Cursor preToolUse hook for the Shell tool: run the shared guard classifier and answer in Cursor's format.

Cursor sends {"tool_name": "Shell", "tool_input": {"command", "cwd", "timeout"}, ...} on stdin. The classifier is
~/.local/share/agent-harness/hooks/refuse_pattern_kill.py (the one Claude Code, Codex and Pi run): it reads the same JSON,
exits 2 with the reason on stderr to refuse. Here exit 2 prints {"permission": "deny", ...} and exits 0. Every other case
prints nothing and exits 1: a command that passes, another tool, garbage input, a missing classifier and an error in this file.
Cursor reads exit 1 as "hook failed, action proceeds", so the command runs without an answer from this guard.
The guard never answers "allow". ~/.cursor/hooks.json is user-level, so the guard also runs in a person's own Cursor
sessions, and an allow could skip their approval prompts. A fault in this file lets the command run, so it does not stop an agent.
Cursor's cwd is inside tool_input, and the classifier reads a top-level one, so it runs in that directory.
"""
import json
import os
import subprocess
import sys


def decide(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("tool_name") != "Shell":
        return None
    tool_input = data.get("tool_input")
    cwd = tool_input.get("cwd") if isinstance(tool_input, dict) else None
    script = os.path.join(os.environ.get("HOME") or os.path.expanduser("~"), ".local/share/agent-harness/hooks/refuse_pattern_kill.py")
    if not os.path.isfile(script):
        return None  # python exits 2 for a file it cannot open, which would read as a refusal
    result = subprocess.run([sys.executable, "-I", script], input=raw, capture_output=True, text=True, timeout=20,
                            cwd=cwd if isinstance(cwd, str) and os.path.isdir(cwd) else None)
    if result.returncode == 2:
        reason = result.stderr.strip()
        return {"permission": "deny", "user_message": reason, "agent_message": reason}
    return None


def main():
    try:
        answer = decide(sys.stdin.read())
    except Exception:
        return 1
    if answer is None:
        return 1  # no output, exit 1: Cursor reads this as "hook failed, action proceeds"; the guard never answers allow
    print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
