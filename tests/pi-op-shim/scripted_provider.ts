// Test-only Pi extension: a "scripted" model with no network. Turn N of the script in $SCRIPTED_MODEL_SCRIPT is replayed on model call N
// (N = the number of tool results already in the transcript). A turn is {"call": {"name": ..., "arguments": {...}}} for a tool call, or {"text": "..."} to finish.
import { readFileSync } from "node:fs";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";

const empty = (model: any) => ({
	role: "assistant", content: [] as any[], api: model.api, provider: model.provider, model: model.id, stopReason: "pending", timestamp: Date.now(),
	usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
});

function streamScripted(model: any, context: any) {
	const stream = createAssistantMessageEventStream();
	queueMicrotask(() => {
		const output: any = empty(model);
		const turns = JSON.parse(readFileSync(process.env.SCRIPTED_MODEL_SCRIPT!, "utf8")).turns as any[];
		const turn = turns[context.messages.filter((m: any) => m.role === "toolResult").length];
		stream.push({ type: "start", partial: output });
		if (turn?.call) {
			const toolCall = { type: "toolCall", id: `call-${Math.random().toString(36).slice(2)}`, name: turn.call.name, arguments: turn.call.arguments };
			output.content.push(toolCall);
			stream.push({ type: "toolcall_start", contentIndex: 0, partial: output });
			stream.push({ type: "toolcall_end", contentIndex: 0, toolCall, partial: output });
			output.stopReason = "toolUse";
			stream.push({ type: "done", reason: "toolUse", message: output });
		} else {
			const text = turn?.text ?? "script exhausted";
			output.content.push({ type: "text", text });
			stream.push({ type: "text_start", contentIndex: 0, partial: output });
			stream.push({ type: "text_end", contentIndex: 0, content: text, partial: output });
			output.stopReason = "stop";
			stream.push({ type: "done", reason: "stop", message: output });
		}
		stream.end();
	});
	return stream;
}

export default function (pi: any) {
	pi.registerProvider("scripted", {
		baseUrl: "http://127.0.0.1:0", apiKey: "none", api: "scripted-api", streamSimple: streamScripted,
		models: [{ id: "scripted-1", name: "Scripted", reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 8192 }],
	});
}
