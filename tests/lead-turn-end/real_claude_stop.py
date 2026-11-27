#!/usr/bin/env python3
"""Real-path check of the lead turn-end Stop hook: the real `claude` binary ends real turns and the real lead_turn_end.py writes the records.

Run from a checkout of the dotfiles: python3 tests/lead-turn-end/real_claude_stop.py. It exits 0 when every scenario matches and 1 otherwise, and prints one line per scenario.
Nothing live is touched. Each session runs under a scratch HOME and CLAUDE_CONFIG_DIR with a clean environment (the parent's COORDINATOR_SEAT and T3CODE_THREAD_ID cannot leak in),
a scratch state directory with a ledger that lists the lead workstreams' threads (the coordinator's own check cannot read the rest of what it asks about and lets the end stand: one record per end), and a stub `t3` that answers
"no parent" for every thread (so the coordinator reads each thread as a lead, as T3 does for a thread nobody started). Only the settings.json Stop group of this checkout's
dot_claude/modify_settings.json.tmpl is installed in the scratch config, plus the model login the real settings.json names (a key helper command and a base URL; no secret is copied).

  default       a lead workstream's thread on T3's default instance (no COORDINATOR_SEAT, a bare UUID thread id)  -> one record per Stop
  default+agent the same, and its turn starts a native Agent helper (a subagent: it fires no Stop hook)             -> one record per Stop
  seat-lead     a thread launched the seat-lead way (COORDINATOR_SEAT=lead, this checkout's seat-lead.json)          -> one record per Stop
  no-seat       a thread with no seat that no lead workstream names (a session Michael opens himself)               -> 0 records
  no-seat+agent the same, and its turn starts a native Agent helper                                                 -> 0 records
  builder       COORDINATOR_SEAT=builder (the seat file's own value)                                                -> 0 records
  coordinator   COORDINATOR_SEAT=coordinator (the coordinator instance)                                             -> 0 records

Needs chezmoi, jq, node, python3 and claude on PATH, a coordinator checkout (COORDINATOR_REPO, default ~/git/coordinator) and a model login in ~/.claude/settings.json.
"""
import json
import os
import shutil
import sqlite3
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
        # A second Stop handler beside the hook records every Stop event, with the thread's id, so a scenario can compare the records with the Stops that fired.
        stops = home / "stops.log"
        scratch["hooks"]["Stop"][0]["hooks"].append({"type": "command", "command": 'echo "$T3CODE_THREAD_ID $(tr -d "\\n")" >> ' + str(stops)})
        (config / "settings.json").write_text(json.dumps(scratch))
        seat_lead = home / "seat-lead.json"
        seat_lead.write_text(chezmoi(ROOT / "dot_claude/fleet/seat-lead.json.tmpl", home, {}))

        def records(thread):
            log = state / "t3-hook/turn-end.jsonl"
            return [r for r in map(json.loads, log.read_text().splitlines()) if r["thread"] == thread] if log.exists() else []

        ledger = sqlite3.connect(state / "ledger.sqlite")
        ledger.execute("CREATE TABLE workstreams (name TEXT, conversation TEXT)")

        def session(seat, extra_args, lead_workstream=False, helper=False):
            thread = str(uuid.uuid4())
            if lead_workstream:
                ledger.execute("INSERT INTO workstreams VALUES (?, ?)", ("scratch lead", "t3:" + thread))
            ledger.commit()
            prompt = ("Use the Agent tool once with subagent_type general-purpose and the prompt 'Reply with the word ok', then reply with the single word ok." if helper
                      else "Reply with the single word ok.")
            env = {"PATH": os.environ["PATH"], "HOME": str(home), "CLAUDE_CONFIG_DIR": str(config), "T3CODE_THREAD_ID": thread, "T3CODE_CLI_PATH": str(t3)}
            if seat:
                env["COORDINATOR_SEAT"] = seat
            done = subprocess.run(["claude", "-p", prompt, "--model", MODEL, *(["--allowedTools", "Agent"] if helper else []), *extra_args], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
            if done.returncode != 0 or "ok" not in done.stdout.lower():
                die("claude did not complete a turn (exit %s): %s" % (done.returncode, (done.stdout + done.stderr).strip()[:300]))
            fired = [json.loads(line.split(" ", 1)[1]) for line in (stops.read_text().splitlines() if stops.exists() else []) if line.startswith(thread + " ")]
            return records(thread), fired

        failed = False
        scenarios = (("default", None, [], dict(lead_workstream=True), 1), ("default+agent", None, [], dict(lead_workstream=True, helper=True), 1),
                     ("seat-lead", "lead", ["--settings", str(seat_lead)], {}, 1), ("no-seat", None, [], {}, 0), ("no-seat+agent", None, [], dict(helper=True), 0),
                     ("builder", "builder", [], {}, 0), ("coordinator", "coordinator", [], {}, 0))
        for name, seat, args, options, want in scenarios:
            got, fired = session(seat, args, **options)
            # A helper (the Agent tool's subagent) fires no Stop of its own: every Stop belongs to the session. Its completion can wake the session for a second turn, which is a second end and a second record.
            ok = all("agent_id" not in f for f in fired) and all(r["facts"]["lead"] is True for r in got) and len(got) == (len(fired) if want else 0) and len(fired) >= 1
            failed |= not ok
            print("%-14s stops=%d records=%d expected=%s lead=%s %s" % (name, len(fired), len(got), "one per stop" if want else "none", [r["facts"]["lead"] for r in got], "ok" if ok else "MISMATCH"))
        return 1 if failed else 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
