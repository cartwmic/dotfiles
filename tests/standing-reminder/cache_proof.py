#!/usr/bin/env python3
"""Capped live prompt-cache comparison for openai-codex/gpt-6-sol.

Runs matched reminder-off and unchanged-reminder Pi sessions. The model's
request limits are overridden only in a temporary Pi agent directory so a
worst-case token-cost reserve can be enforced before any live call. Credentials
are copied at runtime into that private temporary directory, never printed or
written into the repository. Missing usage/cache counters block the proof;
request-prefix shape is not a substitute.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "dot_pi/private_agent/extensions/standing-reminder/index.ts"
PROVIDER = "openai-codex"
MODEL_ID = "gpt-6-sol"
MODEL_REF = f"{PROVIDER}/{MODEL_ID}"
DEFAULT_CAP_USD = 5.00
MAX_CONTEXT_TOKENS = 45_000
MAX_OUTPUT_TOKENS = 256
WARMUP_TURNS = (2, 3)
MEASURED_TURNS = (4, 5)
TURN_COUNT = 5
REMINDER = "Keep the existing implementation unless the operator asks otherwise."


class ProofFailure(RuntimeError):
    pass


class ProofBlocked(RuntimeError):
    pass


def require_isolated_patched_pi(pi_bin: str) -> None:
    package_value = os.environ.get("PI_STANDING_REMINDER_ORIGIN_PACKAGE")
    if not package_value:
        block("run the cache proof through tests/standing-reminder/isolated_pi.py")
    package = Path(package_value).resolve()
    try:
        Path(pi_bin).resolve().relative_to(package)
    except ValueError:
        block("PI_BIN is outside the isolated Pi package")
    try:
        metadata = json.loads((package / "package.json").read_text(encoding="utf-8"))
        runtime = (package / "dist/core/agent-session.js").read_text(encoding="utf-8")
        declarations = (package / "dist/core/extensions/types.d.ts").read_text(encoding="utf-8")
        bundles = [path for path in (package / "dist/bundle/chunks").glob("*.js")
                   if "chezmoi-pi-patch:standing-reminder-origin v1" in path.read_text(encoding="utf-8")]
    except (OSError, json.JSONDecodeError):
        block("the isolated Pi package or standing-reminder patch is incomplete")
    if metadata.get("name") != "@earendil-works/pi-coding-agent" or metadata.get("version") != "0.87.1":
        block("the cache proof requires isolated @earendil-works/pi-coding-agent 0.87.1")
    if ("chezmoi-pi-patch:standing-reminder-origin v1" not in runtime
            or "chezmoi-pi-patch:standing-reminder-origin v1" not in declarations
            or len(bundles) != 1
            or os.environ.get("PI_CHEZMOI_PROFILE") not in {"personal", "axon-work-computer"}):
        block("the desktop-gated standing-reminder origin patch is missing from isolated Pi")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ProofFailure(message)


def block(message: str) -> None:
    raise ProofBlocked(message)


def run_process(argv: list[str], env: dict[str, str], *, stdin: str | None = None,
                timeout: float = 45) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, env=env, input=stdin, text=True, capture_output=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProofBlocked(f"could not complete Pi preflight: {type(exc).__name__}") from exc


def json_lines(text: str, description: str) -> list[dict[str, Any]]:
    records = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProofFailure(f"{description} emitted non-JSON stdout at line {number}") from exc
        if not isinstance(value, dict):
            raise ProofFailure(f"{description} emitted a non-object JSON record")
        records.append(value)
    return records


def prepare_agent(agent_dir: Path, source_agent_dir: Path) -> None:
    source_auth = source_agent_dir / "auth.json"
    if not source_auth.is_file():
        block(f"Pi credentials are missing at {source_auth}; authenticate openai-codex first")
    try:
        credentials = json.loads(source_auth.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        block("Pi auth.json is unreadable; no live request was sent")
    if not isinstance(credentials, dict) or PROVIDER not in credentials:
        block(f"Pi auth.json has no {PROVIDER!r} credential; no live request was sent")

    agent_dir.mkdir(parents=True, mode=0o700)
    # Copy only the selected provider credential. The copy is private and
    # temporary; token refreshes cannot modify the operator's auth.json.
    auth_path = agent_dir / "auth.json"
    auth_path.write_text(json.dumps({PROVIDER: credentials[PROVIDER]}), encoding="utf-8")
    auth_path.chmod(0o600)
    models = {
        "providers": {
            PROVIDER: {
                "modelOverrides": {
                    MODEL_ID: {
                        "contextWindow": MAX_CONTEXT_TOKENS,
                        "maxTokens": MAX_OUTPUT_TOKENS,
                    }
                }
            }
        }
    }
    (agent_dir / "models.json").write_text(json.dumps(models), encoding="utf-8")
    (agent_dir / "settings.json").write_text(json.dumps({
        "retry": {"enabled": False, "maxRetries": 0, "provider": {"maxRetries": 0}},
        "compaction": {"enabled": False},
        "cacheWarming": "off",
    }), encoding="utf-8")


def base_env(agent_dir: Path, sessions_dir: Path, home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.update({
        "HOME": str(home),
        "PI_CODING_AGENT_DIR": str(agent_dir),
        "PI_CODING_AGENT_SESSION_DIR": str(sessions_dir),
        "PI_OFFLINE": "1",
        "PI_TELEMETRY": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def rpc_models(pi: str, env: dict[str, str], cwd: Path) -> dict[str, Any]:
    argv = [pi, "--mode", "rpc", "--no-session", "--offline", "--approve", "--no-context-files",
            "--no-skills", "--no-prompt-templates", "--no-themes", "--no-extensions",
            "--provider", PROVIDER, "--model", MODEL_REF]
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1)
    except OSError as exc:
        raise ProofBlocked("Pi could not start for model/cap preflight") from exc
    assert process.stdin and process.stdout
    process.stdin.write(json.dumps({"id": "standing-cache-models", "type": "get_available_models"}) + "\n")
    process.stdin.flush()
    response: dict[str, Any] | None = None
    try:
        for line in process.stdout:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("id") == "standing-cache-models" and item.get("type") == "response":
                response = item
                break
    except OSError:
        pass
    process.stdin.close()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        block("Pi model preflight did not exit cleanly")
    if not response or response.get("success") is not True:
        block("Pi could not resolve the selected live model; no completion was requested")
    models = response.get("data", {}).get("models", [])
    model = next((item for item in models if item.get("provider") == PROVIDER and item.get("id") == MODEL_ID), None)
    if not model:
        block(f"Pi did not expose exact model {MODEL_REF}; no fallback model will be used")
    if model.get("api") != "openai-codex-responses":
        block(f"{MODEL_REF} resolved to unexpected API {model.get('api')!r}")
    if model.get("contextWindow") != MAX_CONTEXT_TOKENS or model.get("maxTokens") != MAX_OUTPUT_TOKENS:
        block("temporary request-token limits did not apply; refusing an unbounded live run")
    return model


def worst_case_call_cost(model: dict[str, Any]) -> float:
    cost = model.get("cost")
    if not isinstance(cost, dict):
        block("Pi did not provide model cost rates; refusing a live request")
    rates: list[dict[str, Any]] = [cost]
    tiers = cost.get("tiers", [])
    if not isinstance(tiers, list):
        block("Pi model cost tiers are unusable; refusing a live request")
    rates.extend(tier for tier in tiers if isinstance(tier, dict))
    keys = ("input", "output", "cacheRead", "cacheWrite")
    for rate_set in rates:
        if any(not isinstance(rate_set.get(key), (int, float)) or isinstance(rate_set.get(key), bool)
               or not math.isfinite(rate_set[key]) or rate_set[key] < 0 for key in keys):
            block("Pi model cost rates are incomplete; refusing a live request")
    if not any(rate_set[key] > 0 for rate_set in rates for key in keys):
        block("Pi reported only zero model rates; the $5 spend cap cannot be reserved safely")
    max_input_rate = max(max(rate_set[key] for rate_set in rates) for key in ("input", "cacheRead", "cacheWrite"))
    max_output_rate = max(rate_set["output"] for rate_set in rates)
    return (MAX_CONTEXT_TOKENS * max_input_rate + MAX_OUTPUT_TOKENS * max_output_rate) / 1_000_000


def stable_payload() -> str:
    return "\n".join(
        f"Stable cache fixture row {index:04d}: preserve this shared prefix exactly; it is ordinary context, not an instruction."
        for index in range(240)
    )


def prompt_for(turn: int, payload: str) -> str:
    return (f"CACHE-PROOF-TURN-{turn:02d}\n{payload}\n"
            f"Reply with exactly CACHE-ACK-{turn:02d} and no other text.")


def observer_source() -> str:
    return r'''import { appendFileSync } from "node:fs";
function textOf(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content.filter((part) => part?.type === "text").map((part) => part.text).join("\n");
}
export default function (pi) {
  pi.on("context", (event) => {
    const texts = event.messages.map((message) => textOf(message?.content));
    const reminderTexts = texts.filter((text) => text.startsWith("<standing-reminder>\n"));
    const latestUser = [...event.messages].reverse().find((message) => message?.role === "user"
      && !textOf(message.content).startsWith("<standing-reminder>\n"));
    appendFileSync(process.env.PI_CACHE_AUDIT_FILE, JSON.stringify({
      latestUser: latestUser ? textOf(latestUser.content) : "",
      reminders: reminderTexts,
    }) + "\n");
  });
}
'''


def find_session_file(sessions_dir: Path, session_id: str) -> Path:
    matches = []
    for path in sessions_dir.rglob("*.jsonl"):
        try:
            first_line = path.open(encoding="utf-8").readline()
            header = json.loads(first_line)
        except (OSError, json.JSONDecodeError):
            continue
        if header.get("type") == "session" and header.get("id") == session_id:
            matches.append(path)
    if len(matches) != 1:
        raise ProofFailure(f"expected one saved {session_id} session, found {len(matches)}")
    return matches[0]


def write_reminder_state(sessions_dir: Path, session_id: str) -> None:
    path = sessions_dir / "standing-reminder" / f"{session_id}.json"
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps({"version": 1, "reminder": REMINDER, "pending": False}), encoding="utf-8")
    path.chmod(0o600)


def read_usage(records: list[dict[str, Any]], expected_prompt: str) -> dict[str, Any]:
    user_seen = any(record.get("type") == "message_end"
                    and record.get("message", {}).get("role") == "user"
                    and text_of(record["message"].get("content")) == expected_prompt
                    for record in records)
    if not user_seen:
        raise ProofFailure("Pi JSON events did not preserve the submitted cache-proof prompt")
    assistant_messages = [record["message"] for record in records
                          if record.get("type") == "message_end"
                          and record.get("message", {}).get("role") == "assistant"]
    if not assistant_messages:
        block("live provider returned no completed assistant message or usage counters")
    message = assistant_messages[-1]
    if message.get("provider") != PROVIDER or message.get("model") != MODEL_ID:
        block("live response did not come from the exact selected provider/model")
    usage = message.get("usage")
    if not isinstance(usage, dict):
        block("provider omitted Pi usage data; cache criterion is unproven, with no prefix-only fallback")
    for key in ("input", "cacheRead"):
        value = usage.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            block(f"provider omitted usable {key} counters; cache criterion is unproven, with no prefix-only fallback")
    cost = usage.get("cost")
    total_cost = cost.get("total") if isinstance(cost, dict) else None
    if (not isinstance(total_cost, (int, float)) or isinstance(total_cost, bool)
            or not math.isfinite(total_cost) or total_cost < 0):
        block("provider omitted usable cost counters; stopping to preserve the spend cap")
    if usage["input"] <= 0:
        block("provider reported zero input tokens; live cache counters are unusable")
    return {"input": int(usage["input"]), "cacheRead": int(usage["cacheRead"]),
            "cacheWrite": usage.get("cacheWrite"), "cost": float(total_cost)}


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content
                          if isinstance(part, dict) and part.get("type") == "text")
    return ""


def audit_rows(path: Path, prompts: list[str], reminder_active: bool) -> list[dict[str, Any]]:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    selected = []
    for prompt in prompts:
        matches = [row for row in rows if row.get("latestUser") == prompt]
        if len(matches) != 1:
            block(f"context audit did not observe exactly one model request for {prompt.splitlines()[0]}")
        row = matches[0]
        expected = [f"<standing-reminder>\n{REMINDER}\n</standing-reminder>"] if reminder_active else []
        if row.get("reminders") != expected:
            raise ProofFailure(f"context audit found incorrect reminder delivery for {prompt.splitlines()[0]}")
        selected.append(row)
    return selected


def run_arm(*, pi: str, env: dict[str, str], cwd: Path, sessions: Path, extension: Path,
            observer: Path, session_id: str, audit: Path, cap: float, reserve_per_call: float,
            spent_before: float, remaining_calls: int, payload: str, reminder_arm: bool
            ) -> tuple[list[dict[str, Any]], float]:
    usages: list[dict[str, Any]] = []
    prompts = [prompt_for(turn, payload) for turn in range(1, TURN_COUNT + 1)]
    session_file: Path | None = None
    spent = spent_before
    for turn, prompt in enumerate(prompts, 1):
        calls_left = remaining_calls - (turn - 1)
        if spent + reserve_per_call * calls_left > cap + 1e-9:
            block(f"worst-case reserve would exceed the ${cap:.2f} cap before {session_id} turn {turn}")
        command = [pi, "--mode", "json", "--approve", "--no-context-files", "--no-skills", "--no-prompt-templates",
                   "--no-themes", "--no-extensions", "--extension", str(extension),
                   "--extension", str(observer), "--provider", PROVIDER, "--model", MODEL_REF,
                   "--thinking", "off", "--no-tools", "--session-dir", str(sessions)]
        if session_file is None:
            command.extend(["--session-id", session_id])
        else:
            command.extend(["--session", str(session_file)])
        command.append(prompt)
        call_env = env.copy()
        call_env["PI_CACHE_AUDIT_FILE"] = str(audit)
        completed = run_process(command, call_env, timeout=120)
        if completed.returncode != 0:
            # Don't dump arbitrary provider diagnostics or credentials.
            block(f"{MODEL_REF} call {turn} failed (exit {completed.returncode}); no alternate provider will be tried")
        records = json_lines(completed.stdout, f"Pi JSON {session_id} turn {turn}")
        usage = read_usage(records, prompt)
        spent += usage["cost"]
        if spent > cap + 1e-9:
            block(f"reported live spend exceeded the ${cap:.2f} cap; stopping immediately")
        usages.append(usage)
        if session_file is None:
            session_file = find_session_file(sessions, session_id)
            if reminder_arm:
                write_reminder_state(sessions, session_id)
    if len(usages) != TURN_COUNT:
        raise ProofFailure(f"incomplete {session_id} arm: expected {TURN_COUNT} requests")
    audit_rows(audit, prompts, reminder_active=False) if not reminder_arm else audit_rows(audit, prompts[:1], reminder_active=False)
    if reminder_arm:
        audit_rows(audit, prompts[1:], reminder_active=True)
    return usages, spent


def compare(off: list[dict[str, Any]], on: list[dict[str, Any]]) -> dict[str, Any]:
    for arm_name, arm in (("reminder-off", off), ("reminder-on", on)):
        if len(arm) != TURN_COUNT:
            raise ProofFailure(f"{arm_name} arm has {len(arm)} usage records; expected {TURN_COUNT}")
        for turn, usage in enumerate(arm, 1):
            if not isinstance(usage, dict):
                block(f"{arm_name} turn {turn} has no usable usage record")
            for key in ("input", "cacheRead"):
                value = usage.get(key)
                if (not isinstance(value, (int, float)) or isinstance(value, bool)
                        or not math.isfinite(value) or value < 0):
                    block(f"{arm_name} turn {turn} has no usable {key} counter")
            if usage["input"] <= 0:
                block(f"{arm_name} turn {turn} reported zero input tokens")

    off_warm = [off[index - 1]["cacheRead"] for index in WARMUP_TURNS]
    on_warm = [on[index - 1]["cacheRead"] for index in WARMUP_TURNS]
    if not any(value > 0 for value in off_warm):
        block("reminder-off warm-up produced no cacheRead hits; no cache comparison can be made")
    if not any(value > 0 for value in on_warm):
        block("reminder-on warm-up produced no cacheRead hits; no cache comparison can be made")

    off_measured = sum(off[turn - 1]["cacheRead"] for turn in MEASURED_TURNS)
    on_measured = sum(on[turn - 1]["cacheRead"] for turn in MEASURED_TURNS)
    if off_measured <= 0:
        block("measured reminder-off requests had no cacheRead hits; the control arm was not warmed")
    if on_measured <= 0:
        block("measured reminder-on requests had no cacheRead hits; no prefix-only pass is allowed")
    pairs = []
    misses = 0
    for turn in MEASURED_TURNS:
        baseline = off[turn - 1]
        reminder = on[turn - 1]
        if baseline["input"] <= 0 or reminder["input"] <= 0:
            block("measured request omitted a usable input counter")
        # One isolated zero/deep miss can be provider cache churn; two paired
        # misses are repeatable and block the unchanged-reminder criterion.
        allowance = max(1024, int(baseline["cacheRead"] * 0.20))
        missed = reminder["cacheRead"] <= 0 or (
            baseline["cacheRead"] > 0 and reminder["cacheRead"] + allowance < baseline["cacheRead"]
        )
        if missed:
            misses += 1
        pairs.append({
            "turn": turn,
            "off": baseline,
            "on": reminder,
            "allowed_cache_read_delta": allowance,
        })
    if misses >= 2:
        raise ProofFailure("reminder-on sequence had repeatable cacheRead misses against the warmed reminder-off sequence")
    return {"warm_cacheRead_off": off_warm, "warm_cacheRead_on": on_warm,
            "measured_pairs": pairs, "repeatable_miss_pairs": misses}


def run_self_tests() -> None:
    with tempfile.TemporaryDirectory(prefix="standing-cache-proof-test-") as temporary:
        sessions = Path(temporary)
        session_id = "first-on-arm-session"
        state_path = sessions / "standing-reminder" / f"{session_id}.json"
        require(not state_path.exists(), "state-write regression fixture must start without a sidecar")
        write_reminder_state(sessions, session_id)
        require(json.loads(state_path.read_text(encoding="utf-8")) == {
            "version": 1, "reminder": REMINDER, "pending": False,
        }, "first reminder-on state transition wrote the wrong sidecar")
        require(state_path.stat().st_mode & 0o777 == 0o600, "reminder sidecar mode is not 0600")
        require(state_path.parent.stat().st_mode & 0o777 == 0o700, "reminder sidecar directory mode is not 0700")

    reserve = worst_case_call_cost({"cost": {
        "input": 5.0, "output": 15.0, "cacheRead": 5.0, "cacheWrite": 5.0,
    }})
    require(abs(reserve * TURN_COUNT * 2 - 2.2884) < 1e-9,
            "ten-call worst-case reserve must be $2.28840 at $5/M input and $15/M output")

    usable = [{"input": 10_000, "cacheRead": 2_000} for _ in range(TURN_COUNT)]
    compare(usable, usable)
    for label, bad_arm in (
        ("warm", [{"input": 10_000, "cacheRead": 0} for _ in range(TURN_COUNT)]),
        ("measured", [
            {"input": 10_000, "cacheRead": value}
            for value in (2_000, 2_000, 0, 0, 0)
        ]),
        ("missing", [
            {"input": 10_000} for _ in range(TURN_COUNT)
        ]),
        ("boolean", [
            {"input": 10_000, "cacheRead": True} for _ in range(TURN_COUNT)
        ]),
    ):
        for off, on in ((usable, bad_arm), (bad_arm, usable)):
            try:
                compare(off, on)
            except ProofBlocked:
                continue
            raise ProofFailure(f"cache comparison accepted {label} evidence with missing or zero cacheRead")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap-usd", type=float, default=DEFAULT_CAP_USD,
                        help="lower the approved total spend cap (cannot exceed $5.00)")
    parser.add_argument("--pi", default=os.environ.get("PI_BIN") or shutil.which("pi"),
                        help="Pi executable (default: PI_BIN or PATH)")
    parser.add_argument("--extension", type=Path, default=EXTENSION,
                        help="standing-reminder extension source (default: this worktree)")
    parser.add_argument("--self-test", action="store_true",
                        help="run local no-network checks for sidecar creation, cache evidence, and spend reserve")
    args = parser.parse_args()
    if args.self_test:
        try:
            run_self_tests()
            print("PASS: no-network cache-proof state, evidence, and $2.28840 reserve regressions")
            return 0
        except ProofBlocked as exc:
            print(f"BLOCKED: {exc}")
            return 2
        except ProofFailure as exc:
            print(f"FAIL: {exc}")
            return 1
    if not args.pi:
        print("BLOCKED: `pi` is not on PATH (or set PI_BIN)")
        return 2
    if not math.isfinite(args.cap_usd) or args.cap_usd <= 0 or args.cap_usd > DEFAULT_CAP_USD:
        print("BLOCKED: --cap-usd must be greater than 0 and no more than $5.00")
        return 2
    extension = args.extension.resolve()
    if not extension.is_file():
        print(f"BLOCKED: extension source not found: {extension}")
        return 2

    try:
        run_self_tests()
        print("PASS: local no-network cache-proof state, evidence, and $2.28840 spend-reserve checks")
        require_isolated_patched_pi(args.pi)
        version = run_process([args.pi, "--version"], os.environ.copy(), timeout=10)
        if version.returncode != 0:
            block("Pi version could not be read")
        if version.stdout.strip() != "0.87.1":
            block(f"the live comparison is prepared for Pi 0.87.1; found {version.stdout.strip()!r}")

        source_agent = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi" / "agent")).expanduser()
        with tempfile.TemporaryDirectory(prefix="pi-standing-cache-proof-") as temporary:
            root = Path(temporary)
            agent = root / "agent"
            sessions = root / "sessions"
            project = root / "project"
            private_home = root / "home"
            project.mkdir()
            sessions.mkdir()
            private_home.mkdir()
            prepare_agent(agent, source_agent)
            observer = root / "cache-audit.ts"
            observer.write_text(observer_source(), encoding="utf-8")
            observer.chmod(0o600)
            env = base_env(agent, sessions, private_home)
            model = rpc_models(args.pi, env, project)
            reserve = worst_case_call_cost(model)
            total_reserve = reserve * (TURN_COUNT * 2)
            if total_reserve > args.cap_usd:
                block(f"the enforced worst-case reserve (${total_reserve:.4f}) exceeds the ${args.cap_usd:.2f} cap")
            print(f"Pi {version.stdout.strip()} · exact model {MODEL_REF}")
            print(f"Worst-case reserve: ${total_reserve:.4f} for {TURN_COUNT * 2} bounded requests; cap ${args.cap_usd:.2f}")

            payload = stable_payload()
            off_audit = root / "off-context.jsonl"
            on_audit = root / "on-context.jsonl"
            off, spent = run_arm(pi=args.pi, env=env, cwd=project, sessions=sessions, extension=extension,
                observer=observer, session_id="cache-proof-off", audit=off_audit, cap=args.cap_usd,
                reserve_per_call=reserve, spent_before=0.0, remaining_calls=TURN_COUNT * 2,
                payload=payload, reminder_arm=False)
            on, spent = run_arm(pi=args.pi, env=env, cwd=project, sessions=sessions, extension=extension,
                observer=observer, session_id="cache-proof-on", audit=on_audit, cap=args.cap_usd,
                reserve_per_call=reserve, spent_before=spent, remaining_calls=TURN_COUNT,
                payload=payload, reminder_arm=True)
            result = compare(off, on)
            report = {
                "status": "PASS",
                "model": MODEL_REF,
                "cap_usd": args.cap_usd,
                "worst_case_reserved_usd": round(total_reserve, 6),
                "reported_cost_usd": round(spent, 6),
                "provider_requests": TURN_COUNT * 2,
                "reminder": REMINDER,
                **result,
            }
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            print("PASS: live counters are usable, warm cacheRead is nonzero in both arms, and reminder-on has no repeatable miss")
            return 0
    except ProofBlocked as exc:
        print(f"BLOCKED: {exc}")
        return 2
    except ProofFailure as exc:
        print(f"FAIL: {exc}")
        return 1
    except Exception as exc:
        print(f"BLOCKED: {type(exc).__name__}: live cache proof could not complete safely")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
