#!/usr/bin/env python3
"""Complete a real read/result/resume path with the full winning prompt (<=3 sends)."""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

from pi_probe import sha, write_private, install_model_config, ensure_exact_model


def verify(config, prompt, output, expected_hash, remaining):
    if remaining < 3 or sha(prompt.read_bytes()) != expected_hash:
        raise ValueError("Need three reserved sends and the exact winning prompt")
    if config["mode"] not in ("live", "fixture"):
        raise ValueError("Unknown mode")
    if config["mode"] == "live" and config.get("transportExtension"):
        raise ValueError("Live mode cannot substitute transport")
    host = subprocess.run([config["pi"], "-ne", "--offline", "--version"],
                          capture_output=True, text=True, timeout=10)
    if host.returncode or host.stdout.strip() != config["expectedPiVersion"]:
        raise ValueError("Host version changed")
    credential = json.loads(pathlib.Path(config["authPath"]).read_text())[config["authProvider"]]
    if credential.get("type") != "oauth" or credential["expires"] < time.time()*1000+300000:
        raise ValueError("Owner OAuth access is not current")
    fixture = output / "challenge.txt"
    write_private(fixture, "8417\n")
    wire = output / "wire.jsonl"
    write_private(wire, "")
    phases = []
    with tempfile.TemporaryDirectory(prefix="verify-agent-", dir=output) as temp:
        agent = pathlib.Path(temp)
        write_private(agent / "auth.json", json.dumps({"claude-compat": {
            "type": "oauth", "access": credential["access"],
            "refresh": "VERIFY-REFRESH-DISABLED", "expires": credential["expires"],
        }}))
        write_private(agent / "settings.json", json.dumps({"retry": {"enabled": False}}))
        install_model_config(config, agent)
        profile = agent / "claude-request-compat"
        profile.mkdir(mode=0o700)
        write_private(profile / "profile.json", json.dumps({
            "schema": 2, "installId": config["installId"], "cacheMain": "long",
        }))
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("ANTHROPIC_", "PI_", "PROMPT_COMPAT_")) and k != "NODE_OPTIONS"}
        env.update({
            "PI_CODING_AGENT_DIR": str(agent), "PI_OFFLINE": "1", "PI_TELEMETRY": "0",
            "PI_SKIP_VERSION_CHECK": "1", "PROMPT_COMPAT_SOURCE": str(prompt),
            "PROMPT_COMPAT_EXPECTED_MODEL": config["model"],
            "PROMPT_COMPAT_WIRE": str(wire),
            "PROMPT_COMPAT_AUTHORIZATION_SHA": sha(("Bearer " + credential["access"]).encode()),
            "PROMPT_COMPAT_CWD": str(pathlib.Path(config["cwd"]).resolve()),
        })
        base = [config["pi"], "--offline", "--no-approve", "-ne", "-ns", "-nc", "-np",
                "--no-themes", "--tools", "read", "--system-prompt", str(prompt)]
        if config["mode"] == "fixture":
            base += ["-e", config["transportExtension"]]
        base += ["-e", str(pathlib.Path(__file__).with_name("wire_guard.mjs")),
                 "-e", config["extension"]]
        ensure_exact_model(base, config, env, wire)
        base += ["--provider", "claude-compat", "--model", config["model"],
                 "--thinking", "off", "--mode", "json"]

        def phase(name, args, limit):
            env["PROMPT_COMPAT_MAX_MESSAGES"] = str(limit)
            process = subprocess.run(args, cwd=config["cwd"], env=env,
                                     capture_output=True, text=True, timeout=90)
            events = []
            for line in process.stdout.split("\n"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
            completed = [e["message"] for e in events if e.get("type") == "message_end"
                         and e.get("message", {}).get("role") == "assistant"]
            if process.returncode or not completed or completed[-1]["stopReason"] != "stop":
                raise ValueError("Functional turn did not complete")
            if any(m.get("provider") != "claude-compat" or m.get("api") != "claude-compat-messages"
                   or m.get("model") != config["model"] for m in completed):
                raise ValueError("Functional provider identity changed")
            text = "".join(b.get("text", "") for b in completed[-1]["content"]
                           if b["type"] == "text").strip()
            tools = [e for e in events if e.get("type") == "tool_execution_end"]
            phases.append({"phase": name, "answer": text,
                           "toolNames": [e.get("toolName") for e in tools]})
            return text, tools

        first, tools = phase("read-result", base + [
            f"Use the read tool to read {fixture}. Subtract 37 from the integer in that file. "
            "Respond with only the resulting integer."], 2)
        if first != "8380" or len(tools) != 1 or tools[0]["toolName"] != "read" or tools[0]["isError"]:
            raise ValueError("Read tool and derived-answer proof failed")
        sessions = list((agent / "sessions").rglob("*.jsonl"))
        if len(sessions) != 1:
            raise ValueError("Expected one private saved session")
        second, tools = phase("fresh-process-resume", base + ["--session", str(sessions[0]),
            "Without reading files or calling tools, recall the original integer and the calculated "
            "result from the previous turn. Reply only as original|result."], 1)
        if not re.fullmatch(r"8417\s*\|\s*8380", second) or tools:
            raise ValueError("History coherence or no-repeat-tool proof failed")
    rows = [json.loads(line) for line in wire.read_text().splitlines()]
    sends = [row for row in rows if row["kind"] == "messages"]
    responses = [row for row in rows if row["kind"] == "response"]
    if (len(sends) != 3 or len(responses) != 3 or any(row["status"] != 200 for row in responses)
            or any(row["kind"] == "blocked-retry" for row in rows)
            or any(row["promptSha256"] != expected_hash for row in sends)):
        raise ValueError("Functional wire/count/status proof incomplete")
    return {"status": "verified", "mode": config["mode"], "model": config["model"],
            "catalogOrigin": "approved-isolated-override" if config.get("modelConfigFile") else "stock",
            "promptSha256": expected_hash,
            "inferenceSends": len(sends), "phases": phases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=pathlib.Path)
    parser.add_argument("prompt", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--remaining-inferences", required=True, type=int)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(mode=0o700)
    try:
        result = verify(json.loads(args.config.read_text()), args.prompt.resolve(),
                        output, args.sha256, args.remaining_inferences)
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        wire = output / "wire.jsonl"
        sends = sum(json.loads(line).get("kind") == "messages"
                    for line in wire.read_text().splitlines()) if wire.exists() else 0
        result = {"status": "blocked", "reason": "functional-proof-failed", "inferenceSends": sends}
    write_private(output / "result.json", json.dumps(result, indent=2))
    print(json.dumps(result))
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
