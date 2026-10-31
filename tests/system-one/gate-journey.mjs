// Outside-in journey for openrouter-gate decision classifiers. Asserts; exits non-zero on failure.
// Usage: node tests/system-one/gate-journey.mjs [extension-source-dir] [idle|commands|all]
//   idle:     three decision models Pi does not ship are already allowed; the live list
//             arrives 1.5 s after startup. With no prompt and no command, all three must
//             become classifiers once it lands.
//   commands: /openrouter allow registers d1-ultra as a classifier, classify() reaches the
//             mocked System One endpoint, an unknown id stays chat, deny removes it.
// Real Pi SDK and the real extension. Isolated HOME, fake key, every network call mocked
// (the /models list is a fixture): no OpenRouter credit, no live call.
// Not run in CI: it needs an installed Pi (PI_ROOT).
import assert from "node:assert/strict";
import { cpSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const src = process.argv[2] ?? fileURLToPath(new URL("../../dot_pi/private_agent/extensions/openrouter-gate/", import.meta.url));
const modes = (process.argv[3] ?? "all") === "all" ? ["idle", "commands"] : [process.argv[3]];
const piRoot = process.env.PI_ROOT ?? join(process.env.HOME, ".pi/agent/install/releases/1.2.0/node_modules/@earendil-works/pi-coding-agent");
const { createAgentSession, DefaultResourceLoader, SessionManager, SettingsManager } = await import(pathToFileURL(join(piRoot, "dist/index.js")).href);

const NEW_DECISION_IDS = ["liquid/d1-ultra", "baseten/elephant-1", "nace-ai/drex-max"];
const decision = (id, prompt) => ({
	id, name: id, context_length: 32768,
	architecture: { input_modalities: ["text"], output_modalities: ["decisions"] },
	pricing: { prompt, completion: "0" },
});
const MODELS_FIXTURE = { data: [
	decision("liquid/d1-ultra", "0.000000042"),
	decision("baseten/elephant-1", "0.000000035"),
	decision("nace-ai/drex-max", "0.00000006"),
	{ id: "z-ai/glm-5.3-flash", name: "Z.ai: GLM 5.3 Flash", context_length: 1048576,
		architecture: { input_modalities: ["text"], output_modalities: ["text"] },
		pricing: { prompt: "0.000000075", completion: "0.00000025" } },
] };

const sse = (o) => `data: ${JSON.stringify(o)}\n\n`;
const chunk = (delta, finish) => ({ id: "1", object: "chat.completion.chunk", created: 0, model: "m", choices: [{ index: 0, delta, finish_reason: finish }] });
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function journey(mode) {
	const home = mkdtempSync(join(tmpdir(), "or-gate-journey-"));
	process.env.HOME = home;
	delete process.env.OPENROUTER_API_KEY;
	const agentDir = join(home, ".pi", "agent");
	mkdirSync(agentDir, { recursive: true });
	writeFileSync(join(agentDir, "auth.json"), JSON.stringify({ "openrouter-stashed": { type: "api_key", key: "sk-or-fake-journey" } }));
	const ext = join(home, "ext", "openrouter-gate");
	cpSync(src, ext, { recursive: true, filter: (p) => !p.endsWith(".test.ts") && !p.endsWith("config.json") });
	const allowed = ["typesafe/jev-1.13", "z-ai/glm-5.3-flash", ...(mode === "idle" ? NEW_DECISION_IDS : [])];
	writeFileSync(join(ext, "config.json"), JSON.stringify({ enabled: true, allowedModels: allowed }));

	const calls = [];
	let listServed;
	const listLanded = new Promise((resolve) => { listServed = resolve; });
	globalThis.fetch = async (input, init) => {
		const url = String(input instanceof Request ? input.url : input);
		if (url.endsWith("/systemone")) {
			calls.push({ url, body: JSON.parse(init.body), auth: new Headers(init.headers).get("authorization") });
			return json({ answers: { q: { type: "noul", noul: 0.8 } } });
		}
		if (url.startsWith("https://fake.invalid/")) {
			const body = sse(chunk({ role: "assistant", content: "ok" }, null)) + sse(chunk({}, "stop")) + "data: [DONE]\n\n";
			return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
		}
		if (/openrouter\.ai\/api\/v1\/models\?/.test(url)) {
			await new Promise((r) => setTimeout(r, 1500)); // the live list lands well after session_start
			setTimeout(listServed, 0);
			return json(MODELS_FIXTURE);
		}
		return new Response("{}", { status: 404 }); // no other network
	};

	const fakeChat = (pi) => pi.registerProvider("fakechat", {
		baseUrl: "https://fake.invalid/v1", apiKey: "fake", api: "openai-completions",
		models: [{ id: "m", name: "fake", reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 8000, maxTokens: 1000 }],
	});
	const loader = new DefaultResourceLoader({ cwd: home, agentDir, noExtensions: true, additionalExtensionPaths: [join(ext, "index.ts")], extensionFactories: [fakeChat] });
	await loader.reload();
	const { session } = await createAgentSession({ cwd: home, agentDir, resourceLoader: loader, sessionManager: SessionManager.inMemory(home), settingsManager: SettingsManager.inMemory({}) });
	const notes = [];
	await session.bindExtensions({ uiContext: { notify: (m) => notes.push(m) } });
	const rt = session.modelRuntime;
	const classifierIds = async () => (await rt.getAvailableOfType("classifier", "openrouter")).map((m) => m.id);
	const chatIds = () => rt.getModelsOfType("chat", "openrouter").map((m) => m.id);
	try {
		if (mode === "idle") {
			// Before the list lands: the new ids are chat stubs (proves the delay is real).
			for (const id of NEW_DECISION_IDS) assert.ok(chatIds().includes(id), `${id} should start as a chat stub`);
			await listLanded;
			await new Promise((r) => setTimeout(r, 50));
			// No prompt, no command, no further hook: the gate must have re-applied on its own.
			const classifiers = await classifierIds();
			for (const id of NEW_DECISION_IDS) {
				assert.ok(classifiers.includes(id), `${id} should be a classifier after the list lands; got ${classifiers.join(", ")}`);
				assert.ok(!chatIds().includes(id), `${id} should no longer be chat`);
				const m = rt.getModelOfType("classifier", "openrouter", id);
				assert.equal(m.api, "typesafe-system-one");
				assert.equal(m.baseUrl, "https://openrouter.ai/api/v1");
			}
			assert.equal(rt.getModelOfType("classifier", "openrouter", "liquid/d1-ultra").cost.input, 0.042);
			assert.ok(classifiers.includes("typesafe/jev-1.13"), "Pi's builtin classifier stays");
			assert.ok(chatIds().includes("z-ai/glm-5.3-flash"), "chat model stays chat");
			console.log(`ok idle: ${NEW_DECISION_IDS.join(", ")} are classifiers with no prompt`);
			return;
		}
		await listLanded;
		await session.prompt("/openrouter allow liquid/d1-ultra");
		const d1 = rt.getModelOfType("classifier", "openrouter", "liquid/d1-ultra");
		assert.ok(d1, "allow registers d1-ultra as a classifier");
		const res = await rt.classify(d1, { state: { ask: "journey" }, questions: { q: { type: "bool", instructions: "Approve?", criteria: { true: "yes", false: "no" } } } });
		assert.equal(res.stopReason, "stop", JSON.stringify(res));
		assert.equal(calls.length, 1);
		assert.equal(calls[0].url, "https://openrouter.ai/api/v1/systemone");
		assert.equal(calls[0].body.model, "liquid/d1-ultra");
		assert.equal(calls[0].auth, "Bearer sk-or-fake-journey");
		await session.prompt("/openrouter allow acme/not-a-model");
		assert.ok(chatIds().includes("acme/not-a-model"), "unknown id stays a chat stub");
		assert.ok(!(await classifierIds()).includes("acme/not-a-model"));
		await session.prompt("/openrouter deny liquid/d1-ultra");
		assert.ok(!(await classifierIds()).includes("liquid/d1-ultra"), "deny removes the classifier");
		console.log("ok commands: allow -> classifier, classify -> mocked /systemone, unknown -> chat, deny -> gone");
	} finally {
		session.dispose();
	}
}

for (const mode of modes) await journey(mode);
process.exit(0);
