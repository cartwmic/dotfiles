#!/usr/bin/env python3
"""Prove personal/work search settings through a real Pi tool run, offline."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "dot_pi/private_agent/extensions/web-search"
FACT = "Cobalt-lantern-42"
URL = "https://example.com/search-proof"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def profile_script(profile: str) -> str:
    result = subprocess.run(
        ["chezmoi", "--source", str(ROOT), "--override-data", json.dumps({"profile": profile}),
         "execute-template"],
        input=(SOURCE / "modify_config.json.tmpl").read_text(),
        text=True, capture_output=True, check=True, timeout=20,
    )
    return result.stdout


def modify(script: str, existing: str = "") -> str:
    return subprocess.run(["sh", "-c", script], input=existing, text=True,
                          capture_output=True, check=True, timeout=10).stdout


class Backend(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, body))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.path == "/codex/responses":
            output = [
                {"type": "web_search_call", "action": {"type": "search", "query": "scripted fact"}},
                {"type": "message", "role": "assistant", "content": [{
                    "type": "output_text", "text": FACT,
                    "annotations": [{"type": "url_citation", "url": URL, "title": "Proof source"}],
                }]},
            ]
            response = {"response": {"model": body["model"], "output": output,
                                     "usage": {"input_tokens": 10, "output_tokens": 20}}}
            self.wfile.write(("event: response.completed\ndata: " + json.dumps(response) + "\n\n").encode())
        else:
            results = [m for m in body["messages"] if m.get("role") == "tool"]
            if not results:
                delta = {"role": "assistant", "tool_calls": [{
                    "index": 0, "id": "proof-search", "type": "function",
                    "function": {"name": "web_search", "arguments": json.dumps({"query": "Find the scripted fact"})},
                }]}
                reason = "tool_calls"
            else:
                content = json.dumps(results)
                text = f"Verified {FACT} from {URL}" if FACT in content and URL in content else "FAIL: missing search result"
                delta, reason = {"role": "assistant", "content": text}, "stop"
            common = {"id": "proof-chat", "object": "chat.completion.chunk", "created": 1, "model": "scripted"}
            for part, finish in [(delta, None), ({}, reason)]:
                chunk = {**common, "choices": [{"index": 0, "delta": part, "finish_reason": finish}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *_args) -> None:
        pass


def prove_pi(profile: str, config: str) -> None:
    with tempfile.TemporaryDirectory(prefix="pi-web-search-proof-") as temporary:
        root = Path(temporary)
        agent = root / ".pi/agent"
        extension = root / "extension"
        agent.mkdir(parents=True)
        extension.mkdir()
        for name in ["index.ts", "config.ts", "codex.ts"]:
            shutil.copy2(SOURCE / name, extension / name)
        (extension / "config.json").write_text(config)
        auth = agent / "auth.json"
        auth.write_text(json.dumps({"openai-codex": {
            "type": "oauth", "access": "dummy-proof-token", "accountId": "dummy-proof-account",
            "expires": int(time.time() * 1000) + 3_600_000,
        }}))
        auth.chmod(0o600)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        server.requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        (agent / "models.json").write_text(json.dumps({"providers": {"web-search-proof": {
            "api": "openai-completions", "apiKey": "dummy-proof-key", "baseUrl": base + "/v1",
            "models": [{"id": "scripted", "reasoning": False, "input": ["text"],
                        "contextWindow": 32000, "maxTokens": 512}],
        }}}))
        fixture = root / "fixture.ts"
        fixture.write_text(f"""export default function(pi) {{
  const original = globalThis.fetch;
  pi.on("session_start", () => {{
    globalThis.fetch = (input, init) => {{
      const url = String(input instanceof Request ? input.url : input);
      if (url === "https://chatgpt.com/backend-api/codex/responses")
        return original({json.dumps(base + '/codex/responses')}, init);
      if (url.startsWith({json.dumps(base + '/')})) return original(input, init);
      throw new Error("Proof blocked external network: " + new URL(url).hostname);
    }};
  }});
  pi.on("session_shutdown", () => {{ globalThis.fetch = original; }});
}}
""")
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("PI_") and key not in {
                   "WEB_SEARCH_PROVIDER", "CODEX_SEARCH_MODEL", "CODEX_SEARCH_REASONING_EFFORT"}}
        env.update({"HOME": str(root), "PI_CODING_AGENT_DIR": str(agent), "PI_OFFLINE": "1",
                    "XDG_CONFIG_HOME": str(root / ".config"), "XDG_CACHE_HOME": str(root / ".cache")})
        command = [shutil.which("pi"), "--mode", "json", "--no-session", "--offline", "--approve",
                   "--no-context-files", "--no-extensions", "--no-skills", "--no-prompt-templates",
                   "--no-themes", "--extension", str(fixture), "--extension", str(extension / "index.ts"),
                   "--provider", "web-search-proof", "--model", "web-search-proof/scripted",
                   "--tools", "web_search", "Find the scripted fact using web_search, then cite its source."]
        try:
            result = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, timeout=60)
            require(result.returncode == 0, f"Pi failed: {result.stderr}")
            events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            messages = [e["message"] for e in events if e.get("type") == "message_end"]
            final = [m for m in messages if m.get("role") == "assistant"][-1]
            text = "\n".join(c.get("text", "") for c in final["content"])
            require(final.get("stopReason") == "stop", "Pi did not finish successfully")
            require(f"Verified {FACT}" in text and URL in text and "FAIL" not in text,
                    "Final reply did not use the actual search answer and citation")
            searches = [body for route, body in server.requests if route == "/codex/responses"]
            require(len(searches) == 1, "Expected exactly one Codex search request")
            expected = json.loads(config)
            require(searches[0]["model"] == expected["codexModel"], "Wrong search model")
            if "codexReasoningEffort" in expected:
                require(searches[0].get("reasoning") == {"effort": expected["codexReasoningEffort"]}, "Wrong effort")
            else:
                require("reasoning" not in searches[0], "Unset work effort was changed")
            main = [body for route, body in server.requests if route != "/codex/responses"]
            require(len(main) == 2, "Expected tool call and follow-up model requests")
            names = {tool["function"]["name"] for tool in main[0].get("tools", [])}
            require(names == {"web_search"}, "Codex tool listing changed (fetch must remain omitted)")
            print(f"PASS: {profile} real Pi search → scripted Codex → cited final reply")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def main() -> None:
    for program in ["pi", "chezmoi", "jq"]:
        require(bool(shutil.which(program)), f"{program} is required")
    existing = json.dumps({"searchProvider": "codex", "codexModel": "gpt-5.6-luna",
                           "anthropicModel": "claude-sonnet-5", "custom": {"keep": True}})
    for profile in ["personal", "axon-work-computer"]:
        script = profile_script(profile)
        config = modify(script, existing)
        parsed = json.loads(config)
        require(parsed["custom"] == {"keep": True} and parsed["anthropicModel"] == "claude-sonnet-5",
                "Modifier overwrote unrelated settings")
        require(modify(script, config) == config, "Modifier is not idempotent")
        initial = json.loads(modify(script))
        if profile == "personal":
            require(parsed["codexModel"] == "gpt-6.1-sol" and parsed["codexReasoningEffort"] == "low",
                    "Personal model/effort mismatch")
            require(initial["searchProvider"] == "codex", "Personal bootstrap provider mismatch")
        else:
            require(parsed == json.loads(existing), "Existing work settings changed")
            require(initial == {"searchProvider": "anthropic", "codexModel": "gpt-5.6-luna"}, "Work defaults changed")
        invalid = subprocess.run(["sh", "-c", script], input="[]", text=True, capture_output=True, timeout=10)
        require(invalid.returncode != 0, "Modifier did not reject non-object config")
        print(f"PASS: {profile} modifier preservation, bootstrap, idempotence, invalid-input rejection")
        prove_pi(profile, config)


if __name__ == "__main__":
    main()
