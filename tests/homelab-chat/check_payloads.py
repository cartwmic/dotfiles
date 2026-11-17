#!/usr/bin/env python3
"""Run the homelab-chat PreToolUse hook as a process on each recorded payload in payloads/ and print one line per payload.

A payload named allow-*.json must exit 0 and deny-*.json must exit 2 with a reason on stderr. Exit 0 when every payload does what its name says, else 1.
The hook log goes to a throwaway file, so the real ~/.local/state/homelab-chat/hook.jsonl is not touched.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE.parents[1] / "dot_local/share/agent-harness/hooks/homelab_chat_allowlist.py"


def detail(payload):
    args = payload["tool_input"]
    return args.get("command") or json.dumps(args, sort_keys=True)[:70]


def main():
    bad, files = 0, sorted((HERE / "payloads").glob("*.json"))
    if not files:
        print("no payloads found in %s" % (HERE / "payloads"))
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, HOMELAB_CHAT_HOOK_LOG=str(Path(tmp) / "hook.jsonl"))
        for f in files:
            want = {"allow": 0, "deny": 2}[f.name.split("-", 1)[0]]
            run = subprocess.run([sys.executable, "-I", str(HOOK)], input=f.read_text(), capture_output=True, text=True, env=env, timeout=30)
            ok = run.returncode == want and (want == 0 or "homelab-chat tool list: denied." in run.stderr)
            bad += not ok
            payload = json.loads(f.read_text())
            print("%-5s %-7s %s: %s%s" % ("ok" if ok else "WRONG", "allowed" if run.returncode == 0 else "REFUSED", payload["tool_name"], detail(payload)[:110],
                                       "\n                -> " + run.stderr.strip() if run.returncode else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
