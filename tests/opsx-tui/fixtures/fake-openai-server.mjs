#!/usr/bin/env node
import http from "node:http";
import fs from "node:fs";

const readyPath = process.argv[2];
const logPath = process.argv[3];
const delayMs = Number.parseInt(process.env.FAKE_OPENAI_DELAY_MS || "0", 10) || 0;
const responseText = process.env.FAKE_OPENAI_RESPONSE || "fake opsx tui response";

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
        res.write(`data: ${JSON.stringify(chunk({ content: responseText }))}\n\n`);
        res.write(`data: ${JSON.stringify(chunk({}, "stop"))}\n\n`);
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
        choices: [{ index: 0, message: { role: "assistant", content: responseText }, finish_reason: "stop" }],
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
