#!/usr/bin/env python3
"""Claude Code Stop hook for the lead seat: a lead's turn may end only when something will wake it, an ask that names it is open, or a state note was accepted.

The rule, and every read behind it, is `coordinator t3 turn-end` in the coordinator checkout (src/t3-hook/turn-end.ts); this script holds none of it. It does what the
coordinator cannot: counts this thread's running run-and-wake and kgate jobs (stop_running_jobs.py --count, beside it) and passes the number as `--jobs N`, and it knows
whether this stop follows its own refusal: Claude Code sets `stop_hook_active` in the hook input when the session is already continuing because a Stop hook blocked it. That is
`--continued`: the coordinator then lets the end through and reports it. No refusal is stored anywhere. No message text is read.

Arguments: --repo COORDINATOR_CHECKOUT --state COORDINATOR_STATE_DIR (the seat file renders both per profile). The session's COORDINATOR_STATE_DIR wins when set.
Output: exit 2 and the refusal on stderr to keep the session going, else exit 0. It fails open: no T3CODE_THREAD_ID, a missing checkout or state directory, a command that
fails or times out, or output it cannot read allows the end and prints nothing.
Test hooks: LEAD_TURN_END_NODE names the node binary.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


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


def refusal(argv, hook_input, env):
    """The coordinator's refusal text, or None to let the end stand."""
    thread = env.get("T3CODE_THREAD_ID")
    repo, state = option(argv, "--repo"), env.get("COORDINATOR_STATE_DIR") or option(argv, "--state")
    if not thread or not repo or not state:
        return None
    cli = os.path.join(repo, "src", "coordinatord", "cli.ts")
    if not os.path.isfile(cli) or not os.path.isdir(state):
        return None
    child = {**env, "COORDINATOR_STATE_DIR": state}
    command = [env.get("LEAD_TURN_END_NODE") or "node", "--experimental-strip-types", "--disable-warning=ExperimentalWarning", cli, "t3", "turn-end",
               "--thread", thread, "--jobs", str(count_jobs(child))]
    if hook_input.get("stop_hook_active") is True:
        command.append("--continued")
    done = subprocess.run(command, capture_output=True, text=True, timeout=30, env=child)
    lines = done.stdout.strip().splitlines()
    answer = json.loads(lines[-1]) if lines else {}
    message = answer.get("message")
    return message if answer.get("answer") == "refuse" and isinstance(message, str) and message else None


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
