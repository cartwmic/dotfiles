#!/usr/bin/env python3
"""Real-path check of the lead turn-end Stop hook: the real `claude` binary ends real turns and the real lead_turn_end.py writes the records.

Run from a checkout of the dotfiles: python3 tests/lead-turn-end/real_claude_stop.py. It exits 0 when every scenario matches and 1 otherwise, and prints one line per scenario.
Nothing live is touched. Each session runs under a scratch HOME and CLAUDE_CONFIG_DIR with a clean environment (the parent's COORDINATOR_SEAT and T3CODE_THREAD_ID cannot leak in),
a scratch state directory with no ledger (so the coordinator's check cannot read what it asks about and lets the end stand: one record per end), and a stub `t3` that answers
"no parent" for every thread (so the coordinator reads each thread as a lead, as T3 does for a thread nobody started). Only the settings.json Stop group of this checkout's
dot_claude/modify_settings.json.tmpl is installed in the scratch config, plus the model login the real settings.json names (a key helper command and a base URL; no secret is copied).

  default   a thread on T3's default instance (no COORDINATOR_SEAT, a bare UUID thread id)                      -> 1 record
  seat-lead a thread launched the seat-lead way (COORDINATOR_SEAT=lead, this checkout's seat-lead.json)         -> 1 record
  builder   COORDINATOR_SEAT=builder (the seat file's own value)                                                -> 0 records
  coordinator COORDINATOR_SEAT=coordinator (the coordinator instance)                                           -> 0 records

Needs chezmoi, jq, node, python3 and claude on PATH, a coordinator checkout (COORDINATOR_REPO, default ~/git/coordinator) and a model login in ~/.claude/settings.json.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REAL_HOME = Path(os.path.expanduser("~"))
COORDINATOR = Path(os.environ.get("COORDINATOR_REPO") or REAL_HOME / "git/coordinator")
MODEL = "claude-haiku-5-5"
STUB_T3 = """#!/bin/sh
# `t3 thread show ID --json --messages N`: a thread nobody started.
echo '{"thread":{"status":"idle","parentThreadId":null},"messages":[]}'
"""


def die(text):
    print("real_claude_stop: " + text, file=sys.stderr)
    sys.exit(1)


def chezmoi(template, home, data):
    cfg = home / "chezmoi.yaml"
    cfg.write_text(json.dumps({"data": {"profile": "personal", "hub": {"enabled": False}, **data}}))
    done = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                          input=template.read_text(), capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=str(home)))
    if done.returncode != 0:
        die("chezmoi could not render %s: %s" % (template.name, done.stderr.strip()))
    return done.stdout


def main():
    for tool in ("chezmoi", "jq", "node", "python3", "claude"):
        if not shutil.which(tool):
            die("%s is not on PATH" % tool)
    if not (COORDINATOR / "src/coordinatord/cli.ts").is_file():
        die("no coordinator checkout at %s (set COORDINATOR_REPO)" % COORDINATOR)
    login = json.loads((REAL_HOME / ".claude/settings.json").read_text())
    key_helper, base_url = login.get("apiKeyHelper"), (login.get("env") or {}).get("ANTHROPIC_BASE_URL")
    if not key_helper:
        die("~/.claude/settings.json names no apiKeyHelper: there is no model login to reuse")

    home = Path(tempfile.mkdtemp(prefix="real-stop-"))
    try:
        # The hooks the way an apply installs them: the script under $HOME, the checkout the group's command names, a scratch state directory.
        hooks = home / ".local/share/agent-harness/hooks"
        hooks.mkdir(parents=True)
        for name in ("lead_turn_end.py", "stop_running_jobs.py"):
            shutil.copy(ROOT / "dot_local/share/agent-harness/hooks" / name, hooks / name)
        state = home / ".local/share/coordinator"
        state.mkdir(parents=True)
        t3 = home / "bin/t3"
        t3.parent.mkdir()
        t3.write_text(STUB_T3)
        t3.chmod(0o755)

        script = home / "modify.sh"
        script.write_text(chezmoi(ROOT / "dot_claude/modify_settings.json.tmpl", home, {"instances": {"coordinator": {"repo": str(COORDINATOR)}}}))
        applied = json.loads(subprocess.run(["sh", str(script)], input="{}", capture_output=True, text=True, check=True, timeout=60).stdout)
        config = home / "claude-config"
        config.mkdir()
        scratch = {"apiKeyHelper": key_helper, **({"env": {"ANTHROPIC_BASE_URL": base_url}} if base_url else {}), "hooks": {k: v for k, v in applied.get("hooks", {}).items() if k == "Stop"}}
        (config / "settings.json").write_text(json.dumps(scratch))
        seat_lead = home / "seat-lead.json"
        seat_lead.write_text(chezmoi(ROOT / "dot_claude/fleet/seat-lead.json.tmpl", home, {}))

        def records(thread):
            log = state / "t3-hook/turn-end.jsonl"
            return [r for r in map(json.loads, log.read_text().splitlines()) if r["thread"] == thread] if log.exists() else []

        def session(seat, extra_args):
            thread = str(uuid.uuid4())
            env = {"PATH": os.environ["PATH"], "HOME": str(home), "CLAUDE_CONFIG_DIR": str(config), "T3CODE_THREAD_ID": thread, "T3CODE_CLI_PATH": str(t3)}
            if seat:
                env["COORDINATOR_SEAT"] = seat
            done = subprocess.run(["claude", "-p", "Reply with the single word ok.", "--model", MODEL, *extra_args], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
            if done.returncode != 0 or "ok" not in done.stdout.lower():
                die("claude did not complete a turn (exit %s): %s" % (done.returncode, (done.stdout + done.stderr).strip()[:300]))
            return records(thread)

        failed = False
        for name, seat, args, want in (("default", None, [], 1), ("seat-lead", "lead", ["--settings", str(seat_lead)], 1), ("builder", "builder", [], 0), ("coordinator", "coordinator", [], 0)):
            got = session(seat, args)
            ok = len(got) == want and all(r["facts"]["lead"] is True for r in got)
            failed |= not ok
            print("%-12s records=%d expected=%d lead=%s %s" % (name, len(got), want, [r["facts"]["lead"] for r in got], "ok" if ok else "MISMATCH"))
        return 1 if failed else 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
