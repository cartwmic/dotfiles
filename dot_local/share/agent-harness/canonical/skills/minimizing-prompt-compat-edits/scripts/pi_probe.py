#!/usr/bin/env python3
"""One isolated Pi Claude Compat inference; JSON stdin/stdout oracle protocol."""
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

GATE = "You're out of extra usage."
QUESTION = "Calculate 137 times 29. Reply with only the integer."
ANSWER = "3973"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_private(path, data):
    path.write_text(data)
    path.chmod(0o600)


def install_model_config(config, agent):
    path = config.get("modelConfigFile")
    if not path:
        return
    if config.get("modelConfigApproved") is not True:
        raise ValueError("Isolated model override needs explicit owner approval")
    document = json.loads(pathlib.Path(path).read_text())
    if set(document) != {"providers"} or set(document["providers"]) != {"claude-compat"}:
        raise ValueError("Override must target only Compat")
    provider = document["providers"]["claude-compat"]
    if set(provider) != {"models"} or len(provider["models"]) != 1:
        raise ValueError("Override must add exactly the requested model")
    model = provider["models"][0]
    allowed = {"id", "name", "api", "baseUrl", "reasoning", "input", "cost",
               "contextWindow", "maxTokens", "thinkingLevelMap", "compat",
               "promptCache", "inputLimits"}
    if (set(model) - allowed or model["id"] != config["model"]
            or model["api"] != "claude-compat-messages"
            or model["baseUrl"] != "https://api.anthropic.com"):
        raise ValueError("Override changes routing/auth or uses unreviewed metadata")
    write_private(agent / "models.json", json.dumps(document))


def ensure_exact_model(args, config, env, wire):
    # Inventory only, offline: do not infer/fuzzily substitute an absent id.
    listing = subprocess.run(args + ["--list-models"], cwd=config["cwd"], env=env,
                             capture_output=True, text=True, timeout=30)
    available = {parts[1] for line in listing.stdout.splitlines()
                 if len(parts := line.split()) >= 2 and parts[0] == "claude-compat"}
    if listing.returncode or config["model"] not in available or wire.read_text():
        raise ValueError("Exact requested model unavailable or inventory used network")


def main():
    config = json.loads(pathlib.Path(sys.argv[1]).read_text())
    request = json.load(sys.stdin)
    prompt = pathlib.Path(request["prompt"])
    output = pathlib.Path(request["outputDir"])
    result = {
        "verdict": "inconclusive", "messages": 0,
        "promptSha256": request["promptSha256"], "contextDigest": request["contextDigest"],
        "reason": "not-started", "mode": config["mode"],
        "model": config["model"],
        "catalogOrigin": "approved-isolated-override" if config.get("modelConfigFile") else "stock",
    }
    try:
        if config["mode"] not in ("live", "fixture"):
            raise ValueError("Unknown oracle mode")
        if request["maxMessages"] != 1 or sha(prompt.read_bytes()) != request["promptSha256"]:
            raise ValueError("Bad frozen prompt or budget")
        if ANSWER in prompt.read_text():
            raise ValueError("Answer already present in prompt; choose a different oracle challenge")
        host = subprocess.run([config["pi"], "-ne", "--offline", "--version"], capture_output=True, text=True, timeout=10)
        if host.returncode or host.stdout.strip() != config["expectedPiVersion"]:
            raise ValueError("Pi host version changed")
        credential = json.loads(pathlib.Path(config["authPath"]).read_text())[config["authProvider"]]
        if credential.get("type") != "oauth" or credential["expires"] < time.time()*1000+300000:
            raise ValueError("Need current OAuth access; login/refresh is an owner action")
        wire = output / "wire.jsonl"
        write_private(wire, "")
        with tempfile.TemporaryDirectory(prefix="pi-probe-", dir=output) as temp:
            agent = pathlib.Path(temp)
            write_private(agent / "auth.json", json.dumps({"claude-compat": {
                "type": "oauth", "access": credential["access"],
                "refresh": "PROBE-REFRESH-DISABLED", "expires": credential["expires"],
            }}))
            write_private(agent / "settings.json", json.dumps({"retry": {"enabled": False}}))
            install_model_config(config, agent)
            profile = agent / "claude-request-compat"
            profile.mkdir(mode=0o700)
            write_private(profile / "profile.json", json.dumps({
                "schema": 2, "installId": config["installId"], "cacheMain": "long",
                "createdAt": "2026-01-01T00:00:00Z",
            }))
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("ANTHROPIC_", "PI_", "PROMPT_COMPAT_")) and k != "NODE_OPTIONS"}
            env.update({
                "PI_CODING_AGENT_DIR": str(agent), "PI_OFFLINE": "1",
                "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0",
                "PROMPT_COMPAT_SOURCE": str(prompt), "PROMPT_COMPAT_WIRE": str(wire),
                "PROMPT_COMPAT_MAX_MESSAGES": "1",
                "PROMPT_COMPAT_EXPECTED_MODEL": config["model"],
                "PROMPT_COMPAT_AUTHORIZATION_SHA": sha(("Bearer " + credential["access"]).encode()),
                "PROMPT_COMPAT_CWD": str(pathlib.Path(config["cwd"]).resolve()),
            })
            args = [config["pi"], "--offline", "--no-approve", "-ne", "-ns", "-nc", "-np",
                    "--no-themes", "--no-tools", "--no-session", "--system-prompt", str(prompt)]
            if config["mode"] == "fixture":
                args += ["-e", config["transportExtension"]]
            elif config.get("transportExtension"):
                raise ValueError("Live mode cannot replace transport")
            args += ["-e", str(pathlib.Path(__file__).with_name("wire_guard.mjs")),
                     "-e", config["extension"]]
            ensure_exact_model(args, config, env, wire)
            args += ["--provider", "claude-compat", "--model", config["model"],
                     "--thinking", "off", "--mode", "json", QUESTION]
            run = subprocess.run(args, cwd=config["cwd"], env=env, capture_output=True, text=True, timeout=90)
        # Do not persist stdout: it contains the full owner prompt and may contain
        # credential-bearing provider diagnostics. Parse only completed messages.
        records = []
        for line in run.stdout.split("\n"):
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        messages = [e["message"] for e in records if e.get("type") == "message_end"
                    and e.get("message", {}).get("role") == "assistant"]
        rows = [json.loads(line) for line in wire.read_text().splitlines()]
        sent = [r for r in rows if r["kind"] == "messages"]
        responses = [r for r in rows if r["kind"] == "response"]
        result["messages"] = len(sent)
        if (len(sent) != 1 or len(responses) != 1 or len(messages) != 1 or run.returncode
                or any(r["kind"] == "blocked-retry" for r in rows)):
            raise ValueError("Incomplete turn, retry, transport failure, or missing wire proof")
        proof = sent[0]
        binding = {k: v for k, v in proof.items() if k not in ("kind", "promptSha256", "sent")}
        binding["credentialFingerprint"] = sha(credential["access"].encode())
        context_path = pathlib.Path(config["wireContext"])
        if context_path.exists():
            if json.loads(context_path.read_text()) != binding:
                raise ValueError("Wire fields outside edited prompt changed")
        else:
            write_private(context_path, json.dumps(binding, sort_keys=True))
        if proof["promptSha256"] != request["promptSha256"] or proof["model"] != config["model"] or proof["tools"]:
            raise ValueError("Unexpected prompt, model, or tools")
        message = messages[0]
        status = responses[0]["status"]
        text = "".join(b.get("text", "") for b in message.get("content", []) if b["type"] == "text").strip()
        if (message.get("provider") != "claude-compat" or message.get("api") != "claude-compat-messages"
                or message.get("model") != config["model"]):
            raise ValueError("Unexpected provider/API identity")
        if status == 200 and message.get("stopReason") == "stop" and text == ANSWER:
            result.update(verdict="accept", reason="completed-correct-answer")
        elif status == 400 and message.get("stopReason") == "error" and GATE in message.get("errorMessage", ""):
            result.update(verdict="reject", reason="known-server-gate")
        else:
            result["reason"] = "other-provider-outcome"
        result.update(httpStatus=status, stopReason=message.get("stopReason"),
                      wireExtraSha256=proof["extraSha256"], completedAnswer=(text == ANSWER))
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        result["reason"] = "probe-preflight-or-evidence-failed"
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
