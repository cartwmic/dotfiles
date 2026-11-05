#!/usr/bin/env python3
"""Prepare a rendered or deployed arm plist for `traces pi proof arm-check` (kit 0.27.0).

arm-check rewrites the home prefix in a plist to its scratch HOME and runs ProgramArguments there. A scratch HOME holds no wrapper, no shim and
no shadow_py_run.py, and arm-check refuses a scratch that is not empty, so a plist run as it is cannot start. This copy of the plist changes
only where the programs are found; every label, switch, state dir and data dir stays exactly as rendered:

  - an entry of ProgramArguments, and AGENT_EVENTS_IMPLEMENTATION, that starts with PREFIX/.local/ now starts with STAGE/.local/ (outside PREFIX,
    so arm-check leaves it alone);
  - it adds the environment the wrapper and the shim find on the real machine and not in a scratch HOME: AGENT_TRACES_KIT (the install dir),
    AGENT_TRACES_NODE, AGENT_EVENTS_PYTHON.

    stage_arm_check.py PLIST OUT --prefix /Users/me --stage /tmp/stage [--kit DIR] [--node PATH] [--python PATH]

STAGE holds .local/bin/{agent-traces,agent-events} and .local/share/agent-events: chezmoi apply into a scratch destination (as test_arms.py does)
or copies. Then: traces pi proof arm-check --plist OUT --scratch EMPTY_DIR --kind ts|py|seed --home-prefix PREFIX [--tools DIR for py]
"""
import argparse
import plistlib
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plist")
    ap.add_argument("out")
    ap.add_argument("--prefix", required=True, help="the home directory spelled in the plist")
    ap.add_argument("--stage", required=True, help="a directory holding .local/bin and .local/share/agent-events")
    ap.add_argument("--kit", help="the kit install dir (holds node_modules/@cartwmic/agent-kit)")
    ap.add_argument("--node", help="a node 22.19 or later")
    ap.add_argument("--python", help="a python 3.11 or later")
    a = ap.parse_args()
    root = plistlib.loads(Path(a.plist).read_bytes())
    swap = lambda v: a.stage + v[len(a.prefix):] if v.startswith(a.prefix + "/.local/") else v
    root["ProgramArguments"] = [swap(x) for x in root["ProgramArguments"]]
    env = root.setdefault("EnvironmentVariables", {})
    if "AGENT_EVENTS_IMPLEMENTATION" in env:
        env["AGENT_EVENTS_IMPLEMENTATION"] = swap(env["AGENT_EVENTS_IMPLEMENTATION"])
    for key, val in (("AGENT_TRACES_KIT", a.kit), ("AGENT_TRACES_NODE", a.node), ("AGENT_EVENTS_PYTHON", a.python)):
        if val:
            env[key] = val
    Path(a.out).write_bytes(plistlib.dumps(root))
    print("wrote %s: programs under %s, places still under %s" % (a.out, a.stage, a.prefix))


if __name__ == "__main__":
    main()
