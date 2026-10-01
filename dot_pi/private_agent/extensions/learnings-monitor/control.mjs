import { piSourceId, privacyFilter } from "./capture.mjs";

export const DEFAULT_OBSERVER_TOOLS = Object.freeze(["read", "grep", "find", "ls"]);
const READ_ONLY_TOOLS = new Set(DEFAULT_OBSERVER_TOOLS);
const MAX_FOCUS_CHARS = 500;
const MAX_PROPOSAL_CHARS = 700;

function commandError(message) {
	return `Learnings monitor: ${message}`;
}

function sourceState(result) {
	if (!result?.ok) {
		if (result?.reason === "ephemeral") {
			return { error: "unsupported in pi --no-session; start a persisted session to enable monitoring." };
		}
		if (result?.reason === "observer") {
			return { error: "observer sessions cannot be monitored as primary sources." };
		}
		return { error: "could not identify this persisted primary session." };
	}
	return { sourceId: result.sourceId, state: result.state };
}

function parseModel(value) {
	const model = value.trim();
	if (!/^[^\s/]+\/.+$/.test(model)) throw new Error("model must be provider/model-id, or 'follow'.");
	return model;
}

function parseTools(value) {
	const input = value.trim();
	if (!input || input === "default") return [...DEFAULT_OBSERVER_TOOLS];
	const tools = input.split(/[\s,]+/).filter(Boolean);
	if (!tools.length) return [...DEFAULT_OBSERVER_TOOLS];
	for (const tool of tools) {
		if (!READ_ONLY_TOOLS.has(tool)) {
			throw new Error(`unsupported observer tool '${tool}'; allowed tools are ${DEFAULT_OBSERVER_TOOLS.join(", ")}.`);
		}
	}
	return [...new Set(tools)];
}

function parseCommand(args) {
	const raw = String(args ?? "").trim();
	if (!raw) return { action: "help" };
	const match = raw.match(/^(\S+)(?:\s+([\s\S]*))?$/);
	return { action: match[1].toLowerCase(), value: (match[2] ?? "").trim() };
}

function modelLabel(model) {
	return model?.provider && model?.id ? `${model.provider}/${model.id}` : "unavailable";
}

function formatUsage(stats) {
	const native = stats?.nativeStats;
	if (!native) return "Native usage: not available yet.";
	const tokens = native.tokens ?? {};
	const total = Number.isFinite(tokens.total) ? tokens.total : 0;
	const cost = Number.isFinite(native.cost) ? native.cost : 0;
	return `Native usage: ${total} tokens (in ${tokens.input ?? 0}, out ${tokens.output ?? 0}); cost $${cost.toFixed(4)}.`;
}

function healthLabel({ failure, worker, state }) {
	if (failure) return "failed";
	if (worker?.running) return "running";
	if (worker?.available === false) return "worker unavailable";
	if (state?.pending?.length) return "pending";
	return state?.enabled ? "ready" : "off";
}

function describeStatus({ capture, worker, state, failure, tools, ctx }) {
	const pendingBatches = capture.pendingCount ?? state?.pending?.length ?? 0;
	const pendingEvidence = capture.pendingEvidenceCount ?? pendingBatches;
	const location = worker?.sessionFile ?? state?.workerSession ?? "not created";
	const modelSelection = state?.modelOverride
		? `override ${state.modelOverride}`
		: `follow ${modelLabel(ctx.model)}`;
	const lines = [
		`Learnings monitor: ${capture.enabled ? "ON" : "OFF"} (${healthLabel({ failure, worker, state })})`,
		`Source: ${capture.sourceId}`,
		`Branch: ${capture.branch ?? "unknown"}`,
		`Pending: ${pendingBatches} batch(es), ${pendingEvidence} evidence item(s)`,
		`Observer session: ${location}`,
		`Observer model: ${worker?.model ? modelLabel(worker.model) : modelSelection}`,
		`Model selection: ${modelSelection}`,
		`Observer tools: ${(worker?.tools?.length ? worker.tools : tools).join(", ")}`,
		formatUsage(worker),
	];
	if (state?.focus) lines.push(`Focus: ${state.focus}`);
	if (failure) lines.push(`Failure: ${failure}`);
	return lines.join("\n");
}

/** Register primary-session controls. No command sends messages into the primary transcript. */
export function createLearningsMonitorControls({
	capture,
	store,
	getWorker,
	getTools = () => [...DEFAULT_OBSERVER_TOOLS],
	setTools,
} = {}) {
	if (!capture || !store || typeof getWorker !== "function") {
		throw new TypeError("capture, store, and getWorker are required");
	}
	const failures = new Map();
	const warned = new Set();

	function recordFailure(sourceId, channel, error) {
		if (!sourceId || !channel) return;
		const message = privacyFilter(error?.message ?? String(error), 500) || "unknown observer failure";
		let byChannel = failures.get(sourceId);
		if (!byChannel) failures.set(sourceId, byChannel = new Map());
		byChannel.set(channel, message);
	}

	function recordSuccess(sourceId, channel) {
		const byChannel = failures.get(sourceId);
		if (!byChannel) return;
		byChannel.delete(channel);
		if (byChannel.size === 0) {
			failures.delete(sourceId);
			warned.delete(sourceId);
		}
	}

	function failureFor(sourceId) {
		const byChannel = failures.get(sourceId);
		return byChannel?.size ? [...byChannel.values()].join("; ") : null;
	}

	async function inspect(ctx) {
		const captureStatus = await capture.status(ctx);
		const source = sourceState(captureStatus);
		if (source.error) return { error: source.error, capture: captureStatus };
		const state = captureStatus.state ?? await store.getOperationalState(source.sourceId);
		let worker = null;
		try {
			worker = await getWorker(source.sourceId).stats(source.sourceId);
			if (worker?.lastError) recordFailure(source.sourceId, "observer", worker.lastError);
			if (worker?.available === false && state.workerSession) {
				recordFailure(source.sourceId, "observer", new Error("saved observer session file is unavailable"));
			}
		} catch (error) {
			recordFailure(source.sourceId, "observer", error);
		}
		return {
			capture: captureStatus,
			state,
			worker,
			sourceId: source.sourceId,
			failure: failureFor(source.sourceId),
			tools: getTools(source.sourceId),
		};
	}

	async function warnIfFailed(ctx) {
		if (!ctx?.hasUI || typeof ctx.ui?.notify !== "function" || failures.size === 0) return;
		let sourceId;
		try {
			sourceId = piSourceId(ctx.sessionManager.getSessionId());
		} catch {
			return;
		}
		if (!failureFor(sourceId) || warned.has(sourceId)) return;
		warned.add(sourceId);
		try {
			ctx.ui.notify("Learnings monitor has a persistent failure. Run /learnings status for details.", "warning");
		} catch {
			warned.delete(sourceId);
		}
	}

	function syncUiStatus(ctx, enabled) {
		if (ctx?.hasUI && typeof ctx.ui?.setStatus === "function") {
			ctx.ui.setStatus("learnings-monitor", enabled ? "◉ learnings" : undefined);
		}
	}

	async function handle(args, ctx) {
		const { action, value } = parseCommand(args);
		let reply;
		try {
			switch (action) {
				case "help":
				case "?":
					reply = "Usage: /learnings on | off | focus <text|clear> | model <provider/model-id|follow> | tools <read,grep,find,ls|default> | flush | status";
					break;
				case "on": {
					const result = await capture.enable(ctx);
					const source = sourceState(result);
					syncUiStatus(ctx, !source.error);
					reply = source.error ?? "Learnings monitor ON. It runs silently and does not alter the primary conversation.";
					break;
				}
				case "off": {
					const result = await capture.disable(ctx);
					const source = sourceState(result);
					syncUiStatus(ctx, false);
					if (source.error) reply = source.error;
					else {
						const pending = result.state?.pending?.length ?? 0;
						reply = `Learnings monitor OFF. ${pending} pending batch(es) retained; observer work cancelled.`;
					}
					break;
				}
				case "focus": {
					if (!value) throw new Error("use /learnings focus <text> or /learnings focus clear.");
					const status = await capture.status(ctx);
					const source = sourceState(status);
					if (source.error) { reply = source.error; break; }
					const focus = value.toLowerCase() === "clear" ? null : privacyFilter(value, MAX_FOCUS_CHARS);
					await store.updateOperationalState(source.sourceId, { focus });
					reply = focus ? "Observer-only focus saved." : "Observer-only focus cleared.";
					break;
				}
				case "model": {
					if (!value) throw new Error("use /learnings model <provider/model-id> or /learnings model follow.");
					const status = await capture.status(ctx);
					const source = sourceState(status);
					if (source.error) { reply = source.error; break; }
					const modelOverride = value.toLowerCase() === "follow" ? null : parseModel(value);
					await store.updateOperationalState(source.sourceId, { modelOverride });
					reply = modelOverride
						? `Observer model override saved: ${modelOverride}. Unavailable models fail closed; no fallback is used.`
						: "Observer will follow the primary model.";
					break;
				}
				case "tools": {
					if (!value) throw new Error(`use /learnings tools <${DEFAULT_OBSERVER_TOOLS.join(",")}> or /learnings tools default.`);
					const status = await capture.status(ctx);
					const source = sourceState(status);
					if (source.error) { reply = source.error; break; }
					if (typeof setTools !== "function") throw new Error("runtime tool selection is unavailable.");
					const tools = parseTools(value);
					await setTools(source.sourceId, tools);
					reply = `Observer tools selected: ${tools.join(", ")}. This choice lasts until the Pi extension runtime restarts.`;
					break;
				}
				case "flush": {
					const result = await capture.flush(ctx);
					const source = sourceState(result);
					if (source.error) reply = source.error;
					else reply = result.scheduled
						? `Observer flush queued for ${result.pendingCount} pending batch(es); the primary conversation is unchanged.`
						: "No pending activity to flush.";
					break;
				}
				case "status": {
					if (value) throw new Error("status takes no arguments.");
					const status = await inspect(ctx);
					syncUiStatus(ctx, Boolean(status.capture?.ok && status.capture.enabled));
					reply = status.error ?? describeStatus({ ...status, ctx });
					break;
				}
				default:
					throw new Error(`unknown subcommand '${action}'.`);
			}
		} catch (error) {
			reply = commandError(error?.message ?? String(error));
		}
		await warnIfFailed(ctx);
		return reply;
	}

	function register(pi, { command = true } = {}) {
		if (command) pi.registerCommand("learnings", {
			description: "Control the silent workflow observer",
			handler: async (args, ctx) => {
				const reply = await handle(args, ctx);
				if (ctx.hasUI && reply) ctx.ui.notify(reply, "info");
			},
		});
		pi.on("session_start", async (_event, ctx) => {
			try {
				const status = await capture.status(ctx);
				syncUiStatus(ctx, Boolean(status.ok && status.enabled));
				await warnIfFailed(ctx);
			} catch {
				// A status rendering error must not interfere with session startup.
			}
		});
		pi.on("agent_settled", async (_event, ctx) => {
			await warnIfFailed(ctx);
		});
	}

	return Object.freeze({
		handle,
		register,
		recordFailure,
		recordSuccess,
		failureFor,
		warnIfFailed,
	});
}
