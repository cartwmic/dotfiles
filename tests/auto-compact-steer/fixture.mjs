// Proof fixture for tests/auto-compact-steer/proof.py. Writes a JSONL trace and,
// when RACE_SPEC is set, starts two prompts together with deterministic holds.
import fs from "node:fs";
import path from "node:path";

const trace = (entry) => fs.appendFileSync(process.env.PROOF_TRACE, JSON.stringify({ t: Date.now(), ...entry }) + "\n");
const spec = process.env.RACE_SPEC ? JSON.parse(process.env.RACE_SPEC) : undefined;

async function hold(point, text) {
	const list = point === "input" ? spec?.holdInput : point === "bas" ? spec?.holdBAS : spec?.holdSettled;
	if (!list?.includes(text)) return;
	trace({ kind: "held", point, text });
	const release = path.join(process.env.PROOF_HOLDS, `${point}-${text}`);
	while (!fs.existsSync(release)) await new Promise((resolve) => setTimeout(resolve, 20));
	trace({ kind: "released", point, text });
}

export default function (pi) {
	pi.on("session_start", () => trace({ kind: "ready" }));
	let settledCount = 0;
	pi.on("agent_settled", async () => {
		settledCount += 1;
		trace({ kind: "settled" });
		await hold("settled", String(settledCount));
	});
	pi.on("input", async (event) => {
		trace({ kind: "input", text: event.text, source: event.source });
		if (spec && event.text === spec.marker && event.source !== "extension") {
			const options = spec.spawn.deliverAs ? { deliverAs: spec.spawn.deliverAs } : undefined;
			try {
				Promise.resolve(pi.sendUserMessage(spec.spawn.text, options)).catch((error) =>
					trace({ kind: "spawn-error", message: String(error?.message ?? error) }));
			} catch (error) {
				trace({ kind: "spawn-error", message: String(error?.message ?? error) });
			}
		}
		await hold("input", event.text);
	});
	pi.on("before_agent_start", async (event) => {
		trace({ kind: "bas", text: event.prompt });
		await hold("bas", event.prompt);
	});
}
