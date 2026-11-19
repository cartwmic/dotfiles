#!/usr/bin/env python3
"""Cursor preToolUse hook for the Shell tool: run the shared guard classifier and answer in Cursor's format.

Cursor sends {"tool_name": "Shell", "tool_input": {"command", "cwd", "timeout"}, ...} on stdin. The classifier is
~/.local/share/agent-harness/hooks/refuse_pattern_kill.py (the one Claude Code, Codex and Pi run): it reads the same JSON,
exits 2 with the reason on stderr to refuse. Here exit 2 becomes {"permission": "deny", ...}; anything else, including an
error in this file, becomes {"permission": "allow"}. It exits 0 always, so a fault never stops an agent from working.
Cursor's cwd is inside tool_input, and the classifier reads a top-level one, so it runs in that directory.
"""
import json
import os
import subprocess
import sys

ALLOW = {"permission": "allow"}


def decide(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("tool_name") != "Shell":
        return ALLOW
    tool_input = data.get("tool_input")
    cwd = tool_input.get("cwd") if isinstance(tool_input, dict) else None
    script = os.path.join(os.environ.get("HOME") or os.path.expanduser("~"), ".local/share/agent-harness/hooks/refuse_pattern_kill.py")
    if not os.path.isfile(script):
        return ALLOW  # python exits 2 for a file it cannot open, which would read as a refusal
    result = subprocess.run([sys.executable, "-I", script], input=raw, capture_output=True, text=True, timeout=20,
                            cwd=cwd if isinstance(cwd, str) and os.path.isdir(cwd) else None)
    if result.returncode == 2:
        reason = result.stderr.strip()
        return {"permission": "deny", "user_message": reason, "agent_message": reason}
    return ALLOW


def main():
    try:
        answer = decide(sys.stdin.read())
    except Exception:
        answer = ALLOW
    print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
