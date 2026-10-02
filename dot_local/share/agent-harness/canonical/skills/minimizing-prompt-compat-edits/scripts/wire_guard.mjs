import {readFileSync, appendFileSync} from "node:fs";
import {createHash} from "node:crypto";
const hash = (s) => createHash("sha256").update(s).digest("hex");
const canonical = (v) => Array.isArray(v) ? v.map(canonical) :
 v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map(k => [k, canonical(v[k])])) : v;
export default function () {
 const expected = readFileSync(process.env.PROMPT_COMPAT_SOURCE, "utf8");
 const evidence = process.env.PROMPT_COMPAT_WIRE;
 const previous = globalThis.fetch;
 let messages = 0;
 globalThis.fetch = async (input, init) => {
  const url = new URL(input instanceof Request ? input.url : String(input));
  if (url.origin !== "https://api.anthropic.com") throw new Error("Probe blocked unexpected network origin");
  if (url.pathname === "/api/claude_cli/bootstrap") {
   const response = await previous(input, {...init, redirect: "error"});
   appendFileSync(evidence, JSON.stringify({kind: "bootstrap", status: response.status})+"\n");
   return response;
  }
  if (url.pathname !== "/v1/messages") throw new Error("Probe blocked unexpected endpoint");
  messages++;
  if (messages > Number(process.env.PROMPT_COMPAT_MAX_MESSAGES || 1)) {
   appendFileSync(evidence, JSON.stringify({kind: "blocked-retry"})+"\n");
   throw new Error("Probe inference budget exceeded");
  }
  const payload = JSON.parse(Buffer.from(init.body).toString());
  if (process.env.PROMPT_COMPAT_EXPECTED_MODEL && payload.model !== process.env.PROMPT_COMPAT_EXPECTED_MODEL) {
   throw new Error("Probe blocked unexpected model before inference");
  }
  const identity = "You are Claude Code, Anthropic's official CLI for Claude.";
  if (!payload.system?.[0]?.text?.startsWith("x-anthropic-billing-header:") ||
      payload.system?.[1]?.text !== identity) throw new Error("Compat envelope changed");
  const suffix = "\n\n<cwd>\n" + process.env.PROMPT_COMPAT_CWD + "\n</cwd>";
  if (payload.system.length !== 3 || payload.system.some(b => b.type !== "text") ||
      payload.system[2].text !== expected + suffix) {
   throw new Error("Complete system layout or permitted cwd suffix changed");
  }
  const headers = new Headers(init.headers);
  const normalized = structuredClone(payload);
  normalized.system[2].text = "<approved-owner-prompt>" + suffix;
  normalized.system[0].text = normalized.system[0].text.replace(/cch=[0-9a-f]{5}/, "cch=xxxxx");
  const user = JSON.parse(normalized.metadata.user_id);
  if (Object.hasOwn(user, "session_id")) user.session_id = {excluded: "session_id", type: typeof user.session_id};
  normalized.metadata.user_id = canonical(user);
  const normalizedHeaders = Object.fromEntries(headers);
  for (const key of ["x-client-request-id", "x-claude-code-session-id"]) {
   if (key in normalizedHeaders) normalizedHeaders[key] = "<excluded-session-or-request-id>";
  }
  const authorization = headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer sk-ant-oat") ||
      hash(authorization) !== process.env.PROMPT_COMPAT_AUTHORIZATION_SHA) {
   throw new Error("Actual wire authentication differs from pinned credential");
  }
  normalizedHeaders.authorization = {scheme: "Bearer", sha256: hash(authorization)};
  if ("content-length" in normalizedHeaders) {
   if (Number(normalizedHeaders["content-length"]) !== Buffer.byteLength(init.body)) throw new Error("Incorrect content length");
   normalizedHeaders["content-length"] = "<derived-body-length>";
  }
  const row = {
   kind: "messages", promptSha256: hash(expected), extraSha256: hash(suffix),
   wireContextSha256: hash(JSON.stringify(canonical({url: String(url), payload: normalized, headers: normalizedHeaders}))),
   model: payload.model, maxTokens: payload.max_tokens, thinking: payload.thinking,
   tools: (payload.tools || []).map(t => t.name),
   beta: (headers.get("anthropic-beta") || "").split(",").sort(),
   userAgent: headers.get("user-agent"), xApp: headers.get("x-app"),
   systemShape: payload.system.map(b => ({keys: Object.keys(b).sort(), cache: b.cache_control || null})),
   billingFrame: payload.system[0].text.replace(/cch=[0-9a-f]{5}/, "cch=xxxxx"),
   identity: payload.system[1].text, sent: true,
  };
  // Record the attempt before transport, including network failures.
  appendFileSync(evidence, JSON.stringify(row)+"\n");
  const response = await previous(input, {...init, redirect: "error"});
  appendFileSync(evidence, JSON.stringify({kind: "response", status: response.status})+"\n");
  return response;
 };
}
