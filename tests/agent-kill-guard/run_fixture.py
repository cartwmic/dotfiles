#!/usr/bin/env python3
"""Feed one recorded tool call (a hook payload in fixtures/) to the real hook entry point and check its verdict.

usage: run_fixture.py FIXTURE refuse|allow [--text T]... [--env K=V]... [--command TEXT]
--command replaces tool_input.command (for a good variant of a real call). Exit 0 when the verdict matches, else 1 with the reason.
An --env value that starts with @ names a file in fixtures/ (KUBECONFIG=@kubeconfig-other).
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "..", "dot_local", "share", "agent-harness", "hooks", "refuse_pattern_kill.py")


def main(argv):
    fixture, want = argv[1], argv[2]
    texts, env, command = [], dict(os.environ), None
    rest = argv[3:]
    while rest:
        flag, value, rest = rest[0], rest[1], rest[2:]
        if flag == "--text":
            texts.append(value)
        elif flag == "--env":
            k, v = value.split("=", 1)
            env[k] = os.path.join(HERE, "fixtures", v[1:]) if v.startswith("@") else v
        elif flag == "--command":
            command = value
    payload = json.load(open(os.path.join(HERE, "fixtures", fixture)))
    if command is not None:
        payload["tool_input"]["command"] = command
    p = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True, env=env)
    got = "refuse" if p.returncode == 2 else "allow" if p.returncode == 0 else "exit %d" % p.returncode
    missing = [t for t in texts if t not in p.stderr]
    print("%s: %s (exit %d)%s" % (fixture, got, p.returncode, (" stderr: " + p.stderr.strip()) if p.stderr.strip() else ""))
    if got != want or missing:
        print("FAIL: wanted %s%s" % (want, (" with " + repr(missing)) if missing else ""))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
