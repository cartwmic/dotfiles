#!/usr/bin/env python3
"""Claude Code Stop hook for lead threads: a lead's turn may end only when something will wake it, an ask that names it is open, or a state note was accepted.

The rule, and every read behind it, is `coordinator t3 turn-end` in the coordinator checkout (src/t3-hook/turn-end.ts); this script holds none of it. It does what the
coordinator cannot: counts this thread's running run-and-wake and kgate jobs (stop_running_jobs.py --count, beside it) and passes the number as `--jobs N`, and it knows
whether this stop follows its own refusal: Claude Code sets `stop_hook_active` in the hook input when the session is already continuing because a Stop hook blocked it. That is
`--continued`: the coordinator then lets the end through and reports it. No refusal is stored anywhere. No message text is read.

Where it runs: the user-level settings.json (dot_claude/modify_settings.json.tmpl), which every T3 provider instance reads, so a lead thread on the default `claudeAgent` instance gets it too. No seat file registers it.
Whether a thread is a lead is the coordinator's answer (`coordinator t3 turn-end` reads T3's parent field). This script only skips the sessions that name themselves as something else, before any call is made:
COORDINATOR_SEAT builder, planner, reviewer, scout, computer (worker seats), coordinator (the coordinator instance has no lead check), homelab-chat (its settings deny the ledger and state-note calls the refusal asks for).
A skipped session exits 0 and writes nothing. Any other COORDINATOR_SEAT, or none, goes to the coordinator.

Arguments: --repo COORDINATOR_CHECKOUT --state COORDINATOR_STATE_DIR (the settings.json group renders both per profile). The session's COORDINATOR_STATE_DIR wins when set.
Output: exit 2 and the refusal on stderr to keep the session going, else exit 0. It fails open. With no T3CODE_THREAD_ID, or no repo or state argument, the end is allowed and
nothing is written (this is not a lead session, or it is not set up). Once a thread and both arguments are there, an end that is allowed because the check could not run (a missing
checkout or state directory, a command that fails, times out or is missing, output it cannot read) writes one JSON line to <state>/t3-hook/turn-end-adapter.jsonl, as does an end
the coordinator would have refused after a refusal already went out. Each line has `ts`, `adapter`, `thread`, `outcome` ("allowed"), `cause` ("check-failed" or "after-refusal"),
`reason` and `duration_ms`. A refusal is never issued on a stop that follows one (`stop_hook_active`), whatever the coordinator answers.
Test hooks: LEAD_TURN_END_NODE names the node binary; LEAD_TURN_END_TIMEOUT is the command's time limit in seconds (default 30).
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# COORDINATOR_SEAT values (set in each seat file's `env`, and by `coordinator t3 setup`) of sessions that are never asked.
SKIPPED_SEATS = frozenset(["builder", "planner", "reviewer", "scout", "computer", "coordinator", "homelab-chat"])


def option(argv, name):
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


def count_jobs(env):
    """This thread's running jobs, or 0 when they cannot be counted."""
    script = os.path.join(HERE, "stop_running_jobs.py")
    if not os.path.isfile(script):
        return 0
    try:
        done = subprocess.run([sys.executable, script, "--count"], capture_output=True, text=True, timeout=10, env=env)
        n = int(done.stdout.strip())
        return n if done.returncode == 0 and n > 0 else 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


class CheckFailed(Exception):
    """The check could not give an answer; the message is the reason that goes in the log."""


def log_line(state, thread, cause, reason, started):
    """One line in <state>/t3-hook/turn-end-adapter.jsonl. The log is best effort: a line that cannot be written never changes the answer."""
    try:
        folder = os.path.join(state, "t3-hook")
        os.makedirs(folder, exist_ok=True)
        line = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "adapter": "claude-stop-hook", "thread": thread, "outcome": "allowed",
                "cause": cause, "reason": reason, "duration_ms": int((time.monotonic() - started) * 1000)}
        with open(os.path.join(folder, "turn-end-adapter.jsonl"), "a", encoding="utf8") as handle:
            handle.write(json.dumps(line) + "\n")
    except OSError:
        pass


def ask(argv, hook_input, env, thread, repo, state):
    """The coordinator's answer for this end: (refusal text or None, reason it did not refuse though it was asked to, or None). Raises CheckFailed when there is no answer."""
    cli = os.path.join(repo, "src", "coordinatord", "cli.ts")
    if not os.path.isfile(cli):
        raise CheckFailed("coordinator checkout not found: " + cli)
    child = {**env, "COORDINATOR_STATE_DIR": state}
    continued = hook_input.get("stop_hook_active") is True
    command = [env.get("LEAD_TURN_END_NODE") or "node", "--experimental-strip-types", "--disable-warning=ExperimentalWarning", cli, "t3", "turn-end",
               "--thread", thread, "--jobs", str(count_jobs(child))]
    if continued:
        command.append("--continued")
    limit = float(env.get("LEAD_TURN_END_TIMEOUT") or 30)
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=limit, env=child)
    except subprocess.TimeoutExpired:
        raise CheckFailed("the command timed out after %g s" % limit)
    except OSError as error:
        raise CheckFailed("the command could not start: %s" % error)
    lines = done.stdout.strip().splitlines()
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict) or not isinstance(answer.get("answer"), str):
        tail = (done.stderr.strip().splitlines() or [""])[-1][:200]
        raise CheckFailed("no readable answer (exit %s)%s" % (done.returncode, ": " + tail if tail else ""))
    message = answer.get("message")
    if answer["answer"] != "refuse" or not isinstance(message, str) or not message:
        return None, None
    if continued:
        return None, "the coordinator refused a stop that already followed a refusal"
    return message, None


def refusal(argv, hook_input, env):
    """The coordinator's refusal text, or None to let the end stand (writing the log line when the end stands for a reason worth a record)."""
    thread = env.get("T3CODE_THREAD_ID")
    if env.get("COORDINATOR_SEAT") in SKIPPED_SEATS:
        return None
    repo, state = option(argv, "--repo"), env.get("COORDINATOR_STATE_DIR") or option(argv, "--state")
    if not thread or not repo or not state:
        return None
    started = time.monotonic()
    try:
        if not os.path.isdir(state):
            raise CheckFailed("state directory not found: " + state)
        message, capped = ask(argv, hook_input, env, thread, repo, state)
    except CheckFailed as error:
        log_line(state, thread, "check-failed", str(error), started)
        return None
    except Exception as error:  # a fault in this script itself is a failed check too, not a trap for the lead
        log_line(state, thread, "check-failed", "hook error: %s: %s" % (type(error).__name__, error), started)
        return None
    if capped:
        log_line(state, thread, "after-refusal", capped, started)
    return message


def main(argv=()):
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        hook_input = json.loads(raw) if raw.strip() else {}
        if not isinstance(hook_input, dict):
            hook_input = {}
        message = refusal(list(argv), hook_input, dict(os.environ))
    except Exception:
        return 0
    if message is None:
        return 0
    sys.stderr.write(message + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
