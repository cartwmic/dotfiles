#!/usr/bin/env node
// AC: opsx-loop.interrupt-or-error-stops-the-loop
// AC: opsx-loop.opsx-dispatch-forces-resolved-role-model
import http from "node:http";
import fs from "node:fs";

const readyPath = process.argv[2];
const logPath = process.argv[3];
const delayMs = Number.parseInt(process.env.FAKE_OPENAI_DELAY_MS || "0", 10) || 0;
const responseText = process.env.FAKE_OPENAI_RESPONSE || "fake opsx tui response";
const responseSequence = (process.env.FAKE_OPENAI_RESPONSE_SEQUENCE || "").split("|");
const matchText = process.env.FAKE_OPENAI_MATCH_TEXT || "";
const matchResponse = process.env.FAKE_OPENAI_MATCH_RESPONSE || "";
const errorText = process.env.FAKE_OPENAI_ERROR_MESSAGE || "fake provider HTTP {status}";
const statusSequence = (process.env.FAKE_OPENAI_STATUS_SEQUENCE || "")
  .split(",")
  .map((value) => Number.parseInt(value.trim(), 10))
  .filter((value) => Number.isInteger(value) && value >= 100 && value <= 599);
const toolCallMatchSequence = (process.env.FAKE_OPENAI_TOOL_CALL_MATCH_SEQUENCE || "")
  .split("|")
  .filter(Boolean);
const toolCallName = process.env.FAKE_OPENAI_TOOL_CALL_NAME || "opsx_dispatch";
const toolCallArguments = process.env.FAKE_OPENAI_TOOL_CALL_ARGUMENTS ||
  JSON.stringify({ role: "review", task: "verify dispatch ownership" });
let completionRequestIndex = 0;
let toolCallMatchIndex = 0;

if (!readyPath || !logPath) {
  console.error("usage: fake-openai-server.mjs <ready-path> <log-path>");
  process.exit(2);
}

function append(line) {
  fs.appendFileSync(logPath, `${line}\n`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const server = http.createServer(async (req, res) => {
  let body = "";
  req.setEncoding("utf8");
  req.on("data", (chunk) => { body += chunk; });
  req.on("end", async () => {
    append(JSON.stringify({ at: new Date().toISOString(), method: req.method, url: req.url, body }));
    if (delayMs > 0) await sleep(delayMs);

    if (req.url?.includes("/chat/completions")) {
      let parsed = {};
      try { parsed = JSON.parse(body); } catch {}
      const model = parsed.model || "smoke";
      const stream = parsed.stream !== false;
      const requestIndex = completionRequestIndex;
      const status = statusSequence[requestIndex] ?? 200;
      const requestResponseText =
        matchText && matchResponse && body.includes(matchText)
          ? matchResponse
          : responseSequence[requestIndex] || responseText;
      const latestUser = [...(Array.isArray(parsed.messages) ? parsed.messages : [])]
        .reverse()
        .find((message) => message?.role === "user");
      const latestUserText = typeof latestUser?.content === "string"
        ? latestUser.content
        : Array.isArray(latestUser?.content)
          ? latestUser.content.map((part) => part?.text || "").join("\n")
          : "";
      const toolMatch = toolCallMatchSequence[toolCallMatchIndex];
      const shouldCallTool = Boolean(toolMatch && latestUserText.includes(toolMatch));
      if (shouldCallTool) toolCallMatchIndex += 1;
      completionRequestIndex += 1;

      if (status < 200 || status >= 300) {
        res.writeHead(status, { "content-type": "application/json" });
        res.end(JSON.stringify({
          error: {
            message: errorText.replaceAll("{status}", String(status)),
            type: "server_error",
            code: "fake_status_sequence",
          },
        }));
        return;
      }

      if (stream) {
        res.writeHead(200, {
          "content-type": "text/event-stream; charset=utf-8",
          "cache-control": "no-cache",
          connection: "keep-alive",
        });
        const chunk = (delta, finish_reason = null) => ({
          id: "chatcmpl-opsx-tui-fake",
          object: "chat.completion.chunk",
          created: Math.floor(Date.now() / 1000),
          model,
          choices: [{ index: 0, delta, finish_reason }],
        });
        res.write(`data: ${JSON.stringify(chunk({ role: "assistant" }))}\n\n`);
        if (shouldCallTool) {
          res.write(`data: ${JSON.stringify(chunk({
            tool_calls: [{
              index: 0,
              id: `call-opsx-${requestIndex}`,
              type: "function",
              function: { name: toolCallName, arguments: toolCallArguments },
            }],
          }))}\n\n`);
          res.write(`data: ${JSON.stringify(chunk({}, "tool_calls"))}\n\n`);
        } else {
          res.write(`data: ${JSON.stringify(chunk({ content: requestResponseText }))}\n\n`);
          res.write(`data: ${JSON.stringify(chunk({}, "stop"))}\n\n`);
        }
        res.write("data: [DONE]\n\n");
        res.end();
        return;
      }

      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({
        id: "chatcmpl-opsx-tui-fake",
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model,
        choices: [{
          index: 0,
          message: shouldCallTool
            ? {
                role: "assistant",
                content: null,
                tool_calls: [{
                  id: `call-opsx-${requestIndex}`,
                  type: "function",
                  function: { name: toolCallName, arguments: toolCallArguments },
                }],
              }
            : { role: "assistant", content: requestResponseText },
          finish_reason: shouldCallTool ? "tool_calls" : "stop",
        }],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      }));
      return;
    }

    res.writeHead(404, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: { message: `not found: ${req.url}` } }));
  });
});

server.listen(0, "127.0.0.1", () => {
  const addr = server.address();
  fs.writeFileSync(readyPath, String(addr.port));
  append(JSON.stringify({ at: new Date().toISOString(), event: "ready", port: addr.port }));
});

process.on("SIGTERM", () => server.close(() => process.exit(0)));
process.on("SIGINT", () => server.close(() => process.exit(0)));
