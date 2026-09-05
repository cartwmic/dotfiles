// Read-only lifecycle evidence for prove.py; no fake compaction or resume hooks.
import { appendFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	for (const type of ["session_start", "turn_start", "turn_end", "agent_end", "agent_settled", "session_before_compact", "session_compact", "session_compact_failed", "session_shutdown"] as const) {
		pi.on(type, (event, ctx) => {
			appendFileSync(process.env.COMPACTION_PROOF_EVENTS!, JSON.stringify({
				type, time: new Date().toISOString(), usage: ctx.getContextUsage(),
				stopReason: "message" in event ? event.message.stopReason : undefined,
				willRetry: "willRetry" in event ? event.willRetry : undefined,
				error: "errorMessage" in event ? event.errorMessage : undefined,
			}) + "\n");
		});
	}
}
